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
