// 舞台「节奏与卡拍」面板（UI_PLAN §3；原型 natPanel、drawMap；规格 09 §9.4–§9.5、03 §3.3）与语音面板里的「分组与停顿」小弹出（L20）。
// - 卡拍方案直接可选（近快 / 近慢 / 倍快，带倍速与 n 格/拍）；映射图常驻（原句与卡拍同比例秒数轴 + 对应连线）；
// - 试听（所有者 2026-10-08）：声音 原声 / 原声＋咔哒 / 纯咔哒 ×「▶ 不卡拍」「♩ 卡拍」；咔哒声与音块起音同步；
// - 临时「按 mora」与「长音补格」（不保存，换采样回到关），「写进人工占格」把这套占格存下来；
// - 小弹出：人工占格（改即保存，可撤销）、逐音属性；人工项属于旧的分析版本时提示「重新套用 / 清除」。
// 只给语音与未分类（单音没有卡拍）；业务都在 Core（rhythm.view / rhythm.setParams / rhythm.render）。
import { Music2, Play, Square } from "lucide-react";
import { useEffect } from "react";
import { CoreFailure, call } from "../api/core";
import type { RhythmPlan, RhythmScheme, RhythmSound, RhythmView, SampleRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, Segmented, Token } from "../components/Controls";
import { NumberField } from "../components/Fields";
import { AnchoredPanel } from "../components/Panel";
import { PagedTable } from "../components/PagedTable";
import { seconds } from "../format";
import { errorText, t } from "../i18n";
import { type AuditionVersion, useApp } from "../state/store";
import s from "./Library.module.css";
import { useRhythmView } from "./rhythmView";

const PLANS: RhythmPlan[] = ["near_fast", "near_slow", "double"];
const SOUNDS: RhythmSound[] = ["voice", "voice+click", "click"];

export function densityText(d: number): string {
  return d >= 1 ? String(Math.round(d)) : `1/${Math.round(1 / d)}`;
}

function planLabel(k: RhythmPlan, sc: RhythmScheme | undefined): string {
  if (!sc) return t(`rhythm.plan.${k}`);
  return t("rhythm.planLabel", { plan: t(`rhythm.plan.${k}`), speed: sc.speed.toFixed(2), density: densityText(sc.density) });
}

/** 映射图（UI_PLAN §3、R13.3）：原句与卡拍共用同一秒数轴，控制点之间画对应连线。 */
function RhythmMap(props: { scheme: RhythmScheme; window: number[] }) {
  const { scheme, window: w } = props;
  const src = scheme.sourceSeconds;
  const out = scheme.outSeconds;
  const maxT = Math.max(src, out, 1e-6);
  const X = (v: number) => 10 + (v / maxT) * 680;
  return (
    <div className={s.mapWrap}>
      <svg className={s.rhythmMap} viewBox="0 0 700 92" preserveAspectRatio="none" role="img" aria-label={t("rhythm.mapLabel")} data-testid="rhythm-map">
        <line x1={X(0)} y1={18} x2={X(src)} y2={18} className={s.mapSrc} />
        <line x1={X(0)} y1={74} x2={X(out)} y2={74} className={s.mapTgt} />
        {scheme.points.map((p, i) => (
          <g key={i}>
            <line x1={X(p.src - w[0]!)} y1={18} x2={X(p.tgt)} y2={74} className={s.mapLink} data-kind={p.kind} />
            <circle cx={X(p.src - w[0]!)} cy={18} r={3.5} className={s.mapSrcDot} />
            <circle cx={X(p.tgt)} cy={74} r={3.5} className={s.mapTgtDot} data-kind={p.kind} />
          </g>
        ))}
      </svg>
      {/* 文字不放进拉伸的 SVG（窄窗口下会被压扁） */}
      <span className={s.mapLabelTop}>{t("rhythm.mapSource")}</span>
      <span className={s.mapLabelBottom}>{t("rhythm.mapTarget")}</span>
    </div>
  );
}

function fail(toast: ReturnType<typeof useApp.getState>["toast"], e: unknown) {
  toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
}

