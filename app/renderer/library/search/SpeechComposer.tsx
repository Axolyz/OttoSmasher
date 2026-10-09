// 语音 · 节奏 / 音块检索的编辑（03 §3.4.1、09 §9.6.1、UI_PLAN §6.3；原型 renderComposer speech / drawRoll / drawInsp）：
// - 不限节奏：一排编号音块（拖拽排序、「＋ 音块」）；节奏策略：钢琴卷帘（每拍 90 px、吸附网格）——空白处拖动画块、拖块移动、拖右缘改长度、Delete 删除；
// - 选中一个块，在右侧就地编辑它的条件（缺失的测量一律不命中）；越界、重叠、太近就地标红并禁用查找。
import { Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { SpeechBlockCond, SpeechQueryInput } from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox, Disclosure, Segmented } from "../../components/Controls";
import { OptionalNumber, Select, Switch, TextField } from "../../components/Fields";
import { AnchoredPanel } from "../../components/Panel";
import { t } from "../../i18n";
import s from "./Search.module.css";

export type Strategy = "free" | "strict" | "rank";
type Edge = "any" | "head" | "tail" | "both";
type Scope = "both" | "sentence" | "segment";

export interface SBlock {
  id: number;
  a: number;
  b: number;
  c: SpeechBlockCond;
}

export interface SpeechDraft {
  strategy: Strategy;
  edge: Edge;
  edgeBasis: "pause" | "sample";
  cross: boolean;
  maxGap: number | null;
  scope: Scope;
  length: number;
  grid: number;
  speedLimit: boolean;
  speedLo: number;
  speedHi: number;
  speedPreference: number;
  restAdjust: boolean;
  blocks: SBlock[];
}

let seq = 1;
export const newSpeechDraft = (): SpeechDraft => ({
  strategy: "free", edge: "any", edgeBasis: "pause", cross: false, maxGap: null, scope: "both", length: 4, grid: 0.5,
  speedLimit: false, speedLo: 0.8, speedHi: 1.25, speedPreference: 0.1, restAdjust: false,
  blocks: [{ id: seq++, a: 0, b: 0.5, c: {} }, { id: seq++, a: 1, b: 1.5, c: {} }],
});

const BPX = 90;
const NOTE_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
const tolOf = (d: SpeechDraft) => Math.min(0.1, d.grid / 3);
const sorted = (d: SpeechDraft) => (d.strategy === "free" ? d.blocks : [...d.blocks].sort((x, y) => x.a - y.a));

/** 就地校验（与 Core 同一规则：在查询范围内、长度为正、不重叠、相邻起拍间距 > 2 × 容差） */
export function speechProblem(d: SpeechDraft): string | null {
  if (!d.blocks.length) return t("search.speech.empty");
  if (d.strategy === "free") return null;
  const bs = sorted(d);
  const tol = tolOf(d);
  for (let i = 0; i < bs.length; i++) {
    const b = bs[i]!;
    if (!(b.b > b.a) || b.a < 0 || b.b > d.length + 1e-9) return t("search.speech.bounds");
    if (i > 0 && b.a < bs[i - 1]!.b - 1e-9) return t("search.speech.bounds");
    if (i > 0 && !(b.a - bs[i - 1]!.a > 2 * tol + 1e-12)) return t("search.speech.tooClose");
  }
  return null;
}

export function speechQuery(d: SpeechDraft): SpeechQueryInput {
  const rhythm = d.strategy !== "free";
  return {
    blocks: sorted(d).map((b) => ({ ...b.c, ...(rhythm ? { note: [b.a, b.b] } : {}) })),
    strategy: d.strategy, edge: d.edge, edgeBasis: d.edgeBasis, cross: d.cross, maxGap: d.maxGap, scope: d.scope,
    tolerance: tolOf(d), speedPreference: d.speedPreference, speedRange: d.speedLimit ? [d.speedLo, d.speedHi] : null,
    restAdjust: d.restAdjust, length: d.length,
  };
}

