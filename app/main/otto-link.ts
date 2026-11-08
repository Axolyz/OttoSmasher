// 把 otto 装成命令（所有者 2026-11-04：发布版启动时自动做）。不碰别的程序：不是我们放的同名文件一律不动。
// macOS：~/.local/bin/otto 是指向启动器的链接。Windows：普通用户不能建符号链接，写一个转发脚本。
import { existsSync, lstatSync, mkdirSync, readFileSync, readlinkSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export const OTTO_SHIM_MARK = "@rem OttoSmasher";

/** 路径可能带中文（用户名），所以先切到 UTF-8 */
export const ottoShim = (target: string): string => `${OTTO_SHIM_MARK}\r\n@chcp 65001 >nul\r\n@"${target}" %*\r\n`;

export type OttoLinkResult = "current" | "installed" | "conflict";

export function ensureOttoLink(target: string, link: string, win: boolean): OttoLinkResult {
  if (win) {
    if (existsSync(link)) {
      const text = readFileSync(link, "utf8");
      if (!text.startsWith(OTTO_SHIM_MARK)) return "conflict";
      if (text === ottoShim(target)) return "current";
    }
    writeFileSync(link, ottoShim(target), "utf8");
    return "installed";
  }
  let old: string | null = null;
  try {
    const st = lstatSync(link);
    if (!st.isSymbolicLink()) return "conflict";
    old = readlinkSync(link);
  } catch {
    // 不存在
  }
  if (old === target) return "current";
  // 指向还在的别的程序（比如另一个叫 otto 的工具）不动；我们自己的旧位置、已经失效的链接才换
  if (old !== null && existsSync(old) && !old.includes("OttoSmasher")) return "conflict";
  mkdirSync(dirname(link), { recursive: true });
  if (old !== null) unlinkSync(link);
  symlinkSync(target, link);
  return "installed";
}
