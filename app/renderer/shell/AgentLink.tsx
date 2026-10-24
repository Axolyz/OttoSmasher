// 命令行 / agent（阶段 A，UI_PLAN §23）：顶栏的会话标记 + 锚定小面板（会话、修改数、撤回这个会话），以及撤销不了的命令的确认框。
// 命令行每次调用是一条短连接，所以标记显示“本次运行里出现过的会话”，正在连着的标出来；应用重启后清空。
import { Bot } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AgentConfirm, AgentSession, DeletePreview, IndependItem } from "../api/types";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/Overlay";
import { AnchoredPanel } from "../components/Panel";
import { errorText, hasKey, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./AgentLink.module.css";
import { describeLabel } from "./labels";

interface Seen {
  key: string;
  kind: AgentSession["kind"];
  session: string | null;
  lastSeen: number;
  connected: boolean;
  edits: number | null;
}

const keyOf = (x: { kind: string; session: string | null }) => `${x.kind}\u0000${x.session ?? ""}`;
const clock = (ms: number) => new Date(ms).toTimeString().slice(0, 5);

export function AgentIndicator() {
  const ready = useApp((st) => st.core.state === "ready");
  const toast = useApp((st) => st.toast);
  const [seen, setSeen] = useState<Seen[]>([]);
  const [open, setOpen] = useState(false);
  const [undoing, setUndoing] = useState<Seen | null>(null);
  const [busy, setBusy] = useState(false);

  const merge = (live: AgentSession[]) =>
    setSeen((prev) => {
      const now = Date.now();
      const by = new Map(prev.map((x) => [x.key, { ...x, connected: false }]));
      for (const a of live) {
        const k = keyOf(a);
        by.set(k, { key: k, kind: a.kind, session: a.session, lastSeen: now, connected: true, edits: by.get(k)?.edits ?? null });
      }
      return [...by.values()].sort((a, b) => b.lastSeen - a.lastSeen);
    });
  useEffect(() => {
    if (ready) void call("agent.sessions").then(merge, () => {});
  }, [ready]);
  useCoreEvent("agent.sessions", (d) => merge(d as AgentSession[]));

  // 打开面板时数一下每个会话还有几处没撤回的修改
  const count = async () => {
    const out = await Promise.all(
      seen.map(async (x) => {
        if (!x.session) return x;
        const h = await call("edits.history", { session: x.session, limit: 1000 }).catch(() => []);
        return { ...x, edits: h.filter((e) => !e.undoneBy && !e.undoOf).length };
      }),
    );
    setSeen(out);
  };

  const runUndo = async () => {
    if (!undoing?.session) return;
    setBusy(true);
    try {
      const r = await call("edits.undoSession", { session: undoing.session });
      toast({
        text: r.blocked
          ? t("agent.undoneBlocked", { n: r.undone, label: describeLabel(r.blocked.label), remaining: r.remaining })
          : t("agent.undone", { n: r.undone }),
      });
      setUndoing(null);
      void count();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  if (!seen.length) return null;
  const live = seen.filter((x) => x.connected).length;
  return (
    <>
      <AnchoredPanel
        isOpen={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (o) void count();
        }}
        placement="bottom end"
        width={360}
        title={t("agent.panelTitle")}
        aux={t("agent.panelAux")}
        testId="agent-panel"
        trigger={
          <Button variant="flat" icon={<Bot />} aria-label={t("agent.badgeTip")} title={t("agent.badgeTip")} data-testid="agent-badge">
            <span className={s.count} data-live={live > 0 || undefined}>
              {seen.length}
            </span>
          </Button>
        }
      >
        <div className={s.list}>
          {seen.map((x) => (
            <div key={x.key} className={s.row} data-testid="agent-session">
              <span className={s.dot} data-live={x.connected || undefined} />
              <span className={s.name}>
                <b data-user-data="">{x.session ?? t("agent.noSession")}</b>
                <span className={s.meta}>
                  {t(`agent.kind.${x.kind}`)} · {x.connected ? t("agent.connected") : t("agent.lastSeen", { time: clock(x.lastSeen) })}
                  {x.edits != null ? ` · ${t("agent.edits", { n: x.edits })}` : ""}
                </span>
              </span>
              <Button
                size="sm"
                variant="flat"
                isDisabled={!x.session || x.edits === 0}
                onPress={() => {
                  setOpen(false);
                  setUndoing(x);
                }}
                data-testid="agent-undo"
              >
                {t("agent.undoSession")}
              </Button>
            </div>
          ))}
        </div>
      </AnchoredPanel>
      <ConfirmDialog
        isOpen={!!undoing}
        title={t("agent.undoTitle", { session: undoing?.session ?? "" })}
        confirmLabel={t("agent.undoOk")}
        busy={busy}
        onConfirm={() => void runUndo()}
        onClose={() => setUndoing(null)}
        testId="agent-undo-confirm"
      >
        <p>{t("agent.undoBody", { n: undoing?.edits ?? 0 })}</p>
      </ConfirmDialog>
    </>
  );
}

function methodName(m: string): string {
  return hasKey(`agent.method.${m}`) ? t(`agent.method.${m}`) : m;
}

function previewText(c: AgentConfirm): string | null {
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
    if (!cur) return;
    const h = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(h);
  }, [cur?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const answer = async (approve: boolean) => {
    if (!cur) return;
    setQueue((q) => q.slice(1));
    try {
      await call("agent.confirmReply", { id: cur.id, approve });
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
      <p className={s.meta}>{t("agent.confirmCountdown", { s: Math.max(0, Math.round((cur.until - now) / 1000)) })}</p>
    </ConfirmDialog>
  );
}
