import { Command, Ellipsis, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { EditLabel } from "../api/types";
import { Button } from "../components/Button";
import { Menu } from "../components/Menu";
import { Tip } from "../components/Overlay";
import { errorText, t } from "../i18n";
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
  const bpm = useApp((st) => st.bpm);
  const setBpm = useApp((st) => st.setBpm);
  const toast = useApp((st) => st.toast);
  const [bpmDraft, setBpmDraft] = useState("");
  useEffect(() => {
    if (ready) void call("rhythm.bpm").then((r) => setBpm(r.bpm), () => {});
  }, [ready, setBpm]);
  useEffect(() => setBpmDraft(bpm == null ? "" : String(bpm)), [bpm]);
  // 所有窗口同步（03 §3.1）
  useCoreEvent("rhythm.bpm", (d) => setBpm((d as { bpm: number | null }).bpm));
  /** 全局 BPM（03 §3.1）：20–400，留空 = 原速卡拍；改了就停止试听，卡拍方案按需重算 */
  const commitBpm = async () => {
    const text = bpmDraft.trim();
    const value = text === "" ? null : Number(text);
    if (value === bpm) return;
    if (value != null && !(Number.isFinite(value) && value >= 20 && value <= 400)) {
      toast({ text: t("error.bpm-invalid", { min: 20, max: 400 }), tone: "error" });
      setBpmDraft(bpm == null ? "" : String(bpm));
      return;
    }
    try {
      const r = await call("rhythm.setBpm", { bpm: value });
      setBpm(r.bpm);
      window.otto.player.stopAudition();
      toast({ text: r.bpm == null ? t("top.bpm.original") : t("top.bpm.changed", { bpm: r.bpm }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
      setBpmDraft(bpm == null ? "" : String(bpm));
    }
  };
  const [peek, setPeek] = useState<{ label: EditLabel } | null>(null);
  const refreshPeek = () => {
    if (ready) void call("edits.peekUndo").then(setPeek, () => setPeek(null));
  };
  useEffect(refreshPeek, [ready]);
  useCoreEvent("data.changed", refreshPeek);
  return (
    <header className={s.top}>
      <div className={s.ptitle}>{t(`nav.${page}`)}</div>
      {(["library", "sources", "tools"] as const).map((p) => (
        <TopSlotHost key={p} page={p} active={p === page} className={s.slot!} />
      ))}
      <label className={s.tempo} title={t("top.bpm.tip")}>
          <span className={s.tempoNote} aria-hidden>
            ♩
          </span>
          <input
            className="num"
            placeholder={t("top.bpm.placeholder")}
            aria-label={t("top.bpm")}
            value={bpmDraft}
            inputMode="decimal"
            disabled={!ready}
            onChange={(e) => setBpmDraft(e.target.value)}
            onBlur={() => void commitBpm()}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setBpmDraft(bpm == null ? "" : String(bpm));
                (e.target as HTMLInputElement).blur();
              }
            }}
            data-testid="bpm"
          />
          <span className={s.tempoUnit}>{t("top.bpm")}</span>
        </label>
      <Button variant="secondary" isDisabled icon={<Command />} aria-label={t("top.command")}>
        <span className={s.cmdLabel}>{t("top.command")}</span> <kbd className={s.kbd}>⌘K</kbd>
      </Button>
      <Tip content={peek ? t("top.undo.tip", { label: describeLabel(peek.label) }) : t("top.undo.none")}>
        <Button variant="flat" isDisabled={!peek} onPress={() => void undo()} icon={<Undo2 />} aria-label={t("top.undo")} data-testid="undo" />
      </Tip>
      <Menu
        trigger={<Button variant="flat" icon={<Ellipsis />} aria-label={t("top.more")} data-testid="top-more" />}
        items={[
          { id: "manage-tags", label: t("tags.manageDots"), run: () => useApp.getState().setManageTagsOpen(true) },
          "-",
          { id: "theme", label: theme === "dark" ? t("top.theme.light") : t("top.theme.dark"), run: () => setTheme(theme === "dark" ? "light" : "dark") },
          { id: "keys", label: t("shortcuts.title"), shortcut: "?", run: () => setShortcutsOpen(true) },
        ]}
      />
    </header>
  );
}