function blockLabel(c: SpeechBlockCond): string {
  const parts = [];
  if (c.consonants) parts.push(c.consonants.length ? c.consonants.join("") : "∅");
  parts.push(c.vowel ?? "·");
  if (c.pitch != null) parts.push(` ${NOTE_NAMES[c.pitch]}${c.octave ?? ""}`);
  return parts.join("");
}

export function SpeechHeader(props: { d: SpeechDraft; set: (d: SpeechDraft) => void; bpm: number | null }) {
  const { d, set } = props;
  return (
    <>
      <Segmented<Strategy>
        value={d.strategy}
        onChange={(v) => set({ ...d, strategy: v })}
        label={t("search.speech.strategy")}
        size="sm"
        testId="search-strategy"
        options={(["free", "strict", "rank"] as const).map((k) => ({ id: k, label: t(`search.speech.strategy.${k}`), data: { "data-testid": `strategy-${k}` } }))}
      />
      <Segmented<Edge>
        value={d.edge}
        onChange={(v) => set({ ...d, edge: v })}
        label={t("search.speech.edge")}
        size="sm"
        options={(["any", "head", "tail", "both"] as const).map((k) => ({ id: k, label: t(`search.speech.edge.${k}`), data: { "data-testid": `edge-${k}` } }))}
      />
      {d.strategy !== "free" ? (
        <span className={s.muted} data-testid="search-bpm-note">
          {props.bpm == null ? t("search.speech.noBpm") : t("search.speech.byBpm", { bpm: props.bpm })}
        </span>
      ) : null}
    </>
  );
}

export function SpeechSettings(props: { d: SpeechDraft; set: (d: SpeechDraft) => void }) {
  const { d, set } = props;
  const [open, setOpen] = useState(false);
  return (
    <AnchoredPanel
      title={t("search.speech.settings")}
      isOpen={open}
      onOpenChange={setOpen}
      width={340}
      testId="speech-settings"
      trigger={
        <Button size="sm" variant="flat" data-testid="speech-more">
          {t("search.more")}
        </Button>
      }
    >
      <div className={s.field}>
        <span>{t("search.speech.edgeBasis")}</span>
        <Segmented
          value={d.edgeBasis}
          onChange={(v) => set({ ...d, edgeBasis: v })}
          label={t("search.speech.edgeBasis")}
          size="sm"
          options={[{ id: "pause", label: t("search.speech.basis.pause") }, { id: "sample", label: t("search.speech.basis.sample") }]}
        />
      </div>
      <div className={s.field}>
        <span>{t("search.speech.cross")}</span>
        <div className={s.pair}>
          <Switch isSelected={d.cross} onChange={(v) => set({ ...d, cross: v })} label={t("search.speech.cross")} />
          <OptionalNumber value={d.maxGap} onChange={(v) => set({ ...d, maxGap: v })} min={0} placeholder={t("search.speech.maxGap")} label={t("search.speech.maxGap")} width={110} />
        </div>
      </div>
      <div className={s.field}>
        <span>{t("search.speech.length")}</span>
        <OptionalNumber value={d.length} onChange={(v) => v != null && v > 0 && set({ ...d, length: v })} min={0.5} max={64} label={t("search.speech.length")} width={80} />
      </div>
      <div className={s.field}>
        <span>{t("search.speech.grid")}</span>
        <Select value={String(d.grid)} onChange={(v) => set({ ...d, grid: Number(v) })} label={t("search.speech.grid")} options={["1", "0.5", "0.25", "0.125"].map((g) => ({ id: g, label: t("search.speech.beats", { n: g }) }))} />
      </div>
      <div className={s.field}>
        <span>{t("search.speech.scope")}</span>
        <Segmented<Scope>
          value={d.scope}
          onChange={(v) => set({ ...d, scope: v })}
          label={t("search.speech.scope")}
          size="sm"
          options={(["both", "sentence", "segment"] as const).map((k) => ({ id: k, label: t(`search.speech.scope.${k}`) }))}
        />
      </div>
      <Disclosure title={t("search.advanced")}>
        <Checkbox isSelected={d.restAdjust} onChange={(v) => set({ ...d, restAdjust: v })} label={t("search.speech.restAdjust")}>
          {t("search.speech.restAdjust")}
        </Checkbox>
      </Disclosure>
      <Button size="sm" variant="flat" onPress={() => set({ ...d, blocks: [] })}>
        {t("search.speech.clear")}
      </Button>
    </AnchoredPanel>
  );
}

