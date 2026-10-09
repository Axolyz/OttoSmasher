// 舞台的“声音与语音”（UI_PLAN §3、§3.1；原型 renderStage 的波形卡与 speechPanel）：
// - 波形卡：“声音：绑定资产名”（只显示，不能切换，Q7）；图层栏选一个覆盖层（音素 / mora / 无），其他图层用车道；金色 F0 线；
// - 语音面板：音素按 mora 分组（假名在上、音素在下）、分析状态、「语音分析…」；没有台词时「提供台词并分析」。
// - 分析属于“这句”（文本单元，所有者 2026-10-08）：有自己文本的采样只读自己那一句；没有的读范围内的句（只读到一部分标 ◐）。
//   修音素时间、切换版本作用于所选的那一句，所有读这句的采样和原片页音素层同时生效（P13：面板上写明）。
// 时间：这里的时间轴是采样绑定资产的局部秒（测量里的音素时间也是资产局部秒）。
import { AudioWaveform, ChevronDown, Download, Music2, Play, Split, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AssetRecord, JobSummary, SampleRow, SpeechPhone, SpeechSampleView, SpeechUnit } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Segmented, Token } from "../components/Controls";
import { Select, TextArea, TextField, TimeField } from "../components/Fields";
import { Menu } from "../components/Menu";
import { exportWords } from "../exportWords";
import { ClipPanel } from "../sources/ClipPanel";
import { AnchoredPanel } from "../components/Panel";
import { seconds } from "../format";
import { errorText, hasKey, t } from "../i18n";
import { useApp } from "../state/store";
import { useUndo } from "../shell/useUndo";
import { type Curve, type Layer, type LayerBand, type Sel, Timeline, type TimelineHandle } from "../sources/Timeline";
import s from "./Library.module.css";
import { GroupingPanel } from "./StageRhythm";