/** 改逐采样的节奏参数（经编辑通道，可撤销） */
async function setParams(view: RhythmView, patch: Record<string, unknown>) {
  await call("rhythm.setParams", { id: view.sampleId, version: view.version, ...patch });
}

function StaleManual(props: { view: RhythmView }) {
  const toast = useApp((st) => st.toast);
  if (!props.view.manual?.stale) return null;
  return (
    <Callout tone="warn" testId="rhythm-stale">
      <div className={s.calloutRow}>
        <span>{t("rhythm.manualStale")}</span>
        <div className={s.grow} />
        <Button size="sm" onPress={() => void setParams(props.view, { reapply: true }).catch((e) => fail(toast, e))} data-testid="rhythm-reapply">
          {t("rhythm.reapply")}
        </Button>
        <Button size="sm" variant="flat" onPress={() => void setParams(props.view, { clearManual: true }).catch((e) => fail(toast, e))}>
          {t("rhythm.clearManual")}
        </Button>
      </div>
    </Callout>
  );
}

export function StageRhythm(props: { sample: SampleRow; playingKey: string | null; onAudition: (version: AuditionVersion, sound: RhythmSound) => void }) {
  const smp = props.sample;
  const toast = useApp((st) => st.toast);
  const bpm = useApp((st) => st.bpm);
  const sr = useApp((st) => st.stageRhythm);
  const setSr = useApp((st) => st.setStageRhythm);
  useEffect(() => setSr({ sampleId: smp.id }), [smp.id, setSr]);
  const { view, error } = useRhythmView(smp.id, smp.version);
  const plan = sr.sampleId === smp.id ? sr.plan : "near_fast";
  const sound = sr.sampleId === smp.id ? sr.sound : "voice";
  const ok = view?.status === "ok";
  const scheme = ok ? view.schemes?.[plan] : undefined;

  const playing = (v: AuditionVersion) => props.playingKey === `${v}:${sound}`;
  const manualCells = (view?.manual?.applied ? view.manual.cells : {}) as Record<string, number>;
  const saveCell = (i: number, n: number | null) => {
    if (!view) return;
    const cells: Record<string, number | null> = { ...manualCells, [String(i)]: n };
    void setParams(view, { cells }).catch((e) => fail(toast, e));
  };

  return (
    <section className={s.card} data-testid="rhythm-panel">
      <div className={s.waveHead}>
        <h3 className={s.cardTitle}>{t("rhythm.panel")}</h3>
        <div className={s.grow} />
        <span className={s.mutedText} data-testid="rhythm-bpm">
          {bpm == null ? t("rhythm.originalSpeed", { bpm: scheme ? scheme.bpm.toFixed(1) : "–" }) : t("rhythm.bpm", { bpm })}
        </span>
      </div>
      {error && !view ? (
        <Callout tone="bad" testId="rhythm-error">
          {error instanceof CoreFailure ? errorText(error.wire) : String(error)}
        </Callout>
      ) : null}
      {!view ? null : !ok ? (
        <div className={s.hintText} data-testid="rhythm-none">
          {t("rhythm.none")}
        </div>
      ) : (
        <>
          <StaleManual view={view} />
          {view.schemeError ? <Callout tone="bad">{errorText(view.schemeError)}</Callout> : null}
          <div className={s.speechActions}>
            <Segmented<RhythmPlan>
              size="sm"
              label={t("rhythm.planHead")}
              value={plan}
              onChange={(v) => setSr({ sampleId: smp.id, plan: v })}
              options={PLANS.map((k) => ({ id: k, label: planLabel(k, view.schemes?.[k]), data: { "data-testid": `rhythm-plan-${k}` } }))}
              wrap
              testId="rhythm-plans"
            />
            <div className={s.grow} />
            <Checkbox isSelected={sr.mora} onChange={(v) => setSr({ sampleId: smp.id, mora: v, longVowel: v ? sr.longVowel : false })} label={t("rhythm.mora")} testId="rhythm-mora">
              {t("rhythm.mora")}
            </Checkbox>
            {sr.mora ? (
              <>
                <Checkbox isSelected={sr.longVowel} onChange={(v) => setSr({ sampleId: smp.id, longVowel: v })} label={t("rhythm.longVowel")}>
                  {t("rhythm.longVowel")}
                </Checkbox>
                <Button
                  size="sm"
                  variant="flat"
                  isDisabled={view.route !== "mora"}
                  onPress={() =>
                    void setParams(view, { moraToCells: { longVowel: sr.longVowel } }).then(
                      () => {
                        setSr({ sampleId: smp.id, mora: false, longVowel: false });
                        toast({ text: t("rhythm.moraSaved") });
                      },
                      (e) => fail(toast, e),
                    )
                  }
                  data-testid="rhythm-mora-save"
                >
                  {t("rhythm.moraToCells")}
                </Button>
              </>
            ) : null}
          </div>
          {sr.mora && view.routeError ? <Callout tone="warn">{errorText(view.routeError)}</Callout> : null}
          {scheme ? (
            <>
              <RhythmMap scheme={scheme} window={view.window ?? [0, 0]} />
              <div className={s.mutedText} data-testid="rhythm-map-text">
                {t("rhythm.mapCaption", { a: seconds(scheme.sourceSeconds), b: seconds(scheme.outSeconds) })}
              </div>
            </>
          ) : null}
          <div className={s.speechActions}>
            <span className={s.mutedText}>{t("rhythm.audition")}</span>
            <Segmented<RhythmSound>
              size="sm"
              label={t("rhythm.audition")}
              value={sound}
              onChange={(v) => setSr({ sampleId: smp.id, sound: v })}
              options={SOUNDS.map((k) => ({ id: k, label: t(`rhythm.sound.${k}`), data: { "data-testid": `rhythm-sound-${k}` } }))}
              wrap
              testId="rhythm-sounds"
            />
            <div className={s.grow} />
            <Button size="sm" variant="flat" icon={playing("original") ? <Square /> : <Play />} onPress={() => props.onAudition("original", sound)} data-testid="rhythm-play-original">
              {playing("original") ? t("library.stop") : t("rhythm.playOriginal")}
            </Button>
            <Button size="sm" variant="primary" icon={playing("stretched") ? <Square /> : <Music2 />} isDisabled={!scheme} onPress={() => props.onAudition("stretched", sound)} data-testid="rhythm-play-stretched">
              {playing("stretched") ? t("library.stop") : t("rhythm.playStretched")}
            </Button>
          </div>
          <div className={s.speechActions}>
            <AnchoredPanel
              title={t("rhythm.cells")}
              aux={view.tick ? t("rhythm.tick", { ms: Math.round(view.tick * 1000) }) : null}
              width={340}
              testId="rhythm-cells-panel"
              trigger={
                <Button size="sm" variant="flat" data-testid="rhythm-cells">
                  {t("rhythm.cells")}
                </Button>
              }
            >
              <PagedTable
                label={t("rhythm.cells")}
                pageSize={64}
                rows={(view.blocks ?? []).map((b, i) => ({ id: String(i), i, b, beat: scheme?.points.filter((p) => p.kind === "onset")[i]?.beat }))}
                columns={[
                  { id: "block", label: t("rhythm.col.block"), isRowHeader: true, render: (r) => <span lang="ja" data-user-data="">{`◆${r.i + 1} ${r.b.text}`}</span> },
                  { id: "beat", label: t("rhythm.col.beat"), width: "64px", align: "end", render: (r) => <span className="num">{r.beat == null ? "–" : r.beat.toFixed(2)}</span> },
                  {
                    id: "cells",
                    label: t("rhythm.col.cells"),
                    width: "130px",
                    render: (r) => (
                      <div className={s.cellEdit} data-manual={r.b.manual || undefined}>
                        <NumberField value={r.b.cells} minValue={1} maxValue={64} step={1} label={t("rhythm.col.cells")} onChange={(v) => v !== r.b.cells && saveCell(r.i, v)} />
                        {r.b.manual ? (
                          <Button size="sm" variant="flat" onPress={() => saveCell(r.i, null)} title={t("rhythm.cellAuto")}>
                            {t("rhythm.cellAutoShort")}
                          </Button>
                        ) : null}
                      </div>
                    ),
                  },
                ]}
              />
              <div className={s.mutedText}>{t("rhythm.cellsNote")}</div>
            </AnchoredPanel>
            <AnchoredPanel
              title={t("rhythm.attrs")}
              width={460}
              testId="rhythm-attrs-panel"
              trigger={
                <Button size="sm" variant="flat" data-testid="rhythm-attrs">
                  {t("rhythm.attrs")}
                </Button>
              }
            >
              <PagedTable
                label={t("rhythm.attrs")}
                pageSize={64}
                rows={(view.blocks ?? []).map((b, i) => ({ id: String(i), i, b }))}
                columns={[
                  { id: "block", label: t("rhythm.col.block"), isRowHeader: true, render: (r) => <span lang="ja" data-user-data="">{`◆${r.i + 1} ${r.b.text}`}</span> },
                  { id: "vowel", label: t("rhythm.col.vowel"), width: "48px", render: (r) => (r.b.vowel ? <span data-user-data="">{r.b.vowel}</span> : t("common.unknown")) },
                  { id: "cons", label: t("rhythm.col.consonant"), width: "56px", render: (r) => (r.b.consonants.length ? <span data-user-data="">{r.b.consonants.join(" ")}</span> : t("rhythm.noConsonant")) },
                  { id: "pitch", label: t("rhythm.col.relPitch"), width: "64px", align: "end", render: (r) => signed(r.b.relPitch, 1) },
                  { id: "trend", label: t("rhythm.col.trend"), width: "52px", render: (r) => trendText(r.b.trend) },
                  { id: "loud", label: t("rhythm.col.loudness"), width: "60px", align: "end", render: (r) => (r.b.relLoudness == null ? t("common.unknown") : t("rhythm.db", { v: signed(r.b.relLoudness, 1) })) },
                  { id: "strength", label: t("rhythm.col.strength"), width: "52px", align: "end", render: (r) => (r.b.strength == null ? t("common.unknown") : r.b.strength.toFixed(2)) },
                ]}
              />
              <div className={s.mutedText}>{t("rhythm.attrsNote")}</div>
            </AnchoredPanel>
            <div className={s.grow} />
            <span className={s.mutedText}>{t("rhythm.route.raw")}</span>
          </div>
        </>
      )}
    </section>
  );
}

