// 保存筛选器的对话框（规格 07 §7.3；UI_PLAN §2.3；原型 saveFilterModal 与「管理筛选器」）：
// 存为筛选器（名称 1–200 字；只存范围行的标签条件）、管理（改名、上移下移〔一次编辑原子改顺序〕、删除〔确认〕），都走编辑通道、可撤销。
// 范围行的高级表达式在应用前由 Core 校验。
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SavedFilter } from "../api/types";
import { Button } from "../components/Button";
import { TextField } from "../components/Fields";
import { ConfirmDialog, DialogBox } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { type Scope, normScope, scopeSize, scopeSummary } from "./FindBar";
import s from "./Library.module.css";

async function apply(label: { code: string; args?: Record<string, unknown> }, ops: unknown[]): Promise<string | null> {
  const r = await call("edits.apply", { batch: { label, ops } as never });
  return r.changes[0]?.id ?? null;
}

export function SaveFilterDialog(props: { isOpen: boolean; scope: Scope; filters: SavedFilter[]; onClose: () => void; onSaved: (id: string) => void }) {
  const toast = useApp((st) => st.toast);
  const [name, setName] = useState("");
  useEffect(() => {
    if (props.isOpen) setName("");
  }, [props.isOpen]);
  const save = async () => {
    const v = name.trim();
    if (!v) return;
    try {
      const order = Math.max(-1, ...props.filters.map((f) => f.sortOrder)) + 1;
      const id = await apply({ code: "filter-save", args: { name: v } }, [
        { entity: "saved_filter", op: "create", fields: { name: v, conditions: props.scope, sort_order: order } },
      ]);
      if (id) props.onSaved(id);
      toast({ text: t("scope.saved", { name: v }) });
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  return (
    <ConfirmDialog
      isOpen={props.isOpen}
      title={t("scope.saveTitle")}
      confirmLabel={t("scope.saveOk")}
      confirmDisabled={!name.trim() || name.trim().length > 200 || !scopeSize(props.scope)}
      onConfirm={() => void save()}
      onClose={props.onClose}
      testId="filter-save"
    >
      <div className={s.hintText}>{t("scope.saveSay", { n: scopeSize(props.scope) })}</div>
      <div className={s.mutedText}>{scopeSummary(props.scope)}</div>
      <TextField value={name} onChange={setName} onSubmit={() => void save()} autoFocus label={t("scope.nameLabel")} placeholder={t("scope.namePlaceholder")} testId="filter-name" />
    </ConfirmDialog>
  );
}

export function ManageFiltersDialog(props: { isOpen: boolean; filters: SavedFilter[]; onClose: () => void; onChanged: () => void }) {
  const toast = useApp((st) => st.toast);
  const [names, setNames] = useState<Record<string, string>>({});
  const [del, setDel] = useState<SavedFilter | null>(null);
  useEffect(() => {
    if (props.isOpen) setNames(Object.fromEntries(props.filters.map((f) => [f.id, f.name])));
  }, [props.isOpen, props.filters]);
  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      props.onChanged();
    }
  };
  const rename = (f: SavedFilter) => {
    const v = (names[f.id] ?? "").trim();
    if (!v || v === f.name) return setNames((n) => ({ ...n, [f.id]: f.name }));
    void run(() => apply({ code: "filter-rename", args: { name: v } }, [{ entity: "saved_filter", id: f.id, version: f.version, fields: { name: v } }]));
  };
  /** 上移 / 下移：按新顺序给所有筛选器重新编号（一次编辑，原子） */
  const move = (i: number, d: -1 | 1) => {
    const order = [...props.filters];
    const j = i + d;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j]!, order[i]!];
    const ops = order.flatMap((f, k) => (f.sortOrder === k ? [] : [{ entity: "saved_filter", id: f.id, version: f.version, fields: { sort_order: k } }]));
    void run(() => apply({ code: "filter-reorder" }, ops));
  };
  return (
    <>
      <DialogBox isOpen={props.isOpen} onClose={props.onClose} title={t("scope.manageTitle")} sub={t("scope.manageSub")} width={680} testId="filter-manage">
        <PagedTable<SavedFilter>
          label={t("scope.manageTitle")}
          rows={props.filters}
          pageSize={50}
          columns={[
            {
              id: "name",
              label: t("scope.nameLabel"),
              width: "34%",
              isRowHeader: true,
              render: (f) => (
                <span onBlur={() => rename(f)}>
                  <TextField value={names[f.id] ?? f.name} onChange={(v) => setNames((n) => ({ ...n, [f.id]: v }))} onSubmit={() => rename(f)} label={t("scope.nameLabel")} testId="filter-rename" />
                </span>
              ),
            },
            { id: "cond", label: t("scope.conditions"), render: (f) => <span className={s.mutedText}>{scopeSummary(normScope(f.conditions))}</span> },
            {
              id: "ops",
              label: "",
              width: "120px",
              align: "end",
              render: (f) => {
                const i = props.filters.findIndex((x) => x.id === f.id);
                return (
                  <span className={s.rowOps}>
                    <Button size="sm" variant="flat" icon={<ArrowUp />} isDisabled={i <= 0} onPress={() => move(i, -1)} aria-label={t("scope.moveUp")} />
                    <Button size="sm" variant="flat" icon={<ArrowDown />} isDisabled={i >= props.filters.length - 1} onPress={() => move(i, 1)} aria-label={t("scope.moveDown")} />
                    <Button size="sm" variant="flat" icon={<Trash2 />} onPress={() => setDel(f)} aria-label={t("scope.delete")} data-testid="filter-delete" />
                  </span>
                );
              },
            },
          ]}
        />
      </DialogBox>
      <ConfirmDialog
        isOpen={!!del}
        title={t("scope.deleteTitle", { name: del?.name ?? "" })}
        confirmLabel={t("scope.delete")}
        danger
        onConfirm={() => {
          const f = del!;
          setDel(null);
          void run(() => apply({ code: "filter-delete", args: { name: f.name } }, [{ entity: "saved_filter", id: f.id, version: f.version, fields: { deleted: true } }]));
        }}
        onClose={() => setDel(null)}
        testId="filter-delete-confirm"
      >
        <div>{t("scope.deleteSay")}</div>
      </ConfirmDialog>
    </>
  );
}

