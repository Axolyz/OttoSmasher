// PyMSS Studio 状态（设置 → PyMSS Studio；规格 14 §14.6）：找到的安装、版本、活动环境、模型目录、已下载完整的模型（人声 / 三轨标记），
// 可把人声模型设为“默认人声模型”。读取模型列表是一个轻量任务（会起一次 Studio 子进程），完成后自动刷新。
import { useCallback, useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import type { StudioStatus } from "../api/types";
import { Button } from "../components/Button";
import { Callout } from "../components/Controls";
import { errorText, t } from "../i18n";
import s from "./Settings.module.css";

type Status = StudioStatus;

export function StudioPanel(props: { vocalModel: string; onVocalModel: (name: string) => void }) {
  const [st, setSt] = useState<Status | null>(null);
  const load = useCallback(async () => setSt(await call("studio.status")), []);
  useEffect(() => void load(), [load]);
  useCoreEvent("job.updated", (d) => {
    const j = d as { id: string; status: string };
    if (st?.listingJob === j.id && j.status !== "queued" && j.status !== "running") void load();
  });
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).setting) void load();
  });
  if (!st) return null;
  if (!st.ok) return <Callout tone="bad" testId="studio-status">{st.error ? errorText(st.error) : ""}</Callout>;
  return (
    <div className={s.itemWide} data-testid="studio-status">
      <div className={s.label}>{t("studio.found", { version: st.env?.version ?? t("studio.versionUnknown") })}</div>
      <div className={`${s.hint} mono`}>{st.env?.app}</div>
      <div className={`${s.hint} mono`}>{t("studio.modelDir", { path: st.env?.model_dir ?? "" })}</div>
      {st.models == null ? (
        <div className={s.hint}>{t("sep.listing")}</div>
      ) : (
        <ul className={s.modelList}>
          {st.models.map((m) => (
            <li key={m.name}>
              <span className="mono">{m.name}</span>
              <span className={s.hint}>{m.stems.join(" | ")}</span>
              {m.vocal ? <span className={s.tag}>{t("studio.vocal")}</span> : null}
              {m.threeTrack ? <span className={s.tag}>{t("sep.threeTrack")}</span> : null}
              <span className={s.grow} />
              {m.vocal ? (
                m.name === props.vocalModel ? (
                  <span className={s.hint}>{t("sep.preferred")}</span>
                ) : (
                  <Button size="sm" variant="flat" onPress={() => props.onVocalModel(m.name)}>
                    {t("studio.setDefault")}
                  </Button>
                )
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
