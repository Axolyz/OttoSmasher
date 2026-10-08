// 调 Core 的公开命令（经 preload 白名单）。失败统一抛 CoreFailure（错误码 + 参数）。
import { useEffect, useRef } from "react";
import type { CoreErrorWire, CoreEvent } from "../../shared/protocol";
import type { CommandName, Commands } from "./generated";

export class CoreFailure extends Error {
  constructor(public wire: CoreErrorWire) {
    super(wire.code);
  }
}

type Params<M extends CommandName> = Commands[M]["params"];
export type Result<M extends CommandName> = Commands[M]["result"];
/** 参数全部可选的命令可以不传参数。 */
type Args<M extends CommandName> = {} extends Params<M> ? [params?: Params<M>] : [params: Params<M>];

/** 调一条 Core 命令；参数与返回类型按命令名从命令目录推断（generated.ts，ROADMAP L2）。 */
export async function call<M extends CommandName>(method: M, ...args: Args<M>): Promise<Result<M>> {
  const res = await window.otto.core.request<Result<M>>(method, args[0] as Record<string, unknown> | undefined);
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
