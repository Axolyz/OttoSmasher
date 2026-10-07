import { Clapperboard } from "lucide-react";
import { t } from "../i18n";
import s from "../shell/Shell.module.css";

/** 原片页（阶段 1：只有空状态；播放、台本、时间线从阶段 2 起实现）。 */
export function SourcesPage() {
  return (
    <div className={s.empty} data-testid="page-sources">
      <Clapperboard size={36} strokeWidth={1.2} />
      <h3>{t("sources.empty.title")}</h3>
      <div>{t("sources.empty.body")}</div>
    </div>
  );
}
