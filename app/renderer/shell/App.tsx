// 全局外壳（UI_PLAN §1）：三页常驻（切页只隐藏不卸载）、左侧导航、顶栏、全局播放条、任务抽屉、设置工作台。
import { useEffect, useRef } from "react";
import { call } from "../api/core";
import type { Hello } from "../api/types";
import { Sheet } from "../components/Overlay";
import { Toasts } from "../components/Toasts";
import { LibraryPage } from "../library/LibraryPage";
import { t } from "../i18n";
import { SourcesPage } from "../sources/SourcesPage";
import { type Page, useApp } from "../state/store";
import { ToolsPage } from "../tools/ToolsPage";
import { SettingsSheet } from "../workbenches/SettingsSheet";
import { CoreBanner } from "./CoreBanner";
import { Dock } from "./Dock";
import { Rail } from "./Rail";
import s from "./Shell.module.css";
import { TaskDrawer, useJobs } from "./TaskDrawer";
import { TopBar } from "./TopBar";
import { useUndo } from "./useUndo";

const PAGES: Page[] = ["library", "sources", "tools"];

function isTyping(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement).isContentEditable;
}

export function App() {
  const st = useApp();
  const jobs = useJobs();
  const undo = useUndo();
  const restored = useRef(false);
  const active = jobs.filter((j) => j.status === "queued" || j.status === "running").length;

  // Core 状态
  useEffect(() => {
    void window.otto.core.status().then(st.setCore);
    return window.otto.core.onStatus(st.setCore);
  }, [st.setCore]);

  // Core 就绪：握手、恢复界面状态（规格 03 §3.1：重启恢复各页条件与当前对象）
  useEffect(() => {
    if (st.core.state !== "ready") return;
    void call("core.hello").then((h) => {
      st.setHello(h);
      if (h.interrupted_on_start > 0) st.toast({ text: t("tasks.interruptedOnStart", { n: h.interrupted_on_start }) });
    });
    void call("ui.get", { page: "shell" }).then((v) => {
      if (typeof v.page === "string" && PAGES.includes(v.page as Page)) st.setPage(v.page as Page);
      if (v.theme === "light" || v.theme === "dark") st.setTheme(v.theme);
      restored.current = true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [st.core.state]);

  useEffect(() => {
    if (restored.current) void call("ui.set", { page: "shell", key: "page", value: st.page });
  }, [st.page]);
  useEffect(() => {
    document.documentElement.dataset.theme = st.theme;
    if (restored.current) void call("ui.set", { page: "shell", key: "theme", value: st.theme });
  }, [st.theme]);

  // 资料变化只提示，不自动刷新（P8）
  useEffect(
    () =>
      window.otto.core.onEvent((ev) => {
        if (ev.e === "data.changed") {
          const d = ev.d as Record<string, string[]>;
          if (Object.keys(d).some((k) => k !== "setting")) st.setStale(true);
        }
      }),
    [st.setStale],
  );

  // 全局快捷键（UI_PLAN §7）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && ["1", "2", "3"].includes(e.key)) {
        e.preventDefault();
        st.setSettingsOpen(false);
        st.setPage(PAGES[Number(e.key) - 1]!);
      } else if (mod && e.key === ",") {
        e.preventDefault();
        st.setSettingsOpen(true);
      } else if (mod && e.key.toLowerCase() === "j") {
        e.preventDefault();
        st.setTasksOpen(!useApp.getState().tasksOpen);
      } else if (mod && e.key.toLowerCase() === "z" && !e.shiftKey && !isTyping(document.activeElement)) {
        e.preventDefault();
        void undo();
      } else if (e.key === "?" && !isTyping(document.activeElement)) {
        st.setShortcutsOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [st, undo]);

  return (
    <div className={s.app}>
      <Rail activeJobs={active} />
      <div className={s.main}>
        <div>
          <CoreBanner />
        </div>
        <TopBar />
        <div className={s.pages}>
          <div className={`${s.page} ${st.page === "library" ? "" : s.hidden}`}>
            <LibraryPage />
          </div>
          <div className={`${s.page} ${st.page === "sources" ? "" : s.hidden}`}>
            <SourcesPage />
          </div>
          <div className={`${s.page} ${st.page === "tools" ? "" : s.hidden}`}>
            <ToolsPage />
          </div>
        </div>
        <Dock />
      </div>
      <TaskDrawer jobs={jobs} />
      <SettingsSheet />
      <Sheet isOpen={st.shortcutsOpen} onClose={() => st.setShortcutsOpen(false)} title={t("shortcuts.title")}>
        <table className={s.keys}>
          <tbody>
            {[
              ["⌘1 / ⌘2 / ⌘3", t("shortcuts.pages")],
              ["⌘,", t("shortcuts.settings")],
              ["⌘J", t("shortcuts.tasks")],
              ["⌘Z", t("shortcuts.undo")],
              ["?", t("shortcuts.help")],
              ["Esc", t("shortcuts.esc")],
            ].map(([k, v]) => (
              <tr key={k}>
                <td className="mono">{k}</td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Sheet>
      <Toasts />
    </div>
  );
}
