// 原片的两个确认框（UI_PLAN §5）：「作品与输入设置」（规格 05 §5.2，走可撤销编辑通道）与删除原片（写清删什么、不删什么）。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { DeletePreview, IndependItem, SampleRow, SourceDetail, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { Select, TextField } from "../components/Fields";
import { ConfirmDialog } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { basename, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { displayName } from "./SourceList";
import s from "./Sources.module.css";

export function InputSettingsDialog(props: {
  sourceId: string | null;
  onClose: () => void;
  onSaved: () => void;
  /** 原片文件夹里的原片：作品只读，按钮打开该作品的「作品设置…」（阶段 3.13） */
  onWorkSettings?: (rootId: string, work: string) => void;
}) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const [d, setD] = useState<SourceDetail | null>(null);
  const [work, setWork] = useState("");
  const [episode, setEpisode] = useState("");
  const [type, setType] = useState("");
  const [subtitle, setSubtitle] = useState<string | null>(null);
  const [audio, setAudio] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setD(null);
    setError(null);
    if (!props.sourceId) return;
    void call("sources.get", { id: props.sourceId }).then((x) => {
      setD(x);
      setWork(x.work);
      setEpisode(x.episode);
      setType(x.source_type);
      setSubtitle(x.subtitle_path);
      setAudio(x.default_audio_stream);
    });
  }, [props.sourceId]);

  const save = async () => {
    if (!d) return;
    const fields: Record<string, unknown> = {};
    if (work.trim() !== d.work) fields.work = work;
    if (episode.trim() !== d.episode) fields.episode = episode;
    if (type.trim() !== d.source_type) fields.source_type = type;
    if (subtitle !== d.subtitle_path) fields.subtitle_path = subtitle;
    if (audio !== d.default_audio_stream) fields.default_audio_stream = audio;
    if (!Object.keys(fields).length) return props.onClose();
    try {
      await call("edits.apply", {
        batch: { label: { code: "source-settings", args: { name: displayName(d) } }, ops: [{ entity: "source", id: d.id, version: d.version, fields }] },
      });
      toast({ text: t("sources.settingsSaved"), action: { label: t("common.undo"), run: () => void undo() } });
      props.onSaved();
      props.onClose();
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    }
  };

  const audioStreams = (d?.streams ?? []).filter((x) => x.kind === "audio");
  return (
    <ConfirmDialog
      isOpen={!!props.sourceId}
      title={t("sources.settings")}
      confirmLabel={t("common.save")}
      confirmDisabled={!d}
      onConfirm={() => void save()}
      onClose={props.onClose}
      testId="source-settings"
    >
      {d ? (
        <div className={s.form}>
          <span className={s.formLabel}>{t("sources.field.work")}</span>
          {d.root_id ? (
            // 原片文件夹里的原片：作品跟着文件夹走，改名用「作品设置…」（会改文件夹名）
            <div className={s.inline}>
              <span className={s.muted} data-testid="field-work-follows" data-user-data="">
                {t("sources.workFollows", { name: d.work || t("sources.noWork") })}
              </span>
              {d.work && props.onWorkSettings ? (
                <Button size="sm" variant="flat" onPress={() => props.onWorkSettings!(d.root_id!, d.work)}>
                  {t("workSettings.menu")}
                </Button>
              ) : null}
            </div>
          ) : (
            <TextField value={work} onChange={setWork} label={t("sources.field.work")} testId="field-work" />
          )}
          <span className={s.formLabel}>{t("sources.field.episode")}</span>
          <TextField value={episode} onChange={setEpisode} label={t("sources.field.episode")} testId="field-episode" />
          <span className={s.formLabel}>{t("sources.field.type")}</span>
          <TextField value={type} onChange={setType} label={t("sources.field.type")} placeholder={t("sources.field.typeHint")} />
          <span className={s.formLabel}>{t("sources.field.subtitle")}</span>
          <div className={s.inline}>
            <span className={s.path} title={subtitle ?? ""}>
              {subtitle ? basename(subtitle) : t("common.none")}
            </span>
            <Button
              size="sm"
              onPress={async () => {
                const [p] = await window.otto.files.pick("subtitle");
                if (p) setSubtitle(p);
              }}
            >
              {t("sources.choose")}
            </Button>
            <Button size="sm" variant="flat" isDisabled={!subtitle} onPress={() => setSubtitle(null)}>
              {t("sources.clear")}
            </Button>
          </div>
          <span className={s.formLabel}>{t("sources.field.audio")}</span>
          <Select
            value={String(audio)}
            onChange={(v) => setAudio(Number(v))}
            label={t("sources.field.audio")}
            options={audioStreams.map((x) => ({
              id: String(x.ordinal),
              label: [t("sources.trackN", { n: x.ordinal + 1 }), x.language ?? t("sources.langUnknown"), x.title ?? x.codec ?? ""].filter(Boolean).join(" · "),
            }))}
          />
        </div>
      ) : null}
      <div>{t("sources.settingsNote")}</div>
      {error ? <div className={s.warn}>{error}</div> : null}
    </ConfirmDialog>
  );
}

