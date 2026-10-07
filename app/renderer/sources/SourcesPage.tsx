// 原片页（UI_PLAN §4）：左边按作品分组的原片列表（可收起），右边查看器（画面、台本、时间线、动作条）。
// 界面状态（当前原片、展开的作品组、列表是否收起）记在 ui_state 里，重启恢复（规格 03 §3.1）。
import { Clapperboard, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AddResult, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { EmptyState } from "../components/Controls";
import { Menu, type MenuSpec } from "../components/Menu";
import { TopSlot } from "../shell/TopSlot";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { DeleteDialog, InputSettingsDialog } from "./SourceDialogs";
import { SourceList, displayName, displayTitle } from "./SourceList";
import { SourceViewer } from "./SourceViewer";
import { SubtitleBatchSheet, SubtitleImportSheet } from "./SubtitleImportSheet";
import { type IdentifyResult, OpedDialog, identifyText } from "./OpedDialog";
import { TracksDialog } from "./TracksDialog";
import { useUndo } from "../shell/useUndo";
import s from "./Sources.module.css";

export function SourcesPage() {
  const ready = useApp((st) => st.core.state === "ready");
  const page = useApp((st) => st.page);
  const toast = useApp((st) => st.toast);
  const [rows, setRows] = useState<SourceRow[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [listHidden, setListHidden] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [deleteIds, setDeleteIds] = useState<string[] | null>(null);
  const [importFor, setImportFor] = useState<SourceRow | null>(null);
  const [batchImport, setBatchImport] = useState<SourceRow[]>([]);
  const [tracksFor, setTracksFor] = useState<SourceRow | null>(null);
  const [opedFor, setOpedFor] = useState<{ row: SourceRow; initial: IdentifyResult | null } | null>(null);
  const [drop, setDrop] = useState(false);
  const restored = useRef(false);

  const reload = useCallback(async () => {
    const r = await call<SourceRow[]>("sources.list");
    setRows(r);
    return r;
  }, []);

  useEffect(() => {
    if (!ready) return;
    void (async () => {
      const r = await reload();
      const ui = await call<Record<string, unknown>>("ui.get", { page: "sources" });
      if (typeof ui.current === "string" && r.some((x) => x.id === ui.current)) setCurrent(ui.current);
      if (Array.isArray(ui.expanded)) setExpanded(ui.expanded as string[]);
      if (typeof ui.listHidden === "boolean") setListHidden(ui.listHidden);
      restored.current = true;
    })();
  }, [ready, reload]);

  const remember = (key: string, value: unknown) => {
    if (restored.current) void call("ui.set", { page: "sources", key, value });
  };
  useEffect(() => remember("current", current), [current]);
  useEffect(() => remember("expanded", expanded), [expanded]);
  useEffect(() => remember("listHidden", listHidden), [listHidden]);

  // 「返回原片」：打开该原片（区间由查看器接手）
  const jump = useApp((st) => st.sourceJump);
  useEffect(() => {
    if (!jump || !rows) return;
    const row = rows.find((r) => r.id === jump.sourceId);
    if (!row) return;
    setCurrent(row.id);
    setExpanded((e) => (e.includes(row.work) ? e : [...e, row.work]));
  }, [jump, rows]);

  const refreshTick = useApp((st) => st.refreshTick);
  useEffect(() => {
    if (refreshTick && ready) void reload();
  }, [refreshTick, ready, reload]);

  // 离开原片页清空勾选（UI_PLAN §4）
  useEffect(() => {
    if (page !== "sources") setChecked(new Set());
  }, [page]);

  // 原片列表是本页的资料：别处改了（撤销、编辑）就刷新这一页
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).source) void reload();
  });

  const open = (id: string) => {
    setCurrent(id);
    const row = rows?.find((r) => r.id === id);
    if (row && !expanded.includes(row.work)) setExpanded((e) => [...e, row.work]);
  };

  const add = async (paths: string[]) => {
    if (!paths.length) return;
    try {
      const res = await call<AddResult[]>("sources.add", { paths });
      const list = await reload();
      for (const r of res) {
        if (!r.ok && r.error) toast({ text: errorText(r.error), tone: "error" });
        if (r.inferTimedOut?.length) toast({ text: t("sources.inferTimedOut", { list: r.inferTimedOut.map((i) => i + 1).join(", ") }) });
      }
      const fresh = res.find((r) => r.ok && !r.existing);
      const first = fresh ?? res.find((r) => r.ok);
      if (first?.sourceId) {
        const row = list.find((x) => x.id === first.sourceId);
        setCurrent(first.sourceId);
        if (row && !expanded.includes(row.work)) setExpanded((e) => [...e, row.work]);
        if (fresh?.sourceId) setSettingsFor(fresh.sourceId); // 只为第一个新原片弹「作品与输入设置」
      }
      const n = res.filter((r) => r.ok && !r.existing).length;
      if (n) toast({ text: t("sources.added", { n }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const pickAndAdd = async () => add(await window.otto.files.pick("media"));
  const workspace = useApp((st) => st.hello?.workspace);
  const undo = useUndo();
  // 从字幕识别 OP/ED（规格 05 §5.6.1）：没有错误直接登记；有错误就打开 OP/ED 弹窗逐对确认
  const identifyOne = async (r: SourceRow) => {
    try {
      const res = await call<IdentifyResult>("oped.identify", { sourceId: r.id });
      if (res.errors.length) setOpedFor({ row: r, initial: res });
      toast({ text: identifyText(res), tone: res.errors.length ? "error" : "info", action: res.applied ? { label: t("common.undo"), run: () => void undo() } : undefined });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const identifyMany = async (ids: string[]) => {
    const res = await call<Array<IdentifyResult | { sourceId: string; error: { code: string; args: Record<string, unknown> } }>>("oped.identifyMany", { sourceIds: ids });
    const ok = res.filter((x): x is IdentifyResult => "pairs" in x);
    const applied = ok.reduce((a, x) => a + x.applied, 0);
    const withErrors = ok.filter((x) => x.errors.length).length;
    const skipped = res.length - ok.length;
    toast({ text: t("oped.batchDone", { n: res.length, applied, errors: withErrors, skipped }), tone: withErrors ? "error" : "info" });
  };
  // 打开库目录：工作区的素材库（导出、生成的文件都在这里）
  const openLibrary = async () => {
    if (workspace) await window.otto.files.reveal(`${workspace}/Library`);
  };

  const relocate = async (id: string) => {
    const [path] = await window.otto.files.pick("media-one");
    if (!path) return;
    try {
      const r = await call<{ streamsChanged: boolean }>("sources.relocate", { id, path });
      await reload();
      toast({ text: r.streamsChanged ? t("sources.relocatedChanged") : t("sources.relocated"), tone: r.streamsChanged ? "error" : "info" });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };

  const onDeleted = async (ids: string[]) => {
    setDeleteIds(null);
    setChecked(new Set());
    if (current && ids.includes(current)) setCurrent(null);
    await reload();
  };

  const currentRow = rows?.find((r) => r.id === current) ?? null;

  // 单个原片的菜单：列表右键、行末 ⋯、查看器 ⋯ 共用（UI_PLAN §4、§8）；多个 = 已勾选集
  const sourceMenu = (r: SourceRow, ids: string[], multi: boolean): MenuSpec =>
    multi
      ? {
          head: t("menu.checkedN", { n: ids.length }),
          items: [
            { id: "subimport", label: t("subimport.menu"), run: () => setBatchImport((rows ?? []).filter((x) => ids.includes(x.id))) },
            { id: "oped-identify", label: t("oped.menuIdentify"), run: () => void identifyMany(ids) },
            "-",
            { id: "delete", label: t("sources.delete"), danger: true, shortcut: "⌫", run: () => setDeleteIds(ids) },
          ],
        }
      : {
          head: t("menu.on", { name: displayName(r) }),
          items: [
            { id: "tracks", label: t("tracks.menu"), run: () => setTracksFor(r) },
            { id: "subimport", label: t("subimport.menu"), run: () => setImportFor(r) },
            { id: "oped-identify", label: t("oped.menuIdentify"), disabled: !r.subtitle_path, run: () => void identifyOne(r) },
            { id: "oped", label: t("oped.menu"), run: () => setOpedFor({ row: r, initial: null }) },
            "-",
            { id: "settings", label: t("sources.settings"), run: () => setSettingsFor(r.id) },
            { id: "relocate", label: t("sources.relocate"), run: () => void relocate(r.id) },
            "-",
            { id: "reveal", label: t("sources.reveal"), run: () => void window.otto.files.reveal(r.path) },
            { id: "library", label: t("sources.openLibrary"), run: () => void openLibrary() },
            "-",
            { id: "delete", label: t("sources.delete"), danger: true, shortcut: "⌫", run: () => setDeleteIds([r.id]) },
          ],
        };

  return (
    <div
      className={s.page}
      data-testid="page-sources"
      data-list-hidden={listHidden || undefined}
      data-drop={drop || undefined}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDrop(true);
        }
      }}
      onDragLeave={() => setDrop(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrop(false);
        void add([...e.dataTransfer.files].map((f) => window.otto.files.pathOf(f)).filter(Boolean));
      }}
    >
      {!listHidden ? (
        <SourceList
          rows={rows ?? []}
          current={current}
          expanded={expanded}
          checked={checked}
          onOpen={open}
          onToggleGroup={(w, o) => setExpanded((e) => ((o ?? !e.includes(w)) ? (e.includes(w) ? e : [...e, w]) : e.filter((x) => x !== w)))}
          onChecked={setChecked}
          onAdd={() => void pickAndAdd()}
          menu={sourceMenu}
          onDelete={setDeleteIds}
        />
      ) : (
        <div />
      )}
      {currentRow ? (
        <SourceViewer row={currentRow} onImportSubtitles={() => setImportFor(currentRow)} />
      ) : (
        <EmptyState
          icon={<Clapperboard />}
          title={rows && rows.length ? t("sources.pick.title") : t("sources.empty.title")}
          body={rows && rows.length ? t("sources.pick.body") : t("sources.empty.body")}
          actions={
            <Button variant="primary" icon={<Plus />} onPress={() => void pickAndAdd()} data-testid="sources-add-empty">
              {t("sources.add")}
            </Button>
          }
        />
      )}
      <TopSlot page="sources">
        <Button
          variant="flat"
          size="sm"
          icon={listHidden ? <PanelLeftOpen /> : <PanelLeftClose />}
          onPress={() => setListHidden((v) => !v)}
          data-testid="list-toggle"
        >
          {listHidden ? t("sources.showList") : t("sources.hideList")}
        </Button>
        {currentRow ? (
          <>
            <span className={s.topName} title={currentRow.path} data-user-data="">
              {displayTitle(currentRow)}
            </span>
            <Menu
              {...sourceMenu(currentRow, [currentRow.id], false)}
              trigger={<Button variant="flat" size="sm" icon={<MoreHorizontal />} aria-label={t("menu.more")} data-testid="viewer-menu" />}
            />
          </>
        ) : null}
      </TopSlot>
      <TracksDialog source={tracksFor} onClose={() => setTracksFor(null)} />
      <OpedDialog source={opedFor?.row ?? null} initial={opedFor?.initial ?? null} canPreview={opedFor?.row.id === current} onClose={() => setOpedFor(null)} />
      <SubtitleImportSheet source={importFor} onClose={() => setImportFor(null)} onDone={() => void reload()} />
      <SubtitleBatchSheet sources={batchImport} onClose={() => setBatchImport([])} onDone={() => void reload()} />
      <InputSettingsDialog sourceId={settingsFor} onClose={() => setSettingsFor(null)} onSaved={() => void reload()} />
      <DeleteDialog ids={deleteIds} rows={rows ?? []} onClose={() => setDeleteIds(null)} onDeleted={(ids) => void onDeleted(ids)} />
    </div>
  );
}
