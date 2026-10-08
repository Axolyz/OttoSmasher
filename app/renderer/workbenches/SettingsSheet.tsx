// 设置工作台（UI_PLAN §1、规格 13 §13.2）：每项写明默认值怎样生效；修改走可撤销编辑通道，只作用于之后的操作。
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { InferTest, SettingEntry } from "../api/types";
import { Button } from "../components/Button";
import { NumberField, Select, Switch, TextArea, TextField } from "../components/Fields";
import { Sheet } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { DictionaryPanel } from "./DictionaryPanel";
import { ModelsPanel } from "./ModelsPanel";
import { RoleAliasEditor } from "./RoleAliasEditor";
import { RootsPanel } from "./RootsPanel";
import { StudioPanel } from "./StudioPanel";
import { RuleListEditor, type TrialResult } from "./RuleListEditor";
import { SUBTITLE_RULE_KEYS, SubtitleRulesEditor } from "./SubtitleRulesEditor";
import s from "./Settings.module.css";

const GROUPS = ["general", "inference", "source", "subtitle", "frontend", "analysis", "flatten", "studio", "jobs", "storage", "models"] as const;
type Group = (typeof GROUPS)[number];

interface NumSpec {
  min: number;
  max?: number;
  step: number;
}
const NUMERIC: Record<string, NumSpec> = {
  "inference.directml_device": { min: 0, step: 1 },
  "subtitle.pad_before": { min: 0, max: 5, step: 0.05 },
  "subtitle.pad_after": { min: 0, max: 5, step: 0.05 },
  "analysis.tolerance_before": { min: 0, max: 5, step: 0.05 },
  "analysis.tolerance_after": { min: 0, max: 5, step: 0.05 },
  "jobs.concurrency_model": { min: 1, max: 4, step: 1 },
  "jobs.concurrency_light": { min: 1, max: 4, step: 1 },
};
const CHOICES: Record<string, string[]> = {
  "general.ui_language": ["zh-CN"],
  "source.sample_language": ["ja"],
  "studio.device": ["auto", "cpu", "cuda", "mps"],
  // 拉平各入口的默认值（03 §3.7；批量只有自动定音、没有内部拉平，Q10）
  "flatten.detail_range": ["whole", "vowels", "first", "inner"],
  "flatten.detail_target": ["auto", "edge", "manual"],
  "flatten.single_range": ["whole", "vowels", "first", "inner"],
  "flatten.single_target": ["auto", "edge", "manual"],
  "flatten.batch_range": ["whole", "vowels", "first"],
  "flatten.batch_target": ["auto", "edge"],
};
const choiceLabel = (key: string, v: string) =>
  key === "studio.device"
    ? t(`settings.studio.device.${v}`)
    : key.startsWith("flatten.")
      ? t(key.endsWith("_range") ? `flatten.range.${v}` : `flatten.target.${v}`)
      : t(`settings.lang.${v}`);
/** 文字类设置（路径、模型名）：回车或失焦保存 */
const STRINGS = new Set(["studio.app_path", "studio.data_dir", "studio.vocal_model"]);

function StringField(props: { value: string; label: string; placeholder?: string; onSave: (v: string) => void; testId: string }) {
  const [draft, setDraft] = useState(props.value);
  useEffect(() => setDraft(props.value), [props.value]);
  const commit = () => {
    if (draft.trim() !== props.value) props.onSave(draft.trim());
  };
  return (
    <div className={s.linesField} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()}>
      <TextField value={draft} onChange={setDraft} label={props.label} placeholder={props.placeholder} mono testId={props.testId} />
    </div>
  );
}

/** 字符串列表（一行一个）：OP/ED 开始/结束标记（规格 05 §5.6.1）。 */
const STRING_LISTS = new Set(["subtitle.oped_start", "subtitle.oped_end"]);

function LinesField(props: { value: string[]; label: string; onSave: (v: string[]) => void; testId: string }) {
  const text = props.value.join("\n");
  const [draft, setDraft] = useState(text);
  useEffect(() => setDraft(text), [text]);
  const lines = draft.split("\n").map((x) => x.trim()).filter(Boolean);
  return (
    <div className={s.linesField}>
      <TextArea value={draft} onChange={setDraft} label={props.label} rows={2} lang="ja" testId={props.testId} />
      <Button size="sm" variant="primary" isDisabled={draft === text || !lines.length} onPress={() => props.onSave(lines)}>
        {t("common.save")}
      </Button>
    </div>
  );
}

/** 有序正则列表类设置（P10）：整行宽的规则编辑器 + 试算框。 */
const RULE_LISTS = new Set(["source.infer_rules"]);

async function inferTrial(sample: string, rules: string[]): Promise<TrialResult> {
  const r = await call("sources.inferTest", { filename: sample, rules });
  const unknown = t("rules.unknown");
  return {
    rule: r.rule,
    timedOut: r.timedOut,
    text:
      r.rule === null
        ? t("rules.infer.none")
        : t("rules.infer.hit", { n: r.rule + 1, work: r.work ?? unknown, episode: r.episode ?? unknown }),
  };
}

function shown(key: string, v: unknown): string {
  if (Array.isArray(v)) return v.join(" / ");
  if (typeof v === "boolean") return v ? t("common.on") : t("common.off");
  if (CHOICES[key]) return choiceLabel(key, String(v));
  if (v === "") return t("settings.auto");
  return String(v);
}

