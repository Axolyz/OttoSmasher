// 任务抽屉（UI_PLAN §1）：进度、取消、重试、错误与日志位置。
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { JobSummary } from "../api/types";
import { Button } from "../components/Button";
import { Callout, ProgressBar } from "../components/Controls";
import { SeparationResults } from "./SeparationResults";
import { SpeechResults } from "./SpeechResults";
import { FlattenResults, useOpenProduct } from "./FlattenResults";
import { Drawer } from "../components/Overlay";
import { errorText, hasKey, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./TaskDrawer.module.css";

export function useJobs(): JobSummary[] {
  const ready = useApp((st) => st.core.state === "ready");
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  useEffect(() => {
    if (ready) void call("jobs.list").then(setJobs, () => setJobs([]));
  }, [ready]);
  useCoreEvent("job.updated", (d) => {
    const j = d as JobSummary;
    setJobs((prev) => {
      const i = prev.findIndex((x) => x.id === j.id);
      if (i < 0) return [j, ...prev];
      const next = prev.slice();
      next[i] = j;
      return next;
    });
  });
  return jobs;
}

/** 任务成功了但有一部分没做成（P6：不静默降级），例如语音分析里音高没测成。码登记在 Core 的错误码表；``cause`` 是原因（错误码 + 参数） */
interface JobWarning {
  code: string;
  args?: Record<string, unknown>;
  cause?: { code: string; args?: Record<string, unknown> };
}

function warningText(w: JobWarning): string {
  return errorText({ code: w.code, args: { ...w.args, cause: w.cause ? errorText(w.cause) : "" } });
}

function kindLabel(kind: string): string {
  return hasKey(`tasks.kind.${kind}`) ? t(`tasks.kind.${kind}`) : kind;
}

export function jobDeviceText(job: JobSummary): string {
  if (job.kind === "separate") {
    const device = job.separationDevice;
    const requested = device?.requested;
    const label = requested === "auto" ? t("tasks.device.studioAuto")
      : requested === "cuda" ? t("tasks.device.cuda", { n: device?.deviceId ?? t("tasks.device.unknown") })
      : requested ? t(`settings.studio.device.${requested}`) : t("tasks.device.unknown");
    return t("tasks.device.separation", { device: label });
  }
  return t("tasks.device", { device: job.device.accelerate ? t("tasks.device.accel", { n: job.device.directml_device }) : t("tasks.device.cpu") });
}

function JobRow({ job }: { job: JobSummary }) {
  const toast = useApp((st) => st.toast);
  const openProduct = useOpenProduct();
  const [open, setOpen] = useState(false);
  // 单个拉平：「打开结果」= 选中成品采样并回到采样库（03 §3.1.3）
  const singleFlatten = job.kind === "flatten" && !(job.result as { batch?: boolean } | null)?.batch && job.items?.total === 1;
  const openFlatten = async () => {
    const rows = await call("flatten.results", { jobId: job.id });
    const pid = rows.find((r) => r.productId)?.productId;
    if (pid) openProduct(pid);
    else toast({ text: t("flatten.results.none"), tone: "error" });
  };
  const act = async (method: "jobs.cancel" | "jobs.retry") => {
    try {
      await call(method, { id: job.id });
    } catch (e) {
      if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
    }
  };
  const p = job.progress;
  const active = job.status === "queued" || job.status === "running";
  return (
    <div className={s.job} data-testid="job" data-status={job.status}>
      <div className={s.head}>
        <span className={`${s.dot} ${s[job.status]}`} />
        <b className={s.kind}>{kindLabel(job.kind)}</b>
        <span className={s.chip}>{t(`tasks.channel.${job.channel}`)}</span>
        {job.background ? <span className={s.chip}>{t("tasks.background")}</span> : null}
        {job.actor && job.actor.kind !== "user" ? (
          <span className={s.chip} title={job.actor.session ?? undefined} data-testid="job-agent">
            {t("tasks.byAgent")}
          </span>
        ) : null}
        <div className={s.grow} />
        <span className={s.status}>{t(`tasks.status.${job.status}`)}</span>
      </div>
      {job.status === "running" && p ? (
        <div className={s.progRow}>
          <ProgressBar
            value={p.total ? p.percent ?? 0 : null}
            max={100}
            label={kindLabel(job.kind)}
            showValue={p.total ? t("tasks.progress", { done: p.done, total: p.total }) : undefined}
          />
        </div>
      ) : null}
      {(job.kind === "speech.analyze" || (job.kind === "flatten" && !singleFlatten)) && job.items && !active ? (
        <div className={s.meta} data-testid="speech-summary">
          {t(job.kind === "speech.analyze" ? "speech.jobSummary" : "tasks.itemSummary", { ok: job.items.ok ?? 0, failed: job.items.failed ?? 0 })}
        </div>
      ) : null}
      {((job.result as { warnings?: JobWarning[] } | null)?.warnings ?? []).map((w, i) => (
        <Callout key={i} tone="warn" testId="job-warning">
          {warningText(w)}
        </Callout>
      ))}
      {job.error ? (
        <div className={s.err}>
          <div>{errorText(job.error)}</div>
          {typeof job.error.args.log === "string" ? <div className={`${s.path} mono`}>{t("tasks.log", { path: job.error.args.log })}</div> : null}
        </div>
      ) : null}
      <div className={s.meta}>
        <span className="num">{job.created_at.replace("T", " ").slice(0, 19)}</span>
        <span>{jobDeviceText(job)}</span>
        {job.retry_of ? <span>{t("tasks.retryOf", { id: job.retry_of.slice(0, 8) })}</span> : null}
        <div className={s.grow} />
        {active ? (
          <Button size="sm" onPress={() => void act("jobs.cancel")}>
            {t("tasks.cancel")}
          </Button>
        ) : null}
        {singleFlatten && job.status === "succeeded" ? (
          <Button size="sm" variant="flat" onPress={() => void openFlatten()} data-testid="job-results">
            {t("tasks.openResults")}
          </Button>
        ) : null}
        {(job.kind === "separate" || job.kind === "speech.analyze" || (job.kind === "flatten" && !singleFlatten)) && job.status === "succeeded" ? (
          <Button size="sm" variant={open ? "secondary" : "flat"} onPress={() => setOpen((v) => !v)} data-testid="job-results">
            {t("tasks.openResults")}
          </Button>
        ) : null}
        {job.status === "failed" || job.status === "cancelled" || job.status === "interrupted" ? (
          <Button size="sm" onPress={() => void act("jobs.retry")}>
            {t("tasks.retry")}
          </Button>
        ) : null}
      </div>
      {open && job.kind === "separate" ? <SeparationResults jobId={job.id} /> : null}
      {open && job.kind === "speech.analyze" ? <SpeechResults jobId={job.id} /> : null}
      {open && job.kind === "flatten" ? <FlattenResults jobId={job.id} /> : null}
    </div>
  );
}

export function TaskDrawer({ jobs }: { jobs: JobSummary[] }) {
  const open = useApp((st) => st.tasksOpen);
  const setOpen = useApp((st) => st.setTasksOpen);
  return (
    <Drawer isOpen={open} onClose={() => setOpen(false)} title={t("tasks.title")}>
      {jobs.length === 0 ? <div className={s.none}>{t("tasks.empty")}</div> : jobs.map((j) => <JobRow key={j.id} job={j} />)}
    </Drawer>
  );
}
