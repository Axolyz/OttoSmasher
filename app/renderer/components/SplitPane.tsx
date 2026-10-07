// 左右分栏 + 可拖动的分隔条（UI_PLAN §2：列表占 32–68%，记住）。键盘：分隔条获得焦点后 ←→ 每次 2%，Home/End 到边界。
// 比例的保存由页面负责（ui_state），这里只报告变化。
import { type ReactNode, useRef } from "react";
import s from "./Collection.module.css";

export function SplitPane(props: { left: ReactNode; right: ReactNode; ratio: number; onRatio: (r: number) => void; min?: number; max?: number; label: string }) {
  const min = props.min ?? 0.32;
  const max = props.max ?? 0.68;
  const root = useRef<HTMLDivElement>(null);
  const clamp = (r: number) => Math.min(max, Math.max(min, r));
  const ratio = clamp(props.ratio);
  return (
    <div className={s.split} ref={root} style={{ gridTemplateColumns: `${ratio * 100}% 7px minmax(0, 1fr)` }}>
      <div className={s.splitPart}>{props.left}</div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={props.label}
        aria-valuemin={Math.round(min * 100)}
        aria-valuemax={Math.round(max * 100)}
        aria-valuenow={Math.round(ratio * 100)}
        tabIndex={0}
        className={s.splitter}
        data-testid="splitter"
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          e.preventDefault();
          const el = e.currentTarget;
          el.setPointerCapture(e.pointerId);
          const box = root.current!.getBoundingClientRect();
          const move = (ev: PointerEvent) => props.onRatio(clamp((ev.clientX - box.left) / box.width));
          const up = () => {
            el.removeEventListener("pointermove", move);
            el.removeEventListener("pointerup", up);
            el.removeEventListener("pointercancel", up);
          };
          el.addEventListener("pointermove", move);
          el.addEventListener("pointerup", up);
          el.addEventListener("pointercancel", up);
        }}
        onKeyDown={(e) => {
          const step = e.key === "ArrowLeft" ? -0.02 : e.key === "ArrowRight" ? 0.02 : 0;
          if (step) props.onRatio(clamp(ratio + step));
          else if (e.key === "Home") props.onRatio(min);
          else if (e.key === "End") props.onRatio(max);
          else return;
          e.preventDefault();
        }}
      />
      <div className={s.splitPart}>{props.right}</div>
    </div>
  );
}
