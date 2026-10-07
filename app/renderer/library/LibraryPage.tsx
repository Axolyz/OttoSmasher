import { SquareStack } from "lucide-react";
import { t } from "../i18n";
import s from "../shell/Shell.module.css";

/** 采样库（阶段 1：只有空状态；列表、舞台、检索从阶段 2 起实现）。 */
export function LibraryPage() {
  return (
    <div className={s.empty} data-testid="page-library">
      <SquareStack size={36} strokeWidth={1.2} />
      <h3>{t("library.empty.title")}</h3>
      <div>{t("library.empty.body")}</div>
    </div>
  );
}
