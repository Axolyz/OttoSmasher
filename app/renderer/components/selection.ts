// 集合的勾选规则（UI_PLAN §6.1）——纯函数，不碰界面，供 CollectionList 与分页表格共用，单测直接测这里。
// 术语：焦点（focus）= 正在查看的那一项（单击、↑↓ 改它）；勾选（checked）= 批量操作的对象（复选框、⌘/Ctrl+单击、X、Shift、⌘A 改它）。
// 两者互不影响：单击从不改变勾选，勾选也从不移动焦点。

export type Checked = ReadonlySet<string>;

/** 切换一项的勾选（复选框 / ⌘+单击 / X）。失效项不可勾选。 */
export function toggleChecked(checked: Checked, id: string, selectable: (id: string) => boolean = () => true): Set<string> {
  const next = new Set(checked);
  if (next.has(id)) next.delete(id);
  else if (selectable(id)) next.add(id);
  return next;
}

/**
 * Shift+单击：把锚点到目标之间（含两端，按当前显示顺序）的可勾选项**并入**勾选集。
 * 锚点 = 最近一次切换勾选的项，没有时用焦点；锚点不在本页（翻页了）时只切换目标本身。
 * 页外已勾选的项保留（UI_PLAN §6.1：与页外已勾选合并）。
 */
export function extendChecked(
  checked: Checked,
  order: readonly string[],
  anchor: string | null,
  target: string,
  selectable: (id: string) => boolean = () => true,
): Set<string> {
  const from = anchor == null ? -1 : order.indexOf(anchor);
  const to = order.indexOf(target);
  if (from < 0 || to < 0) return toggleChecked(checked, target, selectable);
  const next = new Set(checked);
  for (const id of order.slice(Math.min(from, to), Math.max(from, to) + 1)) if (selectable(id)) next.add(id);
  return next;
}

/** ↑↓ 的下一项：跳过失效项；到头不动（返回 null）。from 不在本页时从首/尾开始。 */
export function stepFocus(order: readonly string[], from: string | null, dir: 1 | -1, selectable: (id: string) => boolean = () => true): string | null {
  let i = from == null ? -1 : order.indexOf(from);
  if (i < 0) i = dir === 1 ? -1 : order.length;
  for (let j = i + dir; j >= 0 && j < order.length; j += dir) if (selectable(order[j]!)) return order[j]!;
  return null;
}

/** 表头复选框的三态（规格 06 §6.4：表头跨所有分页全选，有半选态）。只看可勾选项。 */
export function headerState(checked: Checked, selectableIds: readonly string[]): "none" | "some" | "all" {
  let n = 0;
  for (const id of selectableIds) if (checked.has(id)) n += 1;
  if (n === 0) return "none";
  return n === selectableIds.length ? "all" : "some";
}

/** 表头复选框按下：未全选 → 全选（所有分页）；已全选 → 全部清空。 */
export function toggleHeader(checked: Checked, selectableIds: readonly string[]): Set<string> {
  if (headerState(checked, selectableIds) === "all") {
    const next = new Set(checked);
    for (const id of selectableIds) next.delete(id);
    return next;
  }
  return new Set([...checked, ...selectableIds]);
}

/** 右键菜单的对象（UI_PLAN §6.1）：在已勾选项上且勾选 ≥2 → 整个勾选集；否则只这一项。不改变勾选和焦点。 */
export function menuTarget(checked: Checked, id: string): { ids: string[]; multi: boolean } {
  if (checked.has(id) && checked.size >= 2) return { ids: [...checked], multi: true };
  return { ids: [id], multi: false };
}

/** Delete / 批量动作的对象：有勾选 → 勾选集；无勾选 → 焦点项（没有焦点则为空）。 */
export function actionTarget(checked: Checked, focus: string | null): string[] {
  if (checked.size) return [...checked];
  return focus ? [focus] : [];
}
