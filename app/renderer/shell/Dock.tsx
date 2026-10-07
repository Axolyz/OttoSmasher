import { Play } from "lucide-react";
import { t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Shell.module.css";

/** 全局播放条（UI_PLAN §1）：阶段 1 只有空状态与“资料已更新”。 */
export function Dock() {
  const stale = useApp((st) => st.stale);
  const setStale = useApp((st) => st.setStale);
  return (
    <footer className={s.dock}>
      <div className={s.np}>
        <span className={s.pp} aria-hidden>
          <Play size={14} />
        </span>
        <span className={s.muted}>{t("dock.idle")}</span>
      </div>
      <div className={s.grow} />
      {stale ? (
        <div className={s.note}>
          {t("dock.stale")}
          <button type="button" className={s.noteBtn} onClick={() => setStale(false)}>
            {t("dock.refresh")}
          </button>
        </div>
      ) : null}
    </footer>
  );
}
