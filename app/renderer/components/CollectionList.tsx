// 统一选择规则的列表（UI_PLAN §6.1）：采样列表、原片列表、命中、分离声部、任务……都用它，页面不再各写各的。
//
// 规则（勾选的计算在 selection.ts）：
// - 单击 = 设为焦点（查看），从不改变勾选；双击 = 主动作（onPrimary）；Enter = onEnter（采样：焦点移到波形；命中：定位）
// - 复选框 / ⌘(Ctrl)+单击 / X = 切换勾选；Shift+单击 = 从锚点连续勾选（并入）；Shift+↑↓ = 移动并勾选；⌘A = 勾选全部匹配（跨页，onCheckAll）
// - Esc = 清空勾选（菜单、面板开着时先由它们吃掉 Esc）；Delete/⌫ = 删除勾选项，无勾选时删焦点项（页面确认）
// - 右键 = 菜单：在已勾选项上且勾选 ≥2 → 对象是勾选集，否则只这一项；不改变勾选和焦点；该行描边直到菜单关闭；空白处 = 集合级菜单
// - 失效项（dead）：保留位置、不可勾选、↑↓ 跳过
// - 分组行（kind: "group"）：单击/Enter 展开收起，← 收起、→ 展开；不可勾选
//
// 实现：React Aria GridList 负责焦点移动、键盘导航、无障碍；selectionMode 设为 none——GridList 自带的多选
// 在“已有勾选”时会把单击变成切换勾选（正是 UI_PLAN §10 第 14 条去掉的模式切换），所以勾选状态由这里按上面的规则维护。
import { type CSSProperties, type ReactNode, type Ref, useEffect, useMemo, useRef, useState } from "react";
import { GridList, GridListItem, ListLayout, Virtualizer } from "react-aria-components";
import { t } from "../i18n";
import { Checkbox } from "./Controls";
import { type MenuSpec, useContextMenu } from "./Menu";
import { actionTarget, extendChecked, menuTarget, toggleChecked } from "./selection";
import s from "./Collection.module.css";

export interface CollectionRow {
  id: string;
  kind?: "item" | "group";
  /** 失效项（已删除 / 音源已变化）：保留位置、不可勾选、↑↓ 跳过 */
  dead?: boolean;
}

export interface RowState {
  focused: boolean;
  checked: boolean;
  /** 右键菜单正作用于这一行 */
  inMenu: boolean;
}