function signed(v: number | null, digits: number): string {
  if (v == null) return t("common.unknown");
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}`;
}

function trendText(v: number | null): string {
  if (v == null) return t("common.unknown");
  return v >= 1 ? t("rhythm.trend.up") : v <= -1 ? t("rhythm.trend.down") : t("rhythm.trend.flat");
}

/** 语音面板的「分组与停顿」（L20；03 §3.7：拆点、停顿灵敏度、语段阈值；改即保存，只重建派生节奏，不跑模型）。
 *  拆点：单击音素 = 在它前面拆开（只能拆开合在一起的元音/拨音）；切分：单击音块 = 在它前面切开 / 合并自动切口。 */
export function GroupingPanel(props: { sample: SampleRow; isDisabled?: boolean }) {
  const toast = useApp((st) => st.toast);
  const { view } = useRhythmView(props.sample.id, props.sample.version);
  const ok = view?.status === "ok";
  const applied = ok && view.manual?.applied;
  const splits = new Set(applied ? view.manual!.splits : []);
  const save = (patch: Record<string, unknown>) => view && void setParams(view, patch).catch((e) => fail(toast, e));
  const phones = ok ? (view.phones ?? []) : [];
  const blocks = ok ? (view.blocks ?? []) : [];
  const cuts = ok ? (view.cuts ?? []) : [];
  const cutAt = (k: number) => cuts.find((c) => c.k === k);
  const SYL = new Set(["a", "i", "u", "e", "o", "I", "U", "N"]);
  const splittable = (k: number) => k > 0 && SYL.has(phones[k]!.label) && SYL.has(phones[k - 1]!.label);
  const toggleCut = (k: number) => {
    if (!view) return;
    const m = applied ? view.manual! : { cuts: [] as number[], merges: [] as number[] };
    const c = cutAt(k);
    if (c?.kind === "auto") {
      const merges = c.merged ? m.merges.filter((x) => x !== k) : [...m.merges, k];
      save({ merges });
    } else if (c?.kind === "manual") save({ cuts: m.cuts.filter((x) => x !== k) });
    else save({ cuts: [...m.cuts, k] });
  };
  return (
    <AnchoredPanel
      title={t("rhythm.grouping")}
      width={420}
      placement="bottom end"
      testId="rhythm-grouping-panel"
      trigger={
        <Button size="sm" variant="flat" isDisabled={props.isDisabled || !ok} title={ok ? undefined : t("rhythm.none")} data-testid="rhythm-grouping">
          {t("rhythm.grouping")}
        </Button>
      }
    >
      {view && ok ? (
        <>
          <StaleManual view={view} />
          <div className={s.groupRow}>
            <span className={s.fieldLabel}>{t("rhythm.sensitivity")}</span>
            <NumberField value={view.params!.sensitivity} minValue={0.5} maxValue={2} step={0.1} label={t("rhythm.sensitivity")} onChange={(v) => v !== view.params!.sensitivity && save({ sensitivity: v })} />
            <span className={s.mutedText}>{t("rhythm.pauses", { n: view.pauses?.length ?? 0 })}</span>
          </div>
          <div className={s.groupRow}>
            <span className={s.fieldLabel}>{t("rhythm.segmentThreshold")}</span>
            <NumberField
              value={view.params!.segmentThreshold}
              minValue={0.16}
              maxValue={2}
              step={0.01}
              label={t("rhythm.segmentThreshold")}
              onChange={(v) => v !== view.params!.segmentThreshold && save({ segmentThreshold: v })}
            />
            <span className={s.mutedText}>{t("rhythm.segments", { n: Math.max(1, view.segments?.length ?? 0) })}</span>
          </div>
          <div className={s.subHead}>{t("rhythm.splitHead")}</div>
          <div className={s.tokenRow} data-testid="rhythm-split-phones">
            {phones.map((p, k) => (
              <Token
                key={k}
                label={`${splits.has(k) ? "| " : ""}${p.label}`}
                strong={SYL.has(p.label)}
                selected={splits.has(k)}
                title={t("rhythm.phoneN", { n: k + 1, a: seconds(p.start), b: seconds(p.end) })}
                onPress={splittable(k) || splits.has(k) ? () => save({ splits: splits.has(k) ? [...splits].filter((x) => x !== k) : [...splits, k] }) : undefined}
                testId="rhythm-split-phone"
              />
            ))}
          </div>
          <div className={s.mutedText}>{t("rhythm.splitNote")}</div>
          <div className={s.subHead}>{t("rhythm.cutHead")}</div>
          <div className={s.tokenRow} data-testid="rhythm-cut-blocks">
            {blocks.map((b, k) => {
              const c = cutAt(k);
              const live = c && !c.merged;
              return (
                <Token
                  key={k}
                  label={`${live ? "‖ " : ""}${b.text}`}
                  lang="ja"
                  selected={!!live}
                  strong={c?.kind === "manual"}
                  title={c ? t(c.kind === "auto" ? (c.merged ? "rhythm.cutMerged" : "rhythm.cutAuto") : "rhythm.cutManual", { n: k + 1 }) : t("rhythm.cutNone", { n: k + 1 })}
                  onPress={k > 0 ? () => toggleCut(k) : undefined}
                  testId="rhythm-cut-block"
                />
              );
            })}
          </div>
          <div className={s.mutedText}>{t("rhythm.cutNote")}</div>
        </>
      ) : null}
    </AnchoredPanel>
  );
}
