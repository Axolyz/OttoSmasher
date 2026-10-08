// 语音分析结果（规格 08 §8.4；原型的结果表）：逐条列出台词、状态（成功 / 跳过·已是最新 / 失败）与原因；可勾选失败项直接再发起语音分析。
import { useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import type { SpeechResultRow } from "../api/types";
import { Button } from "../components/Button";
import { PagedTable } from "../components/PagedTable";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Speech.module.css";

type Row = SpeechResultRow & { id: string };

export function SpeechResults({ jobId }: { jobId: string }) {
  const requestSpeech = useApp((st) => st.requestSpeech);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const load = () => void call("speech.results", { jobId }).then((r) => setRows(r.map((x) => ({ ...x, id: String(x.idx) + ":" + x.status }))), () => setRows([]));
  useEffect(load, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("job.updated", (d) => (d as { id: string }).id === jobId && load());
  if (!rows) return null;
  const failed = rows.filter((r) => r.status === "failed" && !r.deleted && r.sampleId !== null);
  const tone = (st: Row["status"]) => (st === "ok" ? s.ok : st === "failed" ? s.bad : s.muted);
  return (
    <div className={s.results} data-testid="speech-results">
      <PagedTable
        label={t("speech.results.col.line")}
        rows={rows}
        pageSize={50}
        checked={checked}
        onChecked={setChecked}
        isSelectable={(r) => r.status === "failed" && !r.deleted && r.sampleId !== null}
        checkLabel={(r) => r.name ?? r.sampleId ?? ""}
        columns={[
          {
            id: "line",
            label: t("speech.results.col.line"),
            isRowHeader: true,
            render: (r) =>
              r.deleted ? (
                <span className={s.muted}>{t("speech.results.deleted")}</span>
              ) : (
                <span lang="ja" data-user-data="">
                  {r.name}
                </span>
              ),
          },
          { id: "status", label: t("speech.results.col.status"), render: (r) => <span className={tone(r.status)}>{t(`speech.results.status.${r.status}`)}</span> },
          { id: "reason", label: t("speech.results.col.reason"), render: (r) => (r.error ? errorText(r.error) : "") },
        ]}
      />
      {failed.length ? (
        <div>
          <Button
            size="sm"
            isDisabled={!checked.size}
            onPress={() => requestSpeech({ entry: "samples", ids: rows.filter((r) => checked.has(r.id) && r.sampleId).map((r) => r.sampleId!) })}
            data-testid="speech-rerun-failed"
          >
            {t("speech.results.rerun")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
