import { Button } from "../components/Button";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Shell.module.css";

/** Core 没准备好、已退出或无法启动时的横幅（ARCHITECTURE §2.3）。 */
export function CoreBanner() {
  const core = useApp((st) => st.core);
  if (core.state === "ready") return null;
  if (core.state === "starting") return <div className={s.banner}>{t("core.starting")}</div>;
  return (
    <div className={`${s.banner} ${s.bannerBad}`} role="alert">
      <span>{core.state === "fatal" ? t("core.fatal") : t("core.exited")}</span>
      {core.error ? <span className={s.muted}>{errorText(core.error)}</span> : null}
      <Button size="sm" variant="primary" onPress={() => void window.otto.core.restart()}>
        {t("common.restart")}
      </Button>
    </div>
  );
}
