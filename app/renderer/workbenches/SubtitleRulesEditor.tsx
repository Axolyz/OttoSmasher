// 字幕规则编辑器（规格 06 §6.2；P10）：音效整行、注释括号、说话人提取、说话人名拆分（可空）、说话人名清理（可空）。
// 五条一起编辑、一起保存（一个编辑记录，可撤销）；草稿每次改动都交给 Core 做保存时的同样校验并试算，
// 试算框显示种类、名称、说话人、对齐文本。改规则只作用于之后导入的字幕标记。
import { RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SettingEntry } from "../api/types";
import { Button } from "../components/Button";
import { TextArea, TextField } from "../components/Fields";
import { errorText, t } from "../i18n";
import s from "./RuleListEditor.module.css";

export const SUBTITLE_RULE_KEYS = [
  "subtitle.sfx_rule",
  "subtitle.note_rule",
  "subtitle.speaker_rule",
  "subtitle.speaker_split",
  "subtitle.speaker_clean",
] as const;
type Key = (typeof SUBTITLE_RULE_KEYS)[number];
type Rules = Record<Key, string>;

interface Classified {
  kind: "line" | "sfx";
  name: string;
  speakers: string[];
  alignText: string;
}

const OPTIONAL: Partial<Record<Key, string>> = {
  "subtitle.speaker_split": "settings.subtitle.speaker_split.example",
  "subtitle.speaker_clean": "settings.subtitle.speaker_clean.example",
};

export function SubtitleRulesEditor(props: { settings: Record<string, SettingEntry>; onSave: (changed: Partial<Rules>) => Promise<void> }) {
  const saved = Object.fromEntries(SUBTITLE_RULE_KEYS.map((k) => [k, String(props.settings[k]?.value ?? "")])) as Rules;
  const defaults = Object.fromEntries(SUBTITLE_RULE_KEYS.map((k) => [k, String(props.settings[k]?.default ?? "")])) as Rules;
  const [draft, setDraft] = useState<Rules>(saved);
  const [sample, setSample] = useState(t("settings.subtitle.trialSample"));
  const [result, setResult] = useState<Classified | null>(null);
  const [error, setError] = useState<{ text: string; key: string | null } | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const savedJson = JSON.stringify(saved);
  const dirty = JSON.stringify(draft) !== savedJson;
  const isDefault = JSON.stringify(draft) === JSON.stringify(defaults);

  // 撤销或别处改了已保存的值：跟上
  useEffect(() => setDraft(saved), [savedJson]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      call<Classified>("subtitles.ruleTest", { text: sample, rules: draft })
        .then((r) => {
          if (!live) return;
          setResult(r);
          setError(null);
        })
        .catch((e) => {
          if (!live) return;
          setResult(null);
          setError(
            e instanceof CoreFailure ? { text: errorText(e.wire), key: typeof e.wire.args.setting === "string" ? e.wire.args.setting : null } : { text: String(e), key: null },
          );
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [sample, draft]);

  const save = () => {
    root.current?.focus();
    const changed: Partial<Rules> = {};
    for (const k of SUBTITLE_RULE_KEYS) if (draft[k] !== saved[k]) changed[k] = draft[k];
    void props.onSave(changed);
  };

  return (
    <div className={s.editor} ref={root} tabIndex={-1} data-testid="subtitle-rules">
      <div className={s.fields}>
        {SUBTITLE_RULE_KEYS.map((k) => (
          <div key={k} className={s.field} data-invalid={error?.key === k || undefined} data-testid={`setting-${k}`}>
            <div className={s.fieldHead}>
              <span className={s.fieldLabel}>{t(`settings.${k}.label`)}</span>
              <span className={s.fieldHint}>{t(`settings.${k}.hint`)}</span>
            </div>
            <div className={s.fieldRow}>
              <TextField
                value={draft[k]}
                onChange={(v) => setDraft((d) => ({ ...d, [k]: v }))}
                label={t(`settings.${k}.label`)}
                placeholder={OPTIONAL[k] ? t("settings.subtitle.optionalOff") : undefined}
                mono
                invalid={error?.key === k}
                testId={`rule-${k}`}
              />
              {OPTIONAL[k] ? (
                <Button size="sm" variant="flat" onPress={() => setDraft((d) => ({ ...d, [k]: t(OPTIONAL[k]!) }))} title={t("settings.subtitle.useExample")}>
                  {t("settings.subtitle.example", { pattern: t(OPTIONAL[k]!) })}
                </Button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
      <div className={s.bar}>
        <Button size="sm" variant="flat" icon={<RotateCcw size={13} />} isDisabled={isDefault} onPress={() => setDraft(defaults)}>
          {t("rules.restoreDefault")}
        </Button>
        <span className={s.grow} />
        <Button size="sm" variant="flat" isDisabled={!dirty} onPress={() => setDraft(saved)}>
          {t("rules.discard")}
        </Button>
        <Button size="sm" variant="primary" isDisabled={!dirty || error !== null} onPress={save} data-testid="subtitle-rules-save">
          {t("common.save")}
        </Button>
      </div>
      <div className={s.trial}>
        <span className={s.trialLabel}>{t("rules.trial")}</span>
        <TextArea value={sample} onChange={setSample} label={t("rules.trial")} lang="ja" testId="subtitle-trial" />
      </div>
      <div className={s.result} data-testid="subtitle-trial-result" data-state={error ? "error" : "hit"}>
        {error ? (
          <span className={s.error}>{error.text}</span>
        ) : result ? (
          <dl className={s.classified}>
            <dt>{t("settings.subtitle.kind")}</dt>
            <dd data-testid="trial-kind">{t(`subtitle.kind.${result.kind}`)}</dd>
            <dt>{t("settings.subtitle.name")}</dt>
            <dd lang="ja" data-testid="trial-name">
              {result.name || t("settings.subtitle.emptyName")}
            </dd>
            <dt>{t("settings.subtitle.speakers")}</dt>
            <dd lang="ja" data-testid="trial-speakers">
              {result.speakers.length ? result.speakers.join(t("settings.subtitle.speakerSep")) : t("settings.subtitle.none")}
              {result.speakers.length > 1 ? <span className={s.note}>{t("settings.subtitle.participants")}</span> : null}
            </dd>
            <dt>{t("settings.subtitle.alignText")}</dt>
            <dd lang="ja" className={s.pre} data-testid="trial-align">
              {result.kind === "sfx" ? t("settings.subtitle.noAlign") : result.alignText || t("settings.subtitle.none")}
            </dd>
          </dl>
        ) : null}
      </div>
      <div className={s.dialect}>{t("settings.subtitle.rulesNote")}</div>
      <div className={s.dialect}>{t("rules.dialect")}</div>
    </div>
  );
}