const NAV_KEYS = new Set(["ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]);

function isTyping(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null;
  return !!e && (e.tagName === "INPUT" || e.tagName === "TEXTAREA" || e.isContentEditable) && (e as HTMLInputElement).type !== "checkbox";
}

export function CollectionList<T extends CollectionRow>(props: {
  label: string;
  items: T[];
  textValue: (item: T) => string;
  focus: string | null;
  onFocus: (id: string) => void;
  checked: ReadonlySet<string>;
  onChecked: (next: Set<string>) => void;
  /** ⌘A：勾选全部匹配（跨页）。不给时只勾本页 */
  onCheckAll?: () => void;
  onPrimary?: (id: string) => void;
  onEnter?: (id: string) => void;
  onGroup?: (id: string, open?: boolean) => void;
  isGroupOpen?: (id: string) => boolean;
  /** 行菜单；组头也会调用（target.ids 为空），返回 null = 没有组级菜单 */
  menu?: (item: T, target: { ids: string[]; multi: boolean }) => MenuSpec | null;
  onDelete?: (ids: string[]) => void;
  /** 页面自己的键（Space 试听、1/2/3/0、S 星标……）；返回 true 表示已处理 */
  onKey?: (e: React.KeyboardEvent, focusItem: T | null) => boolean;
  /** 行上按下（捕获阶段，先于行的按压处理）：⌥ 拖出用 */
  onRowPointerDown?: (e: React.PointerEvent, item: T) => void;
  /** 行上额外的 data-* 属性（样式与测试用） */
  rowData?: (item: T) => Record<string, string>;
  renderItem: (item: T, st: RowState) => ReactNode;
  /** 行内容还依赖的其他状态（例如正在试听哪一行）：GridList 按 items 缓存行，不声明就不重画 */
  renderDeps?: unknown[];
  renderGroup?: (item: T, open: boolean) => ReactNode;
  checkLabel: (item: T) => string;
  empty?: ReactNode;
  /** 放在列表底部的浮动物（批量条） */
  footer?: ReactNode;
  testId?: string;
  rowTestId?: string;
  /** 行很多时只渲染看得见的行（React Aria Virtualizer；原片列表，L15）。rowHeight = 估计行高 */
  virtual?: { rowHeight: number };
  /** 一屏一页：固定行高，批量条在列表外占位。 */
  fixedRowHeight?: number;
  listRef?: Ref<HTMLDivElement>;
  groupTestId?: string;
  className?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const pointer = useRef<{ shift: boolean; meta: boolean } | null>(null);
  const keyNav = useRef<{ shift: boolean } | null>(null);
  const anchor = useRef<string | null>(null);
  const [menuFor, setMenuFor] = useState<ReadonlySet<string>>(new Set());
  const ctx = useContextMenu();

  const byId = useMemo(() => new Map(props.items.map((i) => [i.id, i])), [props.items]);
  const order = useMemo(() => props.items.filter((i) => i.kind !== "group").map((i) => i.id), [props.items]);
  const selectable = (id: string) => {
    const it = byId.get(id);
    return !!it && it.kind !== "group" && !it.dead;
  };
  const deadKeys = useMemo(() => props.items.filter((i) => i.dead).map((i) => i.id), [props.items]);
  const focusItem = props.focus ? (byId.get(props.focus) ?? null) : null;

  const rowEl = (id: string) => wrap.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(id)}"]`) ?? null;
  const rowOf = (target: EventTarget | null) => {
    const el = (target as HTMLElement | null)?.closest<HTMLElement>("[data-key]");
    return el && wrap.current?.contains(el) ? el : null;
  };

  // 焦点在别处改变（打开新采样、返回原片）：滚到可见；列表正持有键盘焦点时让键盘焦点跟上
  useEffect(() => {
    if (!props.focus) return;
    const el = rowEl(props.focus);
    if (!el) return;
    el.scrollIntoView?.({ block: "nearest" });
    const active = document.activeElement;
    if (active && wrap.current?.contains(active) && rowOf(active)?.dataset.key !== props.focus) el.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.focus]);

  const toggle = (id: string) => {
    anchor.current = id;
    props.onChecked(toggleChecked(props.checked, id, selectable));
  };

  const onAction = (key: React.Key) => {
    const id = String(key);
    const item = byId.get(id);
    const p = pointer.current;
    pointer.current = null;
    if (!item) return;
    if (item.kind === "group") return props.onGroup?.(id);
    if (!p) return props.onEnter?.(id);
    if (p.meta) return toggle(id);
    if (p.shift) return props.onChecked(extendChecked(props.checked, order, anchor.current ?? props.focus, id, selectable));
    anchor.current = id;
    props.onFocus(id);
  };

  const openMenu = (at: { clientX: number; clientY: number }, item: T) => {
    if (!props.menu) return;
    const target = menuTarget(props.checked, item.id);
    const spec = props.menu(item, target);
    if (!spec) return;
    setMenuFor(new Set(target.ids));
    ctx.open(at, spec, () => setMenuFor(new Set()));
  };

  const checkAll = () => {
    if (props.onCheckAll) props.onCheckAll();
    else props.onChecked(new Set([...props.checked, ...order.filter(selectable)]));
  };

  const onKeyDownCapture = (e: React.KeyboardEvent) => {
    // 只处理列表自己 DOM 里的按键（弹出物经 React 传送门冒泡上来的不算）
    if (!wrap.current?.contains(e.target as Node)) return;
    pointer.current = null;
    if (isTyping(e.target)) return;
    const handled = () => {
      e.preventDefault();
      e.stopPropagation();
    };
    const row = rowOf(document.activeElement);
    const rowItem = row ? byId.get(row.dataset.key!) : undefined;
    if (rowItem?.kind === "group" && (e.key === "ArrowLeft" || e.key === "ArrowRight") && document.activeElement === row) {
      handled();
      props.onGroup?.(rowItem.id, e.key === "ArrowRight");
      return;
    }
    if (NAV_KEYS.has(e.key)) {
      keyNav.current = { shift: e.shiftKey };
      return; // 交给 GridList 移动焦点，onFocusCapture 里同步焦点
    }
    if (props.onKey?.(e, focusItem)) return handled();
    const k = e.key;
    const mod = e.metaKey || e.ctrlKey;
    if ((k === "x" || k === "X") && !mod && !e.altKey) {
      if (focusItem && focusItem.kind !== "group") toggle(focusItem.id);
      return handled();
    }
    if ((k === "a" || k === "A") && mod) {
      checkAll();
      return handled();
    }
    if (k === "Escape" && props.checked.size) {
      props.onChecked(new Set());
      return handled();
    }
    if ((k === "Delete" || k === "Backspace") && props.onDelete) {
      const ids = actionTarget(props.checked, props.focus);
      if (ids.length) props.onDelete(ids);
      return handled();
    }
    if (k === "ContextMenu" || (k === "F10" && e.shiftKey)) {
      const it = rowItem && rowItem.kind !== "group" ? rowItem : focusItem;
      const el = it ? rowEl(it.id) : null;
      if (it && el) {
        const r = el.getBoundingClientRect();
        openMenu({ clientX: r.left + 40, clientY: r.bottom - 4 }, it);
      }
      return handled();
    }
  };

  const onFocusCapture = (e: React.FocusEvent) => {
    const row = rowOf(e.target);
    if (!row || row !== e.target) return;
    const id = row.dataset.key!;
    // 从列表外进入（Tab）：落到当前焦点项上，不改变查看对象
    if (!wrap.current?.contains(e.relatedTarget as Node | null)) {
      if (props.focus && id !== props.focus && !keyNav.current && !pointer.current) {
        const el = rowEl(props.focus);
        if (el) queueMicrotask(() => el.focus({ preventScroll: true }));
      }
    }
    const nav = keyNav.current;
    keyNav.current = null;
    if (!nav || pointer.current) return; // 指针按下引起的聚焦由 onAction 处理
    const item = byId.get(id);
    if (!item || item.kind === "group") return;
    props.onFocus(id); // ↑↓ = 上/下一项并打开
    if (nav.shift && selectable(id)) props.onChecked(new Set(props.checked).add(id)); // Shift+↑↓ = 移动并勾选
  };

  return (
    <>
      <div
        ref={wrap}
        className={`${s.wrap} ${props.className ?? ""}`}
        data-fixed-rows={props.fixedRowHeight != null || undefined}
        style={props.fixedRowHeight == null ? undefined : { "--collection-row-height": `${props.fixedRowHeight}px` } as CSSProperties}
        data-testid={props.testId}
        onPointerDownCapture={(e) => {
          pointer.current = { shift: e.shiftKey, meta: e.metaKey || e.ctrlKey };
          // 捕获阶段：React Aria 的按压处理会在行上阻止 pointerdown 冒泡（⌥ 拖出要在这里接管）
          const row = rowOf(e.target);
          const item = row ? byId.get(row.dataset.key!) : undefined;
          if (item && item.kind !== "group") props.onRowPointerDown?.(e, item);
        }}
        onKeyDownCapture={onKeyDownCapture}
        onFocusCapture={onFocusCapture}
        onDoubleClick={(e) => {
          if ((e.target as HTMLElement).closest("button, input, label, [role=checkbox]")) return;
          const row = rowOf(e.target);
          const item = row ? byId.get(row.dataset.key!) : undefined;
          if (item && item.kind !== "group" && !item.dead) props.onPrimary?.(item.id);
        }}
        onContextMenu={(e) => {
          if (!wrap.current?.contains(e.target as Node)) return;
          e.preventDefault();
          const row = rowOf(e.target);
          const item = row ? byId.get(row.dataset.key!) : undefined;
          if (item && item.kind !== "group") return openMenu(e, item);
          if (item && item.kind === "group") {
            // 组头右键：组级菜单（不改勾选；菜单头写组名）
            const spec = props.menu?.(item, { ids: [], multi: false });
            if (spec) ctx.open(e, spec);
            return;
          }
          if (!row) {
            // 空白处：集合级菜单
            ctx.open(e, {
              head: props.label,
              items: [
                { id: "check-all", label: t("collection.checkAll"), shortcut: "⌘A", run: checkAll },
                { id: "clear", label: t("collection.clear"), shortcut: "Esc", disabled: !props.checked.size, run: () => props.onChecked(new Set()) },
              ],
            });
          }
        }}
      >
        <MaybeVirtual on={!!props.virtual} rowHeight={props.virtual?.rowHeight ?? 48}>
        <GridList
          ref={props.listRef}
          aria-label={props.label}
          items={props.items}
          selectionMode="none"
          disallowTypeAhead
          disabledKeys={deadKeys}
          disabledBehavior="all"
          onAction={onAction}
          // 行的渲染依赖焦点、勾选与菜单对象：GridList 默认按 items 缓存行，必须声明这些依赖
          dependencies={[props.focus, props.checked, menuFor, props.isGroupOpen, ...(props.renderDeps ?? [])]}
          className={s.list}
          renderEmptyState={() => props.empty ?? null}
        >
          {(item) => {
            if (item.kind === "group") {
              const open = props.isGroupOpen?.(item.id) ?? true;
              return (
                <GridListItem id={item.id} textValue={props.textValue(item)} className={s.groupRow} data-testid={props.groupTestId} data-open={open || undefined}>
                  {props.renderGroup?.(item, open)}
                </GridListItem>
              );
            }
            const st: RowState = { focused: item.id === props.focus, checked: props.checked.has(item.id), inMenu: menuFor.has(item.id) };
            return (
              <GridListItem
                id={item.id}
                textValue={props.textValue(item)}
                className={s.row}
                data-testid={props.rowTestId}
                data-id={item.id}
                data-focus={st.focused || undefined}
                data-checked={st.checked || undefined}
                data-menu={st.inMenu || undefined}
                data-dead={item.dead || undefined}
                {...(props.rowData?.(item) ?? {})}
              >
                <Checkbox isSelected={st.checked} isDisabled={item.dead} onChange={() => toggle(item.id)} label={props.checkLabel(item)} />
                {props.renderItem(item, st)}
              </GridListItem>
            );
          }}
        </GridList>
        </MaybeVirtual>
        {props.fixedRowHeight != null ? <div className={s.fixedFooter}>{props.footer}</div> : props.footer}
      </div>
      {ctx.node}
    </>
  );
}

/** 只在需要时包一层 Virtualizer（行高不一：组头与行都按估计高度起步，渲染后按实际高度修正） */
function MaybeVirtual(props: { on: boolean; rowHeight: number; children: ReactNode }) {
  if (!props.on) return <>{props.children}</>;
  return (
    <Virtualizer layout={ListLayout} layoutOptions={{ estimatedRowHeight: props.rowHeight }}>
      {props.children}
    </Virtualizer>
  );
}
