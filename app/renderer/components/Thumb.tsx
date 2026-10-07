// 列表行的画面缩略图（UI_PLAN D2、§3「每行 88×50，播放按钮在缩略图上」；原型 .th）。
// 图片地址由调用方给（api/thumbs 的 useThumb）；没有画面时显示占位图标（纯音频 ♪ 等），不画假画面。
// play：左下角的试听按钮（左键原声；右键卡拍在阶段 5 接上）。用原生按钮：列表行的按下手势（⌥ 拖出）会跳过按钮。
import type { ReactNode } from "react";
import { Play, Square } from "lucide-react";
import s from "./Collection.module.css";

export function Thumb(props: {
  url: string | null;
  size?: "md" | "sm";
  placeholder?: ReactNode;
  play?: { playing: boolean; onPress: () => void; label: string; testId?: string };
  testId?: string;
}) {
  return (
    <div className={s.thumb} data-size={props.size ?? "md"} data-has-img={props.url ? "" : undefined} data-testid={props.testId}>
      {props.url ? <img src={props.url} alt="" draggable={false} /> : props.play ? null : props.placeholder}
      {props.play ? (
        <button
          type="button"
          className={s.thumbPlay}
          data-playing={props.play.playing || undefined}
          onClick={props.play.onPress}
          aria-label={props.play.label}
          data-testid={props.play.testId}
        >
          {props.play.playing ? <Square /> : <Play />}
        </button>
      ) : null}
    </div>
  );
}
