// 独立音高检索的编辑（10 §10.2.1、03 §3.4.2、UI_PLAN §6.3；原型 renderComposer pitch / drawPitch）：
// 横向时间轴上的音高块（1–16 块首尾相接）：空白处单击在末尾加块、上下拖改音高、拖右缘改时长（≥ 0.1 s、总长 ≤ 10 s）、↑/↓ 半音、Delete 删除；
// 块可以是单个音、音高范围或滑音（所有者 2026-10-08）；就地提示由 Core 的 search.pitchCheck 给（与检索同一套规则）；文本只作复制/粘贴辅助。
import { useEffect, useMemo, useRef, useState } from "react";
import { call } from "../../api/core";
import type { PitchBlockInput, PitchChecked, PitchParamsInput } from "../../api/types";
import { Button } from "../../components/Button";
import { Disclosure, Segmented } from "../../components/Controls";
import { OptionalNumber, Switch, TextArea, TextField } from "../../components/Fields";
import { AnchoredPanel } from "../../components/Panel";
import { t } from "../../i18n";
import { useApp } from "../../state/store";
import s from "./Search.module.css";
import { noteName } from "../../pitch";

export interface PBlock {
  id: number;
  seconds: number;
  lo: number;
  hi: number;
  /** 滑音终点（单个音）；null = 普通块 */
  to: number | null;
}

export interface PitchDraft {
  mode: "samples" | "sources";
  blocks: PBlock[];
  tolerance: number | null;
  coverage: number | null;
  maxGap: number | null;
  stability: number | null;
  energyMin: number | null;
  energyMax: number | null;
  ignoreOctave: boolean;
  elastic: boolean;
  elasticLo: number;
  elasticHi: number;
  head: number | null;
  tail: number | null;
}

let seq = 1;
export const newPitchDraft = (): PitchDraft => ({
  mode: "samples",
  blocks: [{ id: seq++, seconds: 0.4, lo: 69, hi: 69, to: null }, { id: seq++, seconds: 0.3, lo: 72, hi: 74, to: null }],
  tolerance: null, coverage: null, maxGap: null, stability: null, energyMin: null, energyMax: null,
  ignoreOctave: false, elastic: false, elasticLo: 0.8, elasticHi: 1.25, head: null, tail: null,
});

export { noteName };
const PHI = 96;
const PLO = 36;
const RH = 10;
const SPX = 200;
const KEYW = 38;

export function pitchBlocks(d: PitchDraft): PitchBlockInput[] {
  return d.blocks.map((b) => ({
    seconds: b.seconds,
    low: noteName(b.lo),
    high: b.hi !== b.lo ? noteName(b.hi) : null,
    glide: b.to != null ? { low: noteName(b.to), high: null } : null,
  }));
}

export function pitchParams(d: PitchDraft): PitchParamsInput {
  const p: PitchParamsInput = {};
  if (d.tolerance != null) p.tolerance = d.tolerance;
  if (d.coverage != null) p.coverage = d.coverage;
  if (d.maxGap != null) p.maxGap = d.maxGap;
  if (d.stability != null) p.stability = d.stability;
  if (d.energyMin != null) p.energyMin = d.energyMin;
  if (d.energyMax != null) p.energyMax = d.energyMax;
  if (d.ignoreOctave) p.ignoreOctave = true;
  if (d.elastic) p.elastic = [d.elasticLo, d.elasticHi];
  if (d.mode === "sources" && d.head != null) p.headTolerance = d.head;
  if (d.mode === "sources" && d.tail != null) p.tailTolerance = d.tail;
  return p;
}

/** 就地提示：交给 Core 校验（同一套规则），去抖 */
export function usePitchCheck(d: PitchDraft): PitchChecked | null {
  const [r, setR] = useState<PitchChecked | null>(null);
  const blocks = useMemo(() => pitchBlocks(d), [d]);
  useEffect(() => {
    const id = setTimeout(() => void call("search.pitchCheck", { blocks }).then(setR, () => setR(null)), 120);
    return () => clearTimeout(id);
  }, [blocks]);
  return r;
}

