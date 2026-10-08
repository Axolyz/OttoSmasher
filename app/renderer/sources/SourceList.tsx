// 原片列表（UI_PLAN §4、§6.1）：按作品分组、默认折叠（当前原片所在组展开）；搜索作品 / 集数 / 文件名。
// 选择规则全部来自 CollectionList（单击 = 打开到查看器，从不改变勾选；复选框 / ⌘ / Shift / X / ⌘A / Esc / Delete / 右键）。
// 行末 ⋯（悬停或焦点时出现）与右键是同一份菜单（所有者 2026-10-07：保留）。
import { AudioLines, ChevronDown, ChevronRight, Film, MoreHorizontal, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useThumb } from "../api/thumbs";
import type { SourceRow } from "../api/types";
import { BatchBar } from "../components/BatchBar";
import { Button } from "../components/Button";
import { CollectionList } from "../components/CollectionList";
import { EmptyState } from "../components/Controls";
import { TextField } from "../components/Fields";
import { Menu, type MenuSpec } from "../components/Menu";
import { Thumb } from "../components/Thumb";
import { basename, clock, stem } from "../format";
import { t } from "../i18n";
import { durationText, relDir } from "./rowInfo";
import s from "./Sources.module.css";

/** 原片的名字（用在导出文件名、菜单头等）：“作品 集数”，没有作品时用文件名。 */
export function displayName(r: Pick<SourceRow, "work" | "episode" | "path">): string {
  if (r.work && r.episode) return `${r.work} ${r.episode}`;
  return r.work || stem(r.path);
}

/** 顶栏里的原片标题：“作品 · 集数”（原型）。 */
export function displayTitle(r: Pick<SourceRow, "work" | "episode" | "path">): string {
  if (r.work && r.episode) return `${r.work} · ${r.episode}`;
  return basename(r.path); // 没有集数（短音频、单个视频）：文件名，同一作品下的才分得清（原型 hit_01.ogg）
}

function rowTitle(r: SourceRow): string {
  return r.episode ? t("sources.episode", { n: r.episode }) : basename(r.path);
}

type Item = { id: string; kind: "group"; work: string; n: number } | { id: string; kind: "item"; row: SourceRow };
const groupId = (work: string) => `g:${work}`;

