// 调 Core 的公开命令（经 preload 白名单）。失败统一抛 CoreFailure（错误码 + 参数）。
import { useEffect, useRef } from "react";
import type { CoreErrorWire, CoreEvent } from "../../shared/protocol";

export class CoreFailure extends Error {
  constructor(public wire: CoreErrorWire) {
    super(wire.code);
  }
}

export async function call<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
  const res = await window.otto.core.request<T>(method, params);
  if (!res.ok) throw new CoreFailure(res.e);
  return res.r;
}

/** 订阅 Core 事件（例如 job.updated、data.changed）。 */
export function useCoreEvent(name: string, cb: (data: unknown) => void): void {
  const ref = useRef(cb);
  ref.current = cb;
  useEffect(
    () =>
      window.otto.core.onEvent((ev: CoreEvent) => {
        if (ev.e === name) ref.current(ev.d);
      }),
    [name],
  );
}

/** 请求代次：只采纳最新一次请求的结果（规格 17 §17.1 #3：旧响应不能覆盖新选择）。 */
export function useGeneration(): () => () => boolean {
  const gen = useRef(0);
  return () => {
    const mine = ++gen.current;
    return () => mine === gen.current;
  };
}
