// 弹出物：提示、全屏工作台、确认框、右侧抽屉（UI_PLAN §5）。菜单在 Menu.tsx，锚定小面板在 Panel.tsx。
import { X } from "lucide-react";
import type { ReactNode } from "react";
import {
  Dialog,
  Modal,
  ModalOverlay,
  Tooltip,
  TooltipTrigger,
} from "react-aria-components";
import { t } from "../i18n";
import { Button } from "./Button";
import s from "./Overlay.module.css";

export function Tip(props: { content: ReactNode; children: ReactNode; placement?: "top" | "bottom" | "start" | "end" }) {
  return (
    <TooltipTrigger delay={500} closeDelay={80}>
      {props.children}
      <Tooltip className={s.tooltip} placement={props.placement ?? "bottom"} offset={6}>
        {props.content}
      </Tooltip>
    </TooltipTrigger>
  );
}

/** 全屏工作台：从底部升起，覆盖页面（保留左侧导航）；Esc 或“关闭”落下；同一时刻只有一个。 */
export function Sheet(props: { isOpen: boolean; onClose: () => void; title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <ModalOverlay isOpen={props.isOpen} onOpenChange={(o) => !o && props.onClose()} isDismissable className={s.sheetOverlay}>
      <Modal className={s.sheet}>
        <Dialog className={s.sheetDialog} aria-label={props.title}>
          <div className={s.sheetHead}>
            <h2 className={s.sheetTitle}>{props.title}</h2>
            <div className={s.grow} />
            {props.actions}
            <Button variant="flat" onPress={props.onClose} icon={<X />}>
              {t("common.close")}
              <kbd className={s.kbd}>Esc</kbd>
            </Button>
          </div>
          <div className={s.sheetBody}>{props.children}</div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}

/** 确认框（UI_PLAN §5）：居中、小；写清做什么、不做什么。Esc / 取消关闭。 */
export function ConfirmDialog(props: {
  isOpen: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  testId?: string;
}) {
  return (
    <ModalOverlay isOpen={props.isOpen} onOpenChange={(o) => !o && props.onClose()} isDismissable className={s.dialogOverlay}>
      <Modal className={s.dialog}>
        <Dialog className={s.dialogInner} aria-label={props.title} data-testid={props.testId}>
          <h2 className={s.dialogTitle}>{props.title}</h2>
          <div className={s.dialogBody}>{props.children}</div>
          <div className={s.dialogActions}>
            <Button variant="flat" onPress={props.onClose}>
              {t("common.cancel")}
            </Button>
            <Button
              variant={props.danger ? "danger" : "primary"}
              onPress={props.onConfirm}
              isDisabled={props.busy || props.confirmDisabled}
              data-testid="confirm-ok"
            >
              {props.confirmLabel}
            </Button>
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}

/** 右侧抽屉（任务与日志）。 */
export function Drawer(props: { isOpen: boolean; onClose: () => void; title: string; children: ReactNode }) {
  return (
    <ModalOverlay isOpen={props.isOpen} onOpenChange={(o) => !o && props.onClose()} isDismissable className={s.drawerOverlay}>
      <Modal className={s.drawer}>
        <Dialog className={s.drawerDialog} aria-label={props.title}>
          <div className={s.sheetHead}>
            <h2 className={s.drawerTitle}>{props.title}</h2>
            <div className={s.grow} />
            <Button variant="flat" size="sm" onPress={props.onClose} icon={<X />} aria-label={t("common.close")} />
          </div>
          <div className={s.drawerBody}>{props.children}</div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
