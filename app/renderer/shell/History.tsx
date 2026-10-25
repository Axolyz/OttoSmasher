// 操作历史（所有者 2026-10-24，替换原来的 agent 会话面板）：顶栏一个按钮 + 锚定小面板。
// 按时间列出资料修改（谁做的、改了几处、能否单独撤销），可按“我 / 某个 agent 会话”筛选、撤销某一条、整批撤回一个会话；
// 上面列出错过的确认请求（agent 要做撤销不了的操作时没人及时回答）。新建的采样、音轨、导出不在修改记录里。
import { History as HistoryIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AgentMissed, AgentSession, EditHistoryItem, EditLabel } from "../api/types";
import { Button } from "../components/Button";
import { Select } from "../components/Fields";
import { ConfirmDialog } from "../components/Overlay";
import { AnchoredPanel } from "../components/Panel";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { methodName, previewText } from "./AgentLink";
import s from "./History.module.css";
import { describeLabel } from "./labels";

const LIMIT = 200;
const ALL = "*";
const USER = "user";
const clock = (iso: string) => new Date(iso).toTimeString().slice(0, 5);

function labelOf(h: EditHistoryItem): string {
  if (h.label.code !== "undo") return describeLabel(h.label);
  const a = h.label.args as { of?: string; of_args?: EditLabel["args"] };
  return t("history.undoOf", { label: a.of ? describeLabel({ code: a.of, args: a.of_args ?? {} }) : "" });
}

function whoOf(h: EditHistoryItem): string {
  if (h.actor.kind === "user") return t("history.me");
  return `${t(`agent.kind.${h.actor.kind}`)} · ${h.actor.session ?? t("agent.noSession")}`;
}

