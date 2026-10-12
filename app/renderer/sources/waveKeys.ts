// 波形区快捷键（UI_PLAN §7）：原素材页时间线与详情区波形共用同一套键位。
// Space 播放/暂停 · Shift+Space 播放选区 · L 循环选区 · I / O 当前位置设为选区开始 / 结束 · F 适合 · Z 放大选区 ·
// ← → 逐帧（Shift = 1 ms，⌥ = 5 秒）· Esc 清除选区。输入框里不接。
import type React from "react";

export function isTyping(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement).isContentEditable;
}

export interface WaveKeyActions {
  playPause: () => void;
  playSel: (loop: boolean) => void;
  /** I / O：当前位置设为选区开始（true）/ 结束（false） */
  mark: (isIn: boolean) => void;
  fit: () => void;
  zoomSel: () => void;
  /** frame = 逐帧，ms = 1 ms，far = 5 秒 */
  step: (dir: 1 | -1, unit: "frame" | "ms" | "far") => void;
  /** 有选区就清除并返回 true（没有选区时 Esc 留给外层） */
  clearSel: () => boolean;
}

/** 处理了就返回 true（已阻止默认与冒泡） */
export function waveKey(e: React.KeyboardEvent, act: WaveKeyActions): boolean {
  if (isTyping(document.activeElement) || e.metaKey || e.ctrlKey) return false;
  const k = e.key;
  const done = () => {
    e.preventDefault();
    e.stopPropagation();
    return true;
  };
  if (k === " ") {
    if (e.shiftKey) act.playSel(false);
    else act.playPause();
    return done();
  }
  if (k === "l" || k === "L") return (act.playSel(true), done());
  if (k === "i" || k === "I") return (act.mark(true), done());
  if (k === "o" || k === "O") return (act.mark(false), done());
  if (k === "f" || k === "F") return (act.fit(), done());
  if (k === "z" || k === "Z") return (act.zoomSel(), done());
  if (k === "ArrowLeft" || k === "ArrowRight") {
    act.step(k === "ArrowRight" ? 1 : -1, e.altKey ? "far" : e.shiftKey ? "ms" : "frame");
    return done();
  }
  if (k === "Escape" && act.clearSel()) return done();
  return false;
}
