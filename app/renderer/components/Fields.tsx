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
  TextField as RacTextField,
} from "react-aria-components";
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

export function Select(props: { value: string; onChange: (v: string) => void; options: Option[]; label: string; isDisabled?: boolean }) {
  return (
    <RacSelect
      selectedKey={props.value}
      onSelectionChange={(k) => props.onChange(String(k))}
      isDisabled={props.isDisabled}
      aria-label={props.label}
      className={s.select}
    >
      <RacButton className={s.selectBtn}>
        <SelectValue />
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
