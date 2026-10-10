// 环境与模型（规格 13 §13.4、16 R19.7）：文件就位 / 运行库可加载 / 实测状态，三者分开显示。
// 模型权重（所有者 2026-10-10：发布包不带权重，应用里要有地方下载）：显式「下载缺少的模型」（每个模型一个任务，固定地址、核对 SHA-256）、
// 单个模型「下载」、「从文件导入…」（别处下好的文件按 SHA-256 认）、「打开模型目录」；缺的模型写明许可、直链与放置路径（可以自己下载）。
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { JobSummary, ModelDownloadItem, ModelProbe, ModelsStatus } from "../api/types";
import { Button } from "../components/Button";
import { fileSize } from "../format";
import { errorText, t } from "../i18n";
import { useJobs } from "../shell/TaskDrawer";
import { useApp } from "../state/store";
import s from "./Settings.module.css";

/** 实测结果：通过 · 各 EP 节点数 / 失败：原因 / 未实测（规格 14 §14.7：provider 可用 ≠ 实测通过） */
function probeText(p: ModelProbe | undefined): string {
  if (!p) return t("models.probe.untested");
  if (p.status === "failed") return t("models.probe.failed", { error: p.error ?? "" });
  const nodes = Object.entries(p.nodes ?? {});
  if (!nodes.length) return t("models.probe.passedNoNodes");
  return t("models.probe.passed", { nodes: nodes.map(([ep, n]) => `${ep.replace("ExecutionProvider", "")} ${n}`).join(" / ") });
}

const done = (j: JobSummary) => j.status !== "queued" && j.status !== "running";

