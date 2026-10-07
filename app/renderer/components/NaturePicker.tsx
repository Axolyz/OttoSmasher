// 性质四选一（规格 04 §4.2.7）：小圆点颜色用设计令牌的性质四色；数字键 1/2/3/0 的顺序与这里一致。
import type { Nature } from "../api/types";
import { t } from "../i18n";
import s from "./NaturePicker.module.css";

export const NATURES: Nature[] = ["speech", "pitched", "unpitched", "unclassified"];
export const NATURE_KEYS: Record<string, Nature> = { "1": "speech", "2": "pitched", "3": "unpitched", "0": "unclassified" };

export function NatureDot({ nature }: { nature: Nature }) {
  return <span className={s.dot} data-nature={nature} aria-hidden />;
}

export function NaturePicker(props: { value: Nature; onChange: (n: Nature) => void; testId?: string }) {
  return (
    <div className={s.group} role="radiogroup" aria-label={t("nature.label")} data-testid={props.testId}>
      {NATURES.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={props.value === n}
          className={s.opt}
          data-on={props.value === n || undefined}
          onClick={() => props.onChange(n)}
          data-nature={n}
        >
          <NatureDot nature={n} />
          {t(`nature.${n}`)}
        </button>
      ))}
    </div>
  );
}
