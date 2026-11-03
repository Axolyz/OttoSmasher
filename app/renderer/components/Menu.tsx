// 菜单（UI_PLAN §5、§6.1）：按钮菜单与右键菜单共用同一份菜单体——菜单头写明作用对象、分组、快捷键提示、危险项、子菜单。
// 右键菜单在指针位置弹出，打开与关闭都不改变勾选和焦点；Esc 只关菜单（不会顺带清空勾选）。
// 每一项带 data-testid="menu-<id>"（e2e 按 id 点，不按序号、不按文字——伪语言下也能用）。
import { ChevronRight } from "lucide-react";
import { type ReactNode, useCallback, useRef, useState } from "react";
import {
  Header,
  Menu as RacMenu,
  MenuItem,
  MenuSection,
  MenuTrigger,
  Popover,
  Separator,
  SubmenuTrigger,
} from "react-aria-components";
import { keys } from "../i18n";
import s from "./Overlay.module.css";

export interface MenuEntry {
  id: string;
  label: string;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  /** 子菜单（有它时 run 不会被调用） */
  items?: MenuItems;
  run?: () => void;
}
export type MenuItems = Array<MenuEntry | "-">;
export interface MenuSpec {
  /** 菜单头：作用对象（“作用于：…” / “已勾选 N 项”） */
  head?: string;
  items: MenuItems;
}

function groupsOf(items: MenuItems): MenuEntry[][] {
  const groups: MenuEntry[][] = [[]];
  for (const it of items) {
    if (it === "-") groups.push([]);
    else groups[groups.length - 1]!.push(it);
  }
  return groups.filter((g) => g.length);
}

function find(items: MenuItems, id: string): MenuEntry | undefined {
  for (const it of items) {
    if (it === "-") continue;
    if (it.id === id) return it;
    const sub = it.items ? find(it.items, id) : undefined;
    if (sub) return sub;
  }
  return undefined;
}

/** 菜单体（不含触发器）：给 Menu、ContextMenu、子菜单共用。 */
function MenuBody(props: MenuSpec & { onClose?: () => void; testId?: string }) {
  const disabled = props.items.flatMap((x) => (x !== "-" && x.disabled ? [x.id] : []));
  return (
    <RacMenu
      className={s.menu}
      disabledKeys={disabled}
      onAction={(key) => find(props.items, String(key))?.run?.()}
      onClose={props.onClose}
      data-testid={props.testId}
    >
      {props.head ? (
        <MenuSection>
          <Header className={s.menuHead}>{props.head}</Header>
        </MenuSection>
      ) : null}
      {groupsOf(props.items).map((g, gi) => (
        <MenuSection key={gi}>
          {gi > 0 ? <Separator className={s.sep} /> : null}
          {g.map((it) =>
            it.items ? (
              <SubmenuTrigger key={it.id}>
                <MenuItem id={it.id} className={s.item} textValue={it.label} data-testid={`menu-${it.id}`}>
                  <span>{it.label}</span>
                  <ChevronRight size={13} className={s.subArrow} />
                </MenuItem>
                <Popover className={s.popover} offset={-4}>
                  <MenuBody items={it.items} />
                </Popover>
              </SubmenuTrigger>
            ) : (
              <MenuItem key={it.id} id={it.id} className={`${s.item} ${it.danger ? s.danger : ""}`} textValue={it.label} data-testid={`menu-${it.id}`}>
                <span>{it.label}</span>
                {it.shortcut ? <kbd className={s.kbd}>{keys(it.shortcut)}</kbd> : null}
              </MenuItem>
            ),
          )}
        </MenuSection>
      ))}
    </RacMenu>
  );
}

/** 按钮菜单：trigger 是一个 Button。 */
export function Menu(
  props: MenuSpec & {
    trigger: ReactNode;
    isOpen?: boolean;
    onOpenChange?: (open: boolean) => void;
    placement?: "bottom start" | "bottom end" | "top start" | "top end";
    testId?: string;
  },
) {
  return (
    <MenuTrigger isOpen={props.isOpen} onOpenChange={props.onOpenChange}>
      {props.trigger}
      <Popover className={s.popover} placement={props.placement ?? "bottom start"} offset={4}>
        <MenuBody head={props.head} items={props.items} testId={props.testId} />
      </Popover>
    </MenuTrigger>
  );
}

/**
 * 右键菜单：const ctx = useContextMenu(); 在 onContextMenu 里 ctx.open(e, spec)；把 ctx.node 放进页面。
 * 用一个放在指针位置的 1×1 锚点做 Popover 的触发元素。
 */
export function useContextMenu(testId = "context-menu") {
  const anchor = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ x: number; y: number; spec: MenuSpec; onClose?: () => void } | null>(null);
  const open = useCallback((at: { clientX: number; clientY: number }, spec: MenuSpec, onClose?: () => void) => {
    setState({ x: at.clientX, y: at.clientY, spec, onClose });
  }, []);
  const close = useCallback(() => {
    setState((st) => {
      st?.onClose?.();
      return null;
    });
  }, []);
  const node = (
    <>
      <div ref={anchor} aria-hidden style={{ position: "fixed", left: state?.x ?? 0, top: state?.y ?? 0, width: 1, height: 1, pointerEvents: "none" }} />
      {state ? (
        <Popover
          className={s.popover}
          triggerRef={anchor}
          isOpen
          onOpenChange={(o) => !o && close()}
          placement="bottom start"
          offset={2}
          shouldFlip
        >
          <MenuBody head={state.spec.head} items={state.spec.items} onClose={close} testId={testId} />
        </Popover>
      ) : null}
    </>
  );
  return { open, close, isOpen: state != null, node };
}
