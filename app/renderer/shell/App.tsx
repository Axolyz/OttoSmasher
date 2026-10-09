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
import { SpeechDialog } from "./SpeechDialog";
import { FlattenSheet } from "./FlattenSheet";
import { SeparationDialog } from "../sources/SeparationDialog";
import { NewSamplesSheet } from "../sources/NewSamplesSheet";
import { SettingsSheet } from "../workbenches/SettingsSheet";
import { CoreBanner } from "./CoreBanner";
import { Dock } from "./Dock";
import { ManageTags } from "./ManageTags";
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

  // 「刷新浏览列表」的程序入口（自动化测试用：自己窗口的请求引起的变化不提示“资料已更新”）
  useEffect(() => {
    const on = () => st.refreshLists();
    window.addEventListener("otto:refresh-lists", on);
    return () => window.removeEventListener("otto:refresh-lists", on);
  }, [st]);

  // 真实用户输入（键盘、指针、滚轮）报给 Core，作空闲自动整理的计时（13 §13.3.3：界面轮询不算）；最多 15 秒一次
  useEffect(() => {
    let last = 0;
    const on = () => {
      const now = Date.now();
      if (now - last < 15000) return;
      last = now;
      void call("app.userInput", {}).catch(() => {});
    };
    for (const ev of ["keydown", "pointerdown", "wheel"]) window.addEventListener(ev, on, { passive: true, capture: true });
    return () => {
      for (const ev of ["keydown", "pointerdown", "wheel"]) window.removeEventListener(ev, on, { capture: true });
    };
  }, []);

  // 视频片段导出完成（任务）：播放条显示文件，提示里写补了几帧黑帧（规格 12 §12.5）
  useEffect(
    () =>
      window.otto.core.onEvent((ev) => {
        if (ev.e !== "exports.videoDone") return;
        const d = ev.d as { path: string; black: number };
        const name = d.path.split(/[\\/]/).pop() ?? d.path;
        st.setLastExport([d.path]);
        st.toast({
          text: d.black ? t("video.doneBlack", { name, n: d.black }) : t("video.done", { name }),
          action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(d.path) },
        });
      }),
    [st],
  );

  // 资料变化只提示，不自动刷新（P8）
  useEffect(
    () =>
      window.otto.core.onEvent((ev) => {
        if (ev.e === "data.changed") {
          const d = ev.d as Record<string, string[]>;
          // 自己的操作（本窗口的请求引起的）不提示；任务、后台、别的窗口改的才提示（L13）
          if (!ev.own && Object.keys(d).some((k) => k !== "setting")) st.setStale(true);
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
      <SpeechDialog />
      <SeparationDialog />
      <FlattenSheet />
      <NewSamplesSheet />
      <ManageTags />
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
              ["Space / B", t("shortcuts.audition")],
              ["⌥ / ⌥⇧", t("shortcuts.dragOut")],
              ["⌘C", t("shortcuts.reaper")],
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
