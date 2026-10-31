// 动作列表（台本这类“点一行 = 做一件事”的列表；UI_PLAN §4 台本）：
// 单击 = onPress（带 Shift 状态）；双击 = onDouble；右键 = onContext（行的菜单）；Enter = onPress；当前行（例如正在播放的那句）高亮并自动滚到可视区，
// 用户手动滚动后暂停跟随一段时间（默认 3.5 秒，规格 03 §3.4）。没有勾选——要勾选用 CollectionList。
// React Aria GridList：↑↓ 移动焦点、读屏语义。
import { type ReactNode, useEffect, useRef } from "react";
import { GridList, GridListItem } from "react-aria-components";
import s from "./Collection.module.css";

export function ActionList<T extends { id: string }>(props: {
  label: string;
  items: T[];
  textValue: (item: T) => string;
  render: (item: T, st: { current: boolean; selected: boolean }) => ReactNode;
  current: string | null;
  /** 与当前选区对应的行（描边） */
  selected?: ReadonlySet<string>;
  onPress: (id: string, mods: { shift: boolean }) => void;
  onDouble?: (id: string) => void;
  onContext?: (id: string, at: { x: number; y: number }) => void;
  pauseFollowMs?: number;
  /** render 用到的其他状态（行被 React Aria 缓存，这些变了才重画） */
  renderDeps?: unknown[];
  empty?: ReactNode;
  testId?: string;
  rowTestId?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const shift = useRef(false);
  const userScrollAt = useRef(0);

  useEffect(() => {
    if (!props.current) return;
    if (performance.now() - userScrollAt.current < (props.pauseFollowMs ?? 3500)) return;
    const el = wrap.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(props.current)}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "nearest" });
  }, [props.current, props.pauseFollowMs]);

  return (
    <div
      ref={wrap}
      className={s.actionWrap}
      data-testid={props.testId}
      onPointerDownCapture={(e) => (shift.current = e.shiftKey)}
      onKeyDownCapture={(e) => (shift.current = e.shiftKey)}
      // 只把真正的“手动滚动”算作暂停跟随：滚轮、拖滚动条（点击行时列表自己的聚焦滚动不算）
      onWheel={() => (userScrollAt.current = performance.now())}
      onPointerDown={(e) => {
        if (e.target === wrap.current) userScrollAt.current = performance.now();
      }}
      onDoubleClick={(e) => {
        const row = (e.target as HTMLElement).closest<HTMLElement>("[data-key]");
        if (row && wrap.current?.contains(row)) props.onDouble?.(row.dataset.key!);
      }}
      onContextMenu={(e) => {
        const row = (e.target as HTMLElement).closest<HTMLElement>("[data-key]");
        if (!row || !wrap.current?.contains(row) || !props.onContext) return;
        e.preventDefault();
        props.onContext(row.dataset.key!, { x: e.clientX, y: e.clientY });
      }}
    >
      <GridList
        aria-label={props.label}
        items={props.items}
        selectionMode="none"
        disallowTypeAhead
        onAction={(k) => props.onPress(String(k), { shift: shift.current })}
        dependencies={[props.current, props.selected, ...(props.renderDeps ?? [])]}
        className={s.actionList}
        renderEmptyState={() => props.empty ?? null}
      >
        {(item) => {
          const st = { current: item.id === props.current, selected: props.selected?.has(item.id) ?? false };
          return (
            <GridListItem
              id={item.id}
              textValue={props.textValue(item)}
              className={s.actionRow}
              data-current={st.current || undefined}
              data-selected-row={st.selected || undefined}
              data-testid={props.rowTestId}
            >
              {props.render(item, st)}
            </GridListItem>
          );
        }}
      </GridList>
    </div>
  );
}