export function DeleteDialog(props: { ids: string[] | null; rows: SourceRow[]; onClose: () => void; onDeleted: (ids: string[]) => void }) {
  const toast = useApp((st) => st.toast);
  const [previews, setPreviews] = useState<DeletePreview[] | null>(null);
  const [busy, setBusy] = useState(false);
  // 只删一个原片时可以先勾选要独立化的采样（规格 04 §4.8；原型 delSrcModal）
  const one = props.ids?.length === 1 ? props.rows.find((r) => r.id === props.ids![0]) ?? null : null;
  const canIndepend = !!one && one.media_state === "available";
  const [samples, setSamples] = useState<SampleRow[]>([]);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState<IndependItem[]>([]);

  useEffect(() => {
    setPreviews(null);
    setKeep(new Set());
    setQ("");
    setSamples([]);
    if (!props.ids?.length) return;
    void Promise.all(props.ids.map((id) => call("sources.deletePreview", { id })))
      .then(setPreviews)
      .catch((e) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" }));
    if (props.ids.length === 1) void call("samples.list", { sourceId: props.ids[0], limit: 500, sort: "created" }).then((r) => setSamples(r.rows), () => {});
  }, [props.ids, toast]);
  // 勾选的采样：切片大小与要不要生成画面片段
  useEffect(() => {
    if (!keep.size) return setPlan([]);
    const id = setTimeout(() => void call("samples.independPlan", { ids: [...keep] }).then(setPlan, () => {}), 150);
    return () => clearTimeout(id);
  }, [keep]);

  const sum = (k: keyof DeletePreview) => (previews ?? []).reduce((n, p) => n + (p[k] as number), 0);
  const blocked = (previews ?? []).some((p) => p.activeJobs.length > 0);
  const names = (props.ids ?? []).map((id) => props.rows.find((r) => r.id === id)).filter(Boolean) as SourceRow[];
  const released = names.some((r) => r.media_state === "released");
  const independentBefore = sum("independentSamples");
  const shown = samples.filter((r) => !q.trim() || r.name.toLowerCase().includes(q.trim().toLowerCase()));
  const bytes = plan.reduce((n, x) => n + x.bytes, 0);

  const run = async () => {
    if (!props.ids) return;
    setBusy(true);
    const done: string[] = [];
    try {
      if (canIndepend && keep.size) {
        // 先独立化（任务），完成后接着删除原片（原片保留为“媒体已释放”）
        await call("samples.independ", { ids: [...keep], deleteSource: props.ids[0] });
        toast({ text: t("indep.queuedDelete", { n: keep.size }) });
      } else {
        for (const id of props.ids) {
          await call("sources.delete", { id });
          done.push(id);
        }
        toast({ text: t("sources.deleted", { n: done.length }) });
      }
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
      props.onDeleted(done);
    }
  };

  return (
    <ConfirmDialog
      isOpen={!!props.ids?.length}
      title={names.length === 1 ? t("sources.deleteOne", { name: displayName(names[0]!) }) : t("sources.deleteN", { n: names.length })}
      confirmLabel={canIndepend && keep.size ? t("indep.andDelete", { n: keep.size }) : t("sources.delete")}
      danger
      busy={busy}
      confirmDisabled={!previews || blocked}
      onConfirm={() => void run()}
      onClose={props.onClose}
      testId="source-delete"
    >
      {previews ? (
        <>
          <div>{t("sources.deleteWill")}</div>
          <ul className={s.impact}>
            <li>{t(released ? "indep.deleteReleased" : "sources.deleteSources", { n: previews.length })}</li>
            <li>{t("sources.deleteSamples", { n: sum("samples") - (released ? 0 : independentBefore + keep.size) })}</li>
            <li>{t("sources.deleteGenerated", { n: sum("generatedAssets") })}</li>
            {released ? null : <li>{t("sources.deleteTextLayer", { n: sum("segments"), h: sum("hints"), g: sum("rangeTags"), o: sum("oped") })}</li>}
          </ul>
          <div className={s.keep}>{t("sources.deleteKeeps")}</div>
          {!released && (independentBefore || keep.size) ? (
            <div className={s.keep} data-testid="delete-release">{t("indep.releaseNote", { n: independentBefore + keep.size })}</div>
          ) : null}
          {canIndepend && samples.length ? (
            <div className={s.indepBox} data-testid="delete-independ">
              <div className={s.indepHead}>{t("indep.pickTitle")}</div>
              <div className={s.muted}>{t("indep.pickSay")}</div>
              <TextField value={q} onChange={setQ} label={t("indep.filter")} placeholder={t("indep.filter")} />
              <PagedTable<SampleRow>
                label={t("indep.pickTitle")}
                rows={shown}
                pageSize={6}
                checked={keep}
                onChecked={setKeep}
                isSelectable={(r) => !r.independent}
                checkLabel={(r) => r.name}
                columns={[
                  { id: "name", label: t("batch.col.sample"), isRowHeader: true, render: (r) => <span lang="ja" data-user-data="">{r.name}</span> },
                  { id: "dur", label: "", width: "70px", align: "end", render: (r) => <span className="num">{seconds(r.duration)}</span> },
                ]}
              />
              <div className={s.muted} data-testid="indep-size">
                {keep.size ? t("indep.size", { n: keep.size, mb: (bytes / 1048576).toFixed(1), v: plan.filter((x) => x.picture).length }) : t("indep.none")}
              </div>
            </div>
          ) : null}
          {previews.some((p) => p.activeJobs.length) ? <div className={s.warn}>{t("error.source-has-active-jobs")}</div> : null}
        </>
      ) : (
        <div>{t("common.loading")}</div>
      )}
    </ConfirmDialog>
  );
}
