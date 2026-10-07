// 有序正则规则列表的编辑器（原则 P10；规格 06 §6.2.2）：从上到下试，第一条匹配生效。
// 草稿在本地编辑，「保存」才走编辑通道（可撤销）；试算框用草稿规则实时试算，命中的那一条高亮。
import { ArrowDown, ArrowUp, Plus, RotateCcw, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { CoreFailure } from "../api/core";
import { Button } from "../components/Button";
import { TextField } from "../components/Fields";
import { errorText, t } from "../i18n";
import s from "./RuleListEditor.module.css";

export interface TrialResult {
  /** 生效规则的序号（从 0 起）；没有匹配为 null */
  rule: number | null;
  timedOut: number[];
  text: ReactNode;
}

export function RuleListEditor(props: {
  label: string;
  value: string[];
  defaultValue: string[];
  onSave: (rules: string[]) => Promise<void>;
  trial: (sample: string, rules: string[]) => Promise<TrialResult>;
  sample: string;
  testId?: string;
}) {
  const [draft, setDraft] = useState<string[]>(props.value);
  const root = useRef<HTMLDivElement>(null);
  const [sample, setSample] = useState(props.sample);
  const [result, setResult] = useState<TrialResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(props.value);
  const isDefault = JSON.stringify(draft) === JSON.stringify(props.defaultValue);

  // 外部（撤销、别处修改）改了已保存的值：没在编辑时跟上
  useEffect(() => {
    setDraft(props.value);
  }, [JSON.stringify(props.value)]);

  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      props
        .trial(sample, draft)
        .then((r) => {
          if (!live) return;
          setResult(r);
          setError(null);
        })
        .catch((e) => {
          if (!live) return;
          setResult(null);
          setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
        });
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [sample, draft, props.trial]);

  const set = (i: number, v: string) => setDraft((d) => d.map((x, j) => (j === i ? v : x)));
  const move = (i: number, by: number) =>
    setDraft((d) => {
      const n = [...d];
      const [x] = n.splice(i, 1);
      n.splice(i + by, 0, x!);
      return n;
    });

  return (
    <div className={s.editor} data-testid={props.testId} ref={root} tabIndex={-1}>
      <ol className={s.rules}>
        {draft.map((rule, i) => (
          <li key={i} className={s.rule} data-hit={result?.rule === i || undefined} data-timeout={result?.timedOut.includes(i) || undefined}>
            <span className={`${s.no} num`}>{i + 1}</span>
            <TextField value={rule} onChange={(v) => set(i, v)} label={t("rules.rule", { n: i + 1 })} mono testId={`rule-${i}`} />
            <Button variant="flat" size="sm" icon={<ArrowUp size={13} />} title={t("rules.up")} isDisabled={i === 0} onPress={() => move(i, -1)} />
            <Button
              variant="flat"
              size="sm"
              icon={<ArrowDown size={13} />}
              title={t("rules.down")}
              isDisabled={i === draft.length - 1}
              onPress={() => move(i, 1)}
            />
            <Button variant="flat" size="sm" icon={<X size={13} />} title={t("rules.remove")} onPress={() => setDraft((d) => d.filter((_, j) => j !== i))} />
          </li>
        ))}
      </ol>
      <div className={s.bar}>
        <Button size="sm" icon={<Plus size={13} />} onPress={() => setDraft((d) => [...d, ""])}>
          {t("rules.add")}
        </Button>
        <Button size="sm" variant="flat" icon={<RotateCcw size={13} />} isDisabled={isDefault} onPress={() => setDraft(props.defaultValue)}>
          {t("rules.restoreDefault")}
        </Button>
        <span className={s.grow} />
        <Button size="sm" variant="flat" isDisabled={!dirty} onPress={() => setDraft(props.value)}>
          {t("rules.discard")}
        </Button>
        <Button size="sm" variant="primary" isDisabled={!dirty || error !== null} onPress={() => {
            // 保存后按钮变为不可用会丢焦点；把焦点留在编辑器里，Esc 仍能关闭设置
            root.current?.focus();
            void props.onSave(draft);
          }}
          data-testid="rules-save"
        >
          {t("common.save")}
        </Button>
      </div>
      <div className={s.trial}>
        <span className={s.trialLabel}>{t("rules.trial")}</span>
        <TextField value={sample} onChange={setSample} label={t("rules.trial")} testId="rules-sample" />
      </div>
      <div className={s.result} data-testid="rules-result" data-state={error ? "error" : result?.rule == null ? "none" : "hit"}>
        {error ? <span className={s.error}>{error}</span> : result?.text}
        {result && result.timedOut.length > 0 ? (
          <div className={s.warn}>{t("rules.timedOut", { list: result.timedOut.map((i) => i + 1).join(", ") })}</div>
        ) : null}
      </div>
      <div className={s.dialect}>{t("rules.dialect")}</div>
    </div>
  );
}
