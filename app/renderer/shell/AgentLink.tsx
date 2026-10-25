// 命令行 / agent（阶段 A，UI_PLAN §23）：撤销不了的命令的确认框。会话与修改记录在操作历史里（History.tsx）。
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AgentConfirm, DeletePreview, IndependItem } from "../api/types";
import { ConfirmDialog } from "../components/Overlay";
import { errorText, hasKey, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./AgentLink.module.css";

export function methodName(m: string): string {
  return hasKey(`agent.method.${m}`) ? t(`agent.method.${m}`) : m;
}

export function previewText(c: Pick<AgentConfirm, "method" | "preview">): string | null {
  const p = c.preview as Record<string, unknown> | null;
  if (!p) return null;
  if (c.method === "sources.delete") {
    const d = p as unknown as DeletePreview;
    return t("agent.preview.sourceDelete", { path: d.path, samples: d.samples, segments: d.segments, hints: d.hints, rangeTags: d.rangeTags, independent: d.independentSamples });
  }
  if (c.method === "samples.delete") {
    const names = (p.names as string[]) ?? [];
    return t("agent.preview.samplesDelete", { n: Number(p.count ?? 0), names: names.join(t("agent.preview.sep")) });
  }
  if (c.method === "samples.independ") return t("agent.preview.independ", { n: ((p.plan as IndependItem[]) ?? []).length });
  return null;
}

/** 外部连接要执行撤销不了的命令：排队逐个问；别的窗口回答了、超时或连接断了（agent.confirmClosed）就撤下。 */
export function AgentConfirmHost() {
  const toast = useApp((st) => st.toast);
  const [queue, setQueue] = useState<Array<AgentConfirm & { until: number }>>([]);
  const [now, setNow] = useState(Date.now());
  useCoreEvent("agent.confirm", (d) => {
    const c = d as AgentConfirm;
    setQueue((q) => [...q, { ...c, until: Date.now() + c.seconds * 1000 }]);
  });
  useCoreEvent("agent.confirmClosed", (d) => {
    const id = (d as { id: string }).id;
    setQueue((q) => q.filter((x) => x.id !== id));
  });
  const cur = queue[0] ?? null;
  useEffect(() => {
    if (!cur || cur.seconds <= 0) return;
    const h = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(h);
  }, [cur?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const answer = async (approve: boolean) => {
    if (!cur) return;
    setQueue((q) => q.slice(1));
    try {
      const r = await call("agent.confirmReply", { id: cur.id, approve });
      // 提问之后资料变了：没有执行，马上会带新的影响预览再问一次
      if (r.reasked) toast({ text: t("agent.reasked") });
    } catch (e) {
      // 已经超时或连接断了：只提示，不重试
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  if (!cur) return null;
  const preview = previewText(cur);
  return (
    <ConfirmDialog
      isOpen
      danger
      title={t("agent.confirmTitle")}
      confirmLabel={t("agent.confirmOk")}
      onConfirm={() => void answer(true)}
      onClose={() => void answer(false)}
      testId="agent-confirm"
    >
      <p>
        {t("agent.confirmWho", { kind: t(`agent.kind.${cur.actor.kind}`) })} <b data-user-data="">{cur.actor.session ?? t("agent.noSession")}</b>
      </p>
      <p>
        <b>{methodName(cur.method)}</b>
      </p>
      {preview ? <p data-user-data="">{preview}</p> : null}
      <p className={s.meta}>
        {cur.seconds > 0 ? t("agent.confirmCountdown", { s: Math.max(0, Math.round((cur.until - now) / 1000)) }) : t("agent.confirmWaiting")}
      </p>
    </ConfirmDialog>
  );
}
