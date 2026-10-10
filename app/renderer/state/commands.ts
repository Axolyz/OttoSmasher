// 命令面板的命令来源：各页把“当前对象的菜单”和本页的常用动作登记在这里（只在打开面板时现取，不随渲染重算）。
// page = null 的来源任何页都列出；否则只在那一页是当前页时列出。
import { useEffect, useRef } from "react";
import type { PaletteSection } from "../components/CommandPalette";
import type { Page } from "./store";

type Provider = () => PaletteSection[];

const providers = new Map<string, { page: Page | null; ref: { current: Provider } }>();

export function useCommands(key: string, page: Page | null, build: Provider): void {
  const ref = useRef(build);
  ref.current = build;
  useEffect(() => {
    providers.set(key, { page, ref });
    return () => {
      providers.delete(key);
    };
  }, [key, page]);
}

/** 当前页的来源在前（对象、本页），任何页都有的在后。 */
export function collectCommands(page: Page): PaletteSection[] {
  const own: PaletteSection[] = [];
  const shared: PaletteSection[] = [];
  for (const p of providers.values()) {
    if (p.page === page) own.push(...p.ref.current());
    else if (p.page === null) shared.push(...p.ref.current());
  }
  return [...own, ...shared];
}
