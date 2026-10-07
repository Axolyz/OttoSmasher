// 锚定小面板（UI_PLAN §5）：贴着按钮出现，Esc / 点外面关闭。用于截取、准备清单、添加标签、筛选器预设。
// 头部一行：标题 + 右侧附注（例如区间）；正文；底部动作（右对齐）。
import type { ReactNode } from "react";
import { Dialog, DialogTrigger, Heading, Popover } from "react-aria-components";
import s from "./Overlay.module.css";

export function AnchoredPanel(props: {
  trigger: ReactNode;
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
  return (
    <DialogTrigger isOpen={props.isOpen} onOpenChange={props.onOpenChange}>
      {props.trigger}
      <Popover className={s.panelPopover} placement={props.placement ?? "bottom start"} offset={8} style={{ width: props.width ?? 380 }}>
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
      </Popover>
    </DialogTrigger>
  );
}
