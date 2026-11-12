// 拉平台（规格 11 §11.2、§11.6；UI_PLAN §8 拉平行、D3 全屏工作台；原型 flattenSheet）。
// - 单个：打开时冻结音源与外选区（标题写明“已固定”）；独立的小波形与试听（关闭即停）；处理范围与目标音高都由用户选，默认值按入口给出，
//   改范围不自动改定音（Q6）；交界选侧；手动目标由 Core 即时解析（纯数字拒绝、带单位的频率不吸附）；内部拉平在波形上拖金色内区；
//   预估只读缓存（Core 的 flatten.estimate）；成品名（不加音名）；「开始拉平」提交时 Core 核对冻结的资产。
// - 批量：同一套选项，但只有自动定音、没有内部拉平（Q10）；每项按自己的范围与边界独立定音；没有对齐的项单独失败。
// 时间：波形与内区用输入局部秒（外选区起点 = 0）；标题里的外选区是资产局部秒。
import { Play, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { PlayerState } from "../../shared/protocol";
import type { AssetRecord, FlattenEstimate, FlattenOpened, FlattenOptions, ModelsStatus } from "../api/types";
import { Button } from "../components/Button";
import { Callout, RadioList, Segmented } from "../components/Controls";
import { NumberField, TextField } from "../components/Fields";
import { Sheet } from "../components/Overlay";
import { seconds } from "../format";
import { errorText, t } from "../i18n";
import { assetLabel } from "../library/StageSpeech";
import { type Curve, type Layer, type Sel, Timeline } from "../sources/Timeline";
import { currentProjectTags } from "../state/project";
import { type FlattenRequest, useApp } from "../state/store";
import s from "./Flatten.module.css";

type Range = FlattenOptions["range"];
type Target = FlattenOptions["target"];
type Side = "left" | "right";
const VOWELS = new Set(["a", "i", "u", "e", "o", "I", "U", "N"]);
const NEEDED = ["fcpe", "pc_nsf_hifigan"];

function useMissingModels(open: boolean): string[] {
  const [models, setModels] = useState<ModelsStatus | null>(null);
  useEffect(() => {
    if (open) void call("models.status").then(setModels, () => setModels(null));
  }, [open]);
  return (models?.files ?? []).filter((m) => NEEDED.includes(m.model) && m.state === "missing").map((m) => t(`models.name.${m.model}`));
}

function RangeChoices(props: { value: Range; onChange: (v: Range) => void; batch?: boolean }) {
  const ids: Range[] = props.batch ? ["whole", "vowels", "first"] : ["whole", "vowels", "first", "inner"];
  return (
    <RadioList
      stack
      label={t("flatten.range")}
      value={props.value}
      onChange={(v) => props.onChange(v as Range)}
      items={ids.map((id) => ({ id, label: t(`flatten.range.${id}`), note: t(`flatten.range.${id}.note`) }))}
      testId="flatten-range"
    />
  );
}

function TargetChoices(props: { value: Target; onChange: (v: Target) => void; batch?: boolean }) {
  const ids: Target[] = props.batch ? ["auto", "edge"] : ["auto", "edge", "manual"];
  return (
    <RadioList
      stack
      label={t("flatten.target")}
      value={props.value}
      onChange={(v) => props.onChange(v as Target)}
      items={ids.map((id) => ({ id, label: t(`flatten.target.${id}`), note: t(`flatten.target.${id}.note`) }))}
      testId="flatten-target"
    />
  );
}

function SidePicker(props: { value: Side; onChange: (v: Side) => void }) {
  return (
    <Segmented<Side>
      size="sm"
      label={t("flatten.side")}
      value={props.value}
      onChange={props.onChange}
      options={[
        { id: "left", label: t("flatten.side.left") },
        { id: "right", label: t("flatten.side.right") },
      ]}
      testId="flatten-side"
    />
  );
}

export function FlattenSheet() {
  const req = useApp((st) => st.flattenRequest);
  const close = useApp((st) => st.requestFlatten);
  const onClose = () => {
    window.otto.player.stopAudition();
    close(null);
  };
  return req?.kind === "batch" ? (
    <BatchFlatten key={req.ids.join(",")} ids={req.ids} onClose={onClose} />
  ) : (
    <SingleFlatten req={req?.kind === "single" ? req : null} onClose={onClose} />
  );
}

function SingleFlatten({ req, onClose }: { req: Extract<FlattenRequest, { kind: "single" }> | null; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  const missing = useMissingModels(req !== null);
  const [op, setOp] = useState<FlattenOpened | null>(null);
  const [asset, setAsset] = useState<AssetRecord | null>(null);
  const [curve, setCurve] = useState<Curve | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("whole");
  const [target, setTarget] = useState<Target>("auto");
  const [side, setSide] = useState<Side>("left");
  const [manual, setManual] = useState("");
  const [inner, setInner] = useState<Sel | null>(null);
  const [trans, setTrans] = useState<[number, number]>([0.05, 0.05]);
  const [name, setName] = useState("");
  const [est, setEst] = useState<FlattenEstimate | null>(null);
  const [estError, setEstError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const gen = useRef(-1);
  const playAt = useRef<number | null>(null);

  // 打开：冻结并取默认值
  useEffect(() => {
    setOp(null);
    setOpenError(null);
    setSubmitError(null);
    setEst(null);
    if (!req) return;
    let live = true;
    void call("flatten.open", { assetId: req.assetId, start: req.start, end: req.end, entry: req.entry, sampleId: req.sampleId ?? null }).then(
      (r) => {
        if (!live) return;
        setOp(r);
        setRange(r.defaults.range);
        setTarget(r.defaults.target);
        setSide(r.defaults.side);
        setInner({ a: r.inner[0]!, b: r.inner[1]! });
        setTrans([r.transition, r.transition]);
        setName(r.name);
        setManual("");
      },
      (e) => live && setOpenError(e instanceof CoreFailure ? errorText(e.wire) : String(e)),
    );
    void call("assets.get", { id: req.assetId }).then((a) => live && setAsset(a), () => live && setAsset(null));
    // 金色 F0 线：输入资产已缓存的测量（只画可靠帧），平移到输入局部秒；没测过就不画
    setCurve(null);
    void call("measure.f0", { assetId: req.assetId, start: req.start, end: req.end }).then(
      (r) => {
        if (!live || !r.measured) return;
        const f = (b: Uint8Array) => new Float32Array(b.slice().buffer);
        const [f0, conf, en] = [f(r.f0), f(r.confidence), f(r.energy)];
        const v = new Float32Array(r.count);
        for (let i = 0; i < r.count; i++) v[i] = conf[i]! >= 0.5 && en[i]! > 1e-10 && f0[i]! > 0 ? f0[i]! : Number.NaN;
        setCurve({ t0: r.t0 - req.start, step: r.step, values: v });
      },
      () => {},
    );
    return () => {
      live = false;
    };
  }, [req]);

  const options = useMemo<FlattenOptions>(
    () => ({
      range,
      target,
      side,
      manual: target === "manual" ? manual : null,
      inner: range === "inner" && inner ? [inner.a, inner.b] : null,
      transition: range === "inner" ? [trans[0], trans[1]] : null,
    }),
    [range, target, side, manual, inner, trans],
  );

  // 预估（只读缓存，Core 也在这里校验选项：没有对齐、手动目标不对、内区不合法……）
  useEffect(() => {
    if (!op) return;
    let live = true;
    const h = setTimeout(() => {
      void call("flatten.estimate", { token: op.token, options, sampleId: req?.sampleId ?? null }).then(
        (r) => live && (setEst(r), setEstError(null)),
        (e) => live && (setEst(null), setEstError(e instanceof CoreFailure ? errorText(e.wire) : String(e))),
      );
    }, 120);
    return () => {
      live = false;
      clearTimeout(h);
    };
  }, [op, options, req?.sampleId]);

  // 试听外选区（试听播放器，关闭工作台即停；不影响原片播放器）
  useEffect(
    () =>
      window.otto.player.onState((st: PlayerState) => {
        if (st.player !== "audition" || st.gen !== gen.current) return;
        playAt.current = st.time;
        if (st.ended || st.error) {
          setPlaying(false);
          playAt.current = null;
        }
      }),
    [],
  );
  const play = async (a: number, b: number) => {
    if (!op) return;
    if (playing) {
      window.otto.player.stopAudition();
      setPlaying(false);
      return;
    }
    try {
      setPlaying(true);
      const base = op.token.start;
      gen.current = await window.otto.player.audition(op.token.assetId, base + a, base + b);
      playAt.current = 0;
      offsetRef.current = a;
    } catch (e) {
      setPlaying(false);
      toast({ text: errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });
    }
  };
  const offsetRef = useRef(0);

  const submit = async () => {
    if (!op || busy) return;
    setBusy(true);
    setSubmitError(null);
    try {
      await call("flatten.submit", { token: op.token, options, name, sampleId: req?.sampleId ?? null, localTags: currentProjectTags() });
      toast({ text: t("flatten.queued"), action: { label: t("speech.openTasks"), run: () => setTasksOpen(true) } });
      onClose();
    } catch (e) {
      setSubmitError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };

  const d = op?.duration ?? 0;
  const overlay: Layer | null = op?.alignment
    ? {
        id: "ph",
        label: t("speech.layer.ph"),
        bands: op.alignment.phones.map((p) => ({ a: p.start, b: p.end, label: p.label, tone: p.label === "pau" ? "pause" : VOWELS.has(p.label) ? "vowel" : "consonant" })),
      }
    : null;
  const lanes: Layer[] = est?.intervals.length
    ? [{ id: "proc", label: t("flatten.lane"), bands: est.intervals.map(([a, b]) => ({ a: a!, b: b!, label: t("flatten.lane"), tone: "seg" as const })) }]
    : [];
  const tgt = est?.target;
  const blocked = Boolean(estError) || !name.trim() || !op;

  return (
    <Sheet
      isOpen={req !== null}
      onClose={onClose}
      title={t("flatten.title")}
      sub={
        req && op ? (
          <span data-user-data="">{t("flatten.sub", { track: assetLabel(asset), a: seconds(op.token.start), b: seconds(op.token.end) })}</span>
        ) : undefined
      }
      testId="flatten-sheet"
      footer={
        <>
          <span className={s.say}>{t("flatten.defaultsNote")}</span>
          <div className={s.grow} />
          <Button variant="flat" onPress={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isDisabled={blocked || busy} data-testid="flatten-go">
            {t("flatten.go")}
          </Button>
        </>
      }
    >
      {openError ? (
        <div className={s.pad} data-testid="flatten-open-error">
          <Callout tone="bad">{openError}</Callout>
        </div>
      ) : (
        <div className={s.layout}>
          <div className={s.main}>
            {missing.length ? <Callout tone="warn">{t("flatten.modelsMissing", { models: missing.join(t("settings.subtitle.speakerSep")) })}</Callout> : null}
            <section className={s.card}>
              <div className={s.cardHead}>
                <h3 className={s.cardTitle}>{t("flatten.outer")}</h3>
                <div className={s.grow} />
                <span className={s.faint}>{t("flatten.ownPlayer")}</span>
              </div>
              <div className={s.wave} data-testid="flatten-wave">
                {op && asset ? (
                  <Timeline
                    assetId={op.token.assetId}
                    duration={d}
                    offset={-op.token.start}
                    assetDuration={asset.duration}
                    playhead={() => (playing && playAt.current != null ? offsetRef.current + playAt.current : null)}
                    playing={playing}
                    selection={range === "inner" ? inner : null}
                    selectionTone="gold"
                    onSelection={(v) => range === "inner" && v && setInner(v)}
                    onSeek={() => {}}
                    onPlayFrom={(at) => void play(at, d)}
                    overlay={overlay}
                    lanes={lanes}
                    curve={curve}
                  />
                ) : null}
              </div>
              <div className={s.row}>
                <Button variant="flat" icon={playing ? <Square /> : <Play />} onPress={() => void play(0, d)} isDisabled={!op} data-testid="flatten-play">
                  {playing ? t("library.stop") : t("flatten.play")}
                </Button>
                {range === "inner" && inner ? (
                  <Button variant="flat" onPress={() => void play(inner.a, inner.b)}>
                    {t("flatten.playInner")}
                  </Button>
                ) : null}
                <div className={s.grow} />
                <span className={s.estimate} data-testid="flatten-estimate">
                  {estError ? (
                    <span className={s.bad}>{estError}</span>
                  ) : !est ? (
                    ""
                  ) : est.status === "ok" && tgt ? (
                    <>
                      {t(target === "manual" ? "flatten.est.manual" : "flatten.est.target")} <b className={s.note}>{tgt.name}</b>
                      {tgt.ref && target !== "manual" ? ` · ${t("flatten.est.ref", { a: seconds(tgt.ref[0]!), b: seconds(tgt.ref[1]!) })}` : ""}
                      {target === "manual" ? ` · ${t(Number.isInteger(tgt.midi) ? "flatten.est.exactNote" : "flatten.est.exactHz")}` : ` · ${t("flatten.est.cached")}`}
                    </>
                  ) : est.status === "insufficient" && est.error ? (
                    <span className={s.warn}>
                      {errorText(est.error)} · {t("flatten.est.cachedOnly")}
                    </span>
                  ) : (
                    t("flatten.est.inJob")
                  )}
                </span>
              </div>
              {range === "inner" ? <div className={s.faint}>{t("flatten.innerHint")}</div> : null}
              {range !== "whole" && range !== "inner" && !op?.alignment && !estError ? <Callout tone="warn">{t("flatten.needAlignment")}</Callout> : null}
              {op?.alignment?.manual ? <div className={s.faint}>{t("flatten.manualAlignment")}</div> : null}
            </section>
            <section className={s.card}>
              <h3 className={s.cardTitle}>{t("flatten.product")}</h3>
              <label className={s.field}>
                <span className={s.fieldLabel}>{t("flatten.name")}</span>
                <span className={s.fieldInput} lang="ja">
                  <TextField value={name} onChange={setName} label={t("flatten.name")} testId="flatten-name" />
                </span>
              </label>
              <span className={s.faint}>{t("flatten.productNote")}</span>
            </section>
            {submitError ? <Callout tone="bad">{submitError}</Callout> : null}
          </div>
          <aside className={s.side}>
            <div className={s.optTitle}>{t("flatten.range")}</div>
            <RangeChoices value={range} onChange={setRange} />
            {range === "inner" ? (
              <div className={s.trans}>
                <span className={s.fieldLabel}>{t("flatten.transLeft")}</span>
                <NumberField label={t("flatten.transLeft")} value={trans[0]} onChange={(v) => setTrans([v, trans[1]])} minValue={0} maxValue={1} step={0.01} />
                <span className={s.fieldLabel}>{t("flatten.transRight")}</span>
                <NumberField label={t("flatten.transRight")} value={trans[1]} onChange={(v) => setTrans([trans[0], v])} minValue={0} maxValue={1} step={0.01} />
              </div>
            ) : null}
            <div className={s.optTitle}>{t("flatten.target")}</div>
            <TargetChoices value={target} onChange={setTarget} />
            {target === "edge" ? <SidePicker value={side} onChange={setSide} /> : null}
            {target === "manual" ? (
              <TextField value={manual} onChange={setManual} label={t("flatten.manual")} placeholder={t("flatten.manualPlaceholder")} mono testId="flatten-manual" />
            ) : null}
          </aside>
        </div>
      )}
    </Sheet>
  );
}

function BatchFlatten({ ids, onClose }: { ids: string[]; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  const missing = useMissingModels(true);
  const [range, setRange] = useState<Range>("vowels");
  const [target, setTarget] = useState<Target>("auto");
  const [side, setSide] = useState<Side>("left");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 默认值：设置「拉平」组的批量项
  useEffect(() => {
    void call("settings.list").then((st) => {
      setRange(st["flatten.batch_range"]!.value as Range);
      setTarget(st["flatten.batch_target"]!.value as Target);
    });
  }, []);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await call("flatten.submitBatch", { ids, options: { range, target, side }, localTags: currentProjectTags() });
      toast({ text: t("flatten.batchQueued", { n: ids.length }), action: { label: t("speech.openTasks"), run: () => setTasksOpen(true) } });
      onClose();
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet
      isOpen
      onClose={onClose}
      title={t("flatten.batchTitle", { n: ids.length })}
      sub={t("flatten.batchSub")}
      testId="flatten-batch-sheet"
      footer={
        <>
          <div className={s.grow} />
          <Button variant="flat" onPress={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isDisabled={busy} data-testid="flatten-batch-go">
            {t("flatten.batchGo", { n: ids.length })}
          </Button>
        </>
      }
    >
      <div className={s.layout}>
        <div className={s.main}>
          {missing.length ? <Callout tone="warn">{t("flatten.modelsMissing", { models: missing.join(t("settings.subtitle.speakerSep")) })}</Callout> : null}
          <section className={s.card}>
            <h3 className={s.cardTitle}>{t("flatten.batchWill")}</h3>
            <div className={s.say}>{t("flatten.batchBody", { n: ids.length })}</div>
          </section>
          {error ? <Callout tone="bad">{error}</Callout> : null}
        </div>
        <aside className={s.side}>
          <div className={s.optTitle}>{t("flatten.range")}</div>
          <RangeChoices value={range} onChange={setRange} batch />
          <div className={s.optTitle}>{t("flatten.target")}</div>
          <TargetChoices value={target} onChange={setTarget} batch />
          {target === "edge" ? <SidePicker value={side} onChange={setSide} /> : null}
          <span className={s.faint}>{t("flatten.batchAutoOnly")}</span>
        </aside>
      </div>
    </Sheet>
  );
}
