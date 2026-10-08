// 舞台的“声音与语音”（UI_PLAN §3、§3.1；原型 renderStage 的波形卡与 speechPanel）：
// - 波形卡：“声音：绑定资产名”（只显示，不能切换，Q7）；图层栏选一个覆盖层（音素 / mora / 无），其他图层用车道；金色 F0 线；
// - 语音面板：音素按 mora 分组（假名在上、音素在下）、分析状态、「语音分析…」；没有台词时「提供台词并分析」。
// 时间：这里的时间轴是采样绑定资产的局部秒（测量里的音素时间也是资产局部秒）。
import { useEffect, useMemo, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AssetRecord, SampleRow, SpeechPhone, SpeechSampleView } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Segmented, Token } from "../components/Controls";
import { TextField } from "../components/Fields";
import { seconds } from "../format";
import { errorText, hasKey, t } from "../i18n";
import { useApp } from "../state/store";
import { type Curve, type Layer, type Sel, Timeline, type TimelineHandle } from "../sources/Timeline";
import s from "./Library.module.css";

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
  const model = typeof a.production?.model === "string" ? a.production.model : "";
  return [model, a.stem_name].filter(Boolean).join(" · ");
}

/** 音素 → 覆盖层的色带 */
function phoneBands(phones: SpeechPhone[]): Layer {
  return {
    id: "ph",
    label: t("speech.layer.ph"),
    bands: phones.map((p) => ({ a: p.start, b: p.end, label: p.label, tone: p.label === "pau" ? ("pause" as const) : VOWELS.has(p.label) ? ("vowel" as const) : ("consonant" as const) })),
  };
}

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

export function StageSpeech(props: { sample: SampleRow; playhead: () => number | null; playing: boolean; onPlayRange: (a: number, b: number) => void }) {
  const smp = props.sample;
  const toast = useApp((st) => st.toast);
  const requestSpeech = useApp((st) => st.requestSpeech);
  const [asset, setAsset] = useState<AssetRecord | null>(null);
  const [view, setView] = useState<SpeechSampleView | null>(null);
  const [curve, setCurve] = useState<Curve | null>(null);
  const [layer, setLayer] = useState<LayerId>("ph");
  const [sel, setSel] = useState<Sel | null>(null);
  const [draft, setDraft] = useState("");
  const tl = useRef<TimelineHandle>(null);

  const loadSpeech = () => void call("speech.sample", { id: smp.id }).then(setView, () => setView(null));
  useEffect(() => {
    setView(null);
    setCurve(null);
    setSel(null);
    loadSpeech();
    void call("assets.get", { id: smp.asset_id }).then(setAsset, () => setAsset(null));
  }, [smp.id, smp.asset_id]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const res = view?.head?.result ?? null;
  const layers = useMemo(() => {
    if (!res) return { ph: null, mora: null };
    return { ph: phoneBands(res.phones), mora: moraBands(res.phones, res.morae) };
  }, [res]);
  const overlay = layer === "none" ? null : layers[layer];
  const lanes = (["ph", "mora"] as const).filter((k) => k !== layer && layers[k]).map((k) => layers[k]!);

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

  const lastFail = view?.runs.find((r) => r.status === "failed");
  const headOk = view?.head?.status === "ok";
  const status = !view
    ? ""
    : headOk
      ? view.head!.manual
        ? t("speech.status.manual")
        : t("speech.status.ok")
      : lastFail
        ? t("speech.status.failed", { reason: lastFail.error ? errorText(lastFail.error) : "" })
        : t("speech.status.none");

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
            value={layer}
            onChange={setLayer}
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
        </div>
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
              onSeek={() => {}}
              onPlayFrom={(at) => props.onPlayRange(at, Math.max(at + 0.05, sel && sel.b > at ? sel.b : smp.end))}
              overlay={overlay}
              lanes={lanes}
              onLaneDoubleClick={(id) => setLayer(id as LayerId)}
              curve={curve}
            />
          ) : null}
        </div>
        {sel ? (
          <div className={s.selLine}>
            <span className="num">{t("speech.selection", { a: seconds(sel.a), b: seconds(sel.b) })}</span>
            <Button size="sm" variant="flat" onPress={() => props.onPlayRange(sel.a, sel.b)}>
              {t("speech.playSel")}
            </Button>
          </div>
        ) : null}
      </section>
      <section className={s.card} data-testid="speech-panel">
        <div className={s.waveHead}>
          <h3 className={s.cardTitle}>{t("speech.panel")}</h3>
          <span className={headOk ? s.okText : lastFail ? s.badText : s.mutedText} data-testid="speech-status">
            {status}
          </span>
        </div>
        {res ? (
          <div className={s.moras} data-testid="speech-moras">
            {groups.map((g, gi) => (
              <div key={gi} className={s.mora}>
                <span className={s.kana} lang="ja">
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
            <span className={s.mutedText}>{t(hasKey(`speech.textSource.${view.textSource}`) ? `speech.textSource.${view.textSource}` : "speech.textSource.snapshot")}</span>
            <span lang="ja" data-user-data="" data-testid="speech-text">
              {view.text}
            </span>
          </div>
        ) : null}
        {view?.text && view.head && headOk && view.head.text !== view.text ? <Callout tone="warn">{t("speech.textChanged")}</Callout> : null}
        <div className={s.stageActions}>
          <Button size="sm" onPress={() => requestSpeech({ entry: "samples", ids: [smp.id] })} isDisabled={!view?.text} data-testid="speech-analyze">
            {t("speech.menu")}
          </Button>
        </div>
      </section>
    </>
  );
}