export function problemText(p: PitchChecked["problems"][number]): string {
  const where = p.block != null ? t("search.blockN", { n: p.block }) + " · " : p.line != null ? t("search.pitch.lineN", { n: p.line }) + " · " : "";
  return where + t(`search.pitch.problem.${p.reason}`, { min: p.min ?? 0.1, max: p.max ?? 10 });
}

export function PitchHeader(props: { d: PitchDraft; set: (d: PitchDraft) => void }) {
  const { d, set } = props;
  return (
    <>
      <Segmented
        value={d.mode}
        onChange={(v) => set({ ...d, mode: v })}
        label={t("search.pitch.mode")}
        size="sm"
        options={[{ id: "samples", label: t("search.pitch.mode.samples"), data: { "data-testid": "pitch-mode-samples" } }, { id: "sources", label: t("search.pitch.mode.sources"), data: { "data-testid": "pitch-mode-sources" } }]}
      />
      <span className={s.muted}>{t("search.pitch.tolerance")}</span>
      <OptionalNumber value={d.tolerance} onChange={(v) => set({ ...d, tolerance: v })} min={0} max={1200} placeholder="50" label={t("search.pitch.tolerance")} width={56} testId="pitch-tolerance" />
      <span className={s.muted}>{t("search.pitch.coverage")}</span>
      <OptionalNumber value={d.coverage} onChange={(v) => set({ ...d, coverage: v })} min={0} max={1} placeholder="0.8" label={t("search.pitch.coverage")} width={52} />
      <span className={s.muted}>{t("search.pitch.maxGap")}</span>
      <OptionalNumber value={d.maxGap} onChange={(v) => set({ ...d, maxGap: v })} min={0} max={10} placeholder="0.12" label={t("search.pitch.maxGap")} width={56} />
      <PitchAdvanced d={d} set={set} />
    </>
  );
}

function PitchAdvanced(props: { d: PitchDraft; set: (d: PitchDraft) => void }) {
  const { d, set } = props;
  const [open, setOpen] = useState(false);
  const on = d.ignoreOctave || d.elastic || d.stability != null || d.energyMin != null || d.energyMax != null || d.head != null || d.tail != null;
  return (
    <AnchoredPanel
      title={t("search.pitch.more")}
      isOpen={open}
      onOpenChange={setOpen}
      width={360}
      testId="pitch-more-panel"
      trigger={
        <Button size="sm" variant={on ? "secondary" : "flat"} data-testid="pitch-more">
          {t("search.pitch.more")}
        </Button>
      }
    >
      <div className={s.field}>
        <span>{t("search.pitch.ignoreOctave")}</span>
        <Switch isSelected={d.ignoreOctave} onChange={(v) => set({ ...d, ignoreOctave: v })} label={t("search.pitch.ignoreOctave")} />
      </div>
      <span className={s.hint}>{t("search.pitch.ignoreOctaveHint")}</span>
      <div className={s.field}>
        <span>{t("search.pitch.elastic")}</span>
        <div className={s.pair}>
          <Switch isSelected={d.elastic} onChange={(v) => set({ ...d, elastic: v })} label={t("search.pitch.elastic")} />
          <OptionalNumber value={d.elasticLo} onChange={(v) => v != null && set({ ...d, elasticLo: v })} min={0.5} max={2} label={t("search.pitch.elasticLo")} width={52} />
          –
          <OptionalNumber value={d.elasticHi} onChange={(v) => v != null && set({ ...d, elasticHi: v })} min={0.5} max={2} label={t("search.pitch.elasticHi")} width={52} />×
        </div>
      </div>
      <Disclosure title={t("search.advanced")}>
        <div className={s.field}>
          <span>{t("search.pitch.stability")}</span>
          <OptionalNumber value={d.stability} onChange={(v) => set({ ...d, stability: v })} min={0} max={12000} placeholder={t("search.unset")} label={t("search.pitch.stability")} width={80} />
        </div>
        <div className={s.field}>
          <span>{t("search.pitch.energy")}</span>
          <div className={s.pair}>
            <OptionalNumber value={d.energyMin} onChange={(v) => set({ ...d, energyMin: v })} min={0} placeholder={t("search.min")} label={t("search.pitch.energyMin")} width={72} />
            –
            <OptionalNumber value={d.energyMax} onChange={(v) => set({ ...d, energyMax: v })} min={0} placeholder={t("search.max")} label={t("search.pitch.energyMax")} width={72} />
          </div>
        </div>
        {d.mode === "sources" ? (
          <>
            <div className={s.field}>
              <span>{t("search.pitch.head")}</span>
              <OptionalNumber value={d.head} onChange={(v) => set({ ...d, head: v })} min={0} max={5} placeholder={t("search.unset")} label={t("search.pitch.head")} width={72} />
            </div>
            <div className={s.field}>
              <span>{t("search.pitch.tail")}</span>
              <OptionalNumber value={d.tail} onChange={(v) => set({ ...d, tail: v })} min={0} max={5} placeholder={t("search.unset")} label={t("search.pitch.tail")} width={72} />
            </div>
          </>
        ) : null}
      </Disclosure>
    </AnchoredPanel>
  );
}

