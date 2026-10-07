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

declare global {
  interface Window {
    otto: OttoApi;
  }
}
