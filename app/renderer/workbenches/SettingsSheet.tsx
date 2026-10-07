// 设置工作台（UI_PLAN §1、规格 13 §13.2）：每项写明默认值怎样生效；修改走可撤销编辑通道，只作用于之后的操作。
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { SettingEntry } from "../api/types";
import { Button } from "../components/Button";
import { NumberField, Select, Switch } from "../components/Fields";
import { Sheet } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { ModelsPanel } from "./ModelsPanel";
import { RuleListEditor, type TrialResult } from "./RuleListEditor";
import s from "./Settings.module.css";

const GROUPS = ["general", "inference", "source", "subtitle", "analysis", "jobs", "storage", "models"] as const;
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
};

/** 有序正则列表类设置（P10）：整行宽的规则编辑器 + 试算框。 */
const RULE_LISTS = new Set(["source.infer_rules"]);

interface InferTest {
  work: string | null;
  episode: string | null;
  rule: number | null;
  timedOut: number[];
}

async function inferTrial(sample: string, rules: string[]): Promise<TrialResult> {
  const r = await call<InferTest>("sources.inferTest", { filename: sample, rules });
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
  if (typeof v === "boolean") return v ? t("common.on") : t("common.off");
  if (CHOICES[key]) return t(`settings.lang.${String(v)}`);
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
    if (ready) void call<Record<string, SettingEntry>>("settings.list").then(setSettings);
  }, [ready]);
  useEffect(() => {
    if (open) reload();
  }, [open, reload]);
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).setting) reload();
  });

  const save = async (key: string, value: unknown) => {
    const cur = settings[key];
    if (!cur) return;
    try {
      await call("edits.apply", {
        batch: { label: { code: "setting", args: { key } }, ops: [{ entity: "setting", id: key, version: cur.version, fields: { value } }] },
      });
      toast({ text: t("settings.saved", { name: t(`settings.${key}.label`) }), action: { label: t("common.undo"), run: () => void undo() } });
    } catch (e) {
      if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
      reload();
    }
  };

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
          {group === "models" ? (
            <ModelsPanel />
          ) : (
            keys.map((key) => {
              const e = settings[key]!;
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
                    {typeof e.value === "boolean" ? (
                      <Switch isSelected={e.value} onChange={(v) => void save(key, v)} label={t(`settings.${key}.label`)} />
                    ) : CHOICES[key] ? (
                      <Select
                        value={String(e.value)}
                        onChange={(v) => void save(key, v)}
                        label={t(`settings.${key}.label`)}
                        options={CHOICES[key]!.map((id) => ({ id, label: t(`settings.lang.${id}`) }))}
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