export function ScopeExprDialog(props: { isOpen: boolean; value: string; onClose: () => void; onApply: (expr: string) => void }) {
  const [v, setV] = useState("");
  const [checked, setChecked] = useState<{ value: string; error: string | null } | null>(null);
  useEffect(() => {
    if (props.isOpen) {
      setV(props.value);
      setChecked(null);
    }
  }, [props.isOpen, props.value]);
  useEffect(() => {
    if (!props.isOpen) return;
    let active = true;
    const id = setTimeout(() => {
      void call("tags.checkExpr", { expr: v }).then(
        (r) => {
          if (!active) return;
          const error = r.ok ? null : t("error.tag-expr-invalid", { position: r.position!, reason: t(`reason.${r.reason}`) });
          setChecked({ value: v, error });
        },
        (e: unknown) => {
          if (active) setChecked({ value: v, error: e instanceof CoreFailure ? errorText(e.wire) : String(e) });
        },
      );
    }, 200);
    return () => {
      active = false;
      clearTimeout(id);
    };
  }, [v, props.isOpen, props.value]);
  const current = checked?.value === v ? checked : null;
  const error = current?.error;
  const canApply = current != null && error == null;
  const applyExpr = () => {
    if (!canApply) return;
    props.onApply(v.trim());
    props.onClose();
  };
  return (
    <ConfirmDialog isOpen={props.isOpen} title={t("scope.exprTitle")} confirmLabel={t("scope.exprOk")} confirmDisabled={!canApply} onConfirm={applyExpr} onClose={props.onClose} testId="scope-expr">
      <div className={s.hintText}>{t("scope.exprSay")}</div>
      <TextField value={v} onChange={setV} onSubmit={applyExpr} autoFocus mono invalid={!!error} label={t("scope.exprChip")} placeholder={t("scope.exprPlaceholder")} testId="scope-expr-input" />
      {error ? <div className={s.badText} role="alert" data-testid="expr-error">{error}</div> : <div className={s.mutedText}>{t("scope.exprHelp")}</div>}
    </ConfirmDialog>
  );
}
