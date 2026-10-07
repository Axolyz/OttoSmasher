// 原片列表（UI_PLAN §4、§6.1）：按作品分组、默认折叠（当前原片所在组展开）；搜索作品 / 集数 / 文件名。
// 单击 = 焦点（打开到查看器），从不改变勾选；复选框 / ⌘+单击切换勾选；Shift+单击连续勾选；Esc 清空勾选；
// 右键 = 菜单，对象是“已勾选 N 项”（在勾选集里且 ≥2）或这一项，不改变勾选和焦点。
import { AudioLines, ChevronDown, ChevronRight, Film, MoreHorizontal, Plus } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { TextField } from "../components/Fields";
import { Menu, type MenuEntry } from "../components/Overlay";
import { basename, clock, stem } from "../format";
import { t } from "../i18n";
import s from "./Sources.module.css";

export function displayName(r: Pick<SourceRow, "work" | "episode" | "path">): string {
  if (r.work && r.episode) return `${r.work} ${r.episode}`;
  return r.work || stem(r.path);
}

function rowTitle(r: SourceRow): string {
  return r.episode ? t("sources.episode", { n: r.episode }) : stem(r.path);
}

export function SourceList(props: {
  rows: SourceRow[];
  current: string | null;
  expanded: string[];
  checked: Set<string>;
  onOpen: (id: string) => void;
  onToggleGroup: (work: string) => void;
  onChecked: (s: Set<string>) => void;
  onAdd: () => void;
  onSettings: (id: string) => void;
  onRelocate: (id: string) => void;
  onDelete: (ids: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const anchor = useRef<string | null>(null);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const hit = (r: SourceRow) =>
      !needle || [r.work, r.episode, basename(r.path)].some((x) => x.toLowerCase().includes(needle));
    const map = new Map<string, SourceRow[]>();
    for (const r of props.rows) {
      if (!hit(r)) continue;
      const g = map.get(r.work) ?? [];
      g.push(r);
      map.set(r.work, g);
    }
    // 组按作品名排序，“未指定作品”在最后；组内按登记时间倒序（Core 已排好）
    return [...map.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  }, [props.rows, q]);
  const flat = groups.flatMap(([, rs]) => rs);
  const searching = q.trim() !== "";

  const toggle = (id: string) => {
    const next = new Set(props.checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    anchor.current = id;
    props.onChecked(next);
  };
  const extend = (id: string) => {
    const from = flat.findIndex((r) => r.id === (anchor.current ?? props.current));
    const to = flat.findIndex((r) => r.id === id);
    if (from < 0 || to < 0) return toggle(id);
    const next = new Set(props.checked);
    for (const r of flat.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(r.id);
    props.onChecked(next);
  };

  const menuItems = (r: SourceRow): { head: string; items: Array<MenuEntry | "-"> } => {
    const multi = props.checked.has(r.id) && props.checked.size >= 2;
    if (multi) {
      const ids = [...props.checked];
      return {
        head: t("menu.checkedN", { n: ids.length }),
        items: [{ id: "delete", label: t("sources.delete"), danger: true, run: () => props.onDelete(ids) }],
      };
    }
    return {
      head: t("menu.source", { name: displayName(r) }),
      items: [
        { id: "settings", label: t("sources.settings"), run: () => props.onSettings(r.id) },
        { id: "relocate", label: t("sources.relocate"), run: () => props.onRelocate(r.id) },
        { id: "reveal", label: t("sources.reveal"), run: () => void window.otto.files.reveal(r.path) },
        "-",
        { id: "delete", label: t("sources.delete"), danger: true, shortcut: "⌫", run: () => props.onDelete([r.id]) },
      ],
    };
  };

  return (
    <aside className={s.list} data-testid="source-list">
      <div className={s.listHead}>
        <TextField value={q} onChange={setQ} label={t("sources.search")} placeholder={t("sources.search")} testId="sources-search" />
        <Button variant="secondary" icon={<Plus />} onPress={props.onAdd} title={t("sources.add")} data-testid="sources-add" />
      </div>
      {props.checked.size ? (
        <div className={s.checkedBar} data-testid="sources-checked">
          {t("sources.checkedN", { n: props.checked.size })}
          <span className={s.grow} />
          <Button size="sm" variant="danger" onPress={() => props.onDelete([...props.checked])}>
            {t("sources.delete")}
          </Button>
          <Button size="sm" variant="flat" onPress={() => props.onChecked(new Set())}>
            {t("sources.clearChecked")}
          </Button>
        </div>
      ) : null}
      <div
        className={s.listBody}
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === "Escape" && props.checked.size) {
            e.stopPropagation();
            props.onChecked(new Set());
          } else if ((e.key === "Delete" || e.key === "Backspace") && !(e.target instanceof HTMLInputElement)) {
            const ids = props.checked.size ? [...props.checked] : props.current ? [props.current] : [];
            if (ids.length) props.onDelete(ids);
          }
        }}
      >
        {groups.map(([work, rs]) => {
          const open = searching || props.expanded.includes(work);
          return (
            <div key={work || "\u0000"}>
              <button type="button" className={s.group} onClick={() => props.onToggleGroup(work)} data-testid="source-group" data-work={work}>
                {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <span className={s.groupName} data-user-data={work ? "" : undefined}>
                  {work || t("sources.noWork")}
                </span>
                <span className="num">{t("sources.groupCount", { n: rs.length })}</span>
              </button>
              {open
                ? rs.map((r) => {
                    const m = menuItems(r);
                    return (
                      <div
                        key={r.id}
                        className={s.row}
                        data-testid="source-row"
                        data-id={r.id}
                        data-focus={r.id === props.current || undefined}
                        data-checked={props.checked.has(r.id) || undefined}
                        onClick={(e) => {
                          if (e.metaKey || e.ctrlKey) toggle(r.id);
                          else if (e.shiftKey) extend(r.id);
                          else {
                            anchor.current = r.id;
                            props.onOpen(r.id);
                          }
                        }}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          setMenuFor(r.id);
                        }}
                      >
                        <input
                          type="checkbox"
                          className={s.check}
                          checked={props.checked.has(r.id)}
                          aria-label={t("sources.check", { name: displayName(r) })}
                          onClick={(e) => e.stopPropagation()}
                          onChange={() => toggle(r.id)}
                        />
                        <span className={s.kind}>{r.has_video ? <Film /> : <AudioLines />}</span>
                        <div className={s.rowMain}>
                          <div className={s.rowTitle} title={basename(r.path)} data-user-data={r.episode ? undefined : ""}>
                            {rowTitle(r)}
                          </div>
                          <div className={s.rowMeta}>
                            <span className="num">{clock(r.duration, 0)}</span>
                            {!r.has_video ? <span>{t("sources.audioOnly")}</span> : null}
                            {r.audio_streams > 1 ? <span>{t("sources.nTracks", { n: r.audio_streams })}</span> : null}
                            <span>{r.subtitle_path ? t("sources.hasSubtitle") : t("sources.noSubtitle")}</span>
                          </div>
                        </div>
                        <span className={s.rowMenu} onClick={(e) => e.stopPropagation()}>
                          <Menu
                            head={m.head}
                            items={m.items}
                            isOpen={menuFor === r.id}
                            onOpenChange={(o) => setMenuFor(o ? r.id : null)}
                            trigger={<Button size="sm" variant="flat" icon={<MoreHorizontal />} aria-label={t("menu.more")} />}
                          />
                        </span>
                      </div>
                    );
                  })
                : null}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
