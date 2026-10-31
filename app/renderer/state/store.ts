// 界面状态（不是用户资料）：当前页、抽屉、工作台、提示条、Core 状态。
import { create } from "zustand";
import type { CoreStatus } from "../../shared/protocol";
import type { Hello, RhythmPlan, RhythmSound } from "../api/types";

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
  /** 原素材秒；b ≤ a = 只打开原素材 */
  a: number;
  b: number;
  /** 换到这条整轨（「返回原素材」= 采样来自的整轨，永远不是局部成品；所有者 2026-10-12）；没有就不换音源 */
  assetId?: string;
  /** 在“采样”车道上突出显示的采样 */
  highlight?: string;
  /** false = 不放大时间线，只设选区、跳到开头（台词搜索的命中，同台本单击） */
  zoom?: boolean;
}

/** 语音分析确认框的请求（规格 08 §8.4：不同入口只是默认范围不同） */
export interface SpeechRequest {
  /** 音素属于原素材时间线（所有者 2026-10-12）：source = 所选原片的段；segments = 这几段；samples = 采样判定区间读到的段；units = 指定的分析单元 */
  entry: "source" | "segments" | "samples" | "units";
  ids: string[];
  /** source / segments：原片页当前查看的轨（确认框里可选“默认人声轨”或它） */
  currentAsset?: { id: string; label: string };
}

/** 批量建采样的请求（所有者 2026-10-09：建采样一个动作，批量 = 整页表格）：从文本段 / 音效提示 / 整段原片 */
export type NewSamplesRequest =
  | { kind: "segments" | "hints"; sourceId: string; currentAsset?: { id: string; label: string } }
  | { kind: "whole"; sourceIds: string[] };

/** 拉平台的请求（规格 11 §11.1：同一个工作台，默认值随入口）。时间：资产局部秒 */
export type FlattenRequest =
  | { kind: "single"; assetId: string; start: number; end: number; entry: "detail" | "single"; sampleId?: string }
  | { kind: "batch"; ids: string[] };

/** 分离确认框的请求（原片页动作条、舞台动作条共用，PB5） */
export interface SeparationRequest {
  assetId: string;
  trackLabel: string;
  duration: number;
  selection: { a: number; b: number } | null;
  scope: "full" | "sel";
}

/** 试听的版本（规格 09 §9.5.3、12 §12.1；所有者 2026-10-08：不卡拍 / 卡拍 × 原声 / 原声＋咔哒 / 纯咔哒） */
export type AuditionVersion = "original" | "stretched";

/** 全局播放条显示的当前声音（UI_PLAN §1） */
export interface NowPlaying {
  sampleId: string;
  name: string;
  version: AuditionVersion;
  sound: RhythmSound;
  plan: RhythmPlan | null;
  bpm: number | null;
  originalSpeed: boolean;
  duration: number;
}

/** 舞台上节奏与卡拍的临时选择（换采样就回到默认；所有者 2026-10-08：纯 mora 不保存） */
export interface StageRhythm {
  sampleId: string | null;
  plan: RhythmPlan;
  mora: boolean;
  longVowel: boolean;
  sound: RhythmSound;
}

