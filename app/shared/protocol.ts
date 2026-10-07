// 渲染进程、preload、主进程共用的类型（与 Core 帧协议对应，见 core/ottosmasher/core/rpc.py）。

export interface CoreErrorWire {
  code: string;
  args: Record<string, unknown>;
}

export type CoreResult<T> = { ok: true; r: T } | { ok: false; e: CoreErrorWire };

export interface CoreEvent {
  e: string;
  d: unknown;
}

export type CoreState = "starting" | "ready" | "exited" | "fatal";

export interface CoreStatus {
  state: CoreState;
  error?: CoreErrorWire;
  exitCode?: number | null;
}

export type PlayerName = "source" | "audition";

/** 播放器状态（约每 50 ms 一次）。time：原片播放器为原片秒，试听为区间本地秒；未知为 null。 */
export interface PlayerState {
  player: PlayerName;
  gen: number;
  time: number | null;
  playing: boolean;
  loading: boolean;
  /** 单次范围被引擎截停：每个代次只出现一次 */
  ended: boolean;
  error?: CoreErrorWire;
}

export interface PlayerApi {
  attachVideo(): boolean;
  openSource(sourceId: string, ordinal?: number): Promise<{ duration: number; hasVideo: boolean }>;
  play(): void;
  pause(): void;
  /** 返回新代次（之后只认这个代次的状态） */
  seek(t: number): number;
  step(dir: 1 | -1): void;
  playRange(a: number, b: number, loop?: boolean): number;
  audition(assetId: string, start: number, end: number, loop?: boolean): Promise<number>;
  stopAudition(): void;
  onState(cb: (s: PlayerState) => void): () => void;
}

export interface OttoApi {
  core: {
    request<T = unknown>(method: string, params?: Record<string, unknown>): Promise<CoreResult<T>>;
    onEvent(cb: (ev: CoreEvent) => void): () => void;
    onStatus(cb: (st: CoreStatus) => void): () => void;
    status(): Promise<CoreStatus>;
    restart(): Promise<void>;
  };
  app: {
    platform: string;
    locale: string;
  };
  player: PlayerApi;
  files: {
    /** 系统对话框选文件：media 可多选；取消返回空数组 */
    pick(kind: "media" | "media-one" | "subtitle"): Promise<string[]>;
    /** 在 Finder / 资源管理器中显示（文件不存在时什么也不做） */
    reveal(path: string): Promise<void>;
    /** 拖进窗口的文件的真实路径（只用于“拖文件进原片页”） */
    pathOf(file: File): string;
  };
}

export interface ProbeStats {
  rendered: number;
  renderMsAvg: number;
  renderMsMax: number;
  renderCpuMsAvg: number;
  renderCpuMsMax: number;
  framesShown: number;
  uiMsAvg: number;
  uiMsMax: number;
  hwdec: string | null;
  timePos: number | null;
  paused: boolean;
  frameDrops: number | null;
  decoderDrops: number | null;
  voDelayed: number | null;
  videoFps: number | null;
  estimatedVfFps: number | null;
}

export interface ProbeMetric {
  type: string;
  cpu: number;
  memoryMB: number;
}

/** 阶段 1 的 mpv 渲染桥探针（开发模式）。 */
export interface ProbeApi {
  attach(): boolean;
  open(): Promise<boolean>;
  control(action: "toggle" | "seek" | "seekRel" | "step" | "backStep", value?: number): void;
  stats(): ProbeStats | null;
  metrics(): Promise<ProbeMetric[]>;
  onEvent(cb: (ev: { type: string; name?: string; value?: unknown }) => void): () => void;
}

declare global {
  interface Window {
    otto: OttoApi;
    ottoProbe?: ProbeApi;
  }
}
