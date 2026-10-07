// 原片页（UI_PLAN §4）：左边按作品分组的原片列表（可收起），右边查看器（画面、台本、时间线、动作条）。
// 界面状态（当前原片、展开的作品组、列表是否收起）记在 ui_state 里，重启恢复（规格 03 §3.1）。
import { Clapperboard, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AddResult, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { errorText, t } from "../i18n";
import shell from "../shell/Shell.module.css";
import { useApp } from "../state/store";
import { DeleteDialog, InputSettingsDialog } from "./SourceDialogs";
import { SourceList } from "./SourceList";
import { SourceViewer } from "./SourceViewer";
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
          onToggleGroup={(w) => setExpanded((e) => (e.includes(w) ? e.filter((x) => x !== w) : [...e, w]))}
          onChecked={setChecked}
          onAdd={() => void pickAndAdd()}
          onSettings={setSettingsFor}
          onRelocate={(id) => void relocate(id)}
          onDelete={setDeleteIds}
        />
      ) : (
        <div />
      )}
      {currentRow ? (
        <SourceViewer
          row={currentRow}
          listHidden={listHidden}
          onToggleList={() => setListHidden((v) => !v)}
          onSettings={() => setSettingsFor(currentRow.id)}
          onRelocate={() => void relocate(currentRow.id)}
          onDelete={() => setDeleteIds([currentRow.id])}
        />
      ) : (
        <div className={shell.empty}>
          <Clapperboard size={36} strokeWidth={1.2} />
          <h3>{rows && rows.length ? t("sources.pick.title") : t("sources.empty.title")}</h3>
          <div>{rows && rows.length ? t("sources.pick.body") : t("sources.empty.body")}</div>
          <Button variant="primary" icon={<Plus />} onPress={() => void pickAndAdd()} data-testid="sources-add-empty">
            {t("sources.add")}
          </Button>
        </div>
      )}
      <InputSettingsDialog sourceId={settingsFor} onClose={() => setSettingsFor(null)} onSaved={() => void reload()} />
      <DeleteDialog ids={deleteIds} rows={rows ?? []} onClose={() => setDeleteIds(null)} onDeleted={(ids) => void onDeleted(ids)} />
    </div>
  );
}
