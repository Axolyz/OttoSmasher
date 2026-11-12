// 查找栏（主）与范围行（副）（UI_PLAN §2.3；规格 07 §7.1–§7.3；Q5、Q16、Q17）。
// - 查找栏：文字（名称、读到的段的原文与读音、备注）+ 主标签表达式 + ★ 只看星标；从原片页跳来时多一个临时“原片：…”块。都不存进筛选器。
// - 范围行：⚑ 保存筛选器 + 标签条件（分面块、可选的“标签表达式”块）+「＋」（可搜索、带计数）；选用筛选器 = 用它替换这一行；
//   改动后显示“已修改 · 更新 · 另存”。各条件取交集，同一分面多个值取并集；人物块单击切换“只要单人”。
import { Flag, ChevronDown, Folder, Star, X } from "lucide-react";
import { type Ref, useEffect, useMemo, useRef, useState } from "react";
import type { FacetCondition, FacetValues, SavedFilter, TagScope } from "../api/types";
import { Button } from "../components/Button";
import { type ChipItem, Chips, Token } from "../components/Controls";
import { Suggest, type SuggestGroup, TextField } from "../components/Fields";
import { Menu, type MenuItems } from "../components/Menu";
import { t } from "../i18n";
import s from "./Library.module.css";

export type Facet = FacetCondition["facet"];
export const FACETS: Facet[] = ["work", "type", "person", "pitch", "other"];

export interface Scope {
  facets: FacetCondition[];
  expr: string;
}
export const EMPTY_SCOPE: Scope = { facets: [], expr: "" };

export interface FindState {
  text: string;
  /** 旧版两条表达式合并后超限时，保留原查询，直到用户编辑表达式或切换范围。 */
  legacyExpr?: string;
  starred: boolean;
  tags: Scope;
  /** 当前选用的保存筛选器（只是界面状态：判断“已修改”、更新时写回哪个） */
  preset: string | null;
  source: { sourceId: string; name: string } | null;
}
export const EMPTY_FIND: FindState = { text: "", starred: false, tags: EMPTY_SCOPE, preset: null, source: null };

export function normScope(x: TagScope | null | undefined): Scope {
  return { facets: (x?.facets ?? []).map((f) => ({ facet: f.facet, values: [...f.values], single: !!f.single && f.facet === "person" })), expr: x?.expr ?? "" };
}
export function sameScope(a: Scope, b: Scope): boolean {
  return JSON.stringify(normScope(a)) === JSON.stringify(normScope(b));
}
export function scopeSize(x: Scope): number {
  return x.facets.length + (x.expr.trim() ? 1 : 0);
}
/** 一行概要（筛选器菜单里的淡色说明）：“作品 Yuru Yuri · 人物 京子（单人）· 标签表达式 …” */
export function scopeSummary(x: Scope): string {
  const parts = x.facets.map((f) => `${t(`facet.${f.facet}`)} ${f.values.join(t("scope.or"))}${f.single ? t("scope.singleMark") : ""}`);
  if (x.expr.trim()) parts.push(`${t("scope.exprChip")} ${x.expr}`);
  return parts.join(" · ") || t("scope.none");
}

/** 输入后 250 ms 再提交；表达式先校验，出错不提交 */
function useDebounced<T>(value: T, ms: number, commit: (v: T) => void): void {
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const id = setTimeout(() => commit(value), ms);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
}

export function scopeExpression(tags: Scope, extra?: string): string {
  const base = tags.expr.trim();
  const second = extra?.trim();
  if (!second || base === second) return base;
  return base ? `(${base}) AND (${second})` : second;
}

