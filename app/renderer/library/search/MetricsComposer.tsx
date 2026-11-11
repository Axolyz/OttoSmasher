// 单音 · 音色 / 单音 · 瞬态（10 §10.3、03 §3.4.3；原型 renderComposer timbre/transient）：即时筛选当前范围（不是固定结果）。
// 勾选指标填最小/最大；缺少所选指标的采样不命中，按指标单独计数；「后台准备当前范围指标」。每个指标悬停显示定义与单位。
import { Info } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../../api/core";
import type { MetricFilter, MetricsStatus, SampleFilter } from "../../api/types";
import { Button } from "../../components/Button";
import { OptionalNumber } from "../../components/Fields";
import { Tip } from "../../components/Overlay";
import { PagedTable } from "../../components/PagedTable";
import { errorText, t } from "../../i18n";
import { useApp } from "../../state/store";
import s from "./Search.module.css";

export type MetricMode = "timbre" | "transient";
const DEFAULTS: Record<MetricMode, string[]> = {
  timbre: ["effectiveDuration", "pitch", "pitchSpread", "voicedDuration", "highHarmonicRatio", "harmonicRatio", "highRatio"],
  transient: ["effectiveDuration", "attackTime", "decayTime", "crestDb", "lowRatio", "highRatio", "flatness"],
};
const MORE = ["rmsDb", "midRatio", "centroid", "attackLowRatio", "attackHighRatio", "attackCentroid", "attackFlatness", "bodyLowRatio", "bodyHighRatio",
  "bodyCentroid", "bodyFlatness", "tailLowRatio", "tailHighRatio", "tailCentroid", "tailFlatness"];

export interface MetricsDraft {
  mode: MetricMode;
  chosen: string[];
  ranges: Record<string, [number | null, number | null]>;
  more: boolean;
}

export const newMetricsDraft = (mode: MetricMode): MetricsDraft => ({ mode, chosen: [], ranges: {}, more: false });

const ALL_METRICS = [...new Set([...DEFAULTS.timbre, ...DEFAULTS.transient, ...MORE])];

export function restoreMetricsDraft(value: unknown): MetricsDraft | null {
  if (!value || typeof value !== "object") return null;
  const saved = value as Partial<MetricsDraft>;
  if (saved.mode !== "timbre" && saved.mode !== "transient") return null;
  const ranges: MetricsDraft["ranges"] = {};
  const bound = (v: unknown) => typeof v === "number" && Number.isFinite(v) ? v : null;
  for (const metric of ALL_METRICS) {
    const pair = saved.ranges?.[metric];
    if (!Array.isArray(pair)) continue;
    const lo = bound(pair[0]);
    const hi = bound(pair[1]);
    if (lo == null || hi == null || lo <= hi) ranges[metric] = [lo, hi];
  }
  const savedChosen = saved.chosen;
  const chosen = Array.isArray(savedChosen) ? ALL_METRICS.filter((metric) => savedChosen.includes(metric)) : [];
  return { mode: saved.mode, ranges, chosen, more: saved.more === true };
}

export function metricFilter(d: MetricsDraft): MetricFilter | null {
  const conditions = d.chosen.map((m) => ({ metric: m, min: d.ranges[m]?.[0] ?? null, max: d.ranges[m]?.[1] ?? null })).filter((c) => c.min != null || c.max != null);
  return conditions.length ? { mode: d.mode, conditions } : null;
}

export function MetricsBody(props: { d: MetricsDraft; set: (d: MetricsDraft) => void; scope: SampleFilter }) {
  const { d, set } = props;
  const toast = useApp((st) => st.toast);
  const advanced = [...MORE, ...DEFAULTS[d.mode === "timbre" ? "transient" : "timbre"]];
  const metrics = [...new Set([...DEFAULTS[d.mode], ...(d.more ? advanced : d.chosen)])];
  const [status, setStatus] = useState<MetricsStatus | null>(null);
  const reload = () => void call("metrics.status", { scope: props.scope, metrics }).then(setStatus, () => setStatus(null));
  useEffect(reload, [JSON.stringify(props.scope), metrics.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("search.coverage", (x) => (x as { mode: string }).mode === "metrics" && reload());
  const prepare = async () => {
    try {
      await call("metrics.prepare", { scope: props.scope });
      toast({ text: t("search.metrics.queued") });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const setRange = (m: string, i: 0 | 1, v: number | null) => {
    const cur: [number | null, number | null] = [...(d.ranges[m] ?? [null, null])] as [number | null, number | null];
    cur[i] = v;
    set({ ...d, ranges: { ...d.ranges, [m]: cur } });
  };
  return (
    <>
      <div className={s.row}>
        <span className={s.muted}>{t("search.metrics.note")}</span>
        <span className={s.grow} />
        {status ? (
          <span className={s.muted} data-testid="metrics-status">
            {t("search.metrics.ready", { ready: status.ready, total: status.total })}
          </span>
        ) : null}
        <Button size="sm" variant="flat" onPress={() => void prepare()} isDisabled={!status?.stale} data-testid="metrics-prepare">
          {t("search.metrics.prepare")}
        </Button>
      </div>
      <PagedTable
        label={t("search.metrics.table")}
        rows={metrics.map((m) => ({ id: m }))}
        checked={new Set(d.chosen)}
        onChecked={(next) => set({ ...d, chosen: [...next] })}
        checkLabel={(r) => t(`metric.${r.id}`)}
        testId="metrics-table"
        columns={[
          {
            id: "name", label: t("search.metrics.metric"), isRowHeader: true,
            render: (r) => (
              <span className={s.pair}>
                {t(`metric.${r.id}`)}
                <Tip content={t(`metric.${r.id}.def`)}>
                  <Info size={12} aria-label={t("search.metrics.def")} />
                </Tip>
              </span>
            ),
          },
          { id: "min", label: t("search.min"), width: "100px", render: (r) => <OptionalNumber value={d.ranges[r.id]?.[0] ?? null} onChange={(v) => setRange(r.id, 0, v)} label={t("search.min")} width={80} testId={`metric-min-${r.id}`} /> },
          { id: "max", label: t("search.max"), width: "100px", render: (r) => <OptionalNumber value={d.ranges[r.id]?.[1] ?? null} onChange={(v) => setRange(r.id, 1, v)} label={t("search.max")} width={80} testId={`metric-max-${r.id}`} /> },
          { id: "unit", label: t("search.metrics.unit"), width: "70px", render: (r) => <span className={s.muted}>{t(`metric.${r.id}.unit`)}</span> },
          { id: "missing", label: t("search.metrics.missing"), width: "70px", align: "end", render: (r) => <span className="num">{status?.missing[r.id] ?? "–"}</span> },
        ]}
      />
      <div className={s.row}>
        <Button size="sm" variant="flat" onPress={() => set({ ...d, more: !d.more })}>
          {d.more ? t("search.metrics.less") : t("search.metrics.more")}
        </Button>
      </div>
    </>
  );
}