export function SourceList(props: {
  rows: SourceRow[];
  current: string | null;
  expanded: string[];
  checked: Set<string>;
  onOpen: (id: string) => void;
  onToggleGroup: (work: string, open?: boolean) => void;
  onChecked: (s: Set<string>) => void;
  onAdd: () => void;
  menu: (r: SourceRow, ids: string[], multi: boolean) => MenuSpec;
  onDelete: (ids: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [rowMenu, setRowMenu] = useState<string | null>(null);
  const searching = q.trim() !== "";

  const { items, visible } = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const hit = (r: SourceRow) => !needle || [r.work, r.episode, basename(r.path)].some((x) => x.toLowerCase().includes(needle));
    const map = new Map<string, SourceRow[]>();
    for (const r of props.rows) {
      if (!hit(r)) continue;
      const g = map.get(r.work) ?? [];
      g.push(r);
      map.set(r.work, g);
    }
    // 组按作品名排序，“未指定作品”在最后；组内按登记时间倒序（Core 已排好）
    const groups = [...map.entries()].sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
    const out: Item[] = [];
    const vis: string[] = [];
    for (const [work, rs] of groups) {
      out.push({ id: groupId(work), kind: "group", work, n: rs.length });
      if (searching || props.expanded.includes(work))
        for (const r of rs) {
          out.push({ id: r.id, kind: "item", row: r });
          vis.push(r.id);
        }
    }
    return { items: out, visible: vis };
  }, [props.rows, props.expanded, q, searching]);
  const workOf = (gid: string) => gid.slice(2);

  return (
    <aside className={s.list} data-testid="source-list">
      <div className={s.listHead}>
        <TextField value={q} onChange={setQ} label={t("sources.search")} placeholder={t("sources.search")} testId="sources-search" />
        <Button variant="primary" icon={<Plus />} onPress={props.onAdd} title={t("sources.add")} data-testid="sources-add" />
      </div>
      <CollectionList<Item>
        label={t("sources.listLabel")}
        items={items}
        textValue={(i) => (i.kind === "group" ? i.work || t("sources.noWork") : displayName(i.row))}
        focus={props.current}
        onFocus={props.onOpen}
        checked={props.checked}
        onChecked={props.onChecked}
        onCheckAll={() => props.onChecked(new Set(visible))}
        onPrimary={props.onOpen}
        onGroup={(gid, open) => props.onToggleGroup(workOf(gid), open)}
        isGroupOpen={(gid) => searching || props.expanded.includes(workOf(gid))}
        onDelete={props.onDelete}
        menu={(i, target) => (i.kind === "item" ? props.menu(i.row, target.ids, target.multi) : null)}
        checkLabel={(i) => t("sources.check", { name: i.kind === "item" ? displayName(i.row) : "" })}
        rowTestId="source-row"
        groupTestId="source-group"
        empty={q ? <EmptyState size="inline" title={t("sources.noMatch")} /> : null}
        renderGroup={(i, open) =>
          i.kind === "group" ? (
            <>
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <span className={s.groupName} data-user-data={i.work ? "" : undefined}>
                {i.work || t("sources.noWork")}
              </span>
              <span className={`${s.groupCount} num`}>{t("sources.groupCount", { n: i.n })}</span>
            </>
          ) : null
        }
        renderItem={(i) => {
          if (i.kind !== "item") return null;
          const r = i.row;
          const m = props.menu(r, [r.id], false);
          return (
            <>
              <SourceThumb id={r.id} hasVideo={r.has_video || r.has_picture} />
              <div className={s.rowMain}>
                <div className={s.rowTitle} title={basename(r.path)} data-user-data={r.episode ? undefined : ""}>
                  {rowTitle(r)}
                </div>
                {/* 只按内容显示（所有者 2026-10-07：原片只有一种）；05 §5.8：句数 = 当前字幕版本中不在 OP/ED 的台词数 */}
                <div className={s.rowMeta}>
                  <span className="num">{durationText(r.duration)}</span>
                  {relDir(r) ? (
                    <span className={s.faint} data-user-data="">
                      {relDir(r)}
                    </span>
                  ) : null}
                  {r.counts?.hasMarkers ? (
                    <span className="num">{t("sources.lines", { n: r.counts.lines })}</span>
                  ) : r.subtitle_path ? (
                    <span>{t("sources.notImported")}</span>
                  ) : r.has_video ? (
                    <span>{t("sources.noSubtitle")}</span>
                  ) : null}
                  {r.counts?.oped ? <span className="num">{t("sources.opedN", { n: r.counts.oped })}</span> : null}
                  {r.has_picture ? <span>{t("sources.samePicture")}</span> : !r.has_video ? <span>{t("sources.audioOnly")}</span> : null}
                  {r.audio_streams > 1 ? <span>{t("sources.nTracks", { n: r.audio_streams })}</span> : null}
                  {r.missing ? <span className={s.warn}>{t("sources.fileMissing")}</span> : null}
                </div>
              </div>
              <span className={s.rowMenu} data-open={rowMenu === r.id || undefined}>
                <Menu
                  head={m.head}
                  items={m.items}
                  isOpen={rowMenu === r.id}
                  onOpenChange={(o) => setRowMenu(o ? r.id : null)}
                  trigger={<Button size="sm" variant="flat" icon={<MoreHorizontal />} aria-label={t("menu.more")} />}
                />
              </span>
            </>
          );
        }}
        footer={
          <BatchBar
            count={props.checked.size}
            onClear={() => props.onChecked(new Set())}
            items={(() => {
              const ids = [...props.checked];
              const first = props.rows.find((r) => r.id === ids[0]);
              return first ? props.menu(first, ids, true).items : [];
            })()}
            testId="sources-checked"
          />
        }
      />
    </aside>
  );
}

function SourceThumb(props: { id: string; hasVideo: boolean }) {
  const url = useThumb("source", props.id);
  return <Thumb size="sm" url={props.hasVideo ? url : null} placeholder={props.hasVideo ? <Film /> : <AudioLines />} testId="source-thumb" />;
}
