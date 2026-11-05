import { AudioLines, Clapperboard, Settings, SquareStack, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { Button as RacButton } from "react-aria-components";
import { t } from "../i18n";
import logo from "../assets/logo-136.png";
import { type Page, useApp } from "../state/store";
import s from "./Shell.module.css";

function Item(props: { on?: boolean; icon: ReactNode; label: string; badge?: number; onPress: () => void; testId: string }) {
  return (
    <RacButton className={`${s.ri} ${props.on ? s.on : ""}`} onPress={props.onPress} data-testid={props.testId}>
      {props.icon}
      <span>{props.label}</span>
      {props.badge ? <span className={`${s.badge} num`}>{props.badge}</span> : null}
    </RacButton>
  );
}

export function Rail(props: { activeJobs: number }) {
  const page = useApp((st) => st.page);
  const dev = useApp((st) => st.hello?.dev ?? false);
  const setPage = useApp((st) => st.setPage);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  const setSettingsOpen = useApp((st) => st.setSettingsOpen);
  const go = (p: Page) => () => {
    setSettingsOpen(false);
    setPage(p);
  };
  return (
    <nav className={s.rail}>
      <img className={s.logo} src={logo} alt="" aria-hidden draggable={false} />
      <Item testId="nav-library" on={page === "library"} icon={<SquareStack />} label={t("nav.library")} onPress={go("library")} />
      <Item testId="nav-sources" on={page === "sources"} icon={<Clapperboard />} label={t("nav.sources")} onPress={go("sources")} />
      {dev ? <Item testId="nav-tools" on={page === "tools"} icon={<Wrench />} label={t("nav.tools")} onPress={go("tools")} /> : null}
      <div className={s.grow} />
      <Item testId="nav-tasks" icon={<AudioLines />} label={t("nav.tasks")} badge={props.activeJobs} onPress={() => setTasksOpen(true)} />
      <Item testId="nav-settings" icon={<Settings />} label={t("nav.settings")} onPress={() => setSettingsOpen(true)} />
    </nav>
  );
}
