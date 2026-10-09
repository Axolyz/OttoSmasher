// 「频谱」开关（规格 05 §5.3.2、UI_PLAN §3 / §4 波形卡头）：波形 / 对数 / 线性 / Mel。舞台与原片时间线共用。
import { ChevronDown } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./Button";
import { Menu } from "./Menu";

export type SpectrumScale = "log" | "linear" | "mel" | null;

export function SpectrumMenu(props: { value: SpectrumScale; onChange: (v: SpectrumScale) => void; testId?: string }) {
  const items = ([null, "log", "linear", "mel"] as const).map((v) => ({
    id: `spec-${v ?? "off"}`,
    label: `${props.value === v ? "✓ " : ""}${t(`spectrum.${v ?? "off"}`)}`,
    run: () => props.onChange(v),
  }));
  return (
    <Menu
      head={t("spectrum.head")}
      items={items}
      placement="bottom end"
      trigger={
        <Button size="sm" variant={props.value ? "primary" : "flat"} data-testid={props.testId}>
          {props.value ? t("spectrum.on", { scale: t(`spectrum.${props.value}`) }) : t("spectrum.button")}
          <ChevronDown size={12} />
        </Button>
      }
    />
  );
}
