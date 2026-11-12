// 拖出手势（规格 12 §12.2、16 R21.8）：Option/Alt + 左键拖动把真实文件拖到 Finder / DAW。
// - 按下时冻结请求（之后选区变化不影响这次拖拽）；移动超过 4 px 才开始生成，只生成一次；
// - 生成期间提示“正在准备文件，保持按住鼠标 · Esc 取消”；Esc / 松手 / 指针取消 / 窗口失焦 → 放弃，
//   之后即使生成完成也不再发起系统拖拽（已生成的文件保留）；
// - 生成完成且仍按住 → 主进程启动系统拖拽；之后 Esc 归系统；
// - 生成失败要提示，不吞掉。
// 只认左键 + 修饰键；按钮、输入框、选区把手上按下由调用方排除。
import type React from "react";
import { CoreFailure } from "./api/core";
import { errorText, t } from "./i18n";
import { useApp } from "./state/store";

export const DRAG_THRESHOLD_PX = 4;

export type DragPhase = "idle" | "armed" | "generating" | "started" | "cancelled" | "failed";

export interface DragOutDeps {
  /** 生成文件（按下时冻结的请求），返回要拖出的路径 */
  generate: () => Promise<string[]>;
  startDrag: (paths: string[]) => void;
  onPhase?: (phase: DragPhase, info?: { error?: unknown; count?: number }) => void;
}

export class DragOut {
  phase: DragPhase = "idle";
  private x0 = 0;
  private y0 = 0;
  private deps: DragOutDeps | null = null;
  private token = 0;

  /** 按下：只有左键 + ⌥/Alt 才接管。返回是否接管（接管时调用方应阻止普通的选区/拖动行为）。 */
  press(e: { button: number; altKey: boolean; clientX: number; clientY: number }, deps: DragOutDeps): boolean {
    if (e.button !== 0 || !e.altKey) return false;
    this.x0 = e.clientX;
    this.y0 = e.clientY;
    this.deps = deps;
    this.token += 1;
    this.set("armed");
    return true;
  }

  move(e: { clientX: number; clientY: number }): void {
    if (this.phase !== "armed" || !this.deps) return;
    if (Math.hypot(e.clientX - this.x0, e.clientY - this.y0) <= DRAG_THRESHOLD_PX) return;
    const mine = this.token;
    const deps = this.deps;
    this.set("generating");
    deps.generate().then(
      (paths) => {
        if (mine !== this.token || this.phase !== "generating") return; // 已放弃：不再发起系统拖拽
        this.set("started", { count: paths.length });
        deps.startDrag(paths);
        this.reset();
      },
      (error) => {
        if (mine !== this.token || this.phase !== "generating") return;
        this.set("failed", { error });
        this.reset();
      },
    );
  }

  /** 松手、Esc、指针取消、窗口失焦都走这里 */
  cancel(): void {
    if (this.phase === "armed") return this.reset();
    if (this.phase === "generating") {
      this.set("cancelled");
      this.reset();
    }
  }

  get active(): boolean {
    return this.phase === "armed" || this.phase === "generating";
  }

  private set(p: DragPhase, info?: { error?: unknown; count?: number }): void {
    this.phase = p;
    this.deps?.onPhase?.(p, info);
  }

  private reset(): void {
    this.phase = "idle";
    this.deps = null;
  }
}

// ---------------------------------------------------------------- 接到界面


const shared = new DragOut();

/** 在 pointerdown 里调用：⌥ + 左键时接管这次拖动，返回 true（调用方随后不要做普通的选区/拖动）。 */
export function beginDragOut(e: PointerEvent | React.PointerEvent, generate: () => Promise<string[]>): boolean {
  const { toast, dismiss } = useApp.getState();
  let hint = 0;
  const cleanup = () => {
    window.removeEventListener("pointermove", onMove, true);
    window.removeEventListener("pointerup", onUp, true);
    window.removeEventListener("pointercancel", onUp, true);
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("blur", onUp);
    if (hint) dismiss(hint);
  };
  const onMove = (ev: PointerEvent) => shared.move(ev);
  const onUp = () => {
    shared.cancel();
    cleanup();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape" && shared.active) {
      ev.preventDefault();
      ev.stopPropagation();
      shared.cancel();
      cleanup();
    }
  };
  const took = shared.press(e, {
    generate,
    startDrag: (paths) => window.otto.files.startDrag(paths),
    onPhase: (phase, info) => {
      if (phase === "generating") hint = toast({ text: t("dragout.preparing"), sticky: true });
      else if (phase === "started") cleanup();
      else if (phase === "failed") {
        cleanup();
        const err = info?.error;
        toast({ text: err instanceof CoreFailure ? errorText(err.wire) : String(err), tone: "error" });
      } else if (phase === "cancelled") toast({ text: t("dragout.cancelled") });
    },
  });
  if (!took) return false;
  e.preventDefault();
  window.addEventListener("pointermove", onMove, true);
  window.addEventListener("pointerup", onUp, true);
  window.addEventListener("pointercancel", onUp, true);
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("blur", onUp);
  return true;
}
