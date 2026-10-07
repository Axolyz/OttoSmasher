// 组件样张（ARCHITECTURE §1.3）：设计令牌与组件清单一页看全，确认后页面只用这些组件。
import { MoreHorizontal } from "lucide-react";
import { useState } from "react";
import { Button } from "../components/Button";
import { NumberField, Select, Switch } from "../components/Fields";
import { Menu, Tip } from "../components/Overlay";
import { t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Tools.module.css";

const COLORS = ["--bg", "--s1", "--s2", "--s3", "--line", "--text", "--sub", "--muted", "--accent", "--wave", "--gold", "--ok", "--warn", "--bad"];
const NATURES = ["speech", "pitched", "unpitched", "unclassified"] as const;
const SIZES = ["--fs-xs", "--fs-sm", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl"];

export function Specimen() {
  const toast = useApp((st) => st.toast);
  const [on, setOn] = useState(true);
  const [num, setNum] = useState(0.65);
  const [sel, setSel] = useState("speech");
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
          <Select
            value={sel}
            onChange={setSel}
            label={t("specimen.select")}
            options={NATURES.map((n) => ({ id: n, label: t(`nature.${n}`) }))}
          />
        </div>
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
