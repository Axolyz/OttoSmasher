// 组件样张（ARCHITECTURE §1.3、AGENTS §9）：设计令牌与组件清单一页看全；页面只用这些组件，缺了先补到这里。
import { AudioLines, ChevronDown, ChevronRight, Film, Inbox, MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";
import { BatchBar } from "../components/BatchBar";
import { Button } from "../components/Button";
import { CollectionList, type CollectionRow } from "../components/CollectionList";
import { Checkbox, Chips, type ChipItem, ClosableTabs, Disclosure, EmptyState, ProgressBar, RadioList, Segmented, StepsBar, Token } from "../components/Controls";
import { NumberField, OptionalNumber, Select, Suggest, Switch, TextArea, TextField, TimeField } from "../components/Fields";
import { Menu, useContextMenu } from "../components/Menu";
import { NatureDot, NaturePicker } from "../components/NaturePicker";
import { Tip } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { AnchoredPanel } from "../components/Panel";
import { SplitPane } from "../components/SplitPane";
import { Thumb } from "../components/Thumb";
import { clock } from "../format";
import { t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Tools.module.css";

const COLORS = ["--bg", "--s1", "--s2", "--s3", "--line", "--text", "--sub", "--muted", "--accent", "--wave", "--gold", "--ok", "--warn", "--bad"];
const NATURES = ["speech", "pitched", "unpitched", "unclassified"] as const;
const SIZES = ["--fs-xs", "--fs-sm", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl"];

type Demo = CollectionRow & { name: string; nature: "speech" | "pitched" | "unpitched" | "unclassified"; dur: number };
const DEMO: Demo[] = [
  { id: "g1", kind: "group", name: "specimen.groupA", nature: "speech", dur: 0 },
  { id: "s1", name: "specimen.item1", nature: "speech", dur: 1.24 },
  { id: "s2", name: "specimen.item2", nature: "pitched", dur: 0.63 },
  { id: "s3", name: "specimen.item3", nature: "speech", dur: 2.1, dead: true },
  { id: "g2", kind: "group", name: "specimen.groupB", nature: "speech", dur: 0 },
  { id: "s4", name: "specimen.item4", nature: "unpitched", dur: 0.17 },
  { id: "s5", name: "specimen.item5", nature: "unclassified", dur: 4.42 },
];
const LINES = Array.from({ length: 23 }, (_, i) => ({ id: `l${i}`, i, a: 80.2 + i * 2.4, excluded: i >= 2 && i <= 4 }));

export function Specimen() {
  const toast = useApp((st) => st.toast);
  const [on, setOn] = useState(true);
  const [thumbPlaying, setThumbPlaying] = useState(false);
  const [opt, setOpt] = useState<number | null>(null);
  const [sq, setSq] = useState("");
  const [picked, setPicked] = useState("");
  const [tab, setTab] = useState("browse");
  const [tabs, setTabs] = useState(["1", "2"]);
  const [num, setNum] = useState(0.65);
  const [sel, setSel] = useState("speech");
  const [area, setArea] = useState("");
  const [cb, setCb] = useState<"none" | "some" | "all">("some");
  const [radio, setRadio] = useState("vowels");
  const [seg, setSeg] = useState<"sub" | "phone" | "seg" | "none">("sub");
  const [lens, setLens] = useState<"all" | "speech" | "pitched">("all");
  const [nature, setNature] = useState<Demo["nature"]>("speech");
  const [chips, setChips] = useState<ChipItem[]>([
    { id: "f", v: t("specimen.chip.filter"), tone: "preset" },
    { id: "w", k: t("specimen.chip.work"), v: "Yuru Yuri" },
    { id: "p", k: t("specimen.chip.person"), v: t("specimen.chip.personValue"), lang: "ja" },
  ]);
  const [focus, setFocus] = useState<string | null>("s1");
  const [checked, setChecked] = useState<Set<string>>(new Set(["s2"]));
  const [open, setOpen] = useState<string[]>(["g1", "g2"]);
  const [rows, setRows] = useState<Set<string>>(new Set());
  const [split, setSplit] = useState(0.5);
  const [time, setTime] = useState(80.2);
  const [panel, setPanel] = useState(false);
  const ctx = useContextMenu("specimen-context");
  const shown = DEMO.filter((d) => d.kind === "group" || open.includes(DEMO.slice(0, DEMO.indexOf(d)).reverse().find((g) => g.kind === "group")!.id));
  return (
    <div className={s.spec} data-testid="specimen">
      <section>
        <h4>{t("specimen.tokens")}</h4>
        <div className={s.row}>
          {COLORS.map((c) => (
            <div key={c} className={s.swatch}>
              <i style={{ background: `var(${c})` }} />
              <span className="mono">{c}</span>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h4>{t("specimen.natures")}</h4>
        <div className={s.row}>
          {NATURES.map((n) => (
            <span key={n} className={s.nat}>
              <i style={{ background: `var(--nat-${n})` }} />
              {t(`nature.${n}`)}
            </span>
          ))}
        </div>
      </section>
      <section>
        <h4>{t("specimen.type")}</h4>
        <div className={s.row}>
          {SIZES.map((z) => (
            <span key={z} style={{ fontSize: `var(${z})` }}>
              <span className="mono">{z}</span>
            </span>
          ))}
        </div>
      </section>
      <section>
        <h4>{t("specimen.buttons")}</h4>
        <div className={s.row}>
          <Button variant="primary">{t("specimen.primary")}</Button>
          <Button>{t("specimen.secondary")}</Button>
          <Button variant="flat">{t("specimen.flat")}</Button>
          <Button variant="danger">{t("specimen.menu.item3")}</Button>
          <Button isDisabled>{t("specimen.disabled")}</Button>
          <Button size="sm">{t("specimen.secondary")}</Button>
        </div>
      </section>
      <section>
        <h4>{t("specimen.fields")}</h4>
        <div className={s.row}>
          <Switch isSelected={on} onChange={setOn} label={t("specimen.switch")} />
          <NumberField value={num} onChange={setNum} step={0.05} minValue={0} maxValue={5} label={t("specimen.number")} />
          <OptionalNumber value={opt} onChange={setOpt} min={0} placeholder={t("specimen.optional")} label={t("specimen.optional")} width={90} />
          <Select
            value={sel}
            onChange={setSel}
            label={t("specimen.select")}
            options={NATURES.map((n) => ({ id: n, label: t(`nature.${n}`) }))}
          />
        </div>
        <div className={s.row}>
          <Suggest
            label={t("scope.add")}
            placeholder="+"
            query={sq}
            onQuery={setSq}
            onPick={setPicked}
            groups={[{ id: "n", title: t("nature.label"), items: NATURES.filter((n) => t(`nature.${n}`).includes(sq)).map((n) => ({ id: n, label: t(`nature.${n}`), detail: "3" })) }]}
            footer={t("scope.onlyTags")}
          />
          <span>{picked ? t(`nature.${picked}`) : ""}</span>
        </div>
      </section>
      <section>
        <h4>{t("specimen.tabs")}</h4>
        <ClosableTabs
          label={t("specimen.tabs")}
          closeLabel={t("specimen.tabClose")}
          value={tab}
          onChange={setTab}
          onClose={(id) => setTabs((xs) => xs.filter((x) => x !== id))}
          items={[{ id: "browse", label: t("specimen.tabBrowse"), count: 51 }, ...tabs.map((x) => ({ id: x, label: t("specimen.tabResult", { n: x }), closable: true }))]}
        />
      </section>
      <section>
        <h4>{t("specimen.disclosure")}</h4>
        <Disclosure title={t("specimen.disclosure")}>
          <span>{t("specimen.item1")}</span>
        </Disclosure>
      </section>
      <section>
        <h4>
          {t("specimen.menu")} · {t("specimen.tooltip")} · {t("specimen.toast")}
        </h4>
        <div className={s.row}>
          <Menu
            head={t("specimen.menu.head", { name: t("specimen.japanese.sample") })}
            trigger={<Button icon={<MoreHorizontal />}>{t("specimen.menu.open")}</Button>}
            items={[
              { id: "a", label: t("specimen.menu.item1"), shortcut: "Space", run: () => {} },
              { id: "b", label: t("specimen.menu.item2"), shortcut: "B", run: () => {} },
              "-",
              { id: "c", label: t("specimen.menu.item3"), shortcut: "⌫", danger: true, run: () => {} },
            ]}
          />
          <Tip content={t("specimen.tooltip.body")}>
            <Button>{t("specimen.tooltip")}</Button>
          </Tip>
          <Button onPress={() => toast({ text: t("specimen.toast.body"), action: { label: t("common.undo"), run: () => {} } })}>
            {t("specimen.toast.show")}
          </Button>
        </div>
      </section>
      <section>
        <h4>{t("specimen.controls")}</h4>
        <div className={s.row}>
          <Checkbox isSelected={cb === "all"} isIndeterminate={cb === "some"} onChange={() => setCb(cb === "all" ? "none" : "all")} label={t("specimen.checkbox")}>
            {t("specimen.checkbox")}
          </Checkbox>
          <Checkbox isSelected onChange={() => {}} label={t("specimen.disabled")} isDisabled>
            {t("specimen.disabled")}
          </Checkbox>
          <Segmented
            value={seg}
            onChange={setSeg}
            label={t("specimen.segmented")}
            options={[
              { id: "sub", label: t("specimen.seg.sub") },
              { id: "phone", label: t("specimen.seg.phone") },
              { id: "seg", label: t("specimen.seg.seg") },
              { id: "none", label: t("common.none") },
            ]}
          />
          <NaturePicker value={nature} onChange={setNature} />
        </div>
        <div className={s.row}>
          <Segmented
            variant="lens"
            value={lens}
            onChange={setLens}
            label={t("specimen.lens")}
            options={[
              { id: "all", label: t("library.all") },
              { id: "speech", label: t("nature.speech"), mark: <NatureDot nature="speech" /> },
              { id: "pitched", label: t("nature.pitched"), mark: <NatureDot nature="pitched" /> },
            ]}
          />
          <Segmented
            size="sm"
            wrap
            value={seg}
            onChange={setSeg}
            label={t("specimen.segWrap")}
            options={[
              { id: "sub", label: t("rhythm.planLabel", { plan: t("rhythm.plan.near_fast"), speed: "1.06", density: 4 }) },
              { id: "phone", label: t("rhythm.planLabel", { plan: t("rhythm.plan.near_slow"), speed: "0.53", density: 2 }) },
              { id: "seg", label: t("rhythm.planLabel", { plan: t("rhythm.plan.double"), speed: "2.12", density: 8 }) },
            ]}
          />
          <TimeField value={time} onCommit={(v) => (v < 1000 ? (setTime(v), true) : false)} label={t("specimen.time")} />
          <span className="num mono">{clock(time)}</span>
        </div>
        <Chips
          label={t("specimen.chips")}
          items={chips}
          onRemove={(id) => setChips((c) => c.filter((x) => x.id !== id))}
          trailing={<Button size="sm" variant="flat" icon={<Plus />} aria-label={t("specimen.chip.add")} />}
        />
        <div className={s.row} style={{ maxWidth: 520 }}>
          <div style={{ flex: 1 }}>
            <ProgressBar value={0.62} label={t("specimen.progress")} showValue="62%" />
          </div>
          <div style={{ flex: 1 }}>
            <ProgressBar value={280} max={312} tone="ok" label={t("specimen.progress")} showValue="280/312" />
          </div>
          <div style={{ flex: 1 }}>
            <ProgressBar value={null} label={t("specimen.progress")} />
          </div>
          <StepsBar steps={[true, true, true, false, true, true, true]} label={t("specimen.steps")} />
        </div>
        <div className={s.row} style={{ maxWidth: 360 }}>
          <div style={{ flex: 1 }}>
            <RadioList
              stack
              value={radio}
              onChange={setRadio}
              label={t("specimen.radioCards")}
              items={[
                { id: "whole", label: t("flatten.range.whole"), note: t("flatten.range.whole.note") },
                { id: "vowels", label: t("flatten.range.vowels"), note: t("flatten.range.vowels.note") },
                { id: "inner", label: t("flatten.range.inner"), note: t("flatten.range.inner.note"), isDisabled: true },
              ]}
            />
          </div>
        </div>
        <div className={s.row}>
          <Thumb url={null} play={{ playing: thumbPlaying, onPress: () => setThumbPlaying((x) => !x), label: t("library.audition") }} />
          <Thumb url={null} size="sm" placeholder={<Film />} />
          <Thumb url={null} size="sm" placeholder={<AudioLines />} />
        </div>
      </section>
      <section>
        <h4>
          {t("specimen.panel")} · {t("specimen.context")}
        </h4>
        <div className={s.row}>
          <AnchoredPanel
            isOpen={panel}
            onOpenChange={setPanel}
            title={t("clip.title")}
            aux="1:20.200–1:22.000"
            trigger={<Button>{t("specimen.panel.open")}</Button>}
            footer={
              <>
                <Button variant="flat" onPress={() => setPanel(false)}>
                  {t("common.cancel")}
                </Button>
                <Button variant="primary" onPress={() => setPanel(false)}>
                  {t("common.save")}
                </Button>
              </>
            }
          >
            <TextField value={t("specimen.item1")} onChange={() => {}} label={t("clip.name")} />
            <NaturePicker value={nature} onChange={setNature} />
          </AnchoredPanel>
          <div
            className={s.ctxTarget}
            onContextMenu={(e) => {
              e.preventDefault();
              ctx.open(e, {
                head: t("menu.on", { name: t("specimen.item1") }),
                items: [
                  { id: "a", label: t("specimen.menu.item1"), shortcut: "Space", run: () => {} },
                  "-",
                  { id: "n", label: t("library.setNature"), items: [{ id: "n1", label: t("nature.speech"), shortcut: "1", run: () => {} }, { id: "n2", label: t("nature.pitched"), shortcut: "2", run: () => {} }] },
                  "-",
                  { id: "d", label: t("specimen.menu.item3"), danger: true, shortcut: "⌫", run: () => {} },
                ],
              });
            }}
          >
            {t("specimen.context.hint")}
          </div>
          {ctx.node}
        </div>
      </section>
      <section>
        <h4>{t("specimen.textArea")}</h4>
        <TextArea value={area} onChange={setArea} label={t("specimen.textArea")} rows={3} mono tabInserts placeholder={t("dict.placeholder")} testId="specimen-textarea" />
      </section>
      <section>
        <h4>{t("specimen.tokens")}</h4>
        <div style={{ display: "flex", gap: 4 }}>
          {["k", "a", "N", "pau"].map((x, i) => (
            <Token key={x} label={x} strong={x === "a" || x === "N"} selected={i === 1} />
          ))}
          <Token label="ka" plain selected />
        </div>
      </section>
      <section>
        <h4>{t("specimen.list")}</h4>
        <div className={s.demoBox}>
          <SplitPane
            ratio={split}
            onRatio={setSplit}
            label={t("library.splitter")}
            left={
              <CollectionList<Demo>
                label={t("specimen.list")}
                items={shown}
                textValue={(d) => t(d.name)}
                focus={focus}
                onFocus={setFocus}
                checked={checked}
                onChecked={setChecked}
                onGroup={(id, o) => setOpen((x) => ((o ?? !x.includes(id)) ? [...new Set([...x, id])] : x.filter((y) => y !== id)))}
                isGroupOpen={(id) => open.includes(id)}
                onDelete={(ids) => toast({ text: t("specimen.deleteAsk", { n: ids.length }) })}
                menu={(d, target) => ({
                  head: target.multi ? t("menu.checkedN", { n: target.ids.length }) : t("menu.on", { name: t(d.name) }),
                  items: [{ id: "x", label: t("specimen.menu.item1"), run: () => {} }],
                })}
                checkLabel={(d) => t(d.name)}
                renderGroup={(d, o) => (
                  <>
                    {o ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <span>{t(d.name)}</span>
                  </>
                )}
                renderItem={(d) => (
                  <>
                    <NatureDot nature={d.nature} />
                    <span style={{ flex: 1 }} lang="ja">
                      {t(d.name)}
                    </span>
                    <span className="num" style={{ color: "var(--muted)" }}>
                      {t("format.sec", { v: d.dur.toFixed(2) })}
                    </span>
                  </>
                )}
                footer={<BatchBar count={checked.size} total={4} onCheckAll={() => setChecked(new Set(["s1", "s2", "s4", "s5"]))} items={[{ id: "d", label: t("specimen.menu.item3"), danger: true, run: () => {} }]} onClear={() => setChecked(new Set())} />}
              />
            }
            right={<EmptyState icon={<Inbox />} title={t("specimen.empty.title")} body={t("specimen.empty.body")} actions={<Button variant="primary">{t("specimen.primary")}</Button>} />}
          />
        </div>
      </section>
      <section>
        <h4>{t("specimen.table")}</h4>
        <div className={s.demoTable}>
          <PagedTable
            label={t("specimen.table")}
            rows={LINES}
            pageSize={10}
            checked={rows}
            onChecked={setRows}
            isSelectable={(r) => !r.excluded}
            checkLabel={(r) => t("specimen.line", { n: r.i + 1 })}
            columns={[
              { id: "name", label: t("clip.name"), isRowHeader: true, render: (r) => t("specimen.line", { n: r.i + 1 }) },
              { id: "range", label: t("specimen.table.range"), render: (r) => <span className="num">{`${(r.a - 0.1).toFixed(2)}–${(r.a + 1.9).toFixed(2)}`}</span> },
              { id: "state", label: t("specimen.table.state"), render: (r) => (r.excluded ? t("specimen.table.excluded") : t("specimen.table.pending")) },
            ]}
          />
        </div>
      </section>
      <section>
        <h4>{t("specimen.japanese")}</h4>
        <div className={s.row}>
          <span>
            {t("specimen.japanese.zh")}
            <span lang="zh-CN">{t("specimen.japanese.sample")}</span>
          </span>
          <span>
            {t("specimen.japanese.ja")}
            <span lang="ja">{t("specimen.japanese.sample")}</span>
          </span>
        </div>
      </section>
    </div>
  );
}
