// 列表缩略图（规格 16 R22.11、ARCHITECTURE §10.2）：行挂载时登记，16 ms 内攒成一批向 Core 要（thumbs.get），
// JPEG 字节转成 blob 地址缓存在页面里；Core 先回 pending 的，等 thumbs.ready 事件再要一次。
// 原片 / 采样改动（data.changed）后对应的缩略图作废、重新要（采样范围变了中点就变了；键由 Core 按文件与时间算）。
import { useEffect, useState } from "react";
import type { CoreEvent } from "../../shared/protocol";
import { call } from "./core";

export type ThumbKind = "source" | "sample";
/** list = 列表行（88×50 / 56×32）；poster = 短音频查看器的画面（320×180） */
export type ThumbSize = "list" | "poster";
type State = { state: "pending" | "ready" | "none" | "failed"; url?: string };
interface Res {
  kind: ThumbKind;
  id: string;
  size: ThumbSize;
  state: State["state"];
  data?: Uint8Array;
}

const cache = new Map<string, State>();
const listeners = new Map<string, Set<() => void>>();
const queue = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;
let subscribed = false;

const keyOf = (kind: ThumbKind, id: string, size: ThumbSize = "list") => `${kind}:${size}:${id}`;

function notify(key: string): void {
  for (const fn of listeners.get(key) ?? []) fn();
}

function set(key: string, st: State): void {
  const old = cache.get(key);
  if (old?.url && old.url !== st.url) URL.revokeObjectURL(old.url);
  cache.set(key, st);
  notify(key);
}

function request(key: string): void {
  queue.add(key);
  timer ??= setTimeout(() => void flush(), 16);
}

async function flush(): Promise<void> {
  timer = null;
  const keys = [...queue].slice(0, 200);
  for (const k of keys) queue.delete(k);
  if (queue.size) timer = setTimeout(() => void flush(), 16);
  const items = keys.map((k) => {
    const [kind, size] = k.split(":", 2);
    return { kind, size, id: k.slice(kind!.length + size!.length + 2) };
  });
  let res: Res[];
  try {
    res = await call<Res[]>("thumbs.get", { items });
  } catch {
    for (const k of keys) set(k, { state: "failed" });
    return;
  }
  for (const r of res) {
    const k = keyOf(r.kind, r.id, r.size);
    if (r.state === "ready" && r.data) {
      const bytes = new Uint8Array(r.data.byteLength);
      bytes.set(r.data);
      set(k, { state: "ready", url: URL.createObjectURL(new Blob([bytes], { type: "image/jpeg" })) });
    } else if (r.state !== "pending" || !cache.get(k)?.url) {
      // pending 时保留旧图（改动后重新生成期间不闪成空白）
      set(k, { state: r.state, url: undefined });
    }
  }
}

function subscribe(): void {
  if (subscribed) return;
  subscribed = true;
  window.otto.core.onEvent((ev: CoreEvent) => {
    if (ev.e === "thumbs.ready") {
      for (const it of (ev.d as { items: Array<{ kind: ThumbKind; id: string; size: ThumbSize }> }).items) {
        const k = keyOf(it.kind, it.id, it.size);
        if (listeners.get(k)?.size) request(k);
        else cache.delete(k);
      }
    } else if (ev.e === "data.changed") {
      const d = ev.d as Record<string, string[]>;
      for (const kind of ["source", "sample"] as const) {
        for (const id of d[kind] ?? []) {
          for (const size of ["list", "poster"] as const) {
            const k = keyOf(kind, id, size);
            if (!cache.has(k)) continue;
            if (listeners.get(k)?.size) request(k);
            else cache.delete(k);
          }
        }
      }
    }
  });
}

/** 一行的缩略图地址；没有视频 / 还在生成 / 失败时为 null。 */
export function useThumb(kind: ThumbKind, id: string, size: ThumbSize = "list"): string | null {
  const key = keyOf(kind, id, size);
  const [, bump] = useState(0);
  useEffect(() => {
    subscribe();
    const fn = () => bump((n) => n + 1);
    let set = listeners.get(key);
    if (!set) listeners.set(key, (set = new Set()));
    set.add(fn);
    if (!cache.has(key)) {
      cache.set(key, { state: "pending" });
      request(key);
    }
    return () => {
      set.delete(fn);
    };
  }, [key]);
  return cache.get(key)?.url ?? null;
}
