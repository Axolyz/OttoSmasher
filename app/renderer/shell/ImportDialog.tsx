// 导入（规格 06 §6.6、05 §5.1、ARCHITECTURE §4.10、UI_PLAN §4、§8；原型 importModal）。原片页「＋」/拖入与采样库「导入」/拖入共用这一个框：
// 选文件或整个文件夹（含子文件夹）→ 轻量任务扫描（探测、确切时长、同名画面）→ 预览数量、能匹配到画面的、读不了的（列出，不导入）
// → 作品（统一设为 / 按文件名推断，预览给出分组；所有者 2026-10-07：文件夹导入的本意是把一批归到一个作品）、类型、同名画面绑定；「直接建立全长采样」勾上才选性质（不靠文件名或音高推断）→「导入 N 个」。
// 所有者 2026-10-07：原片只有一种，两个入口唯一的区别是这个勾选的默认值（采样库勾、原片页不勾）；已登记过的文件不重复登记，勾了就再建一个全长采样。
import { useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { ImportPreview, ImportResult, JobSummary, Nature } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, ProgressBar, Segmented } from "../components/Controls";
import { TextField } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { DialogBox } from "../components/Overlay";
import { basename } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Import.module.css";

export type { ImportResult };
type Preview = ImportPreview;
const GROUPS_MAX = 6;
type Job = JobSummary;
const LIST_MAX = 20;

export function ImportDialog(props: {
  paths: string[] | null;
  /** 「直接建立全长采样」默认勾不勾：采样库 = 勾，原片页 = 不勾 */
  defaultWhole: boolean;
  defaultNature: Nature;
  onClose: () => void;
  onImported: (r: ImportResult) => void;
}) {
  const toast = useApp((st) => st.toast);
  const [job, setJob] = useState<Job | null>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [work, setWork] = useState("");
  const [workMode, setWorkMode] = useState<"unified" | "infer">("unified");
  const workTouched = useRef(false);
  const [type, setType] = useState("");
  const [nature, setNature] = useState<Nature>(props.defaultNature);
  const [bind, setBind] = useState(true);
  const [whole, setWhole] = useState(props.defaultWhole);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!props.paths) return;
    setJob(null);
    setPv(null);
    setError(null);
    setNature(props.defaultNature);
    setBind(true);
    setWhole(props.defaultWhole);
    // 作品：默认“统一设为”，预览出来后预填（推断出的同一个作品，否则文件夹名）；用户改过就不覆盖
    setWork("");
    setWorkMode("unified");
    workTouched.current = false;
    jobId.current = null;
    void call("imports.scan", { paths: props.paths })
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
      void call("imports.preview", { jobId: j.id })
        .then((p) => {
          setPv(p);
          if (!workTouched.current) setWork(p.suggestedWork);
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
      const r = await call("imports.commit", { jobId: job.id, workMode, work, sourceType: type, wholeSample: whole, nature, bindPictures: bind });
      const parts = [t("import.doneSources", { n: r.created })];
      if (whole) parts.push(t("import.doneSamples", { n: r.sampleIds.length }));
      if (r.existing) parts.push(t(whole ? "import.doneExistingWhole" : "import.doneExisting", { n: r.existing }));
      toast({ text: parts.join(t("settings.subtitle.speakerSep")) });
      for (const f of r.failed.slice(0, 3)) toast({ text: t("import.failedOne", { name: basename(f.path), error: errorText(f.error) }), tone: "error" });
      props.onImported(r);
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
          <Button
            variant="primary"
            isDisabled={!pv || !pv.importable || busy || (!whole && pv.existing === pv.importable)}
            onPress={() => void commit()}
            data-testid="import-submit"
          >
            {t("import.submit", { n: pv?.importable ?? 0 })}
          </Button>
        </>
      }
    >
      <Callout>{t("import.note")}</Callout>
      <div className={s.form}>
        <span className={s.formLabel}>{t("sources.field.work")}</span>
        <div className={s.workBox}>
          <Segmented<"unified" | "infer">
            size="sm"
            value={workMode}
            onChange={setWorkMode}
            label={t("sources.field.work")}
            testId="import-work-mode"
            options={[
              { id: "unified", label: t("import.workUnified") },
              { id: "infer", label: t("import.workInfer") },
            ]}
          />
          {workMode === "unified" ? (
            <TextField
              value={work}
              onChange={(v) => {
                workTouched.current = true;
                setWork(v);
              }}
              label={t("sources.field.work")}
              placeholder={t("import.workHint")}
              testId="import-work"
            />
          ) : null}
        </div>
        <span className={s.formLabel}>{t("sources.field.type")}</span>
        <TextField value={type} onChange={setType} label={t("sources.field.type")} placeholder={t("sources.field.typeHint")} testId="import-type" />
      </div>
      <Checkbox isSelected={whole} onChange={setWhole} label={t("import.whole")} testId="import-whole">
        {t("import.whole")}
      </Checkbox>
      {whole ? (
        <div className={s.form}>
          <span className={s.formLabel}>{t("nature.label")}</span>
          <div>
            <NaturePicker value={nature} onChange={setNature} testId="import-nature" />
          </div>
        </div>
      ) : null}
      <Checkbox isSelected={bind} onChange={setBind} label={t("import.bind")}>
        {t("import.bind")}
      </Checkbox>
      {error ? (
        <Callout tone="bad" testId="import-error">
          {error}
        </Callout>
      ) : scanning ? (
        <ProgressBar
          value={p?.total ? ((p.done ?? 0) / p.total) * 100 : null}
          max={100}
          label={t("import.scanning")}
          showValue={p?.total ? t("import.scanningN", { done: p.done, total: p.total }) : t("import.scanning")}
        />
      ) : pv ? (
        <Callout testId="import-preview">
          <div className={s.preview}>
            {t("import.previewHead")}
            <b className="num">{pv.importable}</b>
            {pv.videos ? t("import.previewFilesVideo", { n: pv.videos }) : t("import.previewFiles")}
            {bind ? (
              <>
                {" · "}
                <b className="num">{pv.withPicture}</b>
                {t("import.previewPicture")}
                {" · "}
                {t("import.previewNoPicture", { n: pv.withoutPicture })}
              </>
            ) : null}
            {pv.existing ? ` · ${t(whole ? "import.previewExisting" : "import.previewExistingSkip", { n: pv.existing })}` : ""}
            {pv.unreadable.length ? ` · ${t("import.previewUnreadable", { n: pv.unreadable.length })}` : ""}
          </div>
          <div className={s.preview} data-testid="import-groups">
            {workMode === "unified"
              ? t("import.groupsUnified", { work: work.trim() || t("sources.noWork") })
              : t("import.groupsInfer", {
                  list:
                    pv.inferredGroups
                      .slice(0, GROUPS_MAX)
                      .map(([w, n]) => t("import.groupItem", { work: w || t("sources.noWork"), n }))
                      .join(t("settings.subtitle.speakerSep")) +
                    (pv.inferredGroups.length > GROUPS_MAX ? t("import.groupsMore", { n: pv.inferredGroups.length - GROUPS_MAX }) : ""),
                })}
            {pv.existing ? ` ${t("import.existingKeepWork", { n: pv.existing })}` : ""}
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
