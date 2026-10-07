// 界面状态（不是用户资料）：当前页、抽屉、工作台、提示条、Core 状态。
import { create } from "zustand";
import type { CoreStatus } from "../../shared/protocol";
import type { Hello } from "../api/types";

export type Page = "library" | "sources" | "tools";

export interface Toast {
  id: number;
  text: string;
  tone?: "info" | "error";
  action?: { label: string; run: () => void };
}

/** 跨页跳转：截取后在采样库打开新采样；「返回原片」带着区间回到原片页。 */
export interface SourceJump {
  sourceId: string;
  ordinal: number | null;
  a: number;
  b: number;
}

interface AppState {
  page: Page;
  openSample: string | null;
  sourceJump: SourceJump | null;
  setOpenSample(id: string | null): void;
  setSourceJump(j: SourceJump | null): void;
  tasksOpen: boolean;
  settingsOpen: boolean;
  shortcutsOpen: boolean;
  theme: "dark" | "light";
  core: CoreStatus;
  hello: Hello | null;
  stale: boolean;
  toasts: Toast[];
  setPage(p: Page): void;
  setTasksOpen(v: boolean): void;
  setSettingsOpen(v: boolean): void;
  setShortcutsOpen(v: boolean): void;
  setTheme(v: "dark" | "light"): void;
  setCore(s: CoreStatus): void;
  setHello(h: Hello | null): void;
  setStale(v: boolean): void;
  toast(t: Omit<Toast, "id">): void;
  dismiss(id: number): void;
}

let toastSeq = 0;

export const useApp = create<AppState>((set) => ({
  page: "library",
  openSample: null,
  sourceJump: null,
  setOpenSample: (openSample) => set({ openSample }),
  setSourceJump: (sourceJump) => set({ sourceJump }),
  tasksOpen: false,
  settingsOpen: false,
  shortcutsOpen: false,
  theme: "dark",
  core: { state: "starting" },
  hello: null,
  stale: false,
  toasts: [],
  setPage: (page) => set({ page }),
  setTasksOpen: (tasksOpen) => set({ tasksOpen }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
  setTheme: (theme) => set({ theme }),
  setCore: (core) => set({ core }),
  setHello: (hello) => set({ hello }),
  setStale: (stale) => set({ stale }),
  toast: (t) => {
    const id = ++toastSeq;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { ...t, id }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), t.action ? 6000 : 3500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));
