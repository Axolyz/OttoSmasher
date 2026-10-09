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
import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
  /** 回车 */
  onSubmit?: () => void;
  autoFocus?: boolean;
}) {
  return (
    <RacTextField
      value={props.value}
      onChange={props.onChange}
      autoFocus={props.autoFocus}
      onKeyDown={
        props.onSubmit
          ? (e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                props.onSubmit!();
              }
            }
          : undefined
      }
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

/** 多行文字输入（试算框、对齐文本、备注）：Enter 换行；lang 用于日文字形。
 * ``tabInserts``：Tab 插入制表符而不是移走焦点（UI_PLAN §7：对齐文本、辞典、精确时间文本）；Shift+Tab 仍然移走焦点。 */
export function TextArea(props: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  rows?: number;
  lang?: string;
  mono?: boolean;
  testId?: string;
  placeholder?: string;
  tabInserts?: boolean;
  invalid?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  // 插入制表符后的光标位置：受控值更新提交后立即放回（不能等下一帧，否则紧接着的输入会落到末尾）
  const caret = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (caret.current !== null && ref.current) {
      ref.current.setSelectionRange(caret.current, caret.current);
      caret.current = null;
    }
  }, [props.value]);
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!props.tabInserts || e.key !== "Tab" || e.shiftKey || e.altKey || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    const el = e.currentTarget;
    const a = el.selectionStart;
    const b = el.selectionEnd;
    caret.current = a + 1;
    props.onChange(props.value.slice(0, a) + "\t" + props.value.slice(b));
  };
  return (
    <RacTextField value={props.value} onChange={props.onChange} aria-label={props.label} isInvalid={props.invalid} className={s.text}>
      <RacTextArea
        ref={ref}
        className={`${s.textInput} ${s.textArea} ${props.mono ? "mono" : ""}`}
        rows={props.rows ?? 2}
        lang={props.lang}
        spellCheck={false}
        placeholder={props.placeholder}
        onKeyDown={onKeyDown}
        data-testid={props.testId}
      />
    </RacTextField>
  );
}

/** 可留空的数字（检索条件：留空 = 不限）。输入时就地校验：不是数字或越界标红，不提交；只在合法时回调。 */
export function OptionalNumber(props: {
  value: number | null;
  onChange: (v: number | null) => void;
  label: string;
  placeholder?: string;
  min?: number;
  max?: number;
  testId?: string;
  width?: number;
}) {
  const [draft, setDraft] = useState(props.value == null ? "" : String(props.value));
  const last = useRef(props.value);
  useEffect(() => {
    if (props.value !== last.current) {
      last.current = props.value;
      setDraft(props.value == null ? "" : String(props.value));
    }
  }, [props.value]);
  const parse = (txt: string): number | null | undefined => {
    const v = txt.trim();
    if (!v) return null;
    const n = Number(v);
    if (!Number.isFinite(n)) return undefined;
    if ((props.min != null && n < props.min) || (props.max != null && n > props.max)) return undefined;
    return n;
  };
  const bad = parse(draft) === undefined;
  return (
    <RacTextField
      value={draft}
      onChange={(v) => {
        setDraft(v);
        const n = parse(v);
        if (n !== undefined) {
          last.current = n;
          props.onChange(n);
        }
      }}
      aria-label={props.label}
      isInvalid={bad}
      className={s.text}
      style={props.width ? { flex: "none", width: props.width } : undefined}
    >
      <Input className={`${s.textInput} num`} placeholder={props.placeholder} data-testid={props.testId} />
    </RacTextField>
  );
}

