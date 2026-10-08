// 拉平结果（规格 11 §11.4、§11.6、03 §3.1.3）：批量的逐条结果表（成品 / 失败原因）与「只重跑失败项」；单个的「打开结果」直接跳到成品采样。
import { useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { FlattenResultRow } from "../api/types";
import { Button } from "../components/Button";
import { PagedTable } from "../components/PagedTable";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Speech.module.css";

type Row = FlattenResultRow & { id: string };

/** 跳到成品采样（采样库），不改当前列表的排序与勾选 */
export function useOpenProduct(): (sampleId: string) => void {
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  return (id) => {
    setOpenSample(id);
    setPage("library");
    setTasksOpen(false);
  };
}

export function FlattenResults({ jobId }: { jobId: string }) {
  const toast = useApp((st) => st.toast);
  const open = useOpenProduct();
  const [rows, setRows] = useState<Row[] | null>(null);
  const load = () => void call("flatten.results", { jobId }).then((r) => setRows(r.map((x) => ({ ...x, id: String(x.idx) }))), () => setRows([]));
  useEffect(load, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("job.updated", (d) => (d as { id: string }).id === jobId && load());
  if (!rows) return null;
  const failed = rows.filter((r) => r.status === "failed").length;
  const tone = (st: Row["status"]) => (st === "ok" ? s.ok : st === "failed" ? s.bad : s.muted);
  const rerun = async () => {
    try {
      await call("flatten.rerunFailed", { jobId });
      toast({ text: t("flatten.rerunQueued", { n: failed }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  return (
    <div className={s.results} data-testid="flatten-results">
      <PagedTable
        label={t("flatten.results.col.sample")}
        rows={rows}
        pageSize={50}
        columns={[
          {
            id: "sample",
            label: t("flatten.results.col.sample"),
            isRowHeader: true,
            render: (r) =>
              r.deleted ? (
                <span className={s.muted}>{t("speech.results.deleted")}</span>
              ) : (
                <span lang="ja" data-user-data="" className={s.clamp} title={r.name ?? undefined}>
                  {r.name}
                </span>
              ),
          },
          { id: "status", label: t("speech.results.col.status"), render: (r) => <span className={tone(r.status)}>{t(`speech.results.status.${r.status}`)}</span> },
          {
            id: "product",
            label: t("flatten.results.col.product"),
            render: (r) =>
              r.productId ? (
                <Button size="sm" variant="flat" onPress={() => open(r.productId!)} data-testid="flatten-open-product">
                  {t("flatten.results.open", { note: r.target ?? "" })}
                </Button>
              ) : r.error ? (
                errorText(r.error)
              ) : (
                ""
              ),
          },
        ]}
      />
      {failed ? (
        <div>
          <Button size="sm" onPress={() => void rerun()} data-testid="flatten-rerun-failed">
            {t("flatten.results.rerun", { n: failed })}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
