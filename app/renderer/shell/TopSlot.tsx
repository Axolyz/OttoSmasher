// 顶栏里的页面头（UI_PLAN §1、§2、§4）：采样库放用途切换，原片页放「收起列表 · 当前原片 · 准备 · ⋯」。
// 三页常驻，每页把自己的页面头经传送门放进顶栏里属于自己的槽位；只显示当前页的槽位。
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { create } from "zustand";
import type { Page } from "../state/store";

const useSlots = create<{ els: Partial<Record<Page, HTMLElement>>; set: (p: Page, el: HTMLElement | null) => void }>((set) => ({
  els: {},
  set: (p, el) => set((st) => (st.els[p] === (el ?? undefined) ? st : { els: { ...st.els, [p]: el ?? undefined } })),
}));

export function TopSlotHost(props: { page: Page; active: boolean; className: string }) {
  const setEl = useSlots((st) => st.set);
  return <div className={props.className} hidden={!props.active} ref={(el) => setEl(props.page, el)} data-testid={`top-${props.page}`} />;
}

export function TopSlot(props: { page: Page; children: ReactNode }) {
  const el = useSlots((st) => st.els[props.page]);
  return el ? createPortal(props.children, el) : null;
}