type LayerId = "ph" | "mora" | "none";
const VOWELS = new Set(["a", "i", "u", "e", "o", "N", "cl"]);
const F0_PAD = 2;

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
  onPlayRange: (a: number, b: number) => void;
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
  const [clipOpen, setClipOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const undo = useUndo();
  // 编辑音素时间（UI_PLAN §3.1：覆盖层加把手、编辑条、不能切覆盖层、Esc 放弃）
  const [editBands, setEditBands] = useState<LayerBand[] | null>(null);
  const [editFocus, setEditFocus] = useState<string | null>(null);
  const [timesOpen, setTimesOpen] = useState(false);
  const [timesDraft, setTimesDraft] = useState("");
  const [textOpen, setTextOpen] = useState(false);
  const [textDraft, setTextDraft] = useState("");
  const [g2pJob, setG2pJob] = useState<string | null>(null);
  const [g2p, setG2p] = useState<string | null>(null);
  const [rangeOpen, setRangeOpen] = useState(false);
  const [rangeText, setRangeText] = useState("");
  const [asset, setAsset] = useState<AssetRecord | null>(null);
  const [view, setView] = useState<SpeechSampleView | null>(null);
  const [unitSel, setUnitSel] = useState<string | null>(null);
  const [curve, setCurve] = useState<Curve | null>(null);
  const [layer, setLayer] = useState<LayerId>("ph");
  const [sel, setSel] = useState<Sel | null>(null);
  const [draft, setDraft] = useState("");
  const tl = useRef<TimelineHandle>(null);

  const loadSpeech = () => void call("speech.sample", { id: smp.id }).then(setView, () => setView(null));
  useEffect(() => {
    setView(null);
    setUnitSel(null);
    setCurve(null);
    setSel(null);
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
    if (props.clipTick) setClipOpen(true);
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

  useCoreEvent("data.changed", (d) => {
    if (((d as Record<string, string[]>).measure ?? []).includes(smp.id)) loadSpeech();
  });

  useEffect(() => {
    if (asset) requestAnimationFrame(() => tl.current?.zoomTo(smp.start, smp.end));
  }, [asset, smp.start, smp.end]);

  // 所选的那一句（编辑、版本、精确时间都作用于它）：默认第一句已分析的
  const unitList = view?.units ?? [];
  const unit: SpeechUnit | null = unitList.find((u) => u.unitId === unitSel) ?? unitList.find((u) => u.head?.status === "ok") ?? unitList[0] ?? null;
  const ownHead = unit?.head && unit.head.status === "ok" && unit.head.result ? unit.head : null;
  // 显示：读到的句合成的头；冲突时显示所选那一句（去修它的音素时间）
  const res = view?.head?.result ?? (view?.conflict ? (ownHead?.result ?? null) : null);
  const editing = editBands !== null;
  const layers = useMemo(() => {
    if (!res) return { ph: null, mora: null };
    return { ph: phoneBands(res.phones), mora: moraBands(res.phones, res.morae) };
  }, [res]);
  const overlay = editing ? { ...phoneBands(res?.phones ?? []), bands: editBands } : layer === "none" ? null : layers[layer];
  const lanes = (["ph", "mora"] as const).filter((k) => k !== (editing ? "ph" : layer) && layers[k]).map((k) => layers[k]!);

  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const saveManual = async (args: { phones?: Array<{ label: string; start: number; end: number }>; text?: string }) => {
    if (!ownHead) return false;
    try {
      await call("speech.saveManual", { unitId: unit!.unitId, version: ownHead.version, ...args });
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
  const switchTo = async (runId: string) => {
    if (!ownHead || runId === ownHead.runId) return;
    try {
      await call("speech.switchHead", { unitId: unit!.unitId, runId, version: ownHead.version });
      loadSpeech();
    } catch (e) {
      fail(e);
      loadSpeech();
    }
  };
  const saveText = async () => {
    try {
      const cur = await call("samples.get", { id: smp.id });
      await call("edits.apply", { batch: { label: { code: "align-text", args: {} }, ops: [{ entity: "sample", id: smp.id, version: cur.version, fields: { align_text_manual: textDraft.trim() || null } }] } });
      toast({ text: t("speech.textSaved"), action: { label: t("common.undo"), run: () => void undo().then(loadSpeech) } });
      setTextOpen(false);
      loadSpeech();
    } catch (e) {
      fail(e);
    }
  };
  const previewText = async () => {
    setG2p(null);
    try {
      setG2pJob((await call("dictionary.preview", { sentence: textDraft })).id);
    } catch (e) {
      fail(e);
    }
  };
  useCoreEvent("job.updated", (d) => {
    const j = d as JobSummary;
    if (j.id !== g2pJob || j.status === "queued" || j.status === "running") return;
    setG2pJob(null);
    if (j.status === "succeeded") {
      const r = j.result as { words: Array<{ reading: string }>; phonemes: string[] };
      setG2p(`${r.words.map((w) => w.reading).join(" ")} · ${r.phonemes.join(" ")}`);
    } else if (j.error) setG2p(errorText(j.error));
  });
  const alignRange = async () => {
    if (!sel) return;
    try {
      await call("speech.submitRange", { assetId: smp.asset_id, start: sel.a, end: sel.b, text: rangeText });
      toast({ text: t("speech.rangeQueued") });
      setRangeOpen(false);
    } catch (e) {
      fail(e);
    }
  };

  const provide = async () => {
    const text = draft.trim();
    if (!text) return;
    try {
      const cur = await call("samples.get", { id: smp.id });
      await call("edits.apply", { batch: { label: { code: "align-text", args: {} }, ops: [{ entity: "sample", id: smp.id, version: cur.version, fields: { align_text_manual: text } }] } });
      setDraft("");
      loadSpeech();
      requestSpeech({ entry: "samples", ids: [smp.id] });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };

  // 动作条（UI_PLAN §3：与原片时间线的动作条同构）：没有选区时作用于整个采样
  const range = sel ?? { a: smp.start, b: smp.end };
  const trackLabel = assetLabel(asset);
  const commitSel = (side: "a" | "b") => (v: number) => {
    if (!asset) return false;
    const a = side === "a" ? v : range.a;
    const b = side === "b" ? v : range.b;
    if (!(a >= 0 && b <= asset.duration + 1e-6 && b - a > 1e-3)) return false;
    setSel({ a, b });
    return true;
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

  const lastFail = view?.own ? unit?.runs.find((r) => r.status === "failed") : undefined;
  const headOk = view?.head?.status === "ok";
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
          : t("speech.status.none");
  const unitLabel = (u: SpeechUnit) => `${t(`speech.unit.kind.${u.kind}`)} · ${u.name ?? ""}${u.partial ? ` ${t("speech.unit.partialMark")}` : ""}`;

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

  return (
    <>
      <section className={s.card} data-testid="stage-wave">
        <div className={s.waveHead}>
          <span className={s.cardTitle}>{t("speech.sound", { name: assetLabel(asset) })}</span>
          <div className={s.grow} />
          <Segmented
            size="sm"
            label={t("speech.layer.label")}
            value={editing ? "ph" : layer}
            onChange={(v) => !editing && setLayer(v)}
            options={[
              { id: "ph", label: t("speech.layer.ph") },
              { id: "mora", label: t("speech.layer.mora") },
              { id: "none", label: t("speech.layer.none") },
            ]}
            testId="stage-layer"
          />
          <Button size="sm" variant="flat" onPress={() => tl.current?.zoomTo(smp.start, smp.end)}>
            {t("speech.fit")}
          </Button>
          <Button size="sm" variant="flat" onPress={() => sel && tl.current?.zoomTo(sel.a, sel.b)} isDisabled={!sel} title={t("sources.zoomSelTip")} data-testid="stage-zoom-sel">
            {t("sources.zoomSel")}
          </Button>
        </div>
        {editing ? (
          <div className={s.editBar} data-testid="phone-edit-bar">
            <b>{t("speech.editing")}</b>
            <span className={s.mutedText}>{t("speech.editHint")}</span>
            <div className={s.grow} />
            <Button size="sm" variant="flat" onPress={() => (stopEdit(), toast({ text: t("speech.editDiscarded") }))} data-testid="phone-edit-discard">
              {t("edit.discard")}
            </Button>
            <Button size="sm" variant="primary" onPress={() => void saveEdit()} data-testid="phone-edit-save">
              {t("speech.editSave")}
            </Button>
          </div>
        ) : null}
        <div className={s.waveBox}>
          {asset ? (
            <Timeline
              ref={tl}
              assetId={smp.asset_id}
              duration={asset.duration}
              playhead={props.playhead}
              playing={props.playing}
              selection={sel}
              onSelection={setSel}
              hitBox={props.hit ?? null}
              onSeek={() => {}}
              onPlayFrom={(at) => props.onPlayRange(at, Math.max(at + 0.05, sel && sel.b > at ? sel.b : smp.end))}
              overlay={overlay}
              lanes={lanes}
              onLaneDoubleClick={(id) => !editing && setLayer(id as LayerId)}
              curve={curve}
              editing={editing}
              editFocus={editFocus}
              onEditBands={setEditBands}
              onEditFocus={setEditFocus}
            />
          ) : null}
        </div>
        <div className={s.stageActions} data-testid="stage-actions">
          <div className={s.actGroup}>
            <Button
              variant="flat"
              icon={props.playing ? <Square /> : <Play />}
              onPress={() => (props.playing ? window.otto.player.stopAudition() : props.onPlayRange(range.a, range.b))}
              data-testid="stage-play-range"
            >
              {props.playing ? t("library.stop") : t("stage.original")}
            </Button>
            {props.onStretched ? (
              <Button variant="flat" icon={props.stretchedPlaying ? <Square /> : <Music2 />} onPress={props.onStretched} isDisabled={editing} data-testid="stage-stretched">
                {props.stretchedPlaying ? t("library.stop") : t("stage.stretched")}
              </Button>
            ) : null}
          </div>
          <div className={s.actGroup} data-testid="stage-readout" data-a={range.a} data-b={range.b}>
            <span className={s.mutedText}>{t("sources.selection")}</span>
            <TimeField value={range.a} onCommit={commitSel("a")} label={t("sources.selStart")} testId="stage-sel-start" />
            <span className={s.mutedText}>→</span>
            <TimeField value={range.b} onCommit={commitSel("b")} label={t("sources.selEnd")} testId="stage-sel-end" />
            <span className={`${s.mutedText} num`}>{t("format.sec", { v: seconds(range.b - range.a) })}</span>
          </div>
          <div className={s.actGroup}>
            <ClipPanel
              assetId={smp.asset_id}
              track={trackLabel}
              sel={sel}
              isOpen={clipOpen}
              onOpenChange={setClipOpen}
              parentSampleId={smp.id}
              formatRange={(a, b) => `${seconds(a)}–${seconds(b)}`}
            />
            <Button variant="flat" icon={<AudioWaveform />} onPress={flatten} isDisabled={editing} data-testid="stage-flatten">
              {t("flatten.action")}
            </Button>
            <Button variant="flat" icon={<Split />} onPress={separate} isDisabled={!asset || editing} data-testid="stage-separate">
              {t("sep.action")}
            </Button>
            <Menu
              head={t("stage.exportHead", { a: seconds(range.a), b: seconds(range.b) })}
              items={[{ id: "wav", label: t("stage.exportWav"), run: () => void exportRange() }]}
              placement="top start"
              trigger={
                <Button variant="flat" icon={<Download />} isDisabled={exporting} data-testid="stage-export">
                  {t("sources.export")}
                  <ChevronDown size={13} />
                </Button>
              }
            />
          </div>
        </div>
      </section>
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
            {groups.map((g, gi) => (
              <div key={gi} className={s.mora}>
                <span className={s.kana} lang="ja" data-user-data="">
                  {g.kana}
                </span>
                <div className={s.phs}>
                  {g.items.map(({ p, i }) => (
                    <Token
                      key={i}
                      label={p.label}
                      strong={VOWELS.has(p.label)}
                      selected={sel !== null && Math.abs(sel.a - p.start) < 1e-6 && Math.abs(sel.b - p.end) < 1e-6}
                      title={`${seconds(p.start)}–${seconds(p.end)}`}
                      onPress={() => setSel({ a: p.start, b: p.end })}
                      testId="speech-phone"
                    />
                  ))}
                </div>
              </div>
            ))}
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
            <span className={s.mutedText}>{t(hasKey(`speech.textSource.${view.textSource}`) ? `speech.textSource.${view.textSource}` : "speech.textSource.units")}</span>
            <span lang="ja" data-user-data="" data-testid="speech-text">
              {view.text}
            </span>
          </div>
        ) : null}
        {view?.own && view.text && view.head && headOk && view.head.text !== view.text ? <Callout tone="warn">{t("speech.textChanged")}</Callout> : null}
        {view?.conflict ? (
          <Callout tone="bad" testId="speech-conflict">
            {t("speech.conflict", { a: view.conflict.a, b: view.conflict.b, at: seconds(view.conflict.at) })}
          </Callout>
        ) : null}
        {unit ? (
          <div className={s.mutedText} data-testid="speech-unit-note">
            {view?.own ? t(`speech.unit.own.${unit.kind}`, { name: unit.name ?? "" }) : t("speech.unit.reads", { n: unitList.length })}
            {ownHead ? ` ${t("speech.unit.shared")}` : ""}
          </div>
        ) : null}
        <div className={s.speechActions}>
          <Button size="sm" onPress={() => requestSpeech({ entry: "samples", ids: [smp.id] })} isDisabled={!view?.text || editing} data-testid="speech-analyze">
            {t("speech.menu")}
          </Button>
          <Button size="sm" variant="flat" onPress={startEdit} isDisabled={!ownHead || editing} data-testid="speech-edit">
            {t("speech.edit")}
          </Button>
          <AnchoredPanel
            title={t("speech.rangeTitle")}
            aux={sel ? t("speech.selection", { a: seconds(sel.a), b: seconds(sel.b) }) : null}
            isOpen={rangeOpen}
            onOpenChange={(o) => {
              setRangeOpen(o);
              if (o) setRangeText(view?.text ?? "");
            }}
            width={360}
            testId="speech-range-panel"
            trigger={
              <Button size="sm" variant="flat" isDisabled={editing || !sel} title={sel ? undefined : t("speech.rangeNeedsSel")} data-testid="speech-range">
                {t("speech.range")}
              </Button>
            }
            footer={
              <Button size="sm" variant="primary" isDisabled={!rangeText.trim()} onPress={() => void alignRange()} data-testid="speech-range-go">
                {t("speech.rangeGo")}
              </Button>
            }
          >
            <div className={s.hintText}>{t("speech.rangeHint")}</div>
            <TextField value={rangeText} onChange={setRangeText} label={t("speech.rangeText")} testId="speech-range-text" />
          </AnchoredPanel>
          <div className={s.grow} />
          {smp.nature === "pitched" || smp.nature === "unpitched" ? null : <GroupingPanel sample={smp} isDisabled={editing} />}
          <AnchoredPanel
            title={t("speech.textPanel")}
            isOpen={textOpen}
            onOpenChange={(o) => {
              setTextOpen(o);
              if (o) {
                setTextDraft(view?.text ?? "");
                setG2p(null);
              }
            }}
            width={380}
            placement="bottom end"
            testId="speech-text-panel"
            trigger={
              <Button size="sm" variant="flat" isDisabled={editing} data-testid="speech-text-edit">
                {t("speech.textPanel")}
              </Button>
            }
            footer={
              <>
                <Button size="sm" variant="flat" onPress={() => void previewText()} isDisabled={!textDraft.trim() || g2pJob !== null}>
                  {g2pJob ? t("dict.previewing") : t("dict.preview")}
                </Button>
                <Button size="sm" variant="primary" onPress={() => void saveText()} data-testid="speech-text-save">
                  {t("common.save")}
                </Button>
              </>
            }
          >
            <TextField value={textDraft} onChange={setTextDraft} label={t("speech.textPanel")} testId="speech-text-input" />
            <div className={s.mutedText}>{t("speech.textNote")}</div>
            {g2p ? (
              <div className={s.hintText} lang="ja" data-user-data="">
                {g2p}
              </div>
            ) : null}
          </AnchoredPanel>
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
    </>
  );
}