export function HistoryButton() {
  const ready = useApp((st) => st.core.state === "ready");
  const toast = useApp((st) => st.toast);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<EditHistoryItem[]>([]);
  const [filter, setFilter] = useState(ALL);
  const [live, setLive] = useState<AgentSession[]>([]);
  const [missed, setMissed] = useState<AgentMissed[]>([]);
  const [undoing, setUndoing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ready) return;
    void call("agent.sessions").then(setLive, () => {});
    void call("agent.missed").then(setMissed, () => {});
  }, [ready]);
  useCoreEvent("agent.sessions", (d) => setLive(d as AgentSession[]));
  useCoreEvent("agent.missed", (d) => setMissed(d as AgentMissed[]));

  const load = () => {
    const p = filter === ALL ? {} : filter === USER ? { actorKind: "user" as const } : { session: filter };
    void call("edits.history", { ...p, limit: LIMIT }).then(setItems, () => setItems([]));
  };
  useEffect(() => {
    if (open) load();
  }, [open, filter]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("data.changed", () => {
    if (open) load();
  });

  // 筛选项：我 + 最近记录里出现过的会话 + 正连着的会话
  const [sessions, setSessions] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    void call("edits.history", { limit: 1000 }).then(
      (all) => {
        const seen = new Set<string>();
        for (const x of [...live.map((a) => a.session), ...all.filter((h) => h.actor.kind !== "user").map((h) => h.actor.session)]) if (x) seen.add(x);
        setSessions([...seen]);
      },
      () => {},
    );
  }, [open, live, items]);

  const run = async (f: () => Promise<string>) => {
    try {
      toast({ text: await f() });
      load();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const undoOne = (h: EditHistoryItem) => void run(async () => (await call("edits.undoOne", { editId: h.edit_id }), t("history.undone", { label: labelOf(h) })));
  const undoSession = async () => {
    if (!undoing) return;
    setBusy(true);
    await run(async () => {
      const r = await call("edits.undoSession", { session: undoing });
      return r.blocked
        ? t("agent.undoneBlocked", { n: r.undone, label: describeLabel(r.blocked.label), remaining: r.remaining })
        : t("agent.undone", { n: r.undone });
    });
    setBusy(false);
    setUndoing(null);
  };

  const isSession = filter !== ALL && filter !== USER;
  const pending = isSession ? items.filter((h) => h.actor.session === filter && !h.undoOf && !h.undoneBy).length : 0;
  return (
    <>
      <AnchoredPanel
        isOpen={open}
        onOpenChange={setOpen}
        placement="bottom end"
        width={440}
        title={t("history.title")}
        aux={t("history.aux", { n: LIMIT })}
        testId="history-panel"
        trigger={
          <Button variant="flat" icon={<HistoryIcon />} aria-label={t("history.tip")} title={t("history.tip")} data-testid="history-open">
            {live.length || missed.length ? <span className={s.dot} data-missed={missed.length > 0 || undefined} data-testid="history-dot" /> : null}
          </Button>
        }
      >
        {missed.length ? (
          <div className={s.missed} data-testid="history-missed">
            <div className={s.missedHead}>
              <b>{t("history.missedTitle", { n: missed.length })}</b>
              <Button size="sm" variant="flat" onPress={() => {
                  // 这个按钮随列表一起消失：先把焦点留在面板里，Esc 才还能关面板
                  bar.current?.focus();
                  void call("agent.dismissMissed", {});
                }} data-testid="history-missed-clear">
                {t("history.missedClear")}
              </Button>
            </div>
            {missed.map((m) => (
              <div key={m.id} className={s.missedRow}>
                <span className={s.time}>{clock(m.at)}</span>
                <span className={s.main}>
                  <b>{methodName(m.method)}</b>
                  <span className={s.meta}>
                    <span data-user-data="">{m.actor.session ?? t("agent.noSession")}</span> · {t(`history.missedReason.${m.reason}`)}
                  </span>
                  {previewText(m) ? <span className={s.meta} data-user-data="">{previewText(m)}</span> : null}
                </span>
              </div>
            ))}
          </div>
        ) : null}
        <div className={s.bar} ref={bar} tabIndex={-1}>
          <Select
            value={filter}
            onChange={setFilter}
            label={t("history.filter")}
            testId="history-filter"
            options={[
              { id: ALL, label: t("history.all") },
              { id: USER, label: t("history.me") },
              ...sessions.map((x) => ({ id: x, label: `${t("agent.kind.agent")} · ${x}${live.some((a) => a.session === x) ? ` · ${t("agent.connected")}` : ""}` })),
            ]}
          />
          {isSession ? (
            <Button
              size="sm"
              variant="flat"
              isDisabled={pending === 0}
              onPress={() => {
                setOpen(false);
                setUndoing(filter);
              }}
              data-testid="history-undo-session"
            >
              {t("history.undoSession")}
            </Button>
          ) : null}
        </div>
        <div className={s.list}>
          {items.length === 0 ? <div className={s.empty}>{t("history.empty")}</div> : null}
          {items.map((h) => (
            <div key={h.edit_id} className={s.row} data-undone={h.undoneBy ? "" : undefined} data-testid="history-row">
              <span className={s.time}>{clock(h.created_at)}</span>
              <span className={s.main}>
                <b>{labelOf(h)}</b>
                <span className={s.meta}>
                  <span data-user-data={h.actor.session ? "" : undefined}>{whoOf(h)}</span> · {t("agent.edits", { n: h.changes })}
                  {h.undoneBy ? ` · ${t("history.wasUndone")}` : ""}
                </span>
              </span>
              {h.undoable ? (
                <Button size="sm" variant="flat" onPress={() => undoOne(h)} data-testid="history-undo">
                  {t("common.undo")}
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      </AnchoredPanel>
      <ConfirmDialog
        isOpen={!!undoing}
        title={t("agent.undoTitle", { session: undoing ?? "" })}
        confirmLabel={t("agent.undoOk")}
        busy={busy}
        onConfirm={() => void undoSession()}
        onClose={() => setUndoing(null)}
        testId="agent-undo-confirm"
      >
        <p>{t("agent.undoBody", { n: pending })}</p>
      </ConfirmDialog>
    </>
  );
}
