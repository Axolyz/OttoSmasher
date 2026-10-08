// 文本前端 · 用户辞典（规格 08 §8.2.4、16 R10.2；原型 settingsSheet「文本前端」）：每行「表记<Tab>片假名读音」，
// 边输入边逐行校验（报行号）；「保存并启用」= 后台编译 + 原子启用（失败时当前辞典不变；期间被别处改过就拒绝）；可撤销。
// 预览：用编辑框里的草稿辞典给一句话出音素与读音。改辞典不自动重跑已有分析。
import { useEffect, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { DictionaryCheck, JobSummary, SettingEntry } from "../api/types";
import { Button } from "../components/Button";
import { Callout } from "../components/Controls";
import { TextArea, TextField } from "../components/Fields";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Settings.module.css";

interface DictValue {
  text: string;
  compiled: string | null;
}
/** dictionary.preview 任务的结果（任务结果不在命令目录里） */
interface PreviewResult {
  phonemes: string[];
  words: Array<{ text: string; reading: string; mapped: boolean }>;
  dictionary: string;
}

const CHECK_DELAY_MS = 250;

export function DictionaryPanel(props: { entry: SettingEntry | undefined; onReload: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const saved = (props.entry?.value as DictValue | undefined) ?? { text: "", compiled: null };
  const [draft, setDraft] = useState(saved.text);
  const [check, setCheck] = useState<DictionaryCheck | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [previewJob, setPreviewJob] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [sentence, setSentence] = useState(t("dict.previewDefault"));
  const baseVersion = useRef(props.entry?.version ?? 0);

  // 设置变了（保存成功、撤销、别处修改）：编辑框没有未保存的改动就跟着更新；有改动又被别处改了就提示并载入最新的
  const lastSaved = useRef(saved.text);
  useEffect(() => {
    const v = props.entry?.version ?? 0;
    if (v === baseVersion.current) return;
    if (draft !== lastSaved.current && draft !== saved.text) toast({ text: t("dict.changedElsewhere") });
    setDraft(saved.text);
    lastSaved.current = saved.text;
    baseVersion.current = v;
  }, [props.entry?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = setTimeout(() => void call("dictionary.check", { text: draft }).then(setCheck, () => setCheck(null)), CHECK_DELAY_MS);
    return () => clearTimeout(id);
  }, [draft]);

  useCoreEvent("job.updated", (d) => {
    const j = d as JobSummary;
    if (j.status === "queued" || j.status === "running") return;
    if (j.id === saving) {
      setSaving(null);
      if (j.status === "succeeded") {
        const n = (j.result as { entries?: number } | null)?.entries ?? 0;
        toast({ text: t("dict.saved", { n }), action: { label: t("common.undo"), run: () => void undo() } });
      } else if (j.error) {
        toast({ text: errorText(j.error), tone: "error" });
      }
      props.onReload();
    }
    if (j.id === previewJob) {
      setPreviewJob(null);
      if (j.status === "succeeded") setPreview(j.result as PreviewResult);
      else if (j.error) setPreviewError(errorText(j.error));
    }
  });

  const run = async (fn: () => Promise<JobSummary>, onJob: (id: string) => void, onError: (text: string) => void) => {
    try {
      onJob((await fn()).id);
    } catch (e) {
      onError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    }
  };
  const save = () =>
    void run(
      () => call("dictionary.save", { text: draft, version: baseVersion.current }),
      setSaving,
      (text) => toast({ text, tone: "error" }),
    );
  const runPreview = () => {
    setPreview(null);
    setPreviewError(null);
    void run(() => call("dictionary.preview", { sentence, text: draft === saved.text ? null : draft }), setPreviewJob, setPreviewError);
  };

  const errors = check?.errors ?? [];
  const dirty = draft !== saved.text;
  return (
    <div className={s.itemWide} data-testid="setting-frontend.user_dictionary">
      <div className={s.label}>{t("settings.frontend.user_dictionary.label")}</div>
      <div className={s.hint}>{t("settings.frontend.user_dictionary.hint")}</div>
      <div className={s.dictBody}>
        <TextArea
          value={draft}
          onChange={setDraft}
          label={t("settings.frontend.user_dictionary.label")}
          rows={8}
          lang="ja"
          mono
          tabInserts
          invalid={errors.length > 0}
          placeholder={t("dict.placeholder")}
          testId="dict-text"
        />
        <div className={s.dictStatus}>
          <span className={errors.length ? s.bad : s.ok} data-testid="dict-status">
            {errors.length ? t("dict.errors", { n: errors.length }) : t("dict.entries", { n: check?.entries ?? 0 })}
          </span>
          <div className={s.grow} />
          <Button variant="flat" onPress={() => setDraft(saved.text)} isDisabled={!dirty || saving !== null}>
            {t("dict.revert")}
          </Button>
          <Button variant="primary" onPress={save} isDisabled={!dirty || errors.length > 0 || saving !== null} data-testid="dict-save">
            {saving ? t("dict.saving") : t("dict.save")}
          </Button>
        </div>
        {errors.length ? (
          <ul className={s.dictErrors} data-testid="dict-errors">
            {errors.slice(0, 8).map((e) => (
              <li key={e.line}>{t("dict.lineError", { line: e.line, reason: reasonText(e) })}</li>
            ))}
          </ul>
        ) : null}
        <div className={s.dictPreview}>
          <div className={s.linesField}>
            <TextField value={sentence} onChange={setSentence} label={t("dict.previewSentence")} onSubmit={runPreview} testId="dict-sentence" />
            <Button onPress={runPreview} isDisabled={previewJob !== null || !sentence.trim() || errors.length > 0} data-testid="dict-preview">
              {previewJob ? t("dict.previewing") : t("dict.preview")}
            </Button>
          </div>
          {dirty ? <div className={s.probe}>{t("dict.previewDraft")}</div> : null}
          {previewError ? <Callout tone="bad">{previewError}</Callout> : null}
          {preview ? (
            <div className={s.dictResult} data-testid="dict-result">
              <div>
                <span className={s.role}>{t("dict.previewReading")}</span>{" "}
                {preview.words.map((w, i) => (
                  <span key={i} className={w.mapped ? s.dictWord : `${s.dictWord} ${s.warn}`} title={w.mapped ? undefined : t("dict.previewUnmapped")}>
                    <span lang="ja" data-user-data="">
                      {w.text}
                    </span>
                    <span className={s.role}> · </span>
                    <span lang="ja" data-user-data="">
                      {w.reading}
                    </span>
                  </span>
                ))}
              </div>
              <div>
                <span className={s.role}>{t("dict.previewPhonemes")}</span> <span className="mono">{preview.phonemes.join(" ")}</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** 行错误的原因文字（与 Core 的错误参数同一套文案）。 */
function reasonText(e: { reason: string; first?: number; max?: number }): string {
  return t(`reason.${e.reason}`, { first: e.first ?? "", max: e.max ?? "" });
}
