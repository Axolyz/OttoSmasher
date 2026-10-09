// 锚定小面板（UI_PLAN §5）：贴着按钮出现，Esc / 点外面关闭。用于截取、准备清单、添加标签、筛选器预设。
// 头部一行：标题 + 右侧附注（例如区间）；正文；底部动作（右对齐）。
// 从右键菜单打开时没有按钮：给 at（指针位置），面板贴着那一点出现。
import { type ReactNode, useRef } from "react";
import { Dialog, DialogTrigger, Heading, Popover } from "react-aria-components";
import s from "./Overlay.module.css";

export function AnchoredPanel(props: {
  trigger?: ReactNode;
  /** 没有触发按钮时贴着这一点（客户区坐标）出现 */
  at?: { x: number; y: number } | null;
  title: string;
  /** 标题右侧的附注（淡色、等宽），例如“0:12.300–0:13.050” */
  aux?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  width?: number;
  placement?: "top start" | "top end" | "bottom start" | "bottom end";
  testId?: string;
}) {
  const anchor = useRef<HTMLDivElement>(null);
  const body = (
    <Dialog className={s.panel} aria-label={props.title} data-testid={props.testId}>
      <div className={s.panelHead}>
        <Heading slot="title" className={s.panelTitle}>
          {props.title}
        </Heading>
        {props.aux != null ? <span className={`${s.panelAux} num`}>{props.aux}</span> : null}
      </div>
      <div className={s.panelBody}>{props.children}</div>
      {props.footer ? <div className={s.panelFoot}>{props.footer}</div> : null}
    </Dialog>
  );
  if (props.at)
    return (
      <>
        <div ref={anchor} aria-hidden style={{ position: "fixed", left: props.at.x, top: props.at.y, width: 1, height: 1, pointerEvents: "none" }} />
        <Popover
          className={s.panelPopover}
          triggerRef={anchor}
          isOpen={!!props.isOpen}
          onOpenChange={props.onOpenChange}
          placement={props.placement ?? "bottom start"}
          offset={4}
          shouldFlip
          style={{ width: props.width ?? 380 }}
        >
          {body}
        </Popover>
      </>
    );
  return (
    <DialogTrigger isOpen={props.isOpen} onOpenChange={props.onOpenChange}>
      {props.trigger}
      <Popover className={s.panelPopover} placement={props.placement ?? "bottom start"} offset={8} style={{ width: props.width ?? 380 }}>
        {body}
      </Popover>
    </DialogTrigger>
  );
}