export function FindBar(props: { find: FindState; setFind: (f: (x: FindState) => FindState) => void; textRef?: Ref<HTMLInputElement>; project?: { active: boolean; toggle: () => void } }) {
  const { find, setFind } = props;
  const [text, setText] = useState(find.text);
  useEffect(() => setText(find.text), [find.text]);
  useDebounced(text, 250, (v) => setFind((f) => ({ ...f, text: v })));
  return (
    <div className={s.findWrap}>
      <div className={s.find}>
        <div className={s.findBox}>
          {find.source ? (
            <span className={s.findSource} data-testid="find-source">
              <Token label={t("scope.sourceChip", { name: find.source.name })} />
              <button type="button" className={s.findX} aria-label={t("scope.removeSource")} onClick={() => setFind((f) => ({ ...f, source: null }))}>
                <X size={11} />
              </button>
            </span>
          ) : null}
          <div className={s.findText}>
            <TextField value={text} onChange={setText} label={t("library.search")} placeholder={t("library.searchPlaceholder")} testId="library-search" />
          </div>
        </div>
        <Button
          variant={find.starred ? "primary" : "flat"}
          icon={<Star />}
          onPress={() => setFind((f) => ({ ...f, starred: !f.starred }))}
          aria-label={t("library.starredOnly")}
          title={t("library.starredOnly")}
          aria-pressed={find.starred}
          data-testid="library-starred"
        />
        {props.project ? (
          <Button
            variant={props.project.active ? "primary" : "flat"}
            icon={<Folder />}
            onPress={props.project.toggle}
            aria-label={t("project.only")}
            title={t("project.only")}
            aria-pressed={props.project.active}
            data-testid="library-project-only"
          />
        ) : null}
      </div>
    </div>
  );
}

function presetName(filters: SavedFilter[], id: string | null): string | null {
  return filters.find((f) => f.id === id)?.name ?? null;
}

