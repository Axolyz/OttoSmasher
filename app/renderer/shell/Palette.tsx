// 命令面板（⌘K，所有者 2026-10-10：简单版、按业务来）：
// - 最上面是“作用于”当前对象的命令——采样库：已勾选集，没有勾选就是当前查看的采样；原片页：已勾选的原片，没有勾选就是当前原片。
//   这一组就是右键菜单本身（同一份菜单项），所以面板与右键同源；
// - 然后是当前页的常用动作（检索、用途视图、筛选器、导入、添加原片…），最后是全局（切页、撤销、任务、设置各组、管理标签、BPM、主题）；
// - 输入数字（20–400）直接给“BPM 设为 N”；最近用过的 5 条在空输入时排最上面（重启恢复）。
import { useEffect, useMemo, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { EditLabel } from "../api/types";
import { CommandPalette, type PaletteCommand, type PaletteSection } from "../components/CommandPalette";
import { errorText, t } from "../i18n";
import { collectCommands, useCommands } from "../state/commands";
import { type Page, useApp, visiblePages } from "../state/store";
import { SETTINGS_GROUPS } from "../workbenches/SettingsSheet";
import { describeLabel } from "./labels";
import { useUndo } from "./useUndo";

const RECENT = 5;

async function setBpm(value: number | null): Promise<void> {
  const st = useApp.getState();
  try {
    const r = await call("rhythm.setBpm", { bpm: value });
    st.setBpm(r.bpm);
    window.otto.player.stopAudition();
    st.toast({ text: r.bpm == null ? t("top.bpm.original") : t("top.bpm.changed", { bpm: r.bpm }) });
  } catch (e) {
    st.toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  }
}

/** 输入是 20–400 的数（可带“bpm”）→ “BPM 设为 N” */
function bpmCommand(query: string): PaletteCommand[] {
  const m = /^\s*(?:bpm\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:bpm)?\s*$/i.exec(query);
  if (!m) return [];
  const v = Number(m[1]);
  if (!(v >= 20 && v <= 400)) return [];
  return [{ key: "global/bpm-set", label: t("cmd.bpmSet", { bpm: v }), group: t("cmd.group.global"), run: () => void setBpm(v) }];
}

/** 全局命令（任何页都有）。撤销那一条在面板打开时现查“最近一次资料修改”。 */
function useGlobalCommands(peek: EditLabel | null) {
  const undo = useUndo();
  useCommands("global", null, () => {
    const st = useApp.getState();
    const g = t("cmd.group.global");
    const go = (p: Page) => () => {
      st.setSettingsOpen(false);
      st.setPage(p);
    };
    const items: PaletteCommand[] = [
      ...visiblePages(st.hello?.dev ?? false).map((p, i) => ({ key: `global/page-${p}`, label: t("cmd.goto", { page: t(`nav.${p}`) }), group: g, shortcut: `⌘${i + 1}`, disabled: st.page === p && !st.settingsOpen, run: go(p) })),
      {
        key: "global/undo",
        label: peek ? t("top.undo.tip", { label: describeLabel(peek) }) : t("top.undo.none"),
        group: g,
        shortcut: "⌘Z",
        disabled: !peek,
        keywords: t("shortcuts.undo"),
        run: () => void undo(),
      },
      { key: "global/tasks", label: t("cmd.tasks"), group: g, shortcut: "⌘J", run: () => st.setTasksOpen(true) },
      { key: "global/refresh", label: t("dock.refresh"), group: g, run: () => st.refreshLists() },
      { key: "global/manage-tags", label: t("tags.manageDots"), group: g, run: () => st.setManageTagsOpen(true) },
      { key: "global/bpm-original", label: t("cmd.bpmOriginal"), group: g, disabled: st.bpm == null, keywords: "bpm", run: () => void setBpm(null) },
      { key: "global/settings", label: t("settings.title"), group: g, shortcut: "⌘,", run: () => st.openSettings() },
      ...SETTINGS_GROUPS.map((k) => ({
        key: `global/settings-${k}`,
        label: `${t("settings.title")} › ${t(`settings.group.${k}`)}`,
        group: g,
        keywords: k === "frontend" ? t("cmd.kw.dictionary") : undefined,
        run: () => st.openSettings(k),
      })),
      { key: "global/theme", label: t("cmd.theme", { name: st.theme === "dark" ? t("top.theme.light") : t("top.theme.dark") }), group: g, run: () => st.setTheme(st.theme === "dark" ? "light" : "dark") },
      { key: "global/keys", label: t("shortcuts.title"), group: g, shortcut: "?", run: () => st.setShortcutsOpen(true) },
    ];
    return [{ id: "global", title: g, items }];
  });
}

export function Palette() {
  const open = useApp((st) => st.paletteOpen);
  const setOpen = useApp((st) => st.setPaletteOpen);
  const page = useApp((st) => st.page);
  const ready = useApp((st) => st.core.state === "ready");
  const [peek, setPeek] = useState<EditLabel | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [sections, setSections] = useState<PaletteSection[]>([]);
  useGlobalCommands(peek);

  useEffect(() => {
    if (ready) void call("ui.get", { page: "shell" }).then((v) => Array.isArray(v.recentCommands) && setRecent(v.recentCommands.filter((x): x is string => typeof x === "string")), () => {});
  }, [ready]);
  // 打开时现取：最近一次资料修改，再收集各来源的命令
  useEffect(() => {
    if (!open) return;
    let live = true;
    void call("edits.peekUndo").then(
      (p) => live && setPeek(p ? p.label : null),
      () => live && setPeek(null),
    );
    return () => {
      live = false;
    };
  }, [open]);
  useEffect(() => {
    if (open) setSections(collectCommands(page));
  }, [open, page, peek]);

  const shown = useMemo(() => {
    const all = new Map(sections.flatMap((x) => x.items).map((c) => [c.key, c]));
    const rec = recent.map((k) => all.get(k)).filter((c): c is PaletteCommand => !!c && !c.disabled);
    return rec.length ? [{ id: "recent", title: t("cmd.group.recent"), items: rec }, ...sections] : sections;
  }, [sections, recent]);

  const remember = (c: PaletteCommand) => {
    if (c.key === "global/bpm-set") return;
    const next = [c.key, ...recent.filter((k) => k !== c.key)].slice(0, RECENT);
    setRecent(next);
    void call("ui.set", { page: "shell", key: "recentCommands", value: next }).catch(() => {});
  };

  return (
    <CommandPalette
      isOpen={open}
      onClose={() => setOpen(false)}
      sections={shown}
      extra={bpmCommand}
      onRun={remember}
      label={t("top.command")}
      placeholder={t("cmd.placeholder")}
      empty={t("cmd.empty")}
    />
  );
}
