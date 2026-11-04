// 设置 › 命令行与 agent（所有者 2026-10-30）：otto 在哪、手动重装命令、复制给 agent 的开场白。
import { useEffect, useState } from "react";
import type { OttoInfo } from "../../shared/protocol";
import { Button } from "../components/Button";
import { Callout } from "../components/Controls";
import { t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Settings.module.css";

export function AgentPanel() {
  const [info, setInfo] = useState<OttoInfo | null>(null);
  const toast = useApp((st) => st.toast);
  useEffect(() => void window.otto.agent.ottoInfo().then(setInfo), []);
  if (!info) return null;
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast({ text: t("agentPanel.copied") });
  };
  // 还没装成命令时开场白里写完整路径；路径可能带空格
  const path = info.path ?? "otto";
  const command = info.linked ? "otto" : path.includes(" ") ? `"${path}"` : path;
  return (
    <div className={s.itemWide} data-testid="agent-panel">
      <div className={s.label}>{t("agentPanel.otto")}</div>
      {info.path ? <div className={`${s.hint} mono`} data-testid="agent-otto-path">{info.path}</div> : <Callout tone="bad">{t("agentPanel.ottoMissing")}</Callout>}
      {info.linked ? <div className={s.hint} data-testid="agent-otto-linked">{t("agentPanel.installed", { link: info.link ?? "" })}</div> : null}
      {info.conflict ? <Callout tone="bad">{t("agentPanel.conflict", { link: info.link ?? "" })}</Callout> : null}
      {!info.linked && info.path && info.link && !info.conflict ? <div className={s.hint}>{t("agentPanel.installHint", { link: info.link })}</div> : null}
      {info.path && !info.link ? <div className={s.hint}>{t("agentPanel.noInstall")}</div> : null}
      <div className={s.btnRow}>
        {info.path && info.link && !info.linked && !info.conflict ? (
          <Button variant="secondary" onPress={() => void window.otto.agent.installOtto().then(setInfo)} data-testid="agent-install-otto">
            {t("agentPanel.install")}
          </Button>
        ) : null}
        {info.path ? (
          <Button variant="flat" onPress={() => void copy(info.path!)} data-testid="agent-copy-path">
            {t("agentPanel.copyPath")}
          </Button>
        ) : null}
        <Button variant="flat" onPress={() => void copy(t("agentPanel.prompt", { otto: command }))} data-testid="agent-copy-prompt">
          {t("agentPanel.copyPrompt")}
        </Button>
      </div>
      <div className={s.hint}>{t("agentPanel.promptHint")}</div>
    </div>
  );
}