export function SettingsSheet() {
  const open = useApp((st) => st.settingsOpen);
  const setOpen = useApp((st) => st.setSettingsOpen);
  const toast = useApp((st) => st.toast);
  const ready = useApp((st) => st.core.state === "ready");
  const undo = useUndo();
  const [group, setGroup] = useState<Group>("general");
  const [settings, setSettings] = useState<Record<string, SettingEntry>>({});

  const reload = useCallback(() => {
    if (ready) void call("settings.list").then(setSettings);
  }, [ready]);
  useEffect(() => {
    if (open) reload();
  }, [open, reload]);
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).setting) reload();
  });

  /** 一次保存一项或多项（字幕规则五条一起，一个编辑记录、一次撤销） */
  const saveMany = async (values: Record<string, unknown>, name: string) => {
    const keys = Object.keys(values).filter((k) => settings[k]);
    if (!keys.length) return;
    try {
      await call("edits.apply", {
        batch: {
          label: { code: "setting", args: { key: keys[0] } },
          ops: keys.map((k) => ({ entity: "setting", id: k, version: settings[k]!.version, fields: { value: values[k] } })),
        },
      });
      toast({ text: t("settings.saved", { name }), action: { label: t("common.undo"), run: () => void undo() } });
    } catch (e) {
      if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
      reload();
    }
  };
  const save = (key: string, value: unknown) => saveMany({ [key]: value }, t(`settings.${key}.label`));

  const keys = Object.keys(settings).filter((k) => settings[k]!.group === group);
  return (
    <Sheet isOpen={open} onClose={() => setOpen(false)} title={t("settings.title")}>
      <div className={s.layout}>
        <nav className={s.groups}>
          {GROUPS.map((g) => (
            <Button key={g} variant={g === group ? "secondary" : "flat"} onPress={() => setGroup(g)} data-testid={`settings-group-${g}`}>
              {t(`settings.group.${g}`)}
            </Button>
          ))}
        </nav>
        <div className={s.list}>
          {group === "source" ? <RootsPanel /> : null}
          {group === "studio" ? (
            <StudioPanel vocalModel={String(settings["studio.vocal_model"]?.value ?? "")} onVocalModel={(m) => void save("studio.vocal_model", m)} />
          ) : null}
          {group === "models" ? (
            <ModelsPanel />
          ) : (
            keys.map((key) => {
              const e = settings[key]!;
              if ((SUBTITLE_RULE_KEYS as readonly string[]).includes(key)) {
                // 五条字幕规则合成一个编辑器，放在第一条的位置
                if (key !== SUBTITLE_RULE_KEYS[0]) return null;
                return (
                  <div className={s.itemWide} key="subtitle-rules">
                    <div className={s.label}>{t("settings.subtitle.rules.label")}</div>
                    <div className={s.hint}>{t("settings.subtitle.rules.hint")}</div>
                    <SubtitleRulesEditor settings={settings} onSave={(changed) => saveMany(changed, t("settings.subtitle.rules.label"))} />
                  </div>
                );
              }
              if (key === "frontend.user_dictionary") return <DictionaryPanel key={key} entry={e} onReload={reload} />;
              if (key === "separation.role_aliases") {
                return (
                  <div className={s.itemWide} key={key} data-testid={`setting-${key}`}>
                    <div className={s.label}>{t(`settings.${key}.label`)}</div>
                    <div className={s.hint}>{t(`settings.${key}.hint`)}</div>
                    <RoleAliasEditor value={e.value as Array<[string, "vocal" | "sfx"]>} defaultValue={e.default as Array<[string, "vocal" | "sfx"]>} onSave={(v) => save(key, v)} />
                  </div>
                );
              }
              if (RULE_LISTS.has(key)) {
                return (
                  <div className={s.itemWide} key={key} data-testid={`setting-${key}`}>
                    <div className={s.label}>{t(`settings.${key}.label`)}</div>
                    <div className={s.hint}>{t(`settings.${key}.hint`)}</div>
                    <RuleListEditor
                      label={t(`settings.${key}.label`)}
                      value={e.value as string[]}
                      defaultValue={e.default as string[]}
                      onSave={(v) => save(key, v)}
                      trial={inferTrial}
                      sample={t("rules.infer.sample")}
                    />
                  </div>
                );
              }
              return (
                <div className={s.item} key={key} data-testid={`setting-${key}`}>
                  <div className={s.text}>
                    <div className={s.label}>{t(`settings.${key}.label`)}</div>
                    <div className={s.hint}>{t(`settings.${key}.hint`)}</div>
                  </div>
                  <div className={s.control}>
                    {STRINGS.has(key) ? (
                      <StringField value={String(e.value)} label={t(`settings.${key}.label`)} placeholder={t("settings.auto")} onSave={(v) => void save(key, v)} testId={`text-${key}`} />
                    ) : STRING_LISTS.has(key) ? (
                      <LinesField value={e.value as string[]} label={t(`settings.${key}.label`)} onSave={(v) => void save(key, v)} testId={`lines-${key}`} />
                    ) : typeof e.value === "boolean" ? (
                      <Switch isSelected={e.value} onChange={(v) => void save(key, v)} label={t(`settings.${key}.label`)} />
                    ) : CHOICES[key] ? (
                      <Select
                        value={String(e.value)}
                        onChange={(v) => void save(key, v)}
                        label={t(`settings.${key}.label`)}
                        options={CHOICES[key]!.map((id) => ({ id, label: choiceLabel(key, id) }))}
                      />
                    ) : (
                      <NumberField
                        value={Number(e.value)}
                        onChange={(v) => {
                          if (v !== e.value) void save(key, v);
                        }}
                        label={t(`settings.${key}.label`)}
                        minValue={NUMERIC[key]?.min}
                        maxValue={NUMERIC[key]?.max}
                        step={NUMERIC[key]?.step}
                      />
                    )}
                    <span className={s.def}>{t("common.default", { value: shown(key, e.default) })}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </Sheet>
  );
}
