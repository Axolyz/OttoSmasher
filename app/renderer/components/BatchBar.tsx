// 勾选后浮出的批量条（UI_PLAN §2.1、§6.1）：“n 项已勾选 · 全选全部 N · 批量操作 ▾ · ✕”，没有勾选时不出现。
// 放在列表容器（position: relative）底部居中；批量动作都在“批量操作 ▾”菜单里，菜单头写明对象。
import { ChevronDown, X } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./Button";
import { Menu, type MenuItems } from "./Menu";
import s from "./Collection.module.css";

export function BatchBar(props: {
  count: number;
  /** 全部匹配的数量（跨页）；给了且大于勾选数才显示“全选全部 N” */
  total?: number;
  onCheckAll?: () => void;
  items: MenuItems;
  onClear: () => void;
  testId?: string;
}) {
  if (!props.count) return null;
  return (
    <div className={s.batch} role="toolbar" aria-label={t("batch.label")} data-testid={props.testId}>
      <span>{t("batch.checked", { n: props.count })}</span>
      {props.onCheckAll && props.total != null && props.total > props.count ? (
        <Button size="sm" variant="flat" onPress={props.onCheckAll} data-testid="batch-check-all">
          {t("batch.checkAll", { n: props.total })}
        </Button>
      ) : null}
      <Menu
        head={t("menu.checkedN", { n: props.count })}
        items={props.items}
        placement="top start"
        testId="batch-menu"
        trigger={
          <Button size="sm" variant="primary" data-testid="batch-actions">
            {t("batch.actions")}
            <ChevronDown size={13} />
          </Button>
        }
      />
      <Button size="sm" variant="flat" icon={<X />} onPress={props.onClear} aria-label={t("batch.clear")} title={t("batch.clear")} data-testid="batch-clear" />
    </div>
  );
}
