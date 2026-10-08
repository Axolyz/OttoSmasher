// 带分页的表格（规格 06 §6.4、UI_PLAN §6.1）：字幕导入预览、批量结果表等。
// - 第一列是勾选列；表头复选框跨**所有分页**全选，有半选态；不可勾选的行（如“OP/ED 排除”）淡色、复选框禁用
// - 复选框 Shift+单击 = 从上次勾选的行连续勾选（按全部行的顺序，跨页也算）
// - 底部：已勾选数 + 分页（‹ i/n ›）；行数不超过一页时不显示分页
// React Aria Table 负责表格语义与键盘导航（↑↓←→ 在单元格间移动）；勾选规则同 selection.ts。
import { ChevronLeft, ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Cell, Column, Row, Table, TableBody, TableHeader } from "react-aria-components";
import { t } from "../i18n";
import { Button } from "./Button";
import { Checkbox } from "./Controls";
import { extendChecked, headerState, toggleChecked, toggleHeader } from "./selection";
import s from "./Table.module.css";

export interface TableColumn<T> {
  id: string;
  label: string;
  /** CSS 宽度，例如 "120px" / "30%"；不给时平分 */
  width?: string;
  align?: "start" | "end";
  /** 行头列（读屏用来称呼这一行），一张表一列 */
  isRowHeader?: boolean;
  render: (row: T) => ReactNode;
}

const EMPTY: ReadonlySet<string> = new Set();

export function PagedTable<T extends { id: string }>(props: {
  label: string;
  columns: Array<TableColumn<T>>;
  rows: T[];
  /** 不给 ``checked`` = 只读表格（没有勾选列与“已勾选”计数） */
  checked?: ReadonlySet<string>;
  onChecked?: (next: Set<string>) => void;
  isSelectable?: (row: T) => boolean;
  checkLabel?: (row: T) => string;
  pageSize?: number;
  empty?: ReactNode;
  /** 底部左侧额外信息 */
  footer?: ReactNode;
  testId?: string;
}) {
  const size = props.pageSize ?? 100;
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(props.rows.length / size));
  useEffect(() => setPage((p) => Math.min(p, pages - 1)), [pages]);
  const shown = props.rows.slice(page * size, (page + 1) * size);
  const selectable = useMemo(() => {
    const ok = new Set(props.rows.filter((r) => props.isSelectable?.(r) ?? true).map((r) => r.id));
    return (id: string) => ok.has(id);
  }, [props.rows, props.isSelectable]);
  const allIds = useMemo(() => props.rows.map((r) => r.id), [props.rows]);
  const selectableIds = useMemo(() => allIds.filter(selectable), [allIds, selectable]);
  const withCheck = props.checked !== undefined;
  const checked: ReadonlySet<string> = props.checked ?? EMPTY;
  const head = headerState(checked, selectableIds);
  const anchor = useRef<string | null>(null);
  const shift = useRef(false);

  const onRow = (id: string) => {
    const next = shift.current ? extendChecked(checked, allIds, anchor.current, id, selectable) : toggleChecked(checked, id, selectable);
    anchor.current = id;
    props.onChecked?.(next);
  };
  const nChecked = selectableIds.filter((id) => checked.has(id)).length;

  return (
    <div className={s.wrap} data-testid={props.testId} onPointerDownCapture={(e) => (shift.current = e.shiftKey)} onKeyDownCapture={() => (shift.current = false)}>
      <div className={s.scroll}>
        <Table aria-label={props.label} className={s.table}>
          <TableHeader className={s.head}>
            {withCheck ? (
              <Column className={s.th} style={{ width: 36 }}>
                <Checkbox
                  isSelected={head === "all"}
                  isIndeterminate={head === "some"}
                  isDisabled={!selectableIds.length}
                  onChange={() => props.onChecked?.(toggleHeader(checked, selectableIds))}
                  label={t("table.checkAllPages", { n: selectableIds.length })}
                  testId="table-check-all"
                />
              </Column>
            ) : null}
            {props.columns.map((c) => (
              <Column key={c.id} id={c.id} isRowHeader={c.isRowHeader} className={s.th} data-align={c.align} style={c.width ? { width: c.width } : undefined}>
                {c.label}
              </Column>
            ))}
          </TableHeader>
          <TableBody className={s.body} renderEmptyState={() => props.empty ?? null}>
            {shown.map((r) => {
              const ok = selectable(r.id);
              return (
                <Row key={r.id} id={r.id} className={s.tr} data-disabled-row={(withCheck && !ok) || undefined} data-checked={checked.has(r.id) || undefined} data-testid="table-row">
                  {withCheck ? (
                    <Cell className={s.td}>
                      <Checkbox isSelected={checked.has(r.id)} isDisabled={!ok} onChange={() => onRow(r.id)} label={props.checkLabel?.(r) ?? r.id} />
                    </Cell>
                  ) : null}
                  {props.columns.map((c) => (
                    <Cell key={c.id} className={s.td} data-align={c.align}>
                      {c.render(r)}
                    </Cell>
                  ))}
                </Row>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className={s.foot}>
        {withCheck ? <span data-testid="table-checked">{t("table.checkedOf", { n: nChecked, total: selectableIds.length })}</span> : null}
        {props.footer}
        <span className={s.grow} />
        {pages > 1 ? (
          <>
            <Button size="sm" variant="flat" icon={<ChevronLeft />} isDisabled={page <= 0} onPress={() => setPage(page - 1)} aria-label={t("pager.prev")} />
            <span className="num" data-testid="table-page">
              {page + 1} / {pages}
            </span>
            <Button size="sm" variant="flat" icon={<ChevronRight />} isDisabled={page >= pages - 1} onPress={() => setPage(page + 1)} aria-label={t("pager.next")} />
          </>
        ) : null}
      </div>
    </div>
  );
}
