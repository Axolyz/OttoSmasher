// 舞台画面（UI_PLAN §3：默认 400×225，⤢ 放大到舞台全宽 16:9；点击 = 试听原声 / 停止；规格 12 §12.4）。
// 有效画面：采样自己的绑定 > 原片的画面 > 原片自带的视频流；同步视频与循环动画由 preload 的静音画面播放器显示（跟着试听走，音频是主时钟）；
// 图片直接显示；没有画面时写“此采样没有画面”并给「画面绑定…」。
import { Maximize2, Minimize2 } from "lucide-react";
import { useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import { useThumb } from "../api/thumbs";
import type { SamplePicture } from "../api/types";
import { Button } from "../components/Button";
import { t } from "../i18n";
import s from "./Library.module.css";

export function StagePicture(props: { sampleId: string; wide: boolean; onWide: (v: boolean) => void; onToggle: () => void; onBind: () => void }) {
  const [pic, setPic] = useState<SamplePicture | null>(null);
  const [tick, setTick] = useState(0);
  const thumb = useThumb("sample", props.sampleId, "poster");
  useEffect(() => {
    let live = true;
    void call("visuals.forSample", { id: props.sampleId }).then(
      (p) => live && setPic(p),
      () => live && setPic(null),
    );
    return () => {
      live = false;
    };
  }, [props.sampleId, tick]);
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (c.sample?.includes(props.sampleId) || c.source) setTick((x) => x + 1);
  });
  const b = pic?.binding ?? null;
  const video = !!b && b.state === "ok" && b.mode !== "image";
  // 画布挂上后再让画面播放器换到这个采样（它找 canvas[data-otto-stage-video]）
  useEffect(() => {
    if (!pic) return;
    void window.otto.player.showPicture(video ? props.sampleId : null).catch(() => {});
  }, [pic, video, props.sampleId]);
  useEffect(() => () => void window.otto.player.showPicture(null).catch(() => {}), []);

  return (
    <div className={s.stagePic} data-wide={props.wide || undefined} data-testid="stage-picture" data-mode={b?.mode ?? "none"}>
      {video ? (
        <canvas data-otto-stage-video="" className={s.stagePicMedia} onClick={props.onToggle} />
      ) : b && b.state === "ok" ? (
        thumb ? <img src={thumb} className={s.stagePicMedia} alt="" draggable={false} onClick={props.onToggle} /> : <div className={s.stagePicMedia} />
      ) : (
        <div className={s.stagePicEmpty}>
          <span>{b ? t(`visual.state.${b.state}`) : t("stagePic.none")}</span>
          <Button size="sm" variant="flat" onPress={props.onBind} data-testid="stage-bind">
            {t("visual.menu")}
          </Button>
        </div>
      )}
      {b ? <span className={s.stagePicTag}>{t(`visual.mode.${b.mode}`)}</span> : null}
      <span className={s.stagePicWide}>
        <Button
          size="sm"
          variant="flat"
          icon={props.wide ? <Minimize2 /> : <Maximize2 />}
          onPress={() => props.onWide(!props.wide)}
          aria-label={t(props.wide ? "stagePic.shrink" : "stagePic.widen")}
          data-testid="stage-pic-wide"
        />
      </span>
    </div>
  );
}
