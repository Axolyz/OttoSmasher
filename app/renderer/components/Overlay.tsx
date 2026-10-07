// 弹出物：菜单（菜单头写明作用对象）、提示、全屏工作台、右侧抽屉（UI_PLAN §5）。
import { X } from "lucide-react";
import type { ReactNode } from "react";
import {
  Dialog,
  Header,
  Menu as RacMenu,
  MenuItem,
  MenuSection,
  MenuTrigger,
  Modal,
  ModalOverlay,
  Popover,
  Separator,
  Tooltip,
  TooltipTrigger,
} from "react-aria-components";
import { t } from "../i18n";
import { Button } from "./Button";
import s from "./Overlay.module.css";

export interface MenuEntry {
  id: string;
  label: string;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  run: () => void;
}

export function Menu(props: { trigger: ReactNode; head?: string; items: Array<MenuEntry | "-"> }) {
  const groups: MenuEntry[][] = [[]];
  for (const it of props.items) {
    if (it === "-") groups.push([]);
    else groups[groups.length - 1]!.push(it);
  }
  return (
    <MenuTrigger>
      {props.trigger}
      <Popover className={s.popover} placement="bottom start" offset={4}>
        <RacMenu
          className={s.menu}
          disabledKeys={props.items.flatMap((x) => (x !== "-" && x.disabled ? [x.id] : []))}
          onAction={(key) => {
            for (const g of groups) for (const it of g) if (it.id === key) it.run();
          }}
        >
          {props.head ? (
            <MenuSection>
              <Header className={s.menuHead}>{props.head}</Header>
            </MenuSection>
          ) : null}
          {groups.map((g, gi) => (
            <MenuSection key={gi}>
              {gi > 0 ? <Separator className={s.sep} /> : null}
              {g.map((it) => (
                <MenuItem key={it.id} id={it.id} className={`${s.item} ${it.danger ? s.danger : ""}`} textValue={it.label}>
                  <span>{it.label}</span>
                  {it.shortcut ? <kbd className={s.kbd}>{it.shortcut}</kbd> : null}
                </MenuItem>
              ))}
            </MenuSection>
          ))}
        </RacMenu>
      </Popover>
    </MenuTrigger>
  );
}

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
