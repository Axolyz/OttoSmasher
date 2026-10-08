// 原片页（UI_PLAN §4）：左边按作品分组的原片列表（可收起），右边查看器（画面、台本、时间线、动作条）。
// 界面状态（当前原片、展开的作品组、列表是否收起）记在 ui_state 里，重启恢复（规格 03 §3.1）。
import { Clapperboard, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { SourceRoot, SourceRow, WorkFolder } from "../api/types";
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
import { ImportDialog, type ImportResult } from "../shell/ImportDialog";
import { PrepPanel } from "./PrepPanel";
import { WholeSampleDialog } from "./WholeSampleDialog";
import { WorkSettingsDialog } from "./WorkSettingsDialog";
import { WorkTypeDialog } from "./WorkTypeDialog";
import { type SeparationInput, SeparationDialog } from "./SeparationDialog";
import { SubtitleSampleSheet } from "./SubtitleSampleSheet";
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
  const [sepInput, setSepInput] = useState<SeparationInput | null>(null);
  const [subSamples, setSubSamples] = useState<{ row: SourceRow; kind: "line" | "sfx" } | null>(null);
  const [opedFor, setOpedFor] = useState<{ row: SourceRow; initial: IdentifyResult | null } | null>(null);
  const [drop, setDrop] = useState(false);
  const restored = useRef(false);

  // 原片文件夹与作品文件夹（阶段 3.13）
  const [roots, setRoots] = useState<SourceRoot[]>([]);
  const [works, setWorks] = useState<WorkFolder[]>([]);
  const [workSettingsFor, setWorkSettingsFor] = useState<WorkFolder | null>(null);
  const reload = useCallback(async () => {
    const [r, rs, ws] = await Promise.all([call<SourceRow[]>("sources.list"), call<SourceRoot[]>("roots.list"), call<WorkFolder[]>("works.list")]);
    setRows(r);
    setRoots(rs);
    setWorks(ws);
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
    const c = d as Record<string, string[]>;
    if (c.source || c.work_folder) void reload();
  });
  // 扫描原片文件夹完成（启动时 /「重新扫描」）：提示结果；有新原片时可以一键为它们建立全长采样
  useCoreEvent("sources.scanned", (d) => {
    const r = d as { new: number; moved: number; missing: number; newIds: string[]; byWork: Array<[string, number]>; offline: string[] };
    void reload();
    if (r.offline.length) toast({ text: t("roots.offlineToast", { list: r.offline.join(t("settings.subtitle.speakerSep")) }), tone: "error" });
    if (!r.new && !r.moved) return;
    const parts: string[] = [];
    if (r.new)
      parts.push(
        t("roots.scanNew", { n: r.new }) +
          t("roots.scanByWork", { list: r.byWork.slice(0, 4).map(([w, n]) => `${w || t("sources.noWork")} ${n}`).join(t("settings.subtitle.speakerSep")) }),
      );
    if (r.moved) parts.push(t("roots.scanMoved", { n: r.moved }));
    if (r.missing) parts.push(t("roots.scanMissing", { n: r.missing }));
    toast({
      text: t("roots.scanDone", { list: parts.join(t("settings.subtitle.speakerSep")) }),
      action: r.newIds.length ? { label: t("roots.wholeForNew"), run: () => setWholeFor(r.newIds) } : undefined,
    });
  });
  const rescan = async () => {
    try {
      await call("sources.rescan");
      toast({ text: t("roots.scanning") });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  // 组头（作品）菜单：原片文件夹的作品 → 作品设置、在 Finder 中显示；所有组 → 整组导入字幕标记、建立全长采样；不在原片文件夹的 → 整组设作品与类型
  const groupMenu = (work: string): MenuSpec | null => {
    const members = (rows ?? []).filter((r) => r.work === work);
    if (!members.length) return null;
    const folder = works.find((w) => w.name === work && members.some((m) => m.root_id === w.rootId));
    const loose = members.filter((m) => !m.root_id);
    return {
      head: t("menu.on", { name: work || t("sources.noWork") }),
      items: [
        ...(folder ? [{ id: "work-settings", label: t("workSettings.menu"), run: () => setWorkSettingsFor(folder) }] : []),
        { id: "subimport", label: t("roots.groupSubimport", { n: members.length }), run: () => setBatchImport(members) },
        { id: "whole", label: t("roots.groupWhole", { n: members.length }), run: () => setWholeFor(members.map((m) => m.id)) },
        ...(loose.length ? [{ id: "work-type", label: t("workType.menuN", { n: loose.length }), run: () => setWorkTypeFor(loose) }] : []),
        { id: "check", label: t("roots.groupCheck"), run: () => setChecked(new Set(members.map((m) => m.id))) },
        ...(folder ? (["-", { id: "reveal", label: t("roots.reveal"), run: () => void window.otto.files.reveal(folder.path) }] as const) : []),
      ],
    };
  };

  const open = (id: string) => {
    setCurrent(id);
    const row = rows?.find((r) => r.id === id);
    if (row && !expanded.includes(row.work)) setExpanded((e) => [...e, row.work]);
  };

  // 添加原片 = 导入框（与采样库共用，所有者 2026-10-07）：这里进来「直接建立全长采样」默认不勾
  const [importPaths, setImportPaths] = useState<string[] | null>(null);
  const [wholeFor, setWholeFor] = useState<string[] | null>(null);
  const [workTypeFor, setWorkTypeFor] = useState<SourceRow[] | null>(null);
  const onImported = async (r: ImportResult) => {
    const list = await reload();
    const first = r.sourceIds[0];
    if (!first) return;
    const row = list.find((x) => x.id === first);
    setCurrent(first);
    if (row && !expanded.includes(row.work)) setExpanded((e) => [...e, row.work]);
    setSettingsFor(first); // 只为第一个新原片弹「作品与输入设置」（规格 03 §3.5.3）
  };
  const pickAndAdd = async () => {
    const paths = await window.otto.files.pick("import");
    if (paths.length) setImportPaths(paths);
  };
  const workspace = useApp((st) => st.hello?.workspace);
  const undo = useUndo();
  // 整片分离：输入 = 该原片的分析音轨（整轨资产）
  const separateFull = async (r: SourceRow) => {
    const list = await call<Array<{ id: string; origin: string; stream_ordinal: number | null; duration: number }>>("assets.listForSource", { sourceId: r.id });
    const a = list.find((x) => x.origin === "stream" && x.stream_ordinal === r.default_audio_stream) ?? list.find((x) => x.origin === "stream");
    if (!a) return;
    setSepInput({ assetId: a.id, trackLabel: t("sources.trackN", { n: (a.stream_ordinal ?? 0) + 1 }), duration: a.duration, selection: null, scope: "full" });
  };
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
            { id: "whole", label: t("whole.menuN", { n: ids.length }), run: () => setWholeFor(ids) },
            { id: "work-type", label: t("workType.menuN", { n: ids.length }), run: () => setWorkTypeFor((rows ?? []).filter((x) => ids.includes(x.id))) },
            "-",
            { id: "delete", label: t("sources.delete"), danger: true, shortcut: "⌫", run: () => setDeleteIds(ids) },
          ],
        }
      : {
          head: t("menu.on", { name: displayName(r) }),
          items: [
            { id: "separate", label: t("sep.menuFull"), run: () => void separateFull(r) },
            { id: "tracks", label: t("tracks.menu"), run: () => setTracksFor(r) },
            { id: "subimport", label: t("subimport.menu"), run: () => setImportFor(r) },
            { id: "subsample-line", label: t("subsample.menuLine"), run: () => setSubSamples({ row: r, kind: "line" }) },
            { id: "subsample-sfx", label: t("subsample.menuSfx"), run: () => setSubSamples({ row: r, kind: "sfx" }) },
            { id: "oped-identify", label: t("oped.menuIdentify"), disabled: !r.subtitle_path, run: () => void identifyOne(r) },
            { id: "oped", label: t("oped.menu"), run: () => setOpedFor({ row: r, initial: null }) },
            { id: "whole", label: t("whole.menu"), run: () => setWholeFor([r.id]) },
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
        const paths = [...e.dataTransfer.files].map((f) => window.otto.files.pathOf(f)).filter(Boolean);
        if (paths.length) setImportPaths(paths);
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
          onRescan={roots.length ? () => void rescan() : null}
          menu={sourceMenu}
          groupMenu={groupMenu}
          onDelete={setDeleteIds}
        />
      ) : (
        <div />
      )}
      {currentRow ? (
        <SourceViewer row={currentRow} onImportSubtitles={() => setImportFor(currentRow)} onSeparate={setSepInput} />
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
            <PrepPanel
              source={currentRow}
              onAction={(a) => {
                if (a === "subimport") setImportFor(currentRow);
                else if (a === "separate") void separateFull(currentRow);
                else if (a === "tracks") setTracksFor(currentRow);
                else if (a === "oped") setOpedFor({ row: currentRow, initial: null });
                else setSubSamples({ row: currentRow, kind: "line" });
              }}
            />
            <Menu
              {...sourceMenu(currentRow, [currentRow.id], false)}
              trigger={<Button variant="flat" size="sm" icon={<MoreHorizontal />} aria-label={t("menu.more")} data-testid="viewer-menu" />}
            />
          </>
        ) : null}
      </TopSlot>
      <SubtitleSampleSheet source={subSamples?.row ?? null} kind={subSamples?.kind ?? "line"} onClose={() => setSubSamples(null)} />
      <SeparationDialog input={sepInput} onClose={() => setSepInput(null)} />
      <TracksDialog source={tracksFor} onClose={() => setTracksFor(null)} />
      <OpedDialog source={opedFor?.row ?? null} initial={opedFor?.initial ?? null} canPreview={opedFor?.row.id === current} onClose={() => setOpedFor(null)} />
      <SubtitleImportSheet source={importFor} onClose={() => setImportFor(null)} onDone={() => void reload()} />
      <SubtitleBatchSheet sources={batchImport} onClose={() => setBatchImport([])} onDone={() => void reload()} />
      <ImportDialog paths={importPaths} defaultWhole={false} defaultNature="unclassified" onClose={() => setImportPaths(null)} onImported={(r) => void onImported(r)} />
      <WholeSampleDialog ids={wholeFor} onClose={() => setWholeFor(null)} />
      <WorkTypeDialog rows={workTypeFor} onClose={() => setWorkTypeFor(null)} onDone={() => void reload()} />
      <InputSettingsDialog
        sourceId={settingsFor}
        onClose={() => setSettingsFor(null)}
        onSaved={() => void reload()}
        onWorkSettings={(rootId, work) => {
          const f = works.find((w) => w.rootId === rootId && w.name === work);
          if (f) {
            setSettingsFor(null);
            setWorkSettingsFor(f);
          }
        }}
      />
      <WorkSettingsDialog
        folder={workSettingsFor}
        onClose={() => setWorkSettingsFor(null)}
        onDone={() => void reload()}
        onRenamed={(from, to) => setExpanded((e) => (e.includes(from) ? [...e.filter((x) => x !== from), to] : e))}
      />
      <DeleteDialog ids={deleteIds} rows={rows ?? []} onClose={() => setDeleteIds(null)} onDeleted={(ids) => void onDeleted(ids)} />
    </div>
  );
}
