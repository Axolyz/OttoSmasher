import { Command, Ellipsis, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import type { EditLabel } from "../api/types";
import { Button } from "../components/Button";
import { Menu } from "../components/Menu";
import { Tip } from "../components/Overlay";
import { t } from "../i18n";
import { useApp } from "../state/store";
import { describeLabel } from "./labels";
import { TopSlotHost } from "./TopSlot";
import s from "./Shell.module.css";
import { useUndo } from "./useUndo";

export function TopBar() {
  const page = useApp((st) => st.page);
  const theme = useApp((st) => st.theme);
  const setTheme = useApp((st) => st.setTheme);
  const setShortcutsOpen = useApp((st) => st.setShortcutsOpen);
  const ready = useApp((st) => st.core.state === "ready");
  const undo = useUndo();
  const [peek, setPeek] = useState<{ label: EditLabel } | null>(null);
  const refreshPeek = () => {
    if (ready) void call<{ label: EditLabel } | null>("edits.peekUndo").then(setPeek, () => setPeek(null));
  };
  useEffect(refreshPeek, [ready]);
  useCoreEvent("data.changed", refreshPeek);
  return (
    <header className={s.top}>
      <div className={s.ptitle}>{t(`nav.${page}`)}</div>
      {(["library", "sources", "tools"] as const).map((p) => (
        <TopSlotHost key={p} page={p} active={p === page} className={s.slot!} />
      ))}
      <label className={s.tempo}>
        <span className={s.tempoNote} aria-hidden>
          ♩
        </span>
        <input className="num" placeholder={t("top.bpm.placeholder")} aria-label={t("top.bpm")} disabled />
        <span className={s.tempoUnit}>{t("top.bpm")}</span>
      </label>
      <Button variant="secondary" isDisabled icon={<Command />} aria-label={t("top.command")}>
        <span className={s.cmdLabel}>{t("top.command")}</span> <kbd className={s.kbd}>⌘K</kbd>
      </Button>
      <Tip content={peek ? t("top.undo.tip", { label: describeLabel(peek.label) }) : t("top.undo.none")}>
        <Button variant="flat" isDisabled={!peek} onPress={() => void undo()} icon={<Undo2 />} aria-label={t("top.undo")} data-testid="undo" />
      </Tip>
      <Menu
        trigger={<Button variant="flat" icon={<Ellipsis />} aria-label={t("top.more")} />}
        items={[
          { id: "theme", label: theme === "dark" ? t("top.theme.light") : t("top.theme.dark"), run: () => setTheme(theme === "dark" ? "light" : "dark") },
          { id: "keys", label: t("shortcuts.title"), shortcut: "?", run: () => setShortcutsOpen(true) },
        ]}
      />
    </header>
  );
}
