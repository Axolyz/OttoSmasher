// 小控件（UI_PLAN §5–§6，原型样式按 React Aria 的状态属性实现）：复选框（含半选）、分段选择、条件块、进度条、分段进度、空状态。
import { Check, Minus, X } from "lucide-react";
import type { ReactNode } from "react";
import {
  Button as RacButton,
  Checkbox as RacCheckbox,
  ProgressBar as RacProgressBar,
  Radio,
  RadioGroup,
  Tag,
  TagGroup,
  TagList,
  ToggleButton,
  ToggleButtonGroup,
} from "react-aria-components";
import s from "./Controls.module.css";

/**
 * 复选框：列表行、表格、表头（半选）共用。slot={null}：放在 GridList / Table 行里时不接管集合自带的“选择”槽位，
 * 勾选规则由 selection.ts 统一决定（单击行从不改变勾选）。
 */
export function Checkbox(props: {
  isSelected: boolean;
  isIndeterminate?: boolean;
  onChange: (v: boolean) => void;
  label: string;
  isDisabled?: boolean;
  children?: ReactNode;
  testId?: string;
}) {
  return (
    <RacCheckbox
      slot={null}
      isSelected={props.isSelected}
      isIndeterminate={props.isIndeterminate}
      onChange={props.onChange}
      isDisabled={props.isDisabled}
      aria-label={props.children ? undefined : props.label}
      className={s.checkbox}
      data-testid={props.testId}
    >
      {({ isIndeterminate, isSelected }) => (
        <>
          <span className={s.box}>{isIndeterminate ? <Minus size={11} strokeWidth={3} /> : isSelected ? <Check size={11} strokeWidth={3} /> : null}</span>
          {props.children}
        </>
      )}
    </RacCheckbox>
  );
}

export interface SegOption<K extends string> {
  id: K;
  label: string;
  /** 选项前的小标记（例如性质圆点） */
  mark?: ReactNode;
  /** 额外的 data-* 属性（测试与样式用） */
  data?: Record<string, string>;
  isDisabled?: boolean;
}

/**
 * 分段选择（单选，不可清空）：性质、覆盖层、方案等。variant="lens" 是顶栏用途切换那种无边框样式。
 * 键盘：←→ 在选项间移动，Space/Enter 选中（React Aria ToggleButtonGroup，role=radiogroup）。
 */
