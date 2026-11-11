// 固定结果的标签（规格 04 §4.2.10、03 §3.4.4、UI_PLAN §2.1）：「浏览」+ 每次检索一个，可关闭、重启恢复（不重新检索）；
// 检索完成后加新标签；等待期间用户已继续浏览时，留在当前位置。
import { useCallback, useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../../api/core";
import type { ErrorWire, ResultHeader, SearchFinished } from "../../api/types";
import { errorText, t } from "../../i18n";
import { useApp } from "../../state/store";

export const BROWSE = "browse";

export interface Running {
  searchId: string;
  kind: "speech" | "pitch";
  position: string;
}

export function useResults(ready: boolean, navigationKey: string, onFinished: (r: SearchFinished, activated: boolean) => void) {
  const toast = useApp((st) => st.toast);
  const [tabs, setTabs] = useState<ResultHeader[]>([]);
  const [active, setActiveRaw] = useState<string>(BROWSE);
  const [running, setRunning] = useState<Running | null>(null);
  const restored = useRef(false);
  const runningRef = useRef<Running | null>(null);
  runningRef.current = running;
  const position = JSON.stringify([active, navigationKey]);
  const activeRef = useRef(active);
  activeRef.current = active;
  const currentPosition = useRef(position);
  currentPosition.current = position;
  const finishedRef = useRef(onFinished);
  finishedRef.current = onFinished;

  useEffect(() => {
    if (!ready || restored.current) return;
    restored.current = true;
    void Promise.all([call("results.list"), call("ui.get", { page: "library" })]).then(([list, ui]) => {
      setTabs(list);
      const a = typeof ui.activeResult === "string" ? ui.activeResult : BROWSE;
      setActiveRaw(list.some((h) => h.id === a) ? a : BROWSE);
    });
  }, [ready]);

  const setActive = useCallback((id: string) => {
    setActiveRaw(id);
    void call("ui.set", { page: "library", key: "activeResult", value: id });
  }, []);

  useCoreEvent("search.finished", (d) => {
    const r = d as SearchFinished;
    const current = runningRef.current;
    if (current?.searchId !== r.searchId) return;
    setRunning(null);
    if (r.status === "done" && r.resultId) {
      const id = r.resultId;
      void call("results.page", { id, offset: 0, limit: 1 }).then((p) => {
        setTabs((ts) => [...ts.filter((x) => x.id !== id), p.result]);
        const activate = current.position === currentPosition.current;
        if (activate) setActive(id);
        finishedRef.current(r, activate);
      });
    } else if (r.status === "failed" && r.error) {
      toast({ text: errorText(r.error as ErrorWire), tone: "error" });
    } else if (r.status === "cancelled") {
      toast({ text: t("search.cancelled") });
    }
  });

  const start = useCallback(
    async (run: () => Promise<{ searchId: string }>, kind: "speech" | "pitch") => {
      const position = currentPosition.current;
      try {
        const r = await run();
        setRunning({ searchId: r.searchId, kind, position });
        return true;
      } catch (e) {
        toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
        return false;
      }
    },
    [toast],
  );

  const cancel = useCallback(() => {
    const r = runningRef.current;
    if (r) void call("search.cancel", { searchId: r.searchId });
  }, []);

  const close = useCallback(
    async (id: string) => {
      await call("results.close", { id });
      setTabs((ts) => ts.filter((x) => x.id !== id));
      if (activeRef.current === id) setActive(BROWSE);
    },
    [setActive],
  );

  return { tabs, active, setActive, running, start, cancel, close };
}
