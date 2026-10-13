// 波形卡（所有者 2026-10-13：原素材页与详情区——语音 / 调谐 / 非调谐 / 未分类——共用一个基础组件，各自只加自己的东西，
// 一个问题不用改四遍）。从上到下：标题栏（标题 · 各自的附加 · 适合 / 放大选区 / 频谱 · 各自的附加）→ 图层栏或编辑条 → 时间线 → 动作条
// （播放组 · 选区起止 · 加工组 · 右侧说明）。这里只管排布与共用控件；时间线、按钮的行为由调用方给。
import { AudioWaveform, ChevronDown, Download, Split, Undo2 } from "lucide-react";
import type { KeyboardEvent, ReactNode, Ref } from "react";
import { seconds } from "../format";
import { t } from "../i18n";
import { Button } from "./Button";
import { Checkbox, Segmented } from "./Controls";
import { TimeField } from "./Fields";
import { Menu, type MenuItems } from "./Menu";
import { SpectrumMenu, type SpectrumScale } from "./SpectrumMenu";
import s from "./WaveCard.module.css";

export function WaveCard(props: {
  title: ReactNode;
  /** 标题与「适合」之间（原素材页：编辑边界） */
  headExtra?: ReactNode;
  /** 「频谱」之后（原素材页：采样 n、说明） */
  headTail?: ReactNode;
  /** 标题栏里固定位置的读数（播放指针处的音高） */
  readout?: ReactNode;
  fitLabel: string;
  fitTip?: string;
  onFit: () => void;
  onZoomSel: () => void;
  zoomSelDisabled: boolean;
  zoomSelTestId?: string;
  spectrum: SpectrumScale;
  onSpectrum: (v: SpectrumScale) => void;
  spectrumTestId: string;
  /** 图层栏（WaveLayers）；编辑时换成编辑条（WaveEditBar） */
  bar?: ReactNode;
  /** 标题栏下的错误说明 */
  error?: ReactNode;
  /** 时间线（直接放在卡里，高度由时间线自己定——不再外套固定高度的框） */
  timeline: ReactNode;
  /** 动作条：播放组、选区、加工组、右侧说明 */
  play: ReactNode;
  selection: ReactNode;
  process: ReactNode;
  actionsTail?: ReactNode;
  actionsTestId?: string;
  /** 卡上的对话框、菜单节点 */
  children?: ReactNode;
  testId: string;
  ariaLabel?: string;
  cardRef?: Ref<HTMLElement>;
  focusable?: boolean;
  onKeyDown?: (e: KeyboardEvent<HTMLElement>) => void;
  data?: Record<string, string | undefined>;
}) {
  const data = Object.fromEntries(Object.entries(props.data ?? {}).map(([k, v]) => [`data-${k}`, v]));
  return (
    <section
      className={s.card}
      ref={props.cardRef}
      tabIndex={props.focusable ? 0 : undefined}
      onKeyDown={props.onKeyDown}
      data-testid={props.testId}
      aria-label={props.ariaLabel}
      {...data}
    >
      <div className={s.head}>
        {props.title}
        {props.readout}
        <span className={s.grow} />
        {props.headExtra}
        <Button size="sm" variant="flat" onPress={props.onFit} title={props.fitTip}>
          {props.fitLabel}
        </Button>
        <Button size="sm" variant="flat" onPress={props.onZoomSel} isDisabled={props.zoomSelDisabled} title={t("sources.zoomSelTip")} data-testid={props.zoomSelTestId}>
          {t("sources.zoomSel")}
        </Button>
        <SpectrumMenu value={props.spectrum} onChange={props.onSpectrum} testId={props.spectrumTestId} />
        {props.headTail}
      </div>
      {props.error ? <div className={s.error}>{props.error}</div> : null}
      {props.bar}
      {props.timeline}
      {props.children}
      <div className={s.actions} data-testid={props.actionsTestId}>
        <div className={s.group}>{props.play}</div>
        {props.selection}
        <div className={s.group}>{props.process}</div>
        {props.actionsTail ? (
          <>
            <span className={s.grow} />
            {props.actionsTail}
          </>
        ) : null}
      </div>
    </section>
  );
}

/** 波形卡的标题文字 */
export function WaveTitle(props: { children: ReactNode }) {
  return <span className={s.title}>{props.children}</span>;
}