export function Segmented<K extends string>(props: {
  value: K;
  onChange: (v: K) => void;
  options: Array<SegOption<K>>;
  label: string;
  variant?: "box" | "lens";
  size?: "sm" | "md";
  testId?: string;
}) {
  return (
    <ToggleButtonGroup
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[props.value]}
      onSelectionChange={(keys) => {
        const k = [...keys][0];
        if (k != null) props.onChange(String(k) as K);
      }}
      aria-label={props.label}
      className={`${s.seg} ${props.variant === "lens" ? s.lens : ""} ${props.size === "sm" ? s.segSm : ""}`}
      data-testid={props.testId}
    >
      {props.options.map((o) => (
        <ToggleButton key={o.id} id={o.id} className={s.segBtn} isDisabled={o.isDisabled} {...(o.data ?? {})}>
          {o.mark}
          {o.label}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}

export interface ChipItem {
  id: string;
  /** 条件名（淡色），例如“作品” */
  k?: string;
  /** 条件值，例如“Yuru Yuri” */
  v: string;
  /** preset = 筛选器块（强调色底） */
  tone?: "default" | "preset";
  /** 只读块（继承标签等）不显示 × */
  readOnly?: boolean;
  lang?: string;
}

/**
 * 条件块一行：范围条件、标签、查找栏里的临时块（UI_PLAN §2.3）。× 或 Backspace/Delete 移除；可以在末尾放“＋”。
 * React Aria TagGroup：←→ 在块之间移动焦点。
 */
export function Chips(props: { items: ChipItem[]; label: string; onRemove?: (id: string) => void; onAction?: (id: string) => void; trailing?: ReactNode; testId?: string }) {
  return (
    <div className={s.chipRow} data-testid={props.testId}>
      <TagGroup
        aria-label={props.label}
        onRemove={props.onRemove ? (keys) => keys.forEach((k) => props.onRemove!(String(k))) : undefined}
        onAction={props.onAction ? (k) => props.onAction!(String(k)) : undefined}
        className={s.chipGroup}
      >
        <TagList items={props.items} className={s.chipList}>
          {(it) => (
            <Tag id={it.id} textValue={`${it.k ?? ""} ${it.v}`} className={`${s.chip} ${it.tone === "preset" ? s.chipPreset : ""}`}>
              {({ allowsRemoving }) => (
                <>
                  {it.k ? <span className={s.chipK}>{it.k}</span> : null}
                  <span lang={it.lang} data-user-data="">
                    {it.v}
                  </span>
                  {allowsRemoving && !it.readOnly ? (
                    <RacButton slot="remove" className={s.chipX}>
                      <X size={11} />
                    </RacButton>
                  ) : null}
                </>
              )}
            </Tag>
          )}
        </TagList>
      </TagGroup>
      {props.trailing}
    </div>
  );
}

/** 进度条：任务、原片语音分析进度等。value 为 null = 不确定进度（来回滑动）。 */
export function ProgressBar(props: { value: number | null; max?: number; label: string; tone?: "accent" | "ok" | "warn" | "bad"; size?: "thin" | "md"; showValue?: string; testId?: string }) {
  const max = props.max ?? 1;
  return (
    <RacProgressBar
      value={props.value ?? 0}
      maxValue={max}
      isIndeterminate={props.value == null}
      aria-label={props.label}
      className={`${s.progress} ${props.size === "md" ? s.progressMd : ""}`}
      data-tone={props.tone ?? "accent"}
      data-testid={props.testId}
    >
      {({ percentage, isIndeterminate }) => (
        <>
          <span className={s.track}>
            <span className={s.fill} data-indeterminate={isIndeterminate || undefined} style={isIndeterminate ? undefined : { width: `${percentage}%` }} />
          </span>
          {props.showValue ? <span className={`${s.progressValue} num`}>{props.showValue}</span> : null}
        </>
      )}
    </RacProgressBar>
  );
}

/** 分段进度（准备清单那种 “▬▬▬▭ 6/7”）：每段一个步骤，完成的亮。 */
export function StepsBar(props: { steps: boolean[]; label: string }) {
  const done = props.steps.filter(Boolean).length;
  return (
    <span className={s.steps} role="meter" aria-label={props.label} aria-valuenow={done} aria-valuemin={0} aria-valuemax={props.steps.length}>
      {props.steps.map((ok, i) => (
        <i key={i} data-done={ok || undefined} />
      ))}
      <span className="num">
        {done}/{props.steps.length}
      </span>
    </span>
  );
}

/** 空状态：图标 + 一句标题 + 说明 + 动作（UI_PLAN：两边都没有的状态自己设计，同一设计语言）。 */
export function EmptyState(props: { icon?: ReactNode; title: string; body?: ReactNode; actions?: ReactNode; size?: "page" | "inline"; testId?: string }) {
  return (
    <div className={`${s.empty} ${props.size === "inline" ? s.emptyInline : ""}`} data-testid={props.testId}>
      {props.icon ? <span className={s.emptyIcon}>{props.icon}</span> : null}
      <h3>{props.title}</h3>
      {props.body ? <div className={s.emptyBody}>{props.body}</div> : null}
      {props.actions ? <div className={s.emptyActions}>{props.actions}</div> : null}
    </div>
  );
}

/** 大数字统计（原型 .big3）：导入预览、字幕采样预览、语音分析确认框的 M / N / K。 */
export function Stats(props: { items: Array<{ n: number; label: string; tone?: "default" | "warn" | "bad" | "muted"; testId?: string }> }) {
  return (
    <div className={s.stats}>
      {props.items.map((it) => (
        <div key={it.label} className={s.stat} data-tone={it.tone ?? "default"} data-testid={it.testId}>
          <div className={`${s.statN} num`}>{it.n.toLocaleString("en-US")}</div>
          <div className={s.statLabel}>{it.label}</div>
        </div>
      ))}
    </div>
  );
}

/** 说明块（原型 .say）：弹窗、工作台里“会做什么 / 不会做什么”的一段话。tone="warn" 用于需要补选的情况（例如缺默认轨）。 */
export function Callout(props: { children: ReactNode; tone?: "info" | "warn" | "bad"; testId?: string }) {
  return (
    <div className={s.callout} data-tone={props.tone ?? "info"} data-testid={props.testId}>
      {props.children}
    </div>
  );
}

export interface RadioItem {
  id: string;
  label: ReactNode;
  /** 右侧的淡色说明（例如“默认人声模型”“三轨”） */
  note?: ReactNode;
  isDisabled?: boolean;
}

/** 单选列表（一行一个选项）：分离模型、导出格式这类“从一列里选一个”。React Aria RadioGroup：↑↓ 移动并选中。 */
export function RadioList(props: { value: string | null; onChange: (v: string) => void; items: RadioItem[]; label: string; testId?: string }) {
  return (
    <RadioGroup
      value={props.value}
      onChange={props.onChange}
      aria-label={props.label}
      className={s.radioList}
      data-testid={props.testId}
    >
      {props.items.map((it) => (
        <Radio key={it.id} value={it.id} isDisabled={it.isDisabled} className={s.radioRow}>
          <span className={s.radioDot} />
          <span className={s.radioLabel}>{it.label}</span>
          {it.note ? <span className={s.radioNote}>{it.note}</span> : null}
        </Radio>
      ))}
    </RadioGroup>
  );
}

/** 小记号按钮（音素、音块等一串可单击的短标签；UI_PLAN §3 语音面板）。``strong`` = 强调色（元音、核心） */
export function Token(props: { label: string; onPress?: () => void; strong?: boolean; selected?: boolean; title?: string; lang?: string; testId?: string }) {
  return (
    <RacButton
      className={s.token}
      data-strong={props.strong || undefined}
      data-selected={props.selected || undefined}
      onPress={props.onPress}
      aria-label={props.title ? `${props.label} ${props.title}` : props.label}
      data-testid={props.testId}
    >
      <span lang={props.lang} title={props.title} data-user-data="">
        {props.label}
      </span>
    </RacButton>
  );
}