export function ScopeRow(props: {
  find: FindState;
  setFind: (f: (x: FindState) => FindState) => void;
  filters: SavedFilter[];
  facets: FacetValues | null;
  loadFacets: () => void;
  onSaveAs: () => void;
  onUpdate: () => void;
  onManage: () => void;
  onEditExpr: () => void;
  plusRef?: Ref<HTMLInputElement>;
}) {
  const { find, setFind, filters } = props;
  const [q, setQ] = useState("");
  const tags = find.tags;
  const preset = filters.find((f) => f.id === find.preset) ?? null;
  const expr = scopeExpression(tags, find.legacyExpr);
  const canSave = !find.legacyExpr && !!scopeSize(tags);
  const modified = preset != null && (!!find.legacyExpr || !sameScope(normScope(preset.conditions), tags));
  const setTags = (next: Scope) => setFind((f) => ({ ...f, tags: next }));

  const add = (facet: Facet, value: string) => {
    const i = tags.facets.findIndex((f) => f.facet === facet);
    if (i < 0) return setTags({ ...tags, facets: [...tags.facets, { facet, values: [value], single: false }] });
    const cur = tags.facets[i]!;
    if (cur.values.includes(value)) return;
    setTags({ ...tags, facets: tags.facets.map((f, k) => (k === i ? { ...f, values: [...f.values, value] } : f)) });
  };

  const groups = useMemo<SuggestGroup[]>(() => {
    const needle = q.trim().toLowerCase();
    const out: SuggestGroup[] = [];
    for (const f of FACETS) {
      const label = t(`facet.${f}`);
      const vals = (props.facets?.[f] ?? []).filter((v) => !needle || v.value.toLowerCase().includes(needle) || label.toLowerCase().includes(needle));
      if (!vals.length) continue;
      out.push({
        id: `g:${f}`,
        title: label,
        items: vals.slice(0, needle ? 50 : 8).map((v) => ({
          id: `${f}\x1f${v.value}`,
          label: v.value,
          detail: f === "person" && v.single != null && v.single !== v.count ? t("scope.countSingle", { n: v.count, m: v.single }) : String(v.count),
          lang: f === "person" || f === "work" ? "ja" : undefined,
        })),
      });
    }
    out.push({ id: "g:adv", title: t("scope.advanced"), items: [{ id: "adv:expr", label: t("scope.addExpr") }] });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, props.facets]);

  const chips: ChipItem[] = [
    ...tags.facets.map((f, i) => ({
      id: `f:${i}`,
      k: `${t(`facet.${f.facet}`)}${f.single ? t("scope.singleMark") : ""}`,
      v: f.values.join(t("scope.or")),
      lang: f.facet === "person" || f.facet === "work" ? "ja" : undefined,
    })),
    ...(expr ? [{ id: "expr", k: t("scope.exprChip"), v: expr }] : []),
  ];

  const presetItems: MenuItems = [
    { id: "preset-clear", label: t("scope.clear"), disabled: !scopeSize(tags) && !preset, run: () => setFind((f) => ({ ...f, preset: null, tags: EMPTY_SCOPE, legacyExpr: undefined })) },
    ...(modified && preset ? [{
      id: "preset-restore", label: t("scope.restorePreset"),
      run: () => setFind((f) => ({ ...f, tags: normScope(preset.conditions), legacyExpr: undefined })),
    }] : []),
    "-",
    ...filters.map((f) => ({
      id: `preset-${f.id}`,
      label: `${f.name}  ·  ${scopeSummary(normScope(f.conditions))}`,
      disabled: f.id === find.preset,
      run: () => setFind((x) => ({ ...x, preset: f.id, tags: normScope(f.conditions), legacyExpr: undefined })),
    })),
    ...(filters.length ? (["-"] as MenuItems) : []),
    { id: "preset-save", label: t("scope.saveAsDots"), disabled: !canSave, run: props.onSaveAs },
    { id: "preset-manage", label: t("scope.manageDots"), disabled: !filters.length, run: props.onManage },
  ];

  return (
    <div className={s.scopeRow} data-testid="scope-row">
      <span className={s.scopeLabel}>{t("scope.label")}</span>
      <Menu
        head={t("scope.presetHead")}
        items={presetItems}
        trigger={
          <Button size="sm" variant="flat" icon={<Flag />} data-testid="scope-preset">
            {presetName(filters, find.preset) ?? t(scopeSize(tags) ? "scope.custom" : "scope.all")}
            <ChevronDown size={12} />
          </Button>
        }
      />
      <Chips
        label={t("scope.label")}
        items={chips}
        testId="scope-chips"
        onRemove={(id) => {
          if (id === "expr") return setFind((f) => ({ ...f, tags: { ...f.tags, expr: "" }, legacyExpr: undefined }));
          const i = Number(id.slice(2));
          setTags({ ...tags, facets: tags.facets.filter((_, k) => k !== i) });
        }}
        onAction={(id) => {
          if (id === "expr") return props.onEditExpr();
          const i = Number(id.slice(2));
          const f = tags.facets[i];
          if (f?.facet === "person") setTags({ ...tags, facets: tags.facets.map((x, k) => (k === i ? { ...x, single: !x.single } : x)) });
        }}
        trailing={
          <span className={s.scopePlus} onFocusCapture={props.loadFacets}>
            <Suggest
              groups={groups}
              query={q}
              onQuery={setQ}
              onPick={(id) => {
                if (id === "adv:expr") return props.onEditExpr();
                const [facet, value] = id.split("\x1f") as [Facet, string];
                add(facet, value);
              }}
              label={t("scope.add")}
              placeholder="+"
              footer={t("scope.onlyTags")}
              testId="scope-add"
              inputRef={props.plusRef}
            />
          </span>
        }
      />
      <span className={s.grow} />
      {modified ? (
        <span className={s.scopeModified} data-testid="scope-modified">
          {t("scope.modified")}
          <Button size="sm" variant="flat" isDisabled={!!find.legacyExpr} onPress={props.onUpdate} data-testid="scope-update">
            {t("scope.update")}
          </Button>
          <Button size="sm" variant="flat" isDisabled={!canSave} onPress={props.onSaveAs}>
            {t("scope.saveAsShort")}
          </Button>
        </span>
      ) : !preset && scopeSize(tags) ? (
        <Button size="sm" variant="flat" isDisabled={!canSave} onPress={props.onSaveAs} data-testid="scope-save">
          {t("scope.saveAs")}
        </Button>
      ) : null}
    </div>
  );
}
