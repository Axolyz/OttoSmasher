// 台本（规格 03 §3.4 字幕上下文、UI_PLAN §4；原型 renderSources 的 .line）：当前字幕版本的台词 / 音效（含手动标的歌词），
// 当前播放的那句高亮并跟随（手动滚动后 3.5 秒内暂停跟随）；单击 = 选区设为该句并跳到开头（不播放）；Shift 单击 = 扩展选区到该句；
// 双击 = 播放该句；OP/ED 内的连续行折成一块“♪ OP · 排除字幕采样与批量分析”（单击选中整段）；音效行斜体。
import { FileText, Info } from "lucide-react";
import { useMemo } from "react";
import type { AnnotationRow, OpedRange } from "../api/types";
import { ActionList } from "../components/ActionList";
import { Button } from "../components/Button";
import { EmptyState } from "../components/Controls";
import { Tip } from "../components/Overlay";
import { clock } from "../format";
import { t } from "../i18n";
import s from "./Sources.module.css";

export type Ann = AnnotationRow;
export type Oped = OpedRange;

type Row = { id: string; kind: "ann"; ann: Ann } | { id: string; kind: "oped"; oped: Oped; n: number };

export function Transcript(props: {
  anns: Ann[];
  opeds: Oped[];
  playhead: number | null;
  sel: { a: number; b: number } | null;
  hasSubtitleFile: boolean;
  onSelect: (a: number, b: number, mode: "set" | "extend") => void;
  onPlay: (a: number, b: number) => void;
  onImport: () => void;
}) {
  const rows = useMemo(() => {
    const out: Row[] = [];
    const seen = new Set<string>();
    for (const a of props.anns) {
      if (a.kind === "tag") continue;
      if (a.oped) {
        const o = props.opeds.find((x) => x.kind === a.oped && x.start < a.end && x.end > a.start);
        if (o) {
          if (!seen.has(o.id)) {
            seen.add(o.id);
            out.push({ id: `oped:${o.id}`, kind: "oped", oped: o, n: props.anns.filter((x) => x.oped && x.start < o.end && x.end > o.start).length });
          }
          continue;
        }
      }
      out.push({ id: a.id, kind: "ann", ann: a });
    }
    return out;
  }, [props.anns, props.opeds]);
  const range = (r: Row): [number, number] => (r.kind === "ann" ? [r.ann.start, r.ann.end] : [r.oped.start, r.oped.end]);
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
          textValue={(r) => (r.kind === "ann" ? r.ann.name || r.ann.text : r.oped.kind)}
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
          render={(r) =>
            r.kind === "oped" ? (
              <div className={s.opedBlock}>
                <span className={s.opedNote}>♪ {r.oped.kind}</span>
                <span className="num">{`${r.oped.start.toFixed(1)}–${r.oped.end.toFixed(1)} s`}</span>
                <span className={s.muted}>{t("transcript.opedNote", { n: r.n })}</span>
              </div>
            ) : (
              <>
                <span className={`${s.muted} num`}>{clock(r.ann.start, 1)}</span>
                <span className={s.who} lang="ja" data-user-data="">
                  {r.ann.speakers.join(t("settings.subtitle.speakerSep"))}
                </span>
                <span className={r.ann.kind === "sfx" ? s.sfxLine : undefined} lang="ja" data-user-data="">
                  {r.ann.kind === "sfx" ? t("transcript.sfx", { name: r.ann.name }) : r.ann.name || r.ann.text}
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
            <Button size="sm" variant={props.hasSubtitleFile ? "primary" : "flat"} onPress={props.onImport} data-testid="transcript-import">
              {t("subimport.menu")}
            </Button>
          }
        />
      )}
    </div>
  );
}
