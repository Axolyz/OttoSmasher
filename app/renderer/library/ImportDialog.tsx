// 导入独立采样（规格 06 §6.6、ARCHITECTURE §4.10、UI_PLAN §8；原型 importModal）：
// 选文件或整个文件夹（含子文件夹）/ 拖进采样库 → 轻量任务扫描（探测、确切时长、同名画面）→ 预览数量、能匹配到画面的、读不了的（列出，不导入）
// → 一次设作品、类型、性质（默认 = 当前用途，否则未分类；不靠文件名或音高推断）→「导入 N 个」：每个文件一个原片 + 整段一个采样，已登记的跳过。
import { useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { Nature } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, ProgressBar } from "../components/Controls";
import { TextField } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { DialogBox } from "../components/Overlay";
import { basename } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Library.module.css";

interface Preview {
  total: number;
  importable: number;
  existing: number;
  withPicture: number;
  withoutPicture: number;
  unreadable: Array<{ path: string; error: { code: string; args: Record<string, unknown> } }>;
  conflicts: Array<{ path: string; picture: string; others: string[] }>;
  roots: string[];
}
interface Job {
  id: string;
  status: string;
  progress: { done: number; total: number; percent?: number } | null;
  error: { code: string; args: Record<string, unknown> } | null;
}
const LIST_MAX = 20;

export function ImportDialog(props: { paths: string[] | null; defaultNature: Nature; onClose: () => void; onImported: (sampleIds: string[]) => void }) {
  const toast = useApp((st) => st.toast);
  const [job, setJob] = useState<Job | null>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [work, setWork] = useState("");
  const [type, setType] = useState("");
  const [nature, setNature] = useState<Nature>(props.defaultNature);
  const [bind, setBind] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!props.paths) return;
    setJob(null);
    setPv(null);
    setError(null);
    setNature(props.defaultNature);
    setBind(true);
    // 作品默认取所选文件夹名（只选了一个文件夹时）
    setWork(props.paths.length === 1 ? basename(props.paths[0]!) : "");
    jobId.current = null;
    void call<Job>("imports.scan", { paths: props.paths })
      .then((j) => {
        jobId.current = j.id;
        onJob(seen.current.get(j.id) ?? j);
      })
      .catch((e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)));
  }, [props.paths]); // eslint-disable-line react-hooks/exhaustive-deps

  // 任务事件可能比 imports.scan 的返回先到：先记下来，拿到任务 ID 后补处理
  const seen = useRef(new Map<string, Job>());
  const jobId = useRef<string | null>(null);
  const onJob = (j: Job) => {
    setJob(j);
    if (j.status === "succeeded") {
      void call<Preview>("imports.preview", { jobId: j.id })
        .then((p) => {
          setPv(p);
          // 选的是文件（不是一个文件夹）、作品还空着：用它们所在的文件夹名
          if (p.roots.length === 1 && props.paths?.length !== 1) setWork((w) => w || basename(p.roots[0]!));
        })
        .catch((e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)));
    } else if (j.status === "failed" && j.error) setError(errorText(j.error));
    else if (j.status === "cancelled") setError(t("import.cancelled"));
  };
  useCoreEvent("job.updated", (d) => {
    const j = d as Job;
    seen.current.set(j.id, j);
    if (j.id === jobId.current) onJob(j);
  });

  const commit = async () => {
    if (!job || !pv || busy) return;
    setBusy(true);
    try {
      const r = await call<{ created: number; skipped: number; failed: Array<{ path: string; error: { code: string; args: Record<string, unknown> } }>; sampleIds: string[] }>(
        "imports.commit",
        { jobId: job.id, work, sourceType: type, nature, bindPictures: bind },
      );
      toast({ text: r.skipped ? t("import.doneSkipped", { n: r.created, k: r.skipped }) : t("import.done", { n: r.created }) });
      for (const f of r.failed.slice(0, 3)) toast({ text: t("import.failedOne", { name: basename(f.path), error: errorText(f.error) }), tone: "error" });
      props.onImported(r.sampleIds);
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const scanning = !pv && !error;
  const p = job?.progress;
  return (
    <DialogBox
      isOpen={props.paths != null}
      onClose={props.onClose}
      title={t("import.title")}
      sub={t("import.sub")}
      width={620}
      testId="import-dialog"
      footer={
        <>
          <span className={s.footNote}>{t("import.footer")}</span>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!pv || !pv.importable || busy} onPress={() => void commit()} data-testid="import-submit">
            {t("import.submit", { n: pv?.importable ?? 0 })}
          </Button>
        </>
      }
    >
      <Callout>{t("import.note")}</Callout>
      <div className={s.form}>
        <span className={s.formLabel}>{t("sources.field.work")}</span>
        <TextField value={work} onChange={setWork} label={t("sources.field.work")} placeholder={t("import.workHint")} testId="import-work" />
        <span className={s.formLabel}>{t("sources.field.type")}</span>
        <TextField value={type} onChange={setType} label={t("sources.field.type")} placeholder={t("sources.field.typeHint")} testId="import-type" />
        <span className={s.formLabel}>{t("nature.label")}</span>
        <div>
          <NaturePicker value={nature} onChange={setNature} testId="import-nature" />
        </div>
      </div>
      <Checkbox isSelected={bind} onChange={setBind} label={t("import.bind")}>
        {t("import.bind")}
      </Checkbox>
      {error ? (
        <Callout tone="bad" testId="import-error">
          {error}
        </Callout>
      ) : scanning ? (
        <ProgressBar
          value={p?.total ? (p.done / p.total) * 100 : null}
          max={100}
          label={t("import.scanning")}
          showValue={p?.total ? t("import.scanningN", { done: p.done, total: p.total }) : t("import.scanning")}
        />
      ) : pv ? (
        <Callout testId="import-preview">
          <div className={s.preview}>
            {t("import.previewHead")}
            <b className="num">{pv.importable}</b>
            {t("import.previewAudio")}
            {bind ? (
              <>
                {" · "}
                <b className="num">{pv.withPicture}</b>
                {t("import.previewPicture")}
                {" · "}
                {t("import.previewNoPicture", { n: pv.withoutPicture })}
              </>
            ) : null}
            {pv.existing ? ` · ${t("import.previewExisting", { n: pv.existing })}` : ""}
            {pv.unreadable.length ? ` · ${t("import.previewUnreadable", { n: pv.unreadable.length })}` : ""}
          </div>
          {pv.unreadable.length ? (
            <ul className={s.fileList} data-testid="import-unreadable">
              {pv.unreadable.slice(0, LIST_MAX).map((u) => (
                <li key={u.path} title={errorText(u.error)} data-user-data="">
                  {basename(u.path)}
                </li>
              ))}
              {pv.unreadable.length > LIST_MAX ? <li>{t("import.andMore", { n: pv.unreadable.length - LIST_MAX })}</li> : null}
            </ul>
          ) : null}
          {bind && pv.conflicts.length ? (
            <>
              <div>{t("import.conflicts", { n: pv.conflicts.length })}</div>
              <ul className={s.fileList} data-testid="import-conflicts">
                {pv.conflicts.slice(0, LIST_MAX).map((c) => (
                  <li key={c.path} title={c.others.join("\n")} data-user-data="">
                    {t("import.conflictOne", { name: basename(c.path), picture: basename(c.picture), n: c.others.length })}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </Callout>
      ) : null}
    </DialogBox>
  );
}
