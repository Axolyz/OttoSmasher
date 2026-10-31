// 台本（规格 03 §3.4 字幕上下文、UI_PLAN §4；原型 renderSources 的 .line）：文本层的段（所有者 2026-10-09：字幕上下文显示文本层的段）。
// 当前播放的那段高亮并跟随（手动滚动后 3.5 秒内暂停跟随）；单击 = 选区设为该段并跳到开头（不播放）；Shift 单击 = 扩展选区到该段；
// 双击 = 播放该段；右键 = 这段的菜单（建采样、语音分析、编辑……，由查看器给）；OP/ED 内的连续段折成一块“♪ OP”（单击选中整段）。
// 每行：时间、说话人、文本；两个受保护标记（改过 / 有人工音素版本）可见。
import { FileText, Info } from "lucide-react";
import { useMemo } from "react";
import type { OpedRange, TextSegment } from "../api/types";
import { ActionList } from "../components/ActionList";
import { Button } from "../components/Button";
import { EmptyState } from "../components/Controls";
import { Tip } from "../components/Overlay";
import { clock } from "../format";
import { t } from "../i18n";
import s from "./Sources.module.css";

export type Seg = TextSegment;
export type Oped = OpedRange;

type Row = { id: string; kind: "seg"; seg: Seg } | { id: string; kind: "oped"; oped: Oped; n: number };

export function Transcript(props: {
  segs: Seg[];
  opeds: Oped[];
  playhead: number | null;
  sel: { a: number; b: number } | null;
  hasSubtitleFile: boolean;
  /** 原片关联了字幕但文本层是空的：一键「导入到文本层」 */
  canQuickImport: boolean;
  onSelect: (a: number, b: number, mode: "set" | "extend") => void;
  onPlay: (a: number, b: number) => void;
  onImport: () => void;
  onQuickImport: () => void;
  onMenu: (seg: Seg, at: { x: number; y: number }) => void;
}) {
  const rows = useMemo(() => {
    const out: Row[] = [];
    const seen = new Set<string>();
    for (const a of props.segs) {
      if (a.oped) {
        const o = props.opeds.find((x) => x.kind === a.oped && x.start < a.end && x.end > a.start);
        if (o) {
          if (!seen.has(o.id)) {
            seen.add(o.id);
            out.push({ id: `oped:${o.id}`, kind: "oped", oped: o, n: props.segs.filter((x) => x.oped && x.start < o.end && x.end > o.start).length });
          }
          continue;
        }
      }
      out.push({ id: a.id, kind: "seg", seg: a });
    }
    return out;
  }, [props.segs, props.opeds]);
  const range = (r: Row): [number, number] => (r.kind === "seg" ? [r.seg.start, r.seg.end] : [r.oped.start, r.oped.end]);
  const ph = props.playhead;
  const current = ph == null ? null : (rows.find((r) => ph >= range(r)[0] && ph < range(r)[1])?.id ?? null);
  const selected = useMemo(() => {
    const set = new Set<string>();
    if (props.sel) for (const r of rows) if (Math.abs(range(r)[0] - props.sel.a) < 1e-6 && Math.abs(range(r)[1] - props.sel.b) < 1e-6) set.add(r.id);
    return set;
  }, [rows, props.sel]);

  return (
    <div className={s.transcript} data-testid="transcript">
      <div className={s.transcriptHead}>
        <span>{t("sources.transcript")}</span>
        <span className={s.transcriptSub}>{t("transcript.follow")}</span>
        <Tip content={t("transcript.help")}>
          <Button variant="flat" size="sm" icon={<Info />} aria-label={t("transcript.help")} />
        </Tip>
      </div>
      {rows.length ? (
        <ActionList<Row>
          label={t("sources.transcript")}
          items={rows}
          textValue={(r) => (r.kind === "seg" ? r.seg.text : r.oped.kind)}
          current={current}
          selected={selected}
          testId="transcript-list"
          rowTestId="transcript-row"
          onPress={(id, m) => {
            const r = rows.find((x) => x.id === id);
            if (r) props.onSelect(...range(r), m.shift ? "extend" : "set");
          }}
          onDouble={(id) => {
            const r = rows.find((x) => x.id === id);
            if (r) props.onPlay(...range(r));
          }}
          onContext={(id, at) => {
            const r = rows.find((x) => x.id === id);
            if (r?.kind === "seg") props.onMenu(r.seg, at);
          }}
          render={(r) =>
            r.kind === "oped" ? (
              <div className={s.opedBlock}>
                <span className={s.opedNote}>♪ {r.oped.kind}</span>
                <span className="num">{`${r.oped.start.toFixed(1)}–${r.oped.end.toFixed(1)} s`}</span>
                <span className={s.muted}>{t("transcript.opedNote", { n: r.n })}</span>
              </div>
            ) : (
              <>
                <span className={`${s.muted} num`}>{clock(r.seg.start, 1)}</span>
                <span className={s.who} lang="ja" data-user-data="">
                  {r.seg.speakers.join(t("settings.subtitle.speakerSep"))}
                  {r.seg.speakersWithheld ? (
                    <span className={s.segFlags} data-testid="seg-withheld" title={t("seg.withheld")}>
                      ?
                    </span>
                  ) : null}
                </span>
                <span className={s.segText}>
                  <span lang="ja" data-user-data="">
                    {r.seg.text.replace(/\n/g, " ")}
                  </span>
                  {r.seg.edited || r.seg.manual ? (
                    <span className={s.segFlags} data-testid="seg-flags" title={[r.seg.edited ? t("seg.flag.edited") : "", r.seg.manual ? t("seg.flag.manual") : ""].filter(Boolean).join(" · ")}>
                      {r.seg.edited ? "✎" : ""}
                      {r.seg.manual ? "◆" : ""}
                    </span>
                  ) : null}
                </span>
              </>
            )
          }
        />
      ) : (
        <EmptyState
          size="inline"
          icon={<FileText />}
          title={props.hasSubtitleFile ? t("transcript.notImported") : t("transcript.noSubtitle")}
          body={props.hasSubtitleFile ? t("transcript.notImportedBody") : t("sources.noSubtitleHint")}
          actions={
            <>
              {props.canQuickImport ? (
                <Button size="sm" variant="primary" onPress={props.onQuickImport} data-testid="transcript-quick-import">
                  {t("subimport.quick")}
                </Button>
              ) : null}
              <Button size="sm" variant={props.hasSubtitleFile && !props.canQuickImport ? "primary" : "flat"} onPress={props.onImport} data-testid="transcript-import">
                {t("subimport.menu")}
              </Button>
            </>
          }
        />
      )}
    </div>
  );
}
