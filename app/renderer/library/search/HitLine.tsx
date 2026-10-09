// 命中的呈现（UI_PLAN §2.4、03 §3.4.4；原型 itemHtml 的 hitline / hchips）：
// 行下一条命中时间线（绿 = 严格、琥珀 = 近似；悬停看证据；单击 = 定位）；当前行展开命中小卡：▶ 左键原声、右键卡拍（该命中证据所选的方案）+「前后 0.3 s」。
import { Play, Square } from "lucide-react";
import type { ResultHit } from "../../api/types";
import { Checkbox } from "../../components/Controls";
import { t } from "../../i18n";
import s from "./Search.module.css";

export function evidenceText(h: ResultHit, kind: "speech" | "pitch"): string {
  if (kind === "pitch") {
    const parts = [t("search.hit.score", { v: h.score.toFixed(1) })];
    if (h.octave) parts.push(t("search.hit.octave", { n: h.octave > 0 ? `+${h.octave}` : String(h.octave) }));
    if (h.ratio != null && Math.abs(h.ratio - 1) > 1e-6) parts.push(t("search.hit.ratio", { v: h.ratio.toFixed(2) }));
    return parts.join(" · ");
  }
  const ev = h.evidence;
  if (!ev) return t("search.hit.free");
  const parts = [ev.strict ? t("search.hit.strict") : t("search.hit.approx")];
  if (ev.speed != null) parts.push(`${ev.speed.toFixed(2)}×`);
  if (ev.plan) parts.push(t(`rhythm.plan.${ev.plan}`));
  return parts.join(" · ");
}

export function evidenceDetail(h: ResultHit, kind: "speech" | "pitch"): string {
  const ev = h.evidence;
  if (kind === "pitch" || !ev) return evidenceText(h, kind);
  return [
    evidenceText(h, kind),
    t("search.hit.error", { v: ev.error.toFixed(3) }),
    t("search.hit.conflicts", { n: ev.conflicts }),
    ev.speed != null ? t("search.hit.speedCost", { v: Math.abs(Math.log2(ev.speed)).toFixed(3) }) : "",
    ev.changed ? t("search.hit.rests", { n: ev.changed }) : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function HitLine(props: {
  hits: ResultHit[];
  kind: "speech" | "pitch";
  start: number;
  duration: number;
  focusIndex: number | null;
  disabled?: boolean;
  onLocate: (i: number) => void;
  onMenu: (i: number, e: React.MouseEvent) => void;
}) {
  const d = Math.max(1e-6, props.duration);
  return (
    <div className={s.hitline} data-testid="hitline">
      <div className={s.hitbg}>
        {props.hits.map((h, i) => (
          <button
            type="button"
            key={i}
            className={s.hit}
            data-approx={(props.kind === "speech" && h.evidence && !h.evidence.strict) || undefined}
            data-on={props.focusIndex === i || undefined}
            disabled={props.disabled}
            style={{ left: `${((h.start - props.start) / d) * 100}%`, width: `${Math.max(0.6, ((h.end - h.start) / d) * 100)}%` }}
            title={`${t("search.hit.range", { a: (h.start - props.start).toFixed(2), b: (h.end - props.start).toFixed(2) })} · ${evidenceDetail(h, props.kind)}`}
            onClick={(e) => {
              e.stopPropagation();
              props.onLocate(i);
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              props.onMenu(i, e);
            }}
            data-testid="hit"
          />
        ))}
      </div>
      <span className={s.hitcount}>{t("search.hit.count", { n: props.hits.length })}</span>
    </div>
  );
}

export function HitChips(props: {
  hits: ResultHit[];
  kind: "speech" | "pitch";
  start: number;
  focusIndex: number | null;
  playing: number | null;
  pad: boolean;
  onPad: (v: boolean) => void;
  onPlay: (i: number, version: "original" | "stretched") => void;
  onLocate: (i: number) => void;
  onMenu: (i: number, e: React.MouseEvent) => void;
}) {
  return (
    <div className={s.chips} data-testid="hit-chips">
      {props.hits.map((h, i) => (
        <span
          key={i}
          className={s.hc}
          data-on={props.focusIndex === i || undefined}
          onClick={(e) => {
            e.stopPropagation();
            props.onLocate(i);
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
            props.onMenu(i, e);
          }}
          data-testid="hit-chip"
        >
          <button
            type="button"
            className={s.hplay}
            title={props.kind === "pitch" ? t("search.hit.playPitch") : t("search.hit.play")}
            aria-label={props.kind === "pitch" ? t("search.hit.playPitch") : t("search.hit.play")}
            onClick={(e) => {
              e.stopPropagation();
              props.onPlay(i, "original");
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (props.kind === "speech") props.onPlay(i, "stretched");
            }}
            data-testid="hit-play"
          >
            {props.playing === i ? <Square size={11} /> : <Play size={11} />}
          </button>
          <span className="num">{t("search.hit.range", { a: (h.start - props.start).toFixed(2), b: (h.end - props.start).toFixed(2) })}</span>
          <span className={s.ev} data-approx={(props.kind === "speech" && h.evidence && !h.evidence.strict) || undefined} title={evidenceDetail(h, props.kind)}>
            {evidenceText(h, props.kind)}
          </span>
        </span>
      ))}
      {props.kind === "speech" ? (
        <Checkbox isSelected={props.pad} onChange={props.onPad} label={t("search.hit.pad")}>
          <span className={s.hint}>{t("search.hit.pad")}</span>
        </Checkbox>
      ) : null}
    </div>
  );
}
