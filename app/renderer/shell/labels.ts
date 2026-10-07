// 编辑记录的“这次修改”描述 → 当前语言（撤销提示、↶ 的悬停说明）。
import type { EditLabel } from "../api/types";
import { hasKey, t } from "../i18n";

export function describeLabel(label: EditLabel | null | undefined): string {
  if (!label) return "";
  if (label.code === "setting") {
    const key = String(label.args.key ?? "");
    return t("edit.label.setting", { name: hasKey(`settings.${key}.label`) ? t(`settings.${key}.label`) : key });
  }
  if (label.code === "undo") return t("edit.label.undo");
  return hasKey(`edit.label.${label.code}`) ? t(`edit.label.${label.code}`, label.args as Record<string, string>) : t("edit.label.edit");
}