interface AppState {
  page: Page;
  openSample: string | null;
  sourceJump: SourceJump | null;
  setOpenSample(id: string | null): void;
  setSourceJump(j: SourceJump | null): void;
  /** 从原片页「派生采样」跳到采样库：查找栏里的临时“原片：…”块（UI_PLAN §2.3，不存进筛选器） */
  libraryScope: { sourceId: string; name: string } | null;
  setLibraryScope(v: { sourceId: string; name: string } | null): void;
  tasksOpen: boolean;
  settingsOpen: boolean;
  shortcutsOpen: boolean;
  /** 全局播放条的导出交接条（UI_PLAN §1、L27）：最近一次导出的文件，可普通拖进 DAW、定位 */
  lastExport: string[] | null;
  setLastExport(paths: string[] | null): void;
  /** 「管理标签」（UI_PLAN §8：⋯ 菜单） */
  manageTagsOpen: boolean;
  setManageTagsOpen(v: boolean): void;
  theme: "dark" | "light";
  core: CoreStatus;
  hello: Hello | null;
  stale: boolean;
  /** 「刷新浏览列表」按一次加一：各页据此重新读取当前列表（P8：只提示、由用户触发刷新） */
  refreshTick: number;
  refreshLists(): void;
  toasts: Toast[];
  speechRequest: SpeechRequest | null;
  requestSpeech(r: SpeechRequest | null): void;
  newSamplesRequest: NewSamplesRequest | null;
  requestNewSamples(r: NewSamplesRequest | null): void;
  /** 原片页当前查看的轨（建采样、语音分析的“当前轨”选项用） */
  viewerAsset: { sourceId: string; id: string; label: string } | null;
  setViewerAsset(v: { sourceId: string; id: string; label: string } | null): void;
  flattenRequest: FlattenRequest | null;
  requestFlatten(r: FlattenRequest | null): void;
  separationRequest: SeparationRequest | null;
  requestSeparation(r: SeparationRequest | null): void;
  /** 全局 BPM 的镜像（Core 的 rhythm.bpm；事件 rhythm.bpm 同步） */
  bpm: number | null;
  setBpm(v: number | null): void;
  nowPlaying: NowPlaying | null;
  setNowPlaying(v: NowPlaying | null): void;
  stageRhythm: StageRhythm;
  setStageRhythm(patch: Partial<StageRhythm>): void;
  /** 详情区波形是否显示“判定区间”车道（默认隐藏，会话内记住；所有者 2026-10-12） */
  stageJudgeLane: boolean;
  setStageJudgeLane(v: boolean): void;
  setPage(p: Page): void;
  setTasksOpen(v: boolean): void;
  setSettingsOpen(v: boolean): void;
  /** 打开设置时先切到的分组（命令面板「设置 › …」用；设置工作台读到后清空） */
  settingsGroup: string | null;
  openSettings(group?: string): void;
  /** 命令面板（⌘K） */
  paletteOpen: boolean;
  setPaletteOpen(v: boolean): void;
  setShortcutsOpen(v: boolean): void;
  setTheme(v: "dark" | "light"): void;
  setCore(s: CoreStatus): void;
  setHello(h: Hello | null): void;
  setStale(v: boolean): void;
  toast(t: Omit<Toast, "id"> & { sticky?: boolean }): number;
  dismiss(id: number): void;
}

let toastSeq = 0;

export const useApp = create<AppState>((set) => ({
  page: "library",
  openSample: null,
  sourceJump: null,
  setOpenSample: (openSample) => set({ openSample }),
  speechRequest: null,
  requestSpeech: (speechRequest) => set({ speechRequest }),
  newSamplesRequest: null,
  requestNewSamples: (newSamplesRequest) => set({ newSamplesRequest }),
  viewerAsset: null,
  setViewerAsset: (viewerAsset) =>
    set((st) =>
      st.viewerAsset?.sourceId === viewerAsset?.sourceId && st.viewerAsset?.id === viewerAsset?.id && st.viewerAsset?.label === viewerAsset?.label ? {} : { viewerAsset },
    ),
  flattenRequest: null,
  requestFlatten: (flattenRequest) => set({ flattenRequest }),
  separationRequest: null,
  requestSeparation: (separationRequest) => set({ separationRequest }),
  setSourceJump: (sourceJump) => set({ sourceJump }),
  libraryScope: null,
  setLibraryScope: (libraryScope) => set({ libraryScope }),
  tasksOpen: false,
  settingsOpen: false,
  shortcutsOpen: false,
  lastExport: null,
  setLastExport: (lastExport) => set({ lastExport: lastExport && lastExport.length ? lastExport : null }),
  manageTagsOpen: false,
  setManageTagsOpen: (manageTagsOpen) => set({ manageTagsOpen }),
  theme: "dark",
  core: { state: "starting" },
  hello: null,
  stale: false,
  refreshTick: 0,
  refreshLists: () => set((st) => ({ stale: false, refreshTick: st.refreshTick + 1 })),
  toasts: [],
  bpm: null,
  setBpm: (bpm) => set({ bpm }),
  nowPlaying: null,
  setNowPlaying: (nowPlaying) => set({ nowPlaying }),
  stageRhythm: { sampleId: null, plan: "near_fast", mora: false, longVowel: false, sound: "voice" },
  setStageRhythm: (patch) =>
    set((st) => {
      // 换了采样：临时选择回到默认
      const base = patch.sampleId && patch.sampleId !== st.stageRhythm.sampleId ? { sampleId: patch.sampleId, plan: "near_fast" as const, mora: false, longVowel: false, sound: "voice" as const } : st.stageRhythm;
      return { stageRhythm: { ...base, ...patch } };
    }),
  stageJudgeLane: false,
  setStageJudgeLane: (stageJudgeLane) => set({ stageJudgeLane }),
  setPage: (page) => set({ page }),
  setTasksOpen: (tasksOpen) => set({ tasksOpen }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  settingsGroup: null,
  openSettings: (group) => set({ settingsOpen: true, settingsGroup: group ?? null }),
  paletteOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
  setTheme: (theme) => set({ theme }),
  setCore: (core) => set({ core }),
  setHello: (hello) => set({ hello }),
  setStale: (stale) => set({ stale }),
  toast: (t) => {
    const id = ++toastSeq;
    const { sticky, ...rest } = t;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { ...rest, id }] }));
    if (!sticky) setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), t.action ? 6000 : 3500);
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));