export function ModelsPanel() {
  const toast = useApp((st) => st.toast);
  const [st, setSt] = useState<ModelsStatus | null>(null);
  const [plan, setPlan] = useState<ModelDownloadItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const [importing, setImporting] = useState<string | null>(null);
  /** 下载任务：模型 → 任务 ID（Core 的状态里也有，设置关了再开照样看得到进度） */
  const [started, setStarted] = useState<Record<string, string>>({});
  const jobs = useJobs();
  const reload = useCallback(() => {
    void call("models.status").then((x) => {
      setSt(x);
      setStarted({});
    });
    void call("models.downloadPlan", {}).then(setPlan, () => setPlan([]));
  }, []);
  useEffect(reload, [reload]);
  useCoreEvent("models.changed", reload);
  useCoreEvent("job.updated", (d) => {
    const j = d as JobSummary;
    if (j.id === busy && done(j)) {
      setBusy(null);
      if (j.error) toast({ text: errorText(j.error), tone: "error" });
      reload();
    }
    if (j.id === probing && done(j)) {
      setProbing(null);
      if (j.error) toast({ text: errorText(j.error), tone: "error" });
      reload();
    }
    if (j.id === importing && done(j)) {
      setImporting(null);
      if (j.error) toast({ text: errorText(j.error), tone: "error" });
      else {
        const r = (j.result ?? {}) as { imported?: unknown[]; skipped?: unknown[] };
        const n = r.imported?.length ?? 0;
        toast({ text: n ? t("models.imported", { n }) : t("models.importNone", { n: r.skipped?.length ?? 0 }), tone: n ? "info" : "error" });
      }
      reload();
    }
    const model = Object.keys(downloads).find((m) => downloads[m] === j.id);
    if (model && done(j)) {
      if (j.error) toast({ text: errorText(j.error), tone: "error" });
      else if (j.status === "succeeded") toast({ text: t("models.downloaded", { model: t(`models.name.${model}`) }) });
      reload();
    }
  });
  const fail = (e: unknown) => {
    if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
  };
  const probe = async () => {
    try {
      setProbing((await call("models.probe")).id);
    } catch (e) {
      fail(e);
    }
  };
  const verify = async () => {
    try {
      setBusy((await call("models.verify")).id);
    } catch (e) {
      fail(e);
    }
  };
  const download = async (models?: string[]) => {
    try {
      const res = await call("models.download", models ? { models } : {});
      setStarted((prev) => ({ ...prev, ...Object.fromEntries(res.map((x) => [x.model, x.job.id])) }));
      toast({ text: t("models.downloadStarted", { n: res.length }) });
    } catch (e) {
      fail(e);
    }
  };
  const importFiles = async () => {
    const paths = await window.otto.files.pick("models");
    if (!paths.length) return;
    try {
      setImporting((await call("models.import", { paths })).id);
    } catch (e) {
      fail(e);
    }
  };
  const downloads: Record<string, string> = { ...(st?.downloading ?? {}), ...started };
  if (!st) return null;
  const ort = st.runtime.onnxruntime;
  const pending = plan.filter((p) => !downloads[p.model]);
  const unverified = st.files.some((m) => m.state === "unverified");
  return (
    <div className={s.models}>
      <h4 className={s.sub}>{t("models.getTitle")}</h4>
      <div className={s.hint}>{t("models.getSay")}</div>
      <div className={s.btnRow}>
        <Button variant="primary" onPress={() => void download()} isDisabled={!pending.length} data-testid="models-download">
          {pending.length
            ? t("models.download", { n: pending.length, size: fileSize(pending.reduce((a, p) => a + (p.size ?? 0), 0)) })
            : Object.keys(downloads).length
              ? t("models.downloadQueued")
              : t("models.downloadNone")}
        </Button>
        <Button onPress={() => void importFiles()} isDisabled={importing !== null} title={t("models.importTip")} data-testid="models-import">
          {t("models.import")}
        </Button>
        <Button variant="flat" onPress={() => void window.otto.files.reveal(st.models_dir)} data-testid="models-open-dir">
          {t("models.openDir")}
        </Button>
      </div>
      {!plan.length && unverified ? <div className={s.warn}>{t("models.downloadUnverified")}</div> : null}
      <div className={s.modelsHead}>
        <div className={s.paths}>
          <div className="mono">{t("models.dir", { path: st.models_dir })}</div>
          <div className="mono">{t("models.supportDir", { path: st.support_dir })}</div>
        </div>
        <Button variant="secondary" onPress={() => void verify()} isDisabled={busy !== null} data-testid="models-verify">
          {busy ? t("models.verifying") : t("models.verify")}
        </Button>
        <Button onPress={() => void probe()} isDisabled={probing !== null} data-testid="models-probe">
          {probing ? t("models.probing") : t("models.probeRun")}
        </Button>
      </div>
      <h4 className={s.sub}>{t("models.runtime")}</h4>
      <div className={ort.loadable ? s.ok : s.bad}>
        {ort.loadable ? t("models.runtime.loadable", { version: ort.version }) : t("models.runtime.missing", { error: ort.error })}
      </div>
      <h4 className={s.sub}>{t("models.files")}</h4>
      <div className={s.probe}>{st.device.accelerate ? t("models.device.accel", { n: st.device.directml_device }) : t("models.device.cpu")}</div>
      {st.files.map((m) => {
        const item = plan.find((p) => p.model === m.model);
        const job = downloads[m.model] ? jobs.find((x) => x.id === downloads[m.model]) ?? null : null;
        const prog = job?.progress;
        return (
          <div key={m.model} className={s.model} data-testid={`model-${m.model}`} data-state={m.state}>
            <div className={s.modelHead}>
              <b>{t(`models.name.${m.model}`)}</b>
              <span className={m.state === "ready" ? s.ok : m.state === "unverified" ? s.warn : s.bad}>{t(`models.state.${m.state}`)}</span>
              <span className={s.grow} />
              <span className={s.probe}>{fileSize(m.bytes)}</span>
              {downloads[m.model] ? (
                <span className={s.probe} data-testid={`model-progress-${m.model}`}>
                  {job?.status === "running" && prog ? t("models.downloading", { done: prog.done, total: prog.total }) : t("models.downloadQueued")}
                </span>
              ) : item ? (
                <Button size="sm" variant="flat" onPress={() => void download([m.model])} data-testid={`model-download-${m.model}`}>
                  {t("models.downloadOne")}
                </Button>
              ) : null}
            </div>
            {m.files.map((f) => (
              <div key={f.path} className={s.file}>
                <span className={s.role}>{t(`models.role.${f.role}`)}</span>
                <span className={`mono ${s.fpath}`}>{f.path.split(/[\\/]/).slice(-2).join("/")}</span>
                <span className={f.state === "ok" ? s.ok : f.state === "unverified" ? s.warn : s.bad}>
                  {f.state === "missing" ? t("models.file.missing", { path: f.path }) : t(`models.file.${f.state}`)}
                </span>
              </div>
            ))}
            {item ? (
              <>
                <div className={item.license.includes("NC") ? s.warn : s.probe}>
                  {item.license.includes("NC") ? t("models.licenseNC") : t("models.license", { license: item.license })}
                  {item.replace ? ` · ${t("models.replace")}` : ""}
                </div>
                <div className={`${s.probe} ${s.selectable}`}>{t("models.manual", { url: item.url, path: item.path })}</div>
              </>
            ) : (
              <div className={s.probe}>{t("models.license", { license: m.license })}</div>
            )}
            <div className={s.probe} data-testid={`probe-${m.model}`}>
              {t("models.probe", { status: probeText(st.probes.find((p) => p.model === m.model)) })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