export function PitchCanvas(props: { d: PitchDraft; set: (d: PitchDraft) => void; sel: number | null; setSel: (id: number | null) => void }) {
  const { d, set, sel, setSel } = props;
  const ref = useRef<HTMLDivElement>(null);
  const dRef = useRef(d);
  dRef.current = d;
  const toast = useApp((st) => st.toast);
  const total = d.blocks.reduce((a, b) => a + b.seconds, 0);
  const width = Math.max(600, KEYW + (total + 1) * SPX);
  const height = (PHI - PLO + 1) * RH;
  const y = (m: number) => (PHI - m) * RH;
  // 打开时滚到块所在的音高
  useEffect(() => {
    const el = ref.current;
    if (!el || !d.blocks.length) return;
    const mid = d.blocks.reduce((a, b) => a + (b.lo + b.hi) / 2, 0) / d.blocks.length;
    el.scrollTop = Math.max(0, y(mid) - el.clientHeight / 2);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 选中块的音高变了（拖动、↑↓、在右侧改音名）→ 滚到能看见它
  const selBlock = d.blocks.find((b) => b.id === sel);
  useEffect(() => {
    const el = ref.current;
    if (!el || !selBlock) return;
    const top = y(Math.max(selBlock.hi, selBlock.to ?? selBlock.hi));
    const bottom = y(Math.min(selBlock.lo, selBlock.to ?? selBlock.lo)) + RH;
    if (top < el.scrollTop || bottom > el.scrollTop + el.clientHeight) el.scrollTop = Math.max(0, (top + bottom) / 2 - el.clientHeight / 2);
  }, [selBlock?.lo, selBlock?.hi, selBlock?.to, sel]); // eslint-disable-line react-hooks/exhaustive-deps
  const update = (id: number, f: (b: PBlock) => PBlock) => set({ ...dRef.current, blocks: dRef.current.blocks.map((b) => (b.id === id ? f(b) : b)) });
  const shift = (b: PBlock, dm: number): PBlock => {
    const k = Math.max(-b.lo, Math.min(127 - Math.max(b.hi, b.to ?? 0), dm));
    return { ...b, lo: b.lo + k, hi: b.hi + k, to: b.to == null ? null : b.to + k };
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (sel == null) return;
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      update(sel, (b) => shift(b, e.key === "ArrowUp" ? 1 : -1));
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      set({ ...d, blocks: d.blocks.filter((b) => b.id !== sel) });
      setSel(null);
    }
  };
  const drag = (e: React.MouseEvent, b: PBlock, resize: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    setSel(b.id);
    ref.current?.focus();
    const x0 = e.clientX;
    const y0 = e.clientY;
    const start = b;
    const mv = (ev: MouseEvent) => {
      if (resize) update(b.id, (z) => ({ ...z, seconds: Math.max(0.1, Math.round((start.seconds + (ev.clientX - x0) / SPX) * 100) / 100) }));
      else update(b.id, () => shift(start, -Math.round((ev.clientY - y0) / RH)));
    };
    const up = () => {
      window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", mv);
    window.addEventListener("mouseup", up);
  };
  const lines = [];
  for (let k = 0; k <= Math.ceil(total + 1) * 2; k++) {
    const sec = k / 2;
    lines.push(<line key={`v${k}`} x1={sec * SPX} x2={sec * SPX} y1={0} y2={height} stroke="var(--line)" strokeDasharray={k % 2 ? "3 3" : undefined} />);
    lines.push(<text key={`l${k}`} x={sec * SPX + 3} y={height - 3} fontSize={9} fill="var(--muted)">{t("format.sec", { v: sec.toFixed(1) })}</text>);
  }
  let x = 0;
  const shapes = d.blocks.map((b) => {
    const x0 = x;
    const w = b.seconds * SPX;
    x += b.seconds;
    const x0p = x0 * SPX;
    const label = `${noteName(b.lo)}${b.hi !== b.lo ? ".." + noteName(b.hi) : ""}${b.to != null ? "→" + noteName(b.to) : ""} · ${t("format.sec", { v: b.seconds.toFixed(2) })}`;
    const fill = sel === b.id ? "var(--gold)" : "var(--warn)";
    const shape =
      b.to == null ? (
        <rect x={x0p} y={y(b.hi)} width={Math.max(4, w - 3)} height={(b.hi - b.lo + 1) * RH} rx={3} fill={fill} />
      ) : (
        <polygon points={`${x0p},${y(b.hi)} ${x0p + w - 3},${y(b.to + (b.hi - b.lo))} ${x0p + w - 3},${y(b.to) + RH} ${x0p},${y(b.lo) + RH}`} fill={fill} />
      );
    return (
      <g key={b.id} className={s.pb} onMouseDown={(e) => drag(e, b, false)} data-testid="pitch-block" stroke={sel === b.id ? "var(--text)" : "none"}>
        {shape}
        <text x={x0p + 4} y={y(b.hi) + RH - 2} className={s.pblabel}>
          {label}
        </text>
        <rect x={x0p + w - 9} y={Math.min(y(b.hi), y(b.to ?? b.hi))} width={6} height={(Math.abs((b.to ?? b.lo) - b.lo) + b.hi - b.lo + 1) * RH} fill="transparent"
          style={{ cursor: "ew-resize" }} onMouseDown={(e) => drag(e, b, true)} data-testid="pitch-block-edge" />
      </g>
    );
  });
  const keys = [];
  for (let m = PHI; m >= PLO; m--) {
    keys.push(
      <div key={m} className={s.key} data-black={[1, 3, 6, 8, 10].includes(m % 12) || undefined}>
        {m % 12 === 0 || m === 69 ? noteName(m) : ""}
      </div>,
    );
  }
  return (
    <div className={s.canvas} ref={ref} tabIndex={0} onKeyDown={onKey} style={{ maxHeight: 250 }} data-testid="pitch-canvas">
      <div className={s.pr} style={{ width, height }}>
        <div className={s.keys} aria-hidden="true">{keys}</div>
        <svg
          className={s.pgrid}
          width={width - KEYW}
          height={height}
          onMouseDown={(e) => {
            if (e.button !== 0 || (e.target as Element).closest("g")) return;
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const m = PHI - Math.floor((e.clientY - r.top) / RH);
            if (d.blocks.length >= 16) return toast({ text: t("search.pitch.problem.too-many-blocks") });
            if (total + 0.4 > 10 + 1e-9) return toast({ text: t("search.pitch.problem.too-long", { max: 10 }) });
            const nb = { id: seq++, seconds: 0.4, lo: m, hi: m, to: null };
            set({ ...d, blocks: [...d.blocks, nb] });
            setSel(nb.id);
          }}
          data-testid="pitch-grid"
        >
          {lines}
          {shapes}
        </svg>
      </div>
    </div>
  );
}

export function PitchInspector(props: { d: PitchDraft; set: (d: PitchDraft) => void; sel: number | null; setSel: (id: number | null) => void; check: PitchChecked | null }) {
  const { d, set, sel } = props;
  const b = d.blocks.find((z) => z.id === sel);
  const idx = d.blocks.findIndex((z) => z.id === sel);
  const [lo, setLo] = useState("");
  const [hi, setHi] = useState("");
  const [to, setTo] = useState("");
  const [sec, setSec] = useState("");
  useEffect(() => {
    if (!b) return;
    setLo(noteName(b.lo));
    setHi(noteName(b.hi));
    setTo(b.to == null ? "" : noteName(b.to));
    setSec(b.seconds.toFixed(2));
  }, [b?.id, b?.lo, b?.hi, b?.to, b?.seconds]); // eslint-disable-line react-hooks/exhaustive-deps
  const problems = (props.check?.problems ?? []).filter((p) => p.block == null || p.block === idx + 1);
  if (!b) {
    return (
      <div className={s.insp}>
        <span className={s.muted}>{t("search.pitch.pick")}</span>
        {problems.map((p, i) => (
          <span key={i} className={s.err} data-testid="pitch-problem">{problemText(p)}</span>
        ))}
      </div>
    );
  }
  const kind = b.to != null ? "glide" : b.hi !== b.lo ? "range" : "one";
  const patch = (p: Partial<PBlock>) => set({ ...d, blocks: d.blocks.map((z) => (z.id === b.id ? { ...z, ...p } : z)) });
  const parse = (v: string): number | null => {
    const m = /^\s*([A-Ga-g])\s*([#♯b♭]?)\s*(-?\d+)\s*$/.exec(v);
    if (!m) return null;
    const pc = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1]!.toUpperCase() as "C"]!;
    const acc = m[2] === "#" || m[2] === "♯" ? 1 : m[2] === "b" || m[2] === "♭" ? -1 : 0;
    const n = (Number(m[3]) + 1) * 12 + pc + acc;
    return n >= 0 && n <= 127 ? n : null;
  };
  return (
    <div className={s.insp} data-testid="pitch-inspector">
      <b>{t("search.blockN", { n: idx + 1 })}</b>
      <div className={s.field}>
        <span>{t("search.pitch.seconds")}</span>
        <TextField
          value={sec}
          onChange={(v) => {
            setSec(v);
            const n = Number(v);
            if (Number.isFinite(n) && n > 0) patch({ seconds: Math.round(n * 100) / 100 });
          }}
          label={t("search.pitch.seconds")}
          mono
          testId="pitch-seconds"
        />
      </div>
      <Segmented
        value={kind}
        onChange={(v) => patch(v === "one" ? { hi: b.lo, to: null } : v === "range" ? { hi: Math.min(127, b.lo + 2), to: null } : { hi: b.lo, to: Math.min(127, b.lo + 4) })}
        label={t("search.pitch.kind")}
        size="sm"
        options={[{ id: "one", label: t("search.pitch.kind.one") }, { id: "range", label: t("search.pitch.kind.range") }, { id: "glide", label: t("search.pitch.kind.glide") }]}
      />
      <div className={s.field}>
        <span>{t(kind === "range" ? "search.pitch.low" : kind === "glide" ? "search.pitch.from" : "search.pitch.note")}</span>
        <TextField
          value={lo}
          onChange={(v) => {
            setLo(v);
            const n = parse(v);
            if (n != null) patch(kind === "range" ? { lo: n, hi: Math.max(n, b.hi) } : { lo: n, hi: n });
          }}
          label={t("search.pitch.note")}
          invalid={parse(lo) == null}
          testId="pitch-note"
        />
      </div>
      {kind === "range" ? (
        <div className={s.field}>
          <span>{t("search.pitch.high")}</span>
          <TextField value={hi} onChange={(v) => { setHi(v); const n = parse(v); if (n != null) patch({ hi: n }); }} label={t("search.pitch.high")}
            invalid={parse(hi) == null || (parse(hi) ?? 0) < b.lo} testId="pitch-high" />
        </div>
      ) : null}
      {kind === "glide" ? (
        <div className={s.field}>
          <span>{t("search.pitch.to")}</span>
          <TextField value={to} onChange={(v) => { setTo(v); const n = parse(v); if (n != null) patch({ to: n }); }} label={t("search.pitch.to")} invalid={parse(to) == null} testId="pitch-to" />
        </div>
      ) : null}
      {problems.map((p, i) => (
        <span key={i} className={s.err} data-testid="pitch-problem">{problemText(p)}</span>
      ))}
      <div className={s.row}>
        <Button size="sm" variant="flat" onPress={() => { const nb = { ...b, id: seq++ }; const bs = [...d.blocks]; bs.splice(idx + 1, 0, nb); set({ ...d, blocks: bs }); props.setSel(nb.id); }}>
          {t("search.duplicate")}
        </Button>
        <Button size="sm" variant="danger" onPress={() => { set({ ...d, blocks: d.blocks.filter((z) => z.id !== b.id) }); props.setSel(null); }}>
          {t("search.delete")}
        </Button>
      </div>
    </div>
  );
}

export function PitchFooter(props: { d: PitchDraft; set: (d: PitchDraft) => void; check: PitchChecked | null }) {
  const { d, set } = props;
  const toast = useApp((st) => st.toast);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const copy = async () => {
    const txt = props.check?.text;
    if (!txt) return toast({ text: t("search.pitch.cannotCopy"), tone: "error" });
    await navigator.clipboard.writeText(txt);
    toast({ text: t("search.pitch.copied", { text: txt.replace(/\n/g, " / ") }) });
  };
  const paste = async () => {
    const r = await call("search.pitchCheck", { text });
    if (!r.ok) return setErrors(r.problems.map(problemText));
    const blocks: PBlock[] = r.blocks.map((b) => {
      const p = (n: string) => {
        const m = /^([A-Ga-g])([#♯b♭]?)(-?\d+)$/.exec(n.trim())!;
        return (Number(m[3]) + 1) * 12 + { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1]!.toUpperCase() as "C"]! + (m[2] === "#" || m[2] === "♯" ? 1 : m[2] ? -1 : 0);
      };
      const lo = p(b.low);
      return { id: seq++, seconds: Math.round(b.seconds * 100) / 100, lo, hi: b.high ? p(b.high) : lo, to: b.glide ? p(b.glide.low) : null };
    });
    set({ ...d, blocks });
    setOpen(false);
    setErrors([]);
  };
  return (
    <div className={s.row}>
      <span className={s.hint}>{t("search.pitch.hint")}</span>
      <Button size="sm" variant="flat" onPress={() => void copy()} data-testid="pitch-copy-text">
        {t("search.pitch.copyText")}
      </Button>
      <AnchoredPanel
        title={t("search.pitch.pasteText")}
        isOpen={open}
        onOpenChange={(o) => { setOpen(o); setErrors([]); }}
        width={340}
        trigger={<Button size="sm" variant="flat">{t("search.pitch.pasteText")}</Button>}
        footer={<Button size="sm" variant="primary" isDisabled={!text.trim()} onPress={() => void paste()}>{t("search.pitch.pasteOk")}</Button>}
      >
        <TextArea value={text} onChange={setText} label={t("search.pitch.pasteText")} rows={5} mono placeholder={"0.40 A4\n0.30 C5..D5\n0.50 C5->E5"} invalid={errors.length > 0} />
        {errors.map((e, i) => <span key={i} className={s.err}>{e}</span>)}
      </AnchoredPanel>
    </div>
  );
}