/** 图层栏：覆盖层（分段选择，只能一个）+ 车道（勾选，可以多个；当前覆盖层那一项不可勾） */
export function WaveLayers<T extends string>(props: {
  overlay: { value: T; onChange: (v: T) => void; options: Array<{ id: T; label: string }>; testId?: string };
  lanes: Array<{ id: string; label: string; checked: boolean; isDisabled?: boolean; onChange: (on: boolean) => void; testId?: string }>;
  hint?: string;
  testId?: string;
}) {
  return (
    <div className={s.layers} data-testid={props.testId}>
      <span className={s.groupLabel}>{t("layers.overlay")}</span>
      <Segmented<T> size="sm" value={props.overlay.value} onChange={props.overlay.onChange} label={t("layers.overlay")} options={props.overlay.options} testId={props.overlay.testId} />
      <span className={s.groupLabel}>{t("layers.lanes")}</span>
      {props.lanes.map((l) => (
        <Checkbox key={l.id} isSelected={l.checked} isDisabled={l.isDisabled} onChange={l.onChange} label={l.label} testId={l.testId}>
          {l.label}
        </Checkbox>
      ))}
      {props.hint ? <span className={s.layerHint}>{props.hint}</span> : null}
    </div>
  );
}

/** 编辑条（编辑边界 / 编辑音素时间）：标题、中间的内容（当前区间的起止或提示）、放弃 / 保存 */
export function WaveEditBar(props: {
  title: string;
  children?: ReactNode;
  onDiscard: () => void;
  onSave: () => void;
  saveLabel: string;
  testId: string;
  discardTestId: string;
  saveTestId: string;
}) {
  return (
    <div className={s.editBar} data-testid={props.testId}>
      <b>{props.title}</b>
      {props.children}
      <span className={s.grow} />
      <Button size="sm" variant="flat" onPress={props.onDiscard} data-testid={props.discardTestId}>
        {t("edit.discard")}
      </Button>
      <Button size="sm" variant="primary" onPress={props.onSave} data-testid={props.saveTestId}>
        {props.saveLabel}
      </Button>
    </div>
  );
}

/** 编辑条里的说明文字 */
export function WaveEditHint(props: { children: ReactNode }) {
  return <span className={s.editHint}>{props.children}</span>;
}

/** 编辑条里正在改的那一段的名字 */
export function WaveEditName(props: { children: ReactNode }) {
  return (
    <span className={s.editName} lang="ja" data-user-data="">
      {props.children}
    </span>
  );
}

/** 动作条的选区起止与时长 */
export function WaveSelection(props: {
  a: number | null;
  b: number | null;
  onCommit: (side: "a" | "b") => (v: number) => boolean;
  isDisabled?: boolean;
  testId: string;
  startTestId: string;
  endTestId: string;
}) {
  const ok = props.a != null && props.b != null;
  return (
    <div className={s.group} data-testid={props.testId} data-a={props.a ?? ""} data-b={props.b ?? ""}>
      <span className={s.groupLabel}>{t("sources.selection")}</span>
      <TimeField value={props.a} onCommit={props.onCommit("a")} label={t("sources.selStart")} isDisabled={props.isDisabled} testId={props.startTestId} />
      <span className={s.arrow}>→</span>
      <TimeField value={props.b} onCommit={props.onCommit("b")} label={t("sources.selEnd")} isDisabled={props.isDisabled} testId={props.endTestId} />
      <span className={`${s.dur} num`}>{ok ? t("format.sec", { v: seconds(props.b! - props.a!) }) : ""}</span>
    </div>
  );
}

/** 加工组：截取（调用方给 ClipPanel）· 拉平 · 分离 · 回导 · 导出 ▾（菜单项由调用方给） */
export function WaveProcess(props: {
  clip: ReactNode;
  onFlatten: () => void;
  flattenDisabled: boolean;
  onSeparate: () => void;
  separateDisabled: boolean;
  onReimport: () => void;
  reimportDisabled: boolean;
  exportHead?: string;
  exportItems: MenuItems;
  exportDisabled: boolean;
  testIds: { flatten: string; separate: string; reimport: string; export: string };
}) {
  return (
    <>
      {props.clip}
      <Button variant="flat" icon={<AudioWaveform />} isDisabled={props.flattenDisabled} onPress={props.onFlatten} data-testid={props.testIds.flatten}>
        {t("flatten.action")}
      </Button>
      <Button variant="flat" icon={<Split />} isDisabled={props.separateDisabled} onPress={props.onSeparate} data-testid={props.testIds.separate}>
        {t("sep.action")}
      </Button>
      <Button variant="flat" icon={<Undo2 />} isDisabled={props.reimportDisabled} onPress={props.onReimport} data-testid={props.testIds.reimport}>
        {t("reimport.action")}
      </Button>
      <Menu
        head={props.exportHead}
        items={props.exportItems}
        placement="top start"
        trigger={
          <Button variant="flat" icon={<Download />} isDisabled={props.exportDisabled} data-testid={props.testIds.export}>
            {t("sources.export")}
            <ChevronDown size={13} />
          </Button>
        }
      />
    </>
  );
}

/** 动作条右侧的说明（原素材页：拖出提示） */
export function WaveHint(props: { children: ReactNode }) {
  return <span className={s.hint}>{props.children}</span>;
}
