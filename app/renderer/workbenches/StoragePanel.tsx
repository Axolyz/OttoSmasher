// 设置 → 存储与缓存（规格 13 §13.3.3–§13.3.4、16 S12.4）：按类别列出占用、可清理量、近期（15 分钟内，受保护）数量；
// 按原片列出库内持久音轨的占用；「清理缓存与闲置结果」（有任务时拒绝；可选同时清掉语音检索索引与单音指标）。
// “空闲时整理可重建缓存”的开关在下面的设置项里。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { StorageReport } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox } from "../components/Controls";
import { PagedTable } from "../components/PagedTable";
import { fileSize } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Settings.module.css";

export function StoragePanel() {
  const toast = useApp((st) => st.toast);
  const [rep, setRep] = useState<StorageReport | null>(null);
  const [derived, setDerived] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = () => void call("storage.report", {}).then(setRep, () => setRep(null));
  useEffect(load, []);
  const clean = async () => {
    setBusy(true);
    try {
      const r = await call("storage.clean", { derived });
      toast({ text: t("storage.cleaned", { n: r.files, size: fileSize(r.bytes), rows: r.rows }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
      load();
    }
  };
  if (!rep) return null;
  return (
    <div className={s.itemWide} data-testid="storage-panel">
      <div className={s.label}>{t("storage.title")}</div>
      <div className={s.hint}>{t("storage.hint")}</div>
      <PagedTable<StorageReport["categories"][number] & { id: string }>
        label={t("storage.title")}
        rows={rep.categories.map((c) => ({ ...c, id: c.key }))}
        pageSize={12}
        columns={[
          { id: "k", label: t("storage.col.category"), isRowHeader: true, render: (c) => <span title={t(`storage.cat.${c.key}.hint`)}>{t(`storage.cat.${c.key}`)}</span> },
          { id: "b", label: t("storage.col.size"), width: "90px", align: "end", render: (c) => <span className="num">{fileSize(c.bytes)}</span> },
          { id: "c", label: t("storage.col.cleanable"), width: "90px", align: "end", render: (c) => <span className="num">{c.key === "cache" || c.key === "searchIndex" ? fileSize(c.cleanable) : t("storage.never")}</span> },
          { id: "r", label: t("storage.col.recent"), width: "90px", align: "end", render: (c) => <span className="num">{c.recent || ""}</span> },
        ]}
      />
      <div className={s.storageActions}>
        <Button variant="secondary" onPress={() => void clean()} isDisabled={busy} data-testid="storage-clean">
          {t("storage.clean")}
        </Button>
        <Checkbox isSelected={derived} onChange={setDerived} label={t("storage.derived")}>
          {t("storage.derived")}
        </Checkbox>
      </div>
      {rep.lastAuto ? <div className={s.hint}>{t("storage.lastAuto", { at: new Date(rep.lastAuto * 1000).toTimeString().slice(0, 8) })}</div> : null}
      {rep.sources.length ? (
        <>
          <div className={s.label}>{t("storage.perSource")}</div>
          <PagedTable<StorageReport["sources"][number] & { id: string }>
            label={t("storage.perSource")}
            rows={rep.sources.map((r) => ({ ...r, id: r.sourceId }))}
            pageSize={8}
            columns={[
              { id: "n", label: t("storage.col.source"), isRowHeader: true, render: (r) => <span data-user-data="">{r.name}</span> },
              { id: "f", label: t("storage.col.files"), width: "70px", align: "end", render: (r) => <span className="num">{r.files}</span> },
              { id: "b", label: t("storage.col.size"), width: "90px", align: "end", render: (r) => <span className="num">{fileSize(r.bytes)}</span> },
            ]}
          />
        </>
      ) : null}
      <Callout>{t("storage.never.note")}</Callout>
    </div>
  );
}
