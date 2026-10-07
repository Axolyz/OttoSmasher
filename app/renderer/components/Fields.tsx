// 输入件：开关、数字输入、文字输入、选择框（React Aria）。
import { Check, ChevronDown, Minus, Plus } from "lucide-react";
import {
  Button as RacButton,
  Group,
  Input,
  ListBox,
  ListBoxItem,
  NumberField as RacNumberField,
  Popover,
  Select as RacSelect,
  SelectValue,
  Switch as RacSwitch,
  TextArea as RacTextArea,
  TextField as RacTextField,
} from "react-aria-components";
import { useEffect, useState } from "react";
import { clock, parseClock } from "../format";
import s from "./Fields.module.css";

export function Switch(props: { isSelected: boolean; onChange: (v: boolean) => void; label: string; isDisabled?: boolean }) {
  return (
    <RacSwitch isSelected={props.isSelected} onChange={props.onChange} isDisabled={props.isDisabled} className={s.switch} aria-label={props.label}>
      <span className={s.track}>
        <span className={s.thumb} />
      </span>
    </RacSwitch>
  );
}

export function NumberField(props: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  minValue?: number;
  maxValue?: number;
  step?: number;
  isDisabled?: boolean;
}) {
  return (
    <RacNumberField
      value={props.value}
      onChange={(v) => {
        if (!Number.isNaN(v)) props.onChange(v);
      }}
      minValue={props.minValue}
      maxValue={props.maxValue}
      step={props.step}
      isDisabled={props.isDisabled}
      aria-label={props.label}
      formatOptions={{ useGrouping: false, maximumFractionDigits: 3 }}
      className={s.number}
    >
      <Group className={s.numberGroup}>
        <RacButton slot="decrement" className={s.stepBtn}>
          <Minus size={12} />
        </RacButton>
        <Input className={`${s.numberInput} num`} />
        <RacButton slot="increment" className={s.stepBtn}>
          <Plus size={12} />
        </RacButton>
      </Group>
    </RacNumberField>
  );
}

export function TextField(props: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  placeholder?: string;
  mono?: boolean;
  invalid?: boolean;
  isDisabled?: boolean;
  testId?: string;
}) {
  return (
    <RacTextField
      value={props.value}
      onChange={props.onChange}
      aria-label={props.label}
      isDisabled={props.isDisabled}
      isInvalid={props.invalid}
      className={s.text}
    >
      <Input
        className={`${s.textInput} ${props.mono ? "mono" : ""}`}
        placeholder={props.placeholder}
        spellCheck={false}
        autoComplete="off"
        data-testid={props.testId}
      />
    </RacTextField>
  );
}

export interface Option {
  id: string;
  label: string;
}

export function Select(props: { value: string; onChange: (v: string) => void; options: Option[]; label: string; isDisabled?: boolean; prefix?: string }) {
  return (
    <RacSelect
      selectedKey={props.value}
      onSelectionChange={(k) => props.onChange(String(k))}
      isDisabled={props.isDisabled}
      aria-label={props.label}
      className={s.select}
    >
      <RacButton className={s.selectBtn}>
        {props.prefix ? <span className={s.selectPrefix}>{props.prefix}</span> : null}
        <SelectValue className={s.selectValue} />
        <ChevronDown size={14} />
      </RacButton>
      <Popover className={s.popover} offset={4}>
        <ListBox className={s.listbox} items={props.options}>
          {(o) => (
            <ListBoxItem id={o.id} className={s.option} textValue={o.label}>
              {({ isSelected }) => (
                <>
                  <span>{o.label}</span>
                  {isSelected ? <Check size={13} /> : null}
                </>
              )}
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </RacSelect>
  );
}

/**
 * 时间输入（选区起止的精确输入，UI_PLAN §3 动作条）：显示 `M:SS.mmm`；Enter / 失焦提交，Esc 还原。
 * 解析不了或 onCommit 拒绝（返回 false，例如越界、起点不在终点之前）时标红并还原为原值。
 */
export function TimeField(props: { value: number | null; onCommit: (v: number) => boolean; label: string; isDisabled?: boolean; testId?: string }) {
  const shown = props.value == null ? "" : clock(props.value);
  const [text, setText] = useState(shown);
  const [bad, setBad] = useState(false);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) setText(shown);
  }, [shown, editing]);
  const commit = () => {
    setEditing(false);
    if (text === shown) return setBad(false);
    const v = parseClock(text);
    const ok = v != null && props.onCommit(v);
    setBad(!ok);
    if (!ok) setText(shown);
  };
  return (
    <RacTextField
      value={text}
      onChange={(v) => {
        setEditing(true);
        setText(v);
      }}
      aria-label={props.label}
      isDisabled={props.isDisabled}
      isInvalid={bad}
      className={s.time}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        else if (e.key === "Escape" && editing) {
          e.stopPropagation();
          setEditing(false);
          setBad(false);
          setText(shown);
        } else e.continuePropagation();
      }}
    >
      <Input className={`${s.timeInput} num mono`} spellCheck={false} autoComplete="off" placeholder="—" data-testid={props.testId} />
    </RacTextField>
  );
}

/** 多行文字输入（试算框、对齐文本、备注）：Enter 换行；lang 用于日文字形。 */
export function TextArea(props: { value: string; onChange: (v: string) => void; label: string; rows?: number; lang?: string; mono?: boolean; testId?: string }) {
  return (
    <RacTextField value={props.value} onChange={props.onChange} aria-label={props.label} className={s.text}>
      <RacTextArea
        className={`${s.textInput} ${s.textArea} ${props.mono ? "mono" : ""}`}
        rows={props.rows ?? 2}
        lang={props.lang}
        spellCheck={false}
        data-testid={props.testId}
      />
    </RacTextField>
  );
}
