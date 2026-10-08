// 环境与模型（规格 13 §13.4、16 R19.7）：文件就位 / 运行库可加载 / 实测状态，三者分开显示。
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { JobSummary, ModelsStatus } from "../api/types";
import { Button } from "../components/Button";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Settings.module.css";

export function ModelsPanel() {
  const toast = useApp((st) => st.toast);
  const [st, setSt] = useState<ModelsStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const reload = useCallback(() => void call("models.status").then(setSt), []);
  useEffect(reload, [reload]);
  useCoreEvent("models.changed", reload);
  useCoreEvent("job.updated", (d) => {
    const j = d as JobSummary;
    if (j.id === busy && j.status !== "queued" && j.status !== "running") {
      setBusy(null);
      if (j.error) toast({ text: errorText(j.error), tone: "error" });
      reload();
    }
  });
  const verify = async () => {
    try {
      const job = await call("models.verify");
      setBusy(job.id);
    } catch (e) {
      if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
    }
  };
  if (!st) return null;
  const ort = st.runtime.onnxruntime;
  return (
    <div className={s.models}>
      <div className={s.modelsHead}>
        <div className={s.paths}>
          <div className="mono">{t("models.dir", { path: st.models_dir })}</div>
          <div className="mono">{t("models.supportDir", { path: st.support_dir })}</div>
        </div>
        <Button variant="primary" onPress={() => void verify()} isDisabled={busy !== null} data-testid="models-verify">
          {busy ? t("models.verifying") : t("models.verify")}
        </Button>
      </div>
      <h4 className={s.sub}>{t("models.runtime")}</h4>
      <div className={ort.loadable ? s.ok : s.bad}>
        {ort.loadable ? t("models.runtime.loadable", { version: ort.version }) : t("models.runtime.missing", { error: ort.error })}
      </div>
      <h4 className={s.sub}>{t("models.files")}</h4>
      {st.files.map((m) => (
        <div key={m.model} className={s.model} data-testid={`model-${m.model}`} data-state={m.state}>
          <div className={s.modelHead}>
            <b>{t(`models.name.${m.model}`)}</b>
            <span className={m.state === "ready" ? s.ok : m.state === "unverified" ? s.warn : s.bad}>{t(`models.state.${m.state}`)}</span>
          </div>
          {m.files.map((f) => (
            <div key={f.path} className={s.file}>
              <span className={s.role}>{t(`models.role.${f.role}`)}</span>
              <span className={`mono ${s.fpath}`}>{f.path.split("/").slice(-2).join("/")}</span>
              <span className={f.state === "ok" ? s.ok : f.state === "unverified" ? s.warn : s.bad}>
                {f.state === "missing" ? t("models.file.missing", { path: f.path }) : t(`models.file.${f.state}`)}
              </span>
            </div>
          ))}
          <div className={s.probe}>
            {t("models.probe", { status: st.probes.find((p) => p.model === m.model)?.status ?? t("models.probe.untested") })}
          </div>
        </div>
      ))}
    </div>
  );
}
