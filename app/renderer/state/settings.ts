// 读一个设置项的当前值（界面的显示类设置，比如时间线标签最多行数）：第一次用时取一次 settings.list，设置改了（data.changed 带 setting）再取。
// 所有用到的组件共用一份，不各自去取。
import { useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";

let cache: Record<string, unknown> | null = null;
let pending: Promise<void> | null = null;
const subs = new Set<() => void>();

function load(): Promise<void> {
  pending ??= call("settings.list")
    .then((st) => {
      cache = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, v.value]));
      for (const f of subs) f();
    })
    .catch(() => {})
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function useSettingValue<T>(key: string, fallback: T): T {
  const [, setTick] = useState(0);
  useEffect(() => {
    const f = () => setTick((n) => n + 1);
    subs.add(f);
    if (!cache) void load();
    return () => {
      subs.delete(f);
    };
  }, []);
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).setting) void load();
  });
  const v = cache?.[key];
  return v === undefined || v === null ? fallback : (v as T);
}
