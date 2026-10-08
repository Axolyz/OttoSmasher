// 任务抽屉（UI_PLAN §1）：进度、取消、重试、错误与日志位置。
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { JobSummary } from "../api/types";
import { Button } from "../components/Button";
import { ProgressBar } from "../components/Controls";
import { SeparationResults } from "./SeparationResults";
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

function kindLabel(kind: string): string {
  return hasKey(`tasks.kind.${kind}`) ? t(`tasks.kind.${kind}`) : kind;
}

function JobRow({ job }: { job: JobSummary }) {
  const toast = useApp((st) => st.toast);
  const [open, setOpen] = useState(false);
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
      {job.error ? (
        <div className={s.err}>
          <div>{errorText(job.error)}</div>
          {typeof job.error.args.log === "string" ? <div className={`${s.path} mono`}>{t("tasks.log", { path: job.error.args.log })}</div> : null}
        </div>
      ) : null}
      <div className={s.meta}>
        <span className="num">{job.created_at.replace("T", " ").slice(0, 19)}</span>
        <span>{t("tasks.device", { device: job.device.accelerate ? t("tasks.device.accel", { n: job.device.directml_device }) : t("tasks.device.cpu") })}</span>
        {job.retry_of ? <span>{t("tasks.retryOf", { id: job.retry_of.slice(0, 8) })}</span> : null}
        <div className={s.grow} />
        {active ? (
          <Button size="sm" onPress={() => void act("jobs.cancel")}>
            {t("tasks.cancel")}
          </Button>
        ) : null}
        {job.kind === "separate" && job.status === "succeeded" ? (
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
      {open ? <SeparationResults jobId={job.id} /> : null}
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