export function SpeechCanvas(props: { d: SpeechDraft; set: (d: SpeechDraft) => void; sel: number | null; setSel: (id: number | null) => void }) {
  const { d, set, sel, setSel } = props;
  const ref = useRef<HTMLDivElement>(null);
  const dRef = useRef(d);
  dRef.current = d;
  const snap = (x: number, g = d.grid) => Math.round(x / g) * g;
  const free = d.strategy === "free";

  const onKey = (e: React.KeyboardEvent) => {
    if ((e.key === "Delete" || e.key === "Backspace") && sel != null) {
      e.preventDefault();
      set({ ...d, blocks: d.blocks.filter((b) => b.id !== sel) });
      setSel(null);
    }
  };

  const drag = (e: React.MouseEvent, b: SBlock, mode: "move" | "resize" | "reorder") => {
    e.preventDefault();
    e.stopPropagation();
    setSel(b.id);
    ref.current?.focus();
    const x0 = e.clientX;
    const a0 = b.a;
    const b0 = b.b;
    const idx0 = d.blocks.findIndex((z) => z.id === b.id);
    const mv = (ev: MouseEvent) => {
      const dx = (ev.clientX - x0) / BPX;
      const cur = dRef.current;
      if (mode === "reorder") {
        const to = Math.max(0, Math.min(cur.blocks.length - 1, idx0 + Math.round((ev.clientX - x0) / 118)));
        const rest = cur.blocks.filter((z) => z.id !== b.id);
        rest.splice(to, 0, cur.blocks.find((z) => z.id === b.id)!);
        set({ ...cur, blocks: rest });
        return;
      }
      const blocks = cur.blocks.map((z) => {
        if (z.id !== b.id) return z;
        if (mode === "resize") return { ...z, b: Math.max(z.a + cur.grid, Math.min(cur.length, snap(b0 + dx, cur.grid))) };
        const len = b0 - a0;
        const na = Math.max(0, Math.min(cur.length - len, snap(a0 + dx, cur.grid)));
        return { ...z, a: na, b: na + len };
      });
      set({ ...cur, blocks });
    };
    const up = () => {
      window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", mv);
    window.addEventListener("mouseup", up);
  };

  const add = (a?: number) => {
    const b: SBlock = free ? { id: seq++, a: 0, b: 0.5, c: {} } : { id: seq++, a: a ?? 0, b: Math.min(d.length, (a ?? 0) + d.grid), c: {} };
    set({ ...d, blocks: [...d.blocks, b] });
    setSel(b.id);
    return b;
  };

  if (free) {
    return (
      <div className={s.canvas} ref={ref} tabIndex={0} onKeyDown={onKey} data-testid="speech-canvas">
        <div className={s.free}>
          {d.blocks.map((b, i) => (
            <div key={b.id} className={s.chip} data-sel={sel === b.id || undefined} onMouseDown={(e) => drag(e, b, "reorder")} data-testid="speech-block">
              <span className={s.bt}>{i + 1}</span>
              <span lang="ja">{blockLabel(b.c)}</span>
            </div>
          ))}
          <Button size="sm" variant="flat" icon={<Plus />} onPress={() => add()} data-testid="speech-add">
            {t("search.speech.add")}
          </Button>
        </div>
      </div>
    );
  }
  const bs = sorted(d);
  const lines = [];
  for (let k = 0; k <= d.length + 1e-9; k += d.grid) {
    const whole = Math.abs(k - Math.round(k)) < 1e-9;
    lines.push(
      <div key={`g${k}`} className={s.gl} data-sub={whole ? undefined : ""} style={{ left: k * BPX }}>
        {whole ? <span className={s.bn} style={{ left: 4 }}>{Math.round(k)}</span> : null}
      </div>,
    );
  }
  return (
    <div className={s.canvas} ref={ref} tabIndex={0} onKeyDown={onKey} data-testid="speech-canvas">
      <div
        className={s.roll}
        style={{ width: d.length * BPX + 40 }}
        onMouseDown={(e) => {
          if (e.button !== 0) return;
          const r = e.currentTarget.getBoundingClientRect();
          const a = Math.max(0, Math.min(d.length - d.grid, Math.floor((e.clientX - r.left) / BPX / d.grid) * d.grid));
          const b = add(a);
          drag(e, b, "resize");
        }}
        data-testid="speech-roll"
      >
        {lines}
        {bs.map((b, i) => (
          <div
            key={b.id}
            className={s.blk}
            data-sel={sel === b.id || undefined}
            style={{ left: b.a * BPX, width: Math.max(8, (b.b - b.a) * BPX - 3) }}
            onMouseDown={(e) => drag(e, b, "move")}
            data-testid="speech-block"
          >
            <span className={s.bt}>{i + 1}</span>
            <span lang="ja">{blockLabel(b.c)}</span>
            <div className={s.rs} onMouseDown={(e) => drag(e, b, "resize")} />
          </div>
        ))}
      </div>
    </div>
  );
}

const ANY = "any";

export function SpeechInspector(props: { d: SpeechDraft; set: (d: SpeechDraft) => void; sel: number | null; setSel: (id: number | null) => void }) {
  const { d, set, sel } = props;
  const b = d.blocks.find((z) => z.id === sel);
  const [consText, setConsText] = useState("");
  useEffect(() => setConsText(b?.c.consonants?.join(" ") ?? ""), [b?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!b) return <div className={`${s.insp} ${s.muted}`}>{t("search.speech.pick")}</div>;
  const idx = sorted(d).findIndex((z) => z.id === b.id);
  const patch = (c: Partial<SpeechBlockCond>) => set({ ...d, blocks: d.blocks.map((z) => (z.id === b.id ? { ...z, c: { ...z.c, ...c } } : z)) });
  const unset = (keys: Array<keyof SpeechBlockCond>) => {
    const c = { ...b.c };
    for (const k of keys) delete c[k];
    set({ ...d, blocks: d.blocks.map((z) => (z.id === b.id ? { ...z, c } : z)) });
  };
  const rhythm = d.strategy !== "free";
  const consMode = b.c.consonants == null ? ANY : b.c.consonants.length ? "set" : "none";
  const range = (key: "duration" | "beats", i: 0 | 1, v: number | null) => {
    const cur = [...((b.c[key] as Array<number | null> | null | undefined) ?? [null, null])];
    cur[i] = v;
    if (cur[0] == null && cur[1] == null) unset([key]);
    else patch({ [key]: cur });
  };
  return (
    <div className={s.insp} data-testid="speech-inspector">
      <div className={s.inspHead}>
        <b>{t("search.blockN", { n: idx + 1 })}</b>
        {rhythm ? <span className={s.hint}>{t("search.speech.beatsRange", { a: b.a.toFixed(2), b: b.b.toFixed(2) })}</span> : null}
      </div>
      <div className={s.field}>
        <span>{t("search.speech.consonants")}</span>
        <div className={s.pair}>
          <Select
            value={consMode}
            onChange={(v) => (v === ANY ? unset(["consonants"]) : v === "none" ? patch({ consonants: [] }) : patch({ consonants: consText.split(/\s+/).filter(Boolean).length ? consText.split(/\s+/).filter(Boolean) : ["k"] }))}
            label={t("search.speech.consonants")}
            options={[{ id: ANY, label: t("search.any") }, { id: "none", label: t("search.speech.noConsonant") }, { id: "set", label: t("search.speech.consonantSet") }]}
          />
          {consMode === "set" ? (
            <TextField
              value={consText}
              onChange={(v) => {
                setConsText(v);
                const parts = v.split(/\s+/).filter(Boolean);
                if (parts.length) patch({ consonants: parts });
              }}
              label={t("search.speech.consonantSet")}
              placeholder="k / sh / k y"
              mono
              testId="speech-consonants"
            />
          ) : null}
        </div>
      </div>
      <div className={s.field}>
        <span>{t("search.speech.vowel")}</span>
        <Select
          value={b.c.vowel ?? ANY}
          onChange={(v) => (v === ANY ? unset(["vowel"]) : patch({ vowel: v as SpeechBlockCond["vowel"] }))}
          label={t("search.speech.vowel")}
          options={[{ id: ANY, label: t("search.any") }, ...["a", "i", "u", "e", "o"].map((v) => ({ id: v, label: v }))]}
        />
      </div>
      <div className={s.field}>
        <span>{t("search.speech.pitch")}</span>
        <div className={s.pair}>
          <Select
            value={b.c.pitch == null ? ANY : String(b.c.pitch)}
            onChange={(v) => (v === ANY ? unset(["pitch", "octave"]) : patch({ pitch: Number(v) }))}
            label={t("search.speech.pitch")}
            options={[{ id: ANY, label: t("search.any") }, ...NOTE_NAMES.map((n, i) => ({ id: String(i), label: n }))]}
          />
          <Select
            value={b.c.octave == null ? ANY : String(b.c.octave)}
            onChange={(v) => (v === ANY ? unset(["octave"]) : patch({ octave: Number(v) }))}
            label={t("search.speech.octave")}
            isDisabled={b.c.pitch == null}
            options={[{ id: ANY, label: t("search.speech.anyOctave") }, ...Array.from({ length: 11 }, (_, i) => ({ id: String(i - 1), label: String(i - 1) }))]}
          />
        </div>
      </div>
      <div className={s.field}>
        <span>{t("search.speech.pitchTol")}</span>
        <OptionalNumber value={b.c.pitchTolerance ?? null} onChange={(v) => (v == null ? unset(["pitchTolerance"]) : patch({ pitchTolerance: v }))} min={0} max={600} placeholder="50" label={t("search.speech.pitchTol")} width={80} />
      </div>
      <Disclosure title={t("search.speech.moreConds")} testId="speech-more-conds">
        <div className={s.field}>
          <span>{t("search.speech.spreadMax")}</span>
          <OptionalNumber value={b.c.spreadMax ?? null} onChange={(v) => (v == null ? unset(["spreadMax"]) : patch({ spreadMax: v }))} min={0} placeholder={t("search.unset")} label={t("search.speech.spreadMax")} width={80} />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.coverage")}</span>
          <OptionalNumber value={b.c.coverageMin ?? null} onChange={(v) => (v == null ? unset(["coverageMin"]) : patch({ coverageMin: v }))} min={0} max={1} placeholder="0.5" label={t("search.speech.coverage")} width={80} />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.duration")}</span>
          <div className={s.pair}>
            <OptionalNumber value={b.c.duration?.[0] ?? null} onChange={(v) => range("duration", 0, v)} min={0} placeholder={t("search.min")} label={t("search.speech.durationMin")} width={64} />
            –
            <OptionalNumber value={b.c.duration?.[1] ?? null} onChange={(v) => range("duration", 1, v)} min={0} placeholder={t("search.max")} label={t("search.speech.durationMax")} width={64} />
          </div>
        </div>
        <div className={s.field}>
          <span />
          <Segmented
            value={b.c.durationMode ?? "effective"}
            onChange={(v) => patch({ durationMode: v })}
            label={t("search.speech.durationMode")}
            size="sm"
            options={[{ id: "effective", label: t("search.speech.durationMode.effective") }, { id: "span", label: t("search.speech.durationMode.span") }]}
          />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.character")}</span>
          <TextField
            value={(b.c.character ?? "").replace(/^character:/, "")}
            onChange={(v) => (v.trim() ? patch({ character: `character:${v.trim()}` }) : unset(["character"]))}
            label={t("search.speech.character")}
            placeholder={t("search.any")}
          />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.trend")}</span>
          <Select
            value={b.c.trend ?? ANY}
            onChange={(v) => (v === ANY ? unset(["trend"]) : patch({ trend: v as "up" | "down" }))}
            label={t("search.speech.trend")}
            options={[{ id: ANY, label: t("search.any") }, { id: "up", label: t("search.speech.trend.up") }, { id: "down", label: t("search.speech.trend.down") }]}
          />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.relPitch")}</span>
          <Select
            value={b.c.relPitch ?? ANY}
            onChange={(v) => (v === ANY ? unset(["relPitch"]) : patch({ relPitch: v as "high" | "low" }))}
            label={t("search.speech.relPitch")}
            options={[{ id: ANY, label: t("search.any") }, { id: "high", label: t("search.speech.relPitch.high") }, { id: "low", label: t("search.speech.relPitch.low") }]}
          />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.loudness")}</span>
          <OptionalNumber value={b.c.loudnessMin ?? null} onChange={(v) => (v == null ? unset(["loudnessMin"]) : patch({ loudnessMin: v }))} placeholder="dB" label={t("search.speech.loudness")} width={80} />
        </div>
        <div className={s.field}>
          <span>{t("search.speech.strength")}</span>
          <OptionalNumber value={b.c.strengthMin ?? null} onChange={(v) => (v == null ? unset(["strengthMin"]) : patch({ strengthMin: v }))} min={0} max={1} placeholder="0–1" label={t("search.speech.strength")} width={80} />
        </div>
        {rhythm ? (
          <>
            <div className={s.field}>
              <span>{t("search.speech.beats")}</span>
              <div className={s.pair}>
                <OptionalNumber value={b.c.beats?.[0] ?? null} onChange={(v) => range("beats", 0, v)} min={0} placeholder={t("search.min")} label={t("search.speech.beatsMin")} width={64} />
                –
                <OptionalNumber value={b.c.beats?.[1] ?? null} onChange={(v) => range("beats", 1, v)} min={0} placeholder={t("search.max")} label={t("search.speech.beatsMax")} width={64} />
              </div>
            </div>
            <Checkbox isSelected={!!b.c.sustain} onChange={(v) => (v ? patch({ sustain: true }) : unset(["sustain"]))} label={t("search.speech.sustain")}>
              {t("search.speech.sustain")}
            </Checkbox>
          </>
        ) : null}
      </Disclosure>
      <span className={s.hint}>{t("search.speech.missingNeverMatch")}</span>
      <div className={s.row}>
        <Button
          size="sm"
          variant="flat"
          onPress={() => {
            const nb: SBlock = { ...b, id: seq++, a: Math.min(d.length - (b.b - b.a), b.b), b: Math.min(d.length, b.b + (b.b - b.a)) };
            set({ ...d, blocks: [...d.blocks, nb] });
            props.setSel(nb.id);
          }}
        >
          {t("search.duplicate")}
        </Button>
        <Button
          size="sm"
          variant="danger"
          onPress={() => {
            set({ ...d, blocks: d.blocks.filter((z) => z.id !== b.id) });
            props.setSel(null);
          }}
          data-testid="speech-block-delete"
        >
          {t("search.delete")}
        </Button>
      </div>
    </div>
  );
}

export function SpeechFooter(props: { d: SpeechDraft; set: (d: SpeechDraft) => void }) {
  const { d, set } = props;
  return (
    <div className={s.row}>
      <span className={s.hint}>{t(d.strategy === "free" ? "search.speech.hintFree" : "search.speech.hintRoll")}</span>
      {d.strategy !== "free" ? (
        <>
          <Checkbox isSelected={d.speedLimit} onChange={(v) => set({ ...d, speedLimit: v })} label={t("search.speech.speedLimit")}>
            <span className={s.hint}>{t("search.speech.speedLimit")}</span>
          </Checkbox>
          <OptionalNumber value={d.speedLo} onChange={(v) => v != null && set({ ...d, speedLo: v })} min={0.05} label={t("search.speech.speedLo")} width={56} />
          –
          <OptionalNumber value={d.speedHi} onChange={(v) => v != null && set({ ...d, speedHi: v })} min={0.05} label={t("search.speech.speedHi")} width={56} />
          <span className={s.hint}>{t("search.speech.speedPref")}</span>
          <OptionalNumber value={d.speedPreference} onChange={(v) => v != null && set({ ...d, speedPreference: v })} min={0} max={1} label={t("search.speech.speedPref")} width={56} />
        </>
      ) : null}
    </div>
  );
}
