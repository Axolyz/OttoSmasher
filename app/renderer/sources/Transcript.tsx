// 台本（规格 03 §3.4 字幕上下文、UI_PLAN §4；原型 renderSources 的 .line）：文本层的段（所有者 2026-10-09：字幕上下文显示文本层的段）。
// 当前播放的那段高亮并跟随（手动滚动后 3.5 秒内暂停跟随）；单击 = 选区设为该段并跳到开头（不播放）；Shift 单击 = 扩展选区到该段；
// 双击 = 播放该段；右键 = 这段的菜单（建采样、语音分析、编辑……，由查看器给）；OP/ED 内的连续段折成一块“♪ OP”（单击选中整段）。
// 每行：时间、说话人、文本；两个受保护标记（改过 / 有人工音素版本）可见。
// 搜索（所有者 2026-10-31）：在这一集的段里搜关键词（原文或读音，同采样的“原句”筛选），命中高亮、其余变淡；
// 回车 / Shift 回车跳到下一处 / 上一处（= 单击那一行：选区设为该段、跳到开头），Esc 清空；⌘⇧F 或在台本里按 / 聚焦。
import { ChevronDown, ChevronUp, FileText, Info } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { call } from "../api/core";
import type { OpedRange, TextSegment } from "../api/types";
import { ActionList } from "../components/ActionList";
import { Button } from "../components/Button";
import { EmptyState } from "../components/Controls";
import { TextField } from "../components/Fields";
import { Tip } from "../components/Overlay";
import { clock } from "../format";
import { t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

/** 原文里命中的字符范围标出来（读音命中没有范围） */
export function marked(text: string, spans: number[][] | undefined): ReactNode {
  if (!spans?.length) return text;
  const out: ReactNode[] = [];
  let at = 0;
  for (const [a, b] of spans) {
    if (a! > at) out.push(text.slice(at, a));
    out.push(
      <mark key={a} className={s.hit}>
        {text.slice(a, b)}
      </mark>,
    );
    at = b!;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

/** 这一集里的搜索：命中段 id → 原文范围（按时间） */
function useSegmentSearch(sourceId: string, q: string, segs: TextSegment[]) {
  const [hits, setHits] = useState<Map<string, number[][]> | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    const n = ++seq.current;
    if (!q.trim()) return setHits(null);
    const timer = setTimeout(() => {
      void call("textLayer.search", { query: q, sourceIds: [sourceId], hints: false, limit: 5000 }).then(
        (r) => n === seq.current && setHits(new Map(r.hits.map((h) => [h.id, h.spans]))),
        () => n === seq.current && setHits(new Map()),
      );
    }, 150);
    return () => clearTimeout(timer);
  }, [sourceId, q, segs]);
  return hits;
}

export type Seg = TextSegment;
export type Oped = OpedRange;

type Row = { id: string; kind: "seg"; seg: Seg } | { id: string; kind: "oped"; oped: Oped; n: number };

export function Transcript(props: {
  sourceId: string;
  segs: Seg[];
  opeds: Oped[];
  playhead: number | null;
  sel: { a: number; b: number } | null;
  hasSubtitleFile: boolean;
  /** 原片关联了字幕但文本层是空的：一键「导入到文本层」 */
  canQuickImport: boolean;
  onSelect: (a: number, b: number, mode: "set" | "extend") => void;
  /** 搜索跳到一处：选区设为该段、跳到开头（焦点留在搜索框） */
  onJump: (a: number, b: number) => void;
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

  const [q, setQ] = useState("");
  const hits = useSegmentSearch(props.sourceId, q, props.segs);
  const order = useMemo(() => (hits ? props.segs.filter((g) => hits.has(g.id)) : []), [hits, props.segs]);
  const [at, setAt] = useState(-1);
  useEffect(() => setAt(-1), [hits]);
  const go = (step: 1 | -1) => {
    if (!order.length) return;
    const n = order.length;
    let i: number;
    if (at >= 0) i = (at + step + n) % n;
    else {
      // 第一次跳：从播放头往后找第一处（Shift：往前找最后一处），找不到就绕回
      const k = order.findIndex((g) => g.start >= (ph ?? 0) - 1e-6);
      i = step > 0 ? (k < 0 ? 0 : k) : ((k < 0 ? n : k) - 1 + n) % n;
    }
    setAt(i);
    props.onJump(order[i]!.start, order[i]!.end);
  };
  const box = useRef<HTMLDivElement>(null);
  const focusSearch = () => box.current?.querySelector<HTMLInputElement>('[data-testid="transcript-search"]')?.focus();
  const page = useApp((st) => st.page);
  useEffect(() => {
    if (page !== "sources") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "f") {
        e.preventDefault();
        focusSearch();
      }
    };
    // 捕获阶段：焦点在输入框里（输入框会截住按键）也能用
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [page]);
  const dim = (id: string) => (hits && !hits.has(id) ? s.dim : undefined);

  return (
    <div
      className={s.transcript}
      data-testid="transcript"
      ref={box}
      onKeyDown={(e) => {
        if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
          e.preventDefault();
          focusSearch();
        }
      }}
    >
      <div className={s.transcriptHead}>
        <span>{t("sources.transcript")}</span>
        <span className={s.transcriptSub}>{t("transcript.follow")}</span>
        <Tip content={t("transcript.help")}>
          <Button variant="flat" size="sm" icon={<Info />} aria-label={t("transcript.help")} />
        </Tip>
      </div>
      {props.segs.length ? (
        <div className={s.transcriptSearch}>
          <TextField
            value={q}
            onChange={setQ}
            label={t("transcript.search")}
            placeholder={t("transcript.searchHint")}
            onSubmit={(m) => go(m.shift ? -1 : 1)}
            onEscape={() => setQ("")}
            testId="transcript-search"
          />
          {hits ? (
            <span className={`${s.transcriptSub} num`} data-testid="transcript-search-count">
              {order.length ? (at >= 0 ? t("transcript.searchAt", { i: at + 1, n: order.length }) : t("transcript.searchN", { n: order.length })) : t("transcript.searchNone")}
            </span>
          ) : null}
          <Button variant="flat" size="sm" icon={<ChevronUp />} aria-label={t("transcript.searchPrev")} isDisabled={!order.length} onPress={() => go(-1)} />
          <Button variant="flat" size="sm" icon={<ChevronDown />} aria-label={t("transcript.searchNext")} isDisabled={!order.length} onPress={() => go(1)} />
        </div>
      ) : null}
      {rows.length ? (
        <ActionList<Row>
          label={t("sources.transcript")}
          items={rows}
          textValue={(r) => (r.kind === "seg" ? r.seg.text : r.oped.kind)}
          current={current}
          selected={selected}
          renderDeps={[hits]}
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
                <span className={`${s.muted} num ${dim(r.seg.id) ?? ""}`}>{clock(r.seg.start, 1)}</span>
                <span className={`${s.who} ${dim(r.seg.id) ?? ""}`} lang="ja" data-user-data="">
                  {r.seg.speakers.join(t("settings.subtitle.speakerSep"))}
                  {r.seg.speakersWithheld ? (
                    <span className={s.segFlags} data-testid="seg-withheld" title={t("seg.withheld")}>
                      ?
                    </span>
                  ) : null}
                </span>
                <span className={`${s.segText} ${dim(r.seg.id) ?? ""}`}>
                  <span lang="ja" data-user-data="" data-hit={hits?.has(r.seg.id) ? "" : undefined}>
                    {marked(r.seg.text.replace(/\n/g, " "), hits?.get(r.seg.id))}
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
