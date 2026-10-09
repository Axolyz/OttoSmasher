// 检索浮层（UI_PLAN §2.1：横跨采样库、从顶部展开，查找后自动收起变成结果标签；Esc 收起）。
// 覆盖预检：语音“n/m 已就绪”、音高“已索引 a/b”；为 0 时禁用查找并给「准备当前范围索引」；准备完成只刷新覆盖数，不重新搜索（10 §10.2.5）。
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../../api/core";
import type { SampleFilter, SearchCoverage } from "../../api/types";
import { Button } from "../../components/Button";
import { Segmented } from "../../components/Controls";
import { errorText, t } from "../../i18n";
import { useApp } from "../../state/store";
import { MetricsBody, type MetricsDraft } from "./MetricsComposer";
import { PitchCanvas, type PitchDraft, PitchFooter, PitchHeader, PitchInspector, usePitchCheck } from "./PitchComposer";
import s from "./Search.module.css";
import { SpeechCanvas, type SpeechDraft, SpeechFooter, SpeechHeader, SpeechInspector, SpeechSettings, speechProblem } from "./SpeechComposer";

export type ComposerMode = "speech" | "pitch" | "timbre" | "transient";

export function Composer(props: {
  mode: ComposerMode;
  setMode: (m: ComposerMode) => void;
  speech: SpeechDraft;
  setSpeech: (d: SpeechDraft) => void;
  pitch: PitchDraft;
  setPitch: (d: PitchDraft) => void;
  metrics: MetricsDraft;
  setMetrics: (d: MetricsDraft) => void;
  scope: SampleFilter;
  bpm: number | null;
  running: boolean;
  onFind: () => void;
  onCancel: () => void;
  onClose: () => void;
}) {
  const { mode } = props;
  const toast = useApp((st) => st.toast);
  const [sSel, setSSel] = useState<number | null>(null);
  const [pSel, setPSel] = useState<number | null>(null);
  const check = usePitchCheck(props.pitch);
  const [cov, setCov] = useState<SearchCoverage | null>(null);
  const covMode = mode === "speech" ? "speech" : mode === "pitch" && props.pitch.mode === "samples" ? "pitch" : null;
  const loadCov = () => {
    if (!covMode) return setCov(null);
    void call("search.coverage", { mode: covMode, scope: props.scope }).then(setCov, () => setCov(null));
  };
  useEffect(loadCov, [covMode, JSON.stringify(props.scope)]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("search.coverage", () => loadCov());
  useCoreEvent("job.updated", (j) => {
    const job = j as { kind: string; status: string };
    if ((job.kind === "speech.analyze" || job.kind === "f0.measure") && job.status === "succeeded") loadCov();
  });
  const prepare = async () => {
    if (!covMode) return;
    try {
      await call("search.prepare", { mode: covMode, scope: props.scope });
      toast({ text: t("search.prepareQueued") });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const problem = mode === "speech" ? speechProblem(props.speech) : mode === "pitch" ? (check && !check.ok ? t("search.pitch.fix") : null) : null;
  const noneReady = cov != null && cov.ready === 0;
  const canFind = (mode === "speech" || mode === "pitch") && !problem && !noneReady && (mode !== "pitch" || check?.ok === true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        if (canFind && !props.running) props.onFind();
      } else if (e.key === "Escape" && !document.querySelector("[role=dialog]")) {
        props.onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className={s.composer} data-testid="composer" data-mode={mode}>
      <div className={s.row}>
        <Segmented<ComposerMode>
          value={mode}
          onChange={props.setMode}
          label={t("search.kind")}
          size="sm"
          options={(["speech", "pitch", "timbre", "transient"] as const).map((k) => ({ id: k, label: t(`search.kind.${k}`), data: { "data-testid": `composer-${k}` } }))}
        />
        {mode === "speech" ? <SpeechHeader d={props.speech} set={props.setSpeech} bpm={props.bpm} /> : null}
        {mode === "pitch" ? <PitchHeader d={props.pitch} set={props.setPitch} /> : null}
        <span className={s.grow} />
        {cov ? (
          <span className={s.muted} data-testid="search-coverage">
            {t(covMode === "speech" ? "search.coverage.speech" : "search.coverage.pitch", { ready: cov.ready, total: cov.total })}
            {cov.noAnalysis ? ` · ${t("search.coverage.noAnalysis", { n: cov.noAnalysis })}` : ""}
          </span>
        ) : null}
        {cov && cov.stale > 0 ? (
          <Button size="sm" variant="flat" onPress={() => void prepare()} data-testid="search-prepare">
            {t("search.prepare", { n: cov.stale })}
          </Button>
        ) : null}
        {mode === "speech" ? <SpeechSettings d={props.speech} set={props.setSpeech} /> : null}
        <Button size="sm" variant="flat" onPress={props.onClose} data-testid="composer-close">
          {t("search.collapse")}
        </Button>
        {mode === "speech" || mode === "pitch" ? (
          props.running ? (
            <Button size="sm" variant="secondary" onPress={props.onCancel} data-testid="search-cancel">
              {t("search.cancel")}
            </Button>
          ) : (
            <Button size="sm" variant="primary" onPress={props.onFind} isDisabled={!canFind} data-testid="search-find" title={problem ?? (noneReady ? t("search.noneReady") : undefined)}>
              {t("search.find")} <kbd className={s.kbd}>⌘↵</kbd>
            </Button>
          )
        ) : null}
      </div>
      {props.running ? <span className={s.muted} data-testid="search-running">{t("search.running")}</span> : null}
      {mode === "speech" ? (
        <>
          <div className={s.cv}>
            <SpeechCanvas d={props.speech} set={props.setSpeech} sel={sSel} setSel={setSSel} />
            <SpeechInspector d={props.speech} set={props.setSpeech} sel={sSel} setSel={setSSel} />
          </div>
          {problem ? <span className={s.err} data-testid="speech-problem">{problem}</span> : null}
          <SpeechFooter d={props.speech} set={props.setSpeech} />
        </>
      ) : null}
      {mode === "pitch" ? (
        <>
          <div className={s.cv}>
            <PitchCanvas d={props.pitch} set={props.setPitch} sel={pSel} setSel={setPSel} />
            <PitchInspector d={props.pitch} set={props.setPitch} sel={pSel} setSel={setPSel} check={check} />
          </div>
          <PitchFooter d={props.pitch} set={props.setPitch} check={check} />
        </>
      ) : null}
      {mode === "timbre" || mode === "transient" ? (
        <MetricsBody d={{ ...props.metrics, mode }} set={(d) => props.setMetrics({ ...d, mode })} scope={props.scope} />
      ) : null}
    </div>
  );
}
