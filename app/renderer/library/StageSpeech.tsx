// 舞台的“声音与语音”（UI_PLAN §3、§3.1；原型 renderStage 的波形卡与 speechPanel）：
// - 波形卡：“声音：绑定资产名”（只显示，不能切换，Q7）；图层栏选一个覆盖层（音素 / mora / 无），其他图层用车道；金色 F0 线；
// - 语音面板：音素按 mora 分组（假名在上、音素在下）、分析状态、「语音分析…」；没读到段时「提供台词并分析」（= 在判定区间上加一段）。
// - 采样不拥有分析，只读取（所有者 2026-10-09）：读与判定区间正长度交叠的所有文本段在这条轨上的分析；只读到一部分的音素标 ◐；
//   某段没有可用分析（没分析过 / 改过待重新分析）→ 不可用并写明哪段；两段音素重叠 → 不可用 + 原因（第 X 段与第 Y 段在 a–b 秒重叠），用户自己缩判定区间。
//   判定区间可见可改（这里的时间框 + 波形上的带子；必须在采样范围内）。修音素时间、切换版本、编辑文本都作用于所选的那一段，
//   所有读这段的采样和原片页音素层同时生效（P13：面板上写明）。「添加台词…」= 在文本层加一段（与已有段重叠时选替换 / 切开 / 取消）。
// 时间：这里的时间轴是采样绑定资产的局部秒（测量里的音素时间也是资产局部秒）。
import { Music2, Play, Repeat, Square, SquarePlay } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AssetRecord, SampleRow, SpeechPhone, SpeechSampleView, SpeechUnit } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Token } from "../components/Controls";
import { Select, TextArea, TextField, TimeField } from "../components/Fields";
import { AnnotationDialog, type AnnTarget } from "../sources/AnnotationDialog";
import { hangOffset } from "../sources/hang";
import { exportWords } from "../exportWords";
import { ClipPanel } from "../sources/ClipPanel";
import { AnchoredPanel } from "../components/Panel";
import { clock, seconds } from "../format";
import { errorText, t, type TArgs } from "../i18n";
import { useApp } from "../state/store";
import { type SpectrumScale } from "../components/SpectrumMenu";
import { WaveCard, WaveEditBar, WaveEditHint, WaveLayers, WaveProcess, WaveSelection, WaveTitle } from "../components/WaveCard";
import { ReimportDialog, type ReimportRequest } from "../sources/ReimportDialog";
import { useUndo } from "../shell/useUndo";
import { type Curve, type Layer, type LayerBand, type Sel, Timeline, type TimelineHandle } from "../sources/Timeline";
import { waveKey } from "../sources/waveKeys";
import { midiOf, noteName, readPitch } from "../pitch";
import s from "./Library.module.css";
import { GroupingPanel } from "./StageRhythm";

type LayerId = "ph" | "mora" | "none";
const VOWELS = new Set(["a", "i", "u", "e", "o", "N", "cl"]);
const F0_PAD = 2;
/** ← → 的“一帧”（详情区没有画面帧率可用时按 30 帧） */
const FRAME = 1 / 30;

function toFloats(b: Uint8Array): Float32Array {
  const copy = new Uint8Array(b.byteLength);
  copy.set(b);
  return new Float32Array(copy.buffer);
}

export function assetLabel(a: AssetRecord | null): string {
  if (!a) return "";
  if (a.origin === "stream") return `${t("track.mix")} · ${t("sources.trackN", { n: (a.stream_ordinal ?? 0) + 1 })}`;
  if (a.origin === "flatten" || a.origin === "reimport") {
    const target = (a.production?.target as { name?: string } | undefined)?.name;
    return [t(`track.origin.${a.origin}`), target].filter(Boolean).join(" · ");
  }
  const model = typeof a.production?.model === "string" ? a.production.model : "";
  return [model, a.stem_name].filter(Boolean).join(" · ");
}

/** 音素 → 覆盖层的色带（编辑时带 id = 序号，才能拖） */
function phoneBands(phones: SpeechPhone[], withIds = false): Layer {
  return {
    id: "ph",
    label: t("speech.layer.ph"),
    bands: phones.map((p, i) => ({
      a: p.start,
      b: p.end,
      label: p.label,
      tone: p.label === "pau" ? ("pause" as const) : VOWELS.has(p.label) ? ("vowel" as const) : ("consonant" as const),
      ...(withIds ? { id: `p:${i}` } : {}),
    })),
  };
}

const timesText = (phones: SpeechPhone[]) => phones.map((p) => `${p.start.toFixed(3)}\t${p.end.toFixed(3)}\t${p.label}`).join("\n");

/** 同一个 mora 的音素合成一段，标签是假名 */
function moraBands(phones: SpeechPhone[], morae: string[]): Layer {
  const bands: Layer["bands"] = [];
  for (const p of phones) {
    if (p.mora == null) continue;
    const last = bands[bands.length - 1];
    const label = morae[p.mora] ?? "";
    if (last && last.label === label && (last as { m?: number }).m === p.mora) last.b = p.end;
    else bands.push(Object.assign({ a: p.start, b: p.end, label, tone: "vowel" as const }, { m: p.mora }));
  }
  return { id: "mora", label: t("speech.layer.mora"), bands };
}

