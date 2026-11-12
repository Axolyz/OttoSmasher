import { Command, Ellipsis, Folder, Tag, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { EditLabel } from "../api/types";
import { Button } from "../components/Button";
import { TextField } from "../components/Fields";
import { AnchoredPanel } from "../components/Panel";
import { Menu } from "../components/Menu";
import { Tip } from "../components/Overlay";
import { errorText, keys, t } from "../i18n";
import { PROJECT_NAME_LIMIT, projectTag } from "../state/project";
import { useApp } from "../state/store";
import { HistoryButton } from "./History";
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
      <WorkspaceTag />
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
      <ProjectControl ready={ready} />
      <Button variant="secondary" icon={<Command />} aria-label={t("top.command")} onPress={() => useApp.getState().setPaletteOpen(true)} data-testid="palette-open">
        <span className={s.cmdLabel}>{t("top.command")}</span> <kbd className={s.kbd}>{keys("⌘K")}</kbd>
      </Button>
      <HistoryButton />
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

function ProjectControl({ ready }: { ready: boolean }) {
  const name = useApp((st) => st.currentProject);
  const autoJoin = useApp((st) => st.projectAutoJoin);
  const [savingAutoJoin, setSavingAutoJoin] = useState(false);
  const toggleAutoJoin = async () => {
    if (!ready || !name || savingAutoJoin) return;
    const next = !autoJoin;
    setSavingAutoJoin(true);
    try {
      await call("ui.set", { page: "shell", key: "projectAutoJoin", value: next });
      useApp.getState().setProjectAutoJoin(next);
    } catch (e) {
      useApp.getState().toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setSavingAutoJoin(false);
    }
  };
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const value = draft.trim();
  const invalid = Array.from(value).length > PROJECT_NAME_LIMIT;
  const save = async () => {
    if (!ready || invalid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await call("ui.set", { page: "shell", key: "currentProject", value: value || null });
      useApp.getState().setCurrentProject(value || null);
      setOpen(false);
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setSaving(false);
    }
  };
  const tag = value && !invalid && autoJoin ? projectTag(value) : undefined;
  return (
    <div className={s.projectControls}>
      <AnchoredPanel
        title={t("project.current")}
        width={320}
        placement="bottom end"
        isOpen={open}
        onOpenChange={(next) => {
          if (next) {
            setDraft(name ?? "");
            setError(null);
          }
          setOpen(next);
        }}
        trigger={
          <Button variant="secondary" icon={<Folder />} isDisabled={!ready || name === undefined}
            aria-label={name ? t("project.active", { name }) : t("project.current")}
            title={name ? t("project.active", { name }) : t("project.current")} data-testid="current-project">
            <span className={s.projectName} data-user-data={name ? "" : undefined}>{name || t("project.none")}</span>
          </Button>
        }
        footer={<Button variant="primary" isDisabled={invalid || saving} onPress={() => void save()} data-testid="project-save">{t("common.save")}</Button>}
      >
        <TextField label={t("project.name")} value={draft} onChange={setDraft} onSubmit={() => void save()} invalid={invalid} autoFocus testId="project-name" />
        <div className={s.projectHint}>{tag ? t("project.willTag", { tag }) : t("project.hint")}</div>
        {invalid || error ? <div role="alert">{invalid ? t("project.tooLong", { max: PROJECT_NAME_LIMIT }) : error}</div> : null}
      </AnchoredPanel>
      <Tip content={t(!name ? "project.autoJoinNoProject" : autoJoin ? "project.autoJoinOn" : "project.autoJoinOff")}>
        <Button
          variant={name && autoJoin ? "primary" : "secondary"}
          icon={<Tag />}
          isDisabled={!ready || !name || savingAutoJoin}
          aria-label={t("project.autoJoin")}
          aria-pressed={!!name && autoJoin}
          onPress={() => void toggleAutoJoin()}
          data-testid="project-auto-join"
        />
      </Tip>
    </div>
  );
}

/** 当前连的工作区（两个版本都显示：开发版和发布版可能同时开着，各连各的工作区）；源码运行另标 Dev。悬停看完整路径与版本 */
function WorkspaceTag() {
  const hello = useApp((st) => st.hello);
  const dev = window.otto.app.build === "source";
  if (!hello) return null;
  const name = hello.workspace.split(/[\\/]/).filter(Boolean).pop() ?? hello.workspace;
  return (
    <span
      className={s.wsTag}
      data-testid="workspace-tag"
      title={t("top.workspace.tip", { path: hello.workspace, version: hello.version, build: t(dev ? "top.build.source" : "top.build.packaged") })}
    >
      {dev ? <span className={s.devMark}>{t("top.build.devMark")}</span> : null}
      <span data-user-data="">{name}</span>
    </span>
  );
}

