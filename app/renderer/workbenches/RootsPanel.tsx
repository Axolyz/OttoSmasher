// 设置「原片」组顶部：原片文件夹（阶段 3.13，所有者 2026-10-07）。可以有多个（本机一个、外置盘一个）。
// 第一层子文件夹 = 作品；启动时与「重新扫描」时登记新文件、认出移动/改名的文件。整个文件夹搬了家 →「更换位置…」按相对路径全部找回。
// 「不再作为原片文件夹」：原片照旧（作品名保留，之后可在应用里改），只去掉文件夹关系。
import { FolderPlus, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { SourceRoot } from "../api/types";
import { Button } from "../components/Button";
import { Callout, EmptyState } from "../components/Controls";
import { ConfirmDialog } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Settings.module.css";

export function RootsPanel() {
  const toast = useApp((st) => st.toast);
  const [roots, setRoots] = useState<SourceRoot[]>([]);
  const [removing, setRemoving] = useState<SourceRoot | null>(null);
  const reload = useCallback(() => void call<SourceRoot[]>("roots.list").then(setRoots), []);
  useEffect(reload, [reload]);
  useCoreEvent("sources.scanned", reload);
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).source) reload();
  });

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    try {
      await fn();
      if (done) toast({ text: done });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
    reload();
  };
  const add = async () => {
    const [p] = await window.otto.files.pick("folder");
    if (p) void run(() => call("roots.add", { path: p }), t("roots.added"));
  };
  const relocate = async (r: SourceRoot) => {
    const [p] = await window.otto.files.pick("folder");
    if (p) void run(() => call("roots.relocate", { id: r.id, path: p }), t("roots.relocated"));
  };

  return (
    <div className={s.itemWide} data-testid="roots-panel">
      <div className={s.label}>{t("roots.title")}</div>
      <div className={s.hint}>{t("roots.hint")}</div>
      {roots.length ? (
        <div className={s.rootList}>
          {roots.map((r) => (
            <div key={r.id} className={s.rootRow} data-testid="root-row">
              <span className={`${s.rootPath} mono`} title={r.path} data-user-data="">
                {r.path}
              </span>
              <span className={s.rootMeta}>
                {r.online ? t("roots.counts", { works: r.works, sources: r.sources }) : <span className={s.warn}>{t("roots.offline")}</span>}
              </span>
              <Button size="sm" variant="flat" onPress={() => void relocate(r)}>
                {t("roots.relocate")}
              </Button>
              <Button size="sm" variant="flat" onPress={() => setRemoving(r)}>
                {t("roots.remove")}
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState size="inline" title={t("roots.none")} />
      )}
      <div className={s.rootActions}>
        <Button size="sm" icon={<FolderPlus />} onPress={() => void add()} data-testid="roots-add">
          {t("roots.add")}
        </Button>
        <Button size="sm" variant="flat" icon={<RefreshCw />} isDisabled={!roots.length} onPress={() => void run(() => call("sources.rescan"), t("roots.scanning"))}>
          {t("roots.rescan")}
        </Button>
      </div>
      <ConfirmDialog
        isOpen={!!removing}
        title={t("roots.removeTitle")}
        confirmLabel={t("roots.remove")}
        onConfirm={() => {
          const r = removing!;
          setRemoving(null);
          void run(() => call("roots.remove", { id: r.id }), t("roots.removed"));
        }}
        onClose={() => setRemoving(null)}
        testId="roots-remove"
      >
        <Callout>{t("roots.removeNote", { path: removing?.path ?? "" })}</Callout>
      </ConfirmDialog>
    </div>
  );
}