export function StageSpeech(props: {
  sample: SampleRow;
  playhead: () => number | null;
  playing: boolean;
  onPlayRange: (a: number, b: number, loop?: boolean) => void;
  onStop: () => void;
  /** 刚结束的这次原声试听最后播到的资产局部秒（没有则 null） */
  lastPlayed: () => number | null;
  /** 「♩ 卡拍」（UI_PLAN §3：单音没有，不给）：整个采样按舞台上的方案卡拍试听 */
  onStretched?: () => void;
  stretchedPlaying?: boolean;
  /** 定位到的检索命中（资产局部秒；UI_PLAN §2.4）：选区 = 命中，波形画命中框，滚到命中前 0.3 秒 */
  hit?: { a: number; b: number; approx?: boolean; key: string } | null;
  /** 每加一 = 打开「截取」（命中右键「保存命中区…」：选区已是命中） */
  clipTick?: number;
}) {
  const smp = props.sample;
  const toast = useApp((st) => st.toast);
  const requestSpeech = useApp((st) => st.requestSpeech);
  const requestFlatten = useApp((st) => st.requestFlatten);
  const requestSeparation = useApp((st) => st.requestSeparation);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  const [clipOpen, setClipOpen] = useState(false);
  // 命中右键「保存命中区…」打开的截取记为 hit（建采样的来源之一），保存后留在当前采样
  const [clipVia, setClipVia] = useState<"manual" | "hit">("manual");
  const [exporting, setExporting] = useState(false);
  const undo = useUndo();
  // 编辑音素时间（UI_PLAN §3.1：覆盖层加把手、编辑条、不能切覆盖层、Esc 放弃）
  const [editBands, setEditBands] = useState<LayerBand[] | null>(null);
  const [editFocus, setEditFocus] = useState<string | null>(null);
  const [timesOpen, setTimesOpen] = useState(false);
  const [timesDraft, setTimesDraft] = useState("");
  const [annTarget, setAnnTarget] = useState<AnnTarget | null>(null);
  const [asset, setAsset] = useState<AssetRecord | null>(null);
  const [view, setView] = useState<SpeechSampleView | null>(null);
  const [unitSel, setUnitSel] = useState<string | null>(null);
  const [curve, setCurve] = useState<Curve | null>(null);
  const [layer, setLayer] = useState<LayerId>("ph");
  // 车道（覆盖层之外的图层）：默认音素、mora 都开（当前覆盖层那一项不画）
  const [laneOn, setLaneOn] = useState<{ ph: boolean; mora: boolean }>({ ph: true, mora: true });
  const [sel, setSel] = useState<Sel | null>(null);
  const [draft, setDraft] = useState("");
  const tl = useRef<TimelineHandle>(null);
  const [spectrum, setSpectrum] = useState<SpectrumScale>(null);
  const [reimport, setReimport] = useState<ReimportRequest | null>(null);
  // 光标（资产局部秒；所有者 2026-10-12：单击放光标、画面跳到这一帧，播完停在播到的位置）
  const [cursor, setCursorState] = useState(smp.start);
  const cursorRef = useRef(smp.start);
  const setCursor = (v: number) => {
    cursorRef.current = v;
    setCursorState(v);
  };
  const lastPh = useRef<number | null>(null);
  const wasPlaying = useRef(false);
  const [mode, setMode] = useState<"play" | "sel" | "loop" | null>(null);
  const card = useRef<HTMLElement>(null);
  const judgeOn = useApp((st) => st.stageJudgeLane);
  const setJudgeOn = useApp((st) => st.setStageJudgeLane);

  const loadSpeech = () => void call("speech.sample", { id: smp.id }).then(setView, () => setView(null));
  useEffect(() => {
    setView(null);
    setUnitSel(null);
    setCurve(null);
    setSel(null);
    setCursor(smp.start);
    loadSpeech();
    void call("assets.get", { id: smp.asset_id }).then(setAsset, () => setAsset(null));
  }, [smp.id, smp.asset_id]); // eslint-disable-line react-hooks/exhaustive-deps
  const hitKey = props.hit?.key ?? null;
  useEffect(() => {
    const h = props.hit;
    if (!h) return;
    setSel({ a: h.a, b: h.b });
    const id = setTimeout(() => tl.current?.zoomTo(Math.max(smp.start, h.a - 0.3), Math.min(smp.end, Math.max(h.b + 0.3, h.a - 0.3 + (smp.end - smp.start) / 3))), 60);
    return () => clearTimeout(id);
  }, [hitKey, smp.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!props.clipTick) return;
    setClipVia("hit");
    setClipOpen(true);
  }, [props.clipTick]);

  // F0：采样前后各留 2 秒；只画可靠帧（10 §10.1）
  useEffect(() => {
    if (!asset) return;
    const a = Math.max(0, smp.start - F0_PAD);
    const b = Math.min(asset.duration, smp.end + F0_PAD);
    let live = true;
    void call("measure.f0", { assetId: smp.asset_id, start: a, end: b }).then(
      (r) => {
        if (!live || !r.measured) return setCurve(null);
        const f0 = toFloats(r.f0);
        const conf = toFloats(r.confidence);
        const en = toFloats(r.energy);
        const v = new Float32Array(r.count);
        for (let i = 0; i < r.count; i++) v[i] = conf[i]! >= 0.5 && en[i]! > 1e-10 && f0[i]! > 0 ? f0[i]! : Number.NaN;
        setCurve({ t0: r.t0, step: r.step, values: v });
      },
      () => live && setCurve(null),
    );
    return () => {
      live = false;
    };
  }, [asset, smp.id, view?.head?.runId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 读到的段、它们的分析、判定区间变了都要重读（段在别处改了也会让这里停用）
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (c.segment || (c.measure ?? []).includes(smp.id) || (c.sample ?? []).includes(smp.id)) loadSpeech();
  });

  useEffect(() => {
    if (asset) requestAnimationFrame(() => tl.current?.zoomTo(smp.start, smp.end));
  }, [asset, smp.start, smp.end]);

  // 所选的那一段（编辑、版本、精确时间都作用于它）：默认第一段有可用分析的
  const unitList = view?.units ?? [];
  const unit: SpeechUnit | null = unitList.find((u) => u.unitId === unitSel) ?? unitList.find((u) => u.head?.status === "ok") ?? unitList[0] ?? null;
  const usable = unit?.head && unit.head.status === "ok" && unit.head.result ? unit.head : null;
  // 能直接修的：可用版本就是当前头（段改过、撤销之后可能不是：先在版本里切到它）
  const ownHead = usable && unit?.current?.runId === usable.runId ? usable : null;
  // 显示：读到的段合成的头；冲突时显示所选那一段（去修它的音素时间）
  const res = view?.head?.result ?? (view?.conflict ? (usable?.result ?? null) : null);
  const editing = editBands !== null;
  const layers = useMemo(() => {
    if (!res) return { ph: null, mora: null };
    return { ph: phoneBands(res.phones), mora: moraBands(res.phones, res.morae) };
  }, [res]);
  const overlay = editing ? { ...phoneBands(res?.phones ?? []), bands: editBands } : layer === "none" ? null : layers[layer];
  // 判定区间（资产局部秒）：一条车道上的带子
  const judge = view?.judgeLocal && view.judgeLocal.length === 2 ? { a: view.judgeLocal[0]!, b: view.judgeLocal[1]! } : null;
  const judgeLane: Layer | null = judge ? { id: "judge", label: t("judge.lane"), bands: [{ a: judge.a, b: judge.b, label: "", tone: "seg" }] } : null;
  const lanes = [...(["ph", "mora"] as const).filter((k) => k !== (editing ? "ph" : layer) && laneOn[k] && layers[k]).map((k) => layers[k]!), ...(judgeLane && judgeOn ? [judgeLane] : [])];

  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const saveManual = async (args: { phones?: Array<{ label: string; start: number; end: number }>; text?: string }) => {
    if (!ownHead) return false;
    try {
      await call("speech.saveManual", { unitId: unit!.unitId, version: ownHead.version, assetId: smp.asset_id, ...args });
      toast({ text: t("speech.manualSaved") });
      loadSpeech();
      return true;
    } catch (e) {
      fail(e);
      if (e instanceof CoreFailure && e.wire.code === "speech-edit-conflict") loadSpeech();
      return false;
    }
  };
  const startEdit = () => {
    if (!ownHead?.result) return;
    setLayer("ph");
    setEditBands(phoneBands(ownHead.result.phones, true).bands);
    setEditFocus(null);
  };
  const stopEdit = () => {
    setEditBands(null);
    setEditFocus(null);
  };
  // 编辑期间 Esc = 放弃（捕获阶段，先于集合的 Esc 清除勾选）
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      e.preventDefault();
      stopEdit();
      toast({ text: t("speech.editDiscarded") });
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [editing]); // eslint-disable-line react-hooks/exhaustive-deps
  const saveEdit = async () => {
    if (!editBands) return;
    const byIdx = [...editBands].sort((x, y) => Number(x.id!.slice(2)) - Number(y.id!.slice(2)));
    if (await saveManual({ phones: byIdx.map((b) => ({ label: b.label, start: b.a, end: b.b })) })) stopEdit();
  };
  // 切换版本：在这段这条轨上、内容与段现在一致的成功版本之间换当前头
  const switchTo = async (runId: string) => {
    if (!unit || runId === unit.current?.runId) return;
    try {
      await call("speech.switchHead", { unitId: unit.unitId, runId, version: unit.headVersion });
      loadSpeech();
    } catch (e) {
      fail(e);
      loadSpeech();
    }
  };
  // 编辑这段（文本 = 对齐文本、说话人、边界）：同原片页的段编辑框，写明“这段被 N 个采样使用”（P13）
  const editSegment = async () => {
    if (!unit) return;
    try {
      setAnnTarget({ mode: "edit-segment", seg: await call("segments.get", { id: unit.segmentId }) });
    } catch (e) {
      fail(e);
    }
  };
  // 判定区间（资产局部秒，必须在采样范围内）：一次可撤销的编辑
  const setJudge = async (a: number, b: number) => {
    try {
      const cur = await call("samples.get", { id: smp.id });
      await call("edits.apply", { batch: { label: { code: "sample-judge", args: { name: smp.name } }, ops: [{ entity: "sample", id: smp.id, version: cur.version, fields: { judge: [a, b] } }] } });
      toast({ text: t("judge.saved"), action: { label: t("common.undo"), run: () => void undo().then(loadSpeech) } });
      loadSpeech();
    } catch (e) {
      fail(e);
    }
  };
  const commitJudge = (side: "a" | "b") => (v: number) => {
    if (!judge) return false;
    const a = side === "a" ? v : judge.a;
    const b = side === "b" ? v : judge.b;
    if (!(a >= smp.start - 1e-6 && b <= smp.end + 1e-6 && b - a > 1e-3)) return false;
    void setJudge(a, b);
    return true;
  };
  const selInside = sel != null && sel.a >= smp.start - 1e-6 && sel.b <= smp.end + 1e-6 && sel.b - sel.a > 1e-3;
  // 原片秒 = 局部秒 + 偏移（变速了的资产不能从这里加台词）
  const offset = asset ? hangOffset(asset.mapping) : null;
  const addLine = () => {
    if (!sel || offset == null || !asset) return;
    setAnnTarget({ mode: "create-segment", sourceId: asset.source_id, start: sel.a + offset, end: sel.b + offset, text: "" });
  };

  // 提供台词并分析：在判定区间上加一段（没读到段时，判定区间不会碰到已有段），然后分析这个采样读到的段
  const provide = async () => {
    const text = draft.trim();
    const j = view?.judge;
    if (!text || !asset || !j || j.length !== 2) return;
    try {
      await call("segments.add", { sourceId: asset.source_id, start: j[0]!, end: j[1]!, text, resolve: null });
      setDraft("");
      loadSpeech();
      requestSpeech({ entry: "samples", ids: [smp.id] });
    } catch (e) {
      fail(e);
    }
  };

  // 动作条（UI_PLAN §3：与原片时间线的动作条同构）：没有选区时作用于整个采样
  const range = sel ?? { a: smp.start, b: smp.end };
  const trackLabel = assetLabel(asset);
  // 波形窗口（所有者 2026-10-12）：采样范围两边各留 max(1 秒, 采样长度的一半)（不超出音轨），余量灰显、里面也能框选；更远用「返回原素材」
  const margin = Math.max(1, (smp.end - smp.start) / 2);
  const bounds: [number, number] = [Math.max(0, smp.start - margin), Math.min(asset?.duration ?? smp.end + margin, smp.end + margin)];
  const commitSel = (side: "a" | "b") => (v: number) => {
    if (!asset) return false;
    const a = side === "a" ? v : range.a;
    const b = side === "b" ? v : range.b;
    if (!(a >= bounds[0] - 1e-6 && b <= bounds[1] + 1e-6 && b - a > 1e-3)) return false;
    setSel({ a, b });
    return true;
  };
  // 播放（与原素材页同构，所有者 2026-10-12）：▶ 播放 = 从光标播到采样末尾（光标在余量里就播到余量末尾）；选区 / 循环 = 选区
  const clampT = (v: number) => Math.min(bounds[1], Math.max(bounds[0], v));
  const endFrom = (v: number) => (v < smp.end - 1e-3 ? smp.end : bounds[1]);
  const play = () => {
    if (props.playing) return props.onStop();
    let from = cursorRef.current;
    if (Math.abs(from - smp.end) < 1e-3 || from >= bounds[1] - 1e-3) from = smp.start; // 停在末尾：从头播
    setMode("play");
    props.onPlayRange(from, endFrom(from));
  };
  const playSel = (loop: boolean) => {
    if (!sel) return;
    if (props.playing && mode === (loop ? "loop" : "sel")) return props.onStop();
    setMode(loop ? "loop" : "sel");
    props.onPlayRange(sel.a, sel.b, loop);
  };
  const seek = (v: number) => {
    const at = clampT(v);
    setCursor(at);
    if (props.playing) {
      setMode("play");
      props.onPlayRange(at, endFrom(at));
    } else window.otto.player.pictureAt(smp.id, at);
  };
  // 播放头：播放时取引擎位置；停下后画光标。播完（或停止）光标停在最后播到的位置
  const playhead = () => {
    const p = props.playhead();
    if (p != null) {
      lastPh.current = p;
      return p;
    }
    return props.playing ? (lastPh.current ?? cursorRef.current) : cursorRef.current;
  };
  useEffect(() => {
    const last = wasPlaying.current && !props.playing ? (props.lastPlayed() ?? lastPh.current) : null;
    if (last != null) setCursor(clampT(last));
    if (!props.playing) {
      lastPh.current = null;
      setMode(null);
    }
    wasPlaying.current = props.playing;
  }, [props.playing]); // eslint-disable-line react-hooks/exhaustive-deps
  const onWaveKey = (e: React.KeyboardEvent) => {
    if (editing) return;
    waveKey(e, {
      playPause: play,
      playSel,
      mark: (isIn) => {
        const p = props.playing ? (lastPh.current ?? cursor) : cursor;
        const a = isIn ? p : (sel?.a ?? smp.start);
        const b = isIn ? (sel?.b ?? smp.end) : p;
        if (b - a > 1e-3) setSel({ a, b });
      },
      fit: () => tl.current?.zoomTo(smp.start, smp.end),
      zoomSel: () => sel && tl.current?.zoomTo(sel.a, sel.b),
      step: (dir, unit) => {
        const base = props.playing ? (lastPh.current ?? cursor) : cursor;
        if (props.playing) props.onStop();
        const at = clampT(base + dir * (unit === "far" ? 5 : unit === "ms" ? 0.001 : FRAME));
        setCursor(at);
        window.otto.player.pictureAt(smp.id, at);
      },
      clearSel: () => (sel ? (setSel(null), true) : false),
    });
  };

  const flatten = () =>
    requestFlatten({ kind: "single", assetId: smp.asset_id, start: range.a, end: range.b, entry: "detail", sampleId: smp.id });
  const separate = () =>
    asset && requestSeparation({ assetId: asset.id, trackLabel, duration: asset.duration, selection: { a: range.a, b: range.b }, scope: "sel" });
  const exportRange = async () => {
    setExporting(true);
    try {
      const r = await call("exports.range", { assetId: smp.asset_id, start: range.a, end: range.b, words: exportWords() });
      const name = r.path.split(/[\\/]/).pop() ?? r.path;
      useApp.getState().setLastExport([r.path]);
      toast({
        text: t(r.reused ? "sources.exportReused" : "sources.exported", { name }),
        action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(r.path) },
      });
    } catch (e) {
      fail(e);
    } finally {
      setExporting(false);
    }
  };

  const lastFail = unitList.length === 1 && unit?.state === "failed" ? unit.runs.find((r) => r.status === "failed") : undefined;
  const headOk = view?.head?.status === "ok";
  const blocked = view?.blocked && !view.conflict ? view.blocked : null;
  const status = !view
    ? ""
    : view.conflict
      ? t("speech.status.conflict", { a: view.conflict.a, b: view.conflict.b })
      : headOk
        ? view.head!.manual
          ? t("speech.status.manual")
          : t("speech.status.ok")
        : lastFail
          ? t("speech.status.failed", { reason: lastFail.error ? errorText(lastFail.error) : "" })
          : blocked
            ? t(`speech.status.${blocked.code}`, blocked.args as TArgs)
            : view.reason === "no-voice"
              ? t("speech.status.noVoice")
              : t("speech.status.none");
  const unitLabel = (u: SpeechUnit) =>
    `${t("speech.unit.label", { n: u.ordinal, name: u.name })}${u.partial ? ` ${t("speech.unit.partialMark")}` : ""}${u.state !== "ok" ? ` · ${t(`speech.unit.state.${u.state}`)}` : ""}`;

  // 音素按 mora 分组（假名在上、音素在下）；没有 mora 的（停顿、对不上的）单独成组
  const groups = useMemo(() => {
    if (!res) return [];
    const out: Array<{ kana: string; items: Array<{ p: SpeechPhone; i: number }> }> = [];
    res.phones.forEach((p, i) => {
      const last = out[out.length - 1];
      if (p.mora != null && last && last.items[0]!.p.mora === p.mora) last.items.push({ p, i });
      else out.push({ kana: p.mora != null ? (res.morae[p.mora] ?? "") : p.label === "pau" ? t("speech.pauseMark") : "", items: [{ p, i }] });
    });
    return out;
  }, [res]);

  // 选区与音素块同步（所有者 2026-10-12）：中点落在选区里的音素（和假名）都高亮；单击 = 选中它，Shift+单击 = 把选区扩展到它
  const inSel = (a: number, b: number) => sel !== null && (a + b) / 2 >= sel.a - 1e-6 && (a + b) / 2 <= sel.b + 1e-6;
  const pickRange = (a: number, b: number, extend: boolean) => setSel(extend && sel ? { a: Math.min(sel.a, a), b: Math.max(sel.b, b) } : { a, b });

  // 音高（所有者 2026-10-13）：拉平成品的目标音（虚线 + 偏差）；标题栏固定位置的读数 = 播放指针 / 光标处的音高（播放时每 0.1 秒更新）
  const pitchTarget = asset?.origin === "flatten" ? ((asset.production?.target as { midi?: number } | undefined)?.midi ?? null) : null;
  const [readAt, setReadAt] = useState(cursor);
  useEffect(() => {
    if (!props.playing) return setReadAt(cursor);
    const id = setInterval(() => setReadAt(playhead()), 100);
    return () => clearInterval(id);
  }, [props.playing, cursor]); // eslint-disable-line react-hooks/exhaustive-deps
  const f0At = (tt: number) => {
    if (!curve) return null;
    const v = curve.values[Math.round((tt - curve.t0) / curve.step)];
    return v != null && Number.isFinite(v) && v > 0 ? midiOf(v) : null;
  };
  const deviation = useMemo(() => {
    if (pitchTarget == null || !curve) return null;
    const c = [...curve.values].filter((v) => Number.isFinite(v) && v > 0).map((v) => Math.abs(midiOf(v) - pitchTarget) * 100).sort((x, y) => x - y);
    return c.length ? Math.round(c[Math.min(c.length - 1, Math.floor(c.length * 0.9))]!) : null;
  }, [curve, pitchTarget]);
  const nowPitch = f0At(readAt);
  const pitchReadout = curve ? (
    <span className={s.pitchReadout} data-testid="pitch-readout">
      {nowPitch == null ? t("pitch.none") : (() => {
        const r = readPitch(nowPitch);
        return t("pitch.readout", { note: r.name, cents: `${r.cents > 0 ? "+" : r.cents < 0 ? "\u2212" : "\u00b1"}${Math.abs(r.cents)}` });
      })()}
      {pitchTarget != null && deviation != null ? <span className={s.mutedText}>{t("pitch.deviation", { note: noteName(Math.round(pitchTarget)), n: deviation })}</span> : null}
    </span>
  ) : null;

  return (
    <>
      <WaveCard
        testId="stage-wave"
        cardRef={card}
        focusable
        onKeyDown={onWaveKey}
        data={{ cursor: cursor.toFixed(3), mode: props.playing ? (mode ?? "play") : undefined }}
        ariaLabel={t("speech.sound", { name: assetLabel(asset) })}
        title={<WaveTitle>{t("speech.sound", { name: assetLabel(asset) })}</WaveTitle>}
        readout={pitchReadout}
        fitLabel={t("speech.fit")}
        onFit={() => tl.current?.zoomTo(smp.start, smp.end)}
        onZoomSel={() => sel && tl.current?.zoomTo(sel.a, sel.b)}
        zoomSelDisabled={!sel}
        zoomSelTestId="stage-zoom-sel"
        spectrum={spectrum}
        onSpectrum={setSpectrum}
        spectrumTestId="stage-spectrum"
        bar={
          editing ? (
            <WaveEditBar
              title={t("speech.editing")}
              onDiscard={() => (stopEdit(), toast({ text: t("speech.editDiscarded") }))}
              onSave={() => void saveEdit()}
              saveLabel={t("speech.editSave")}
              testId="phone-edit-bar"
              discardTestId="phone-edit-discard"
              saveTestId="phone-edit-save"
            >
              <WaveEditHint>{t("speech.editHint")}</WaveEditHint>
            </WaveEditBar>
          ) : (
            <WaveLayers<LayerId>
              overlay={{
                value: layer,
                onChange: setLayer,
                options: [
                  { id: "ph", label: t("speech.layer.ph") },
                  { id: "mora", label: t("speech.layer.mora") },
                  { id: "none", label: t("speech.layer.none") },
                ],
                testId: "stage-layer",
              }}
              lanes={[
                ...(["ph", "mora"] as const).map((k) => ({
                  id: k,
                  label: t(`speech.layer.${k}`),
                  checked: laneOn[k] && layer !== k,
                  isDisabled: layer === k || !layers[k],
                  onChange: (on: boolean) => setLaneOn((x) => ({ ...x, [k]: on })),
                })),
                { id: "judge", label: t("judge.lane"), checked: judgeOn && !!judgeLane, isDisabled: !judgeLane, onChange: setJudgeOn, testId: "stage-judge-lane" },
              ]}
            />
          )
        }
        timeline={
          <div onPointerDownCapture={() => card.current?.focus({ preventScroll: true })}>
            {asset ? (
                <Timeline
                  spectrum={spectrum}
                  ref={tl}
                  assetId={smp.asset_id}
                  duration={asset.duration}
                  bounds={bounds}
                  focus={{ a: smp.start, b: smp.end }}
                  playhead={playhead}
                  playing={props.playing}
                  selection={sel}
                  onSelection={setSel}
                  hitBox={props.hit ?? null}
                  onSeek={seek}
                  onPlayFrom={(at) => {
                    setCursor(at);
                    setMode("play");
                    props.onPlayRange(at, Math.max(at + 0.05, sel && sel.b > at ? sel.b : endFrom(at)));
                  }}
                  overlay={overlay}
                  lanes={lanes}
                  onLaneDoubleClick={(id) => !editing && setLayer(id as LayerId)}
                  curve={curve}
              pitchTarget={pitchTarget}
                  editing={editing}
                  editFocus={editFocus}
                  onEditBands={setEditBands}
                  onEditFocus={setEditFocus}
                />
            ) : null}
          </div>
        }
        play={
          <>
            <Button variant="flat" icon={props.playing && mode === "play" ? <Square /> : <Play />} onPress={play} data-testid="stage-play">
              {props.playing && mode === "play" ? t("library.stop") : t("player.play")}
            </Button>
            <Button variant="flat" icon={props.playing && mode === "sel" ? <Square /> : <SquarePlay />} onPress={() => playSel(false)} isDisabled={!sel} data-testid="stage-play-range">
              {props.playing && mode === "sel" ? t("library.stop") : t("player.selection")}
            </Button>
            <Button
              variant="flat"
              icon={props.playing && mode === "loop" ? <Square /> : <Repeat />}
              onPress={() => playSel(true)}
              isDisabled={!sel}
              aria-label={t("player.loop")}
              title={t("player.loop")}
              data-testid="stage-loop"
            />
            {props.onStretched ? (
              <Button variant="flat" icon={props.stretchedPlaying ? <Square /> : <Music2 />} onPress={props.onStretched} isDisabled={editing} data-testid="stage-stretched">
                {props.stretchedPlaying ? t("library.stop") : t("stage.stretched")}
              </Button>
            ) : null}
          </>
        }
        selection={<WaveSelection a={range.a} b={range.b} onCommit={commitSel} testId="stage-readout" startTestId="stage-sel-start" endTestId="stage-sel-end" />}
        process={
          <WaveProcess
            clip={
                <ClipPanel
                  assetId={smp.asset_id}
                  track={trackLabel}
                  sel={sel}
                  isOpen={clipOpen}
                  onOpenChange={(o) => {
                    setClipOpen(o);
                    if (!o) setClipVia("manual");
                  }}
                  via={clipVia}
                  formatRange={(a, b) => `${seconds(a)}–${seconds(b)}`}
                  afterSave={
                    clipVia === "hit"
                      ? (id, name) => toast({ text: t("clip.savedHit", { name }), action: { label: t("clip.open"), run: () => (setOpenSample(id), setPage("library")) } })
                      : undefined
                  }
                />
            }
            onFlatten={flatten}
            flattenDisabled={editing}
            onSeparate={separate}
            separateDisabled={!asset || editing}
            onReimport={() => setReimport({ assetId: smp.asset_id, start: range.a })}
            reimportDisabled={editing}
            exportHead={t("stage.exportHead", { a: seconds(range.a), b: seconds(range.b) })}
            exportItems={[{ id: "wav", label: t("stage.exportWav"), run: () => void exportRange() }]}
            exportDisabled={exporting}
            testIds={{ flatten: "stage-flatten", separate: "stage-separate", reimport: "stage-reimport", export: "stage-export" }}
          />
        }
        actionsTestId="stage-actions"
      />
      <ReimportDialog req={reimport} onClose={() => setReimport(null)} onSaved={(id) => setOpenSample(id)} />
      <section className={s.card} data-testid="speech-panel">
        <div className={s.waveHead}>
          <h3 className={s.cardTitle}>{t("speech.panel")}</h3>
          <span className={view?.conflict ? s.badText : headOk ? s.okText : lastFail ? s.badText : s.mutedText} data-testid="speech-status">
            {status}
          </span>
          {view?.head?.partial ? (
            <span className={s.mutedText} data-testid="speech-partial">
              {t("speech.partial")}
            </span>
          ) : null}
          <div className={s.grow} />
          {unitList.length > 1 ? (
            <Select
              label={t("speech.unit.pick")}
              prefix={t("speech.unit.pick")}
              value={unit?.unitId ?? ""}
              onChange={(id) => setUnitSel(id)}
              isDisabled={editing}
              options={unitList.map((u) => ({ id: u.unitId, label: unitLabel(u) }))}
              testId="speech-unit"
            />
          ) : null}
          {ownHead && (unit?.runs.filter((r) => r.status === "ok").length ?? 0) > 1 ? (
            <Select
              label={t("speech.version")}
              prefix={t("speech.version")}
              value={ownHead.runId}
              onChange={(id) => void switchTo(id)}
              options={unit!.runs
                .filter((r) => r.status === "ok")
                .map((r) => ({ id: r.id, label: `${r.manual ? t("speech.versionManual") : t("speech.versionModel")} · ${r.createdAt.replace("T", " ").slice(5, 16)}` }))}
            />
          ) : null}
        </div>
        {res ? (
          <div className={s.moras} data-testid="speech-moras">
            {groups.map((g, gi) => {
              const ga = g.items[0]!.p.start;
              const gb = g.items[g.items.length - 1]!.p.end;
              return (
                <div key={gi} className={s.mora}>
                  {g.kana ? (
                    <Token
                      label={g.kana}
                      plain
                      lang="ja"
                      selected={inSel(ga, gb)}
                      title={`${seconds(ga)}–${seconds(gb)}`}
                      onPress={(e) => pickRange(ga, gb, e.shiftKey)}
                      testId="speech-mora"
                    />
                  ) : (
                    <span className={s.kana} />
                  )}
                  <div className={s.phs}>
                    {g.items.map(({ p, i }) => (
                      <Token
                        key={i}
                        label={p.clipped ? `${p.label}◐` : p.label}
                        strong={VOWELS.has(p.label)}
                        selected={inSel(p.start, p.end)}
                        title={`${seconds(p.start)}–${seconds(p.end)}${p.clipped ? ` · ${t("speech.clipped")}` : ""}`}
                        onPress={(e) => pickRange(p.start, p.end, e.shiftKey)}
                        testId="speech-phone"
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
        {view && !view.text ? (
          <div className={s.provide}>
            <div className={s.hintText}>{t(`speech.noText.${view.reason ?? "no-text"}`)}</div>
            <div className={s.provideRow}>
              <TextField value={draft} onChange={setDraft} onSubmit={() => void provide()} label={t("speech.provideLabel")} placeholder={t("speech.provideLabel")} testId="speech-provide-text" />
              <Button variant="primary" isDisabled={!draft.trim()} onPress={() => void provide()} data-testid="speech-provide">
                {t("speech.provide")}
              </Button>
            </div>
          </div>
        ) : null}
        {view?.text ? (
          <div className={s.textLine}>
            <span className={s.mutedText}>{t("speech.textSource.segments", { n: unitList.length })}</span>
            <span lang="ja" data-user-data="" data-testid="speech-text">
              {view.text}
            </span>
          </div>
        ) : null}
        {view?.reason === "no-voice" ? (
          <Callout tone="info" testId="speech-no-voice">
            {t("speech.noVoice")}
          </Callout>
        ) : null}
        {view?.conflict ? (
          <Callout tone="bad" testId="speech-conflict">
            {t("speech.conflict", { a: view.conflict.a, b: view.conflict.b, start: clock(view.conflict.start), end: clock(view.conflict.end) })}
          </Callout>
        ) : blocked ? (
          <Callout tone="warn" testId="speech-blocked">
            {t(`speech.blocked.${blocked.code}`, blocked.args as TArgs)}
          </Callout>
        ) : null}
        {usable && !ownHead ? <div className={s.mutedText}>{t("speech.notCurrentHead")}</div> : null}
        {unit ? (
          <div className={s.mutedText} data-testid="speech-unit-note">
            {t("speech.unit.reads", { n: unitList.length })}
            {unit.measuredOn ? ` ${t("speech.unit.measuredOn", { track: assetLabel(unit.measuredOn) })}` : ""}
            {usable ? ` ${t("speech.unit.shared")}` : ""}
          </div>
        ) : null}
        <div className={s.judgeRow} data-testid="judge-row">
          <span className={s.mutedText}>{t("judge.label")}</span>
          {judge ? (
            <>
              <TimeField value={judge.a} onCommit={commitJudge("a")} label={t("judge.start")} isDisabled={editing} testId="judge-start" />
              <span className={s.mutedText}>→</span>
              <TimeField value={judge.b} onCommit={commitJudge("b")} label={t("judge.end")} isDisabled={editing} testId="judge-end" />
              <Button size="sm" variant="flat" isDisabled={!selInside || editing} onPress={() => sel && void setJudge(sel.a, sel.b)} title={selInside ? undefined : t("judge.needSel")} data-testid="judge-from-sel">
                {t("judge.fromSel")}
              </Button>
            </>
          ) : (
            <span className={s.mutedText}>{t("judge.none")}</span>
          )}
          <span className={s.mutedText}>{t("judge.note")}</span>
        </div>
        <div className={s.speechActions}>
          <Button size="sm" onPress={() => requestSpeech({ entry: "samples", ids: [smp.id] })} isDisabled={!unitList.length || editing} data-testid="speech-analyze">
            {t("speech.menu")}
          </Button>
          <Button size="sm" variant="flat" onPress={startEdit} isDisabled={!ownHead || editing} data-testid="speech-edit">
            {t("speech.edit")}
          </Button>
          <Button
            size="sm"
            variant="flat"
            isDisabled={editing || !sel || offset == null}
            title={sel ? undefined : t("speech.addLineNeedsSel")}
            onPress={addLine}
            data-testid="speech-add-line"
          >
            {t("speech.addLine")}
          </Button>
          <div className={s.grow} />
          {smp.nature === "pitched" || smp.nature === "unpitched" ? null : <GroupingPanel sample={smp} isDisabled={editing} />}
          <Button size="sm" variant="flat" isDisabled={editing || !unit} onPress={() => void editSegment()} data-testid="speech-text-edit">
            {t("speech.editSegment")}
          </Button>
          <AnchoredPanel
            title={t("speech.times")}
            isOpen={timesOpen}
            onOpenChange={(o) => {
              setTimesOpen(o);
              if (o && ownHead?.result) setTimesDraft(timesText(ownHead.result.phones));
            }}
            width={340}
            placement="bottom end"
            testId="speech-times-panel"
            trigger={
              <Button size="sm" variant="flat" isDisabled={!ownHead || editing} data-testid="speech-times">
                {t("speech.times")}
              </Button>
            }
            footer={
              <Button size="sm" variant="primary" onPress={() => void saveManual({ text: timesDraft }).then((ok) => ok && setTimesOpen(false))} data-testid="speech-times-save">
                {t("speech.editSave")}
              </Button>
            }
          >
            <TextArea value={timesDraft} onChange={setTimesDraft} label={t("speech.times")} rows={10} mono tabInserts testId="speech-times-text" />
            <div className={s.mutedText}>{t("speech.timesNote")}</div>
          </AnchoredPanel>
        </div>
      </section>
      <AnnotationDialog
        target={annTarget}
        duration={Number.POSITIVE_INFINITY}
        onClose={() => setAnnTarget(null)}
        // 「添加台词…」加完就打开分析确认框（给这条轨上的采样测这句：Core 按采样入口的规则选轨）
        onSegmentAdded={(id) => requestSpeech({ entry: "units", ids: [`seg:${id}@${smp.asset_id}`] })}
      />
    </>
  );
}
