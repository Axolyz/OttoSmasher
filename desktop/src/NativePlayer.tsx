import React, {
  forwardRef,
  useLayoutEffect,
  useRef,
  useState,
  useEffect,
  useImperativeHandle,
} from "react";
import { Button, Slider, Tooltip } from "antd";
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  SoundOutlined,
  MutedOutlined,
} from "@ant-design/icons";
import { attachNativeMedia, setNativeSubtitle } from "./NativeMedia";

const clock = (t: number) =>
  `${Math.floor((t || 0) / 60)}:${Math.floor((t || 0) % 60)
    .toString()
    .padStart(2, "0")}`;
function MediaControls({
  media,
}: {
  media: React.RefObject<HTMLMediaElement | null>;
}) {
  const [state, update] = useState({
    time: 0,
    duration: 0,
    paused: true,
    muted: false,
    error: "",
    decoder: "",
  });
  useEffect(() => {
    const e = media.current;
    if (!e) return;
    const refresh = () =>
      update({
        time: e.currentTime,
        duration: Number.isFinite(e.duration) ? e.duration : 0,
        paused: e.paused,
        muted: e.muted,
        error: e.error?.message || "",
        decoder: e.dataset.decoder || "",
      });
    const events = [
      "timeupdate",
      "loadedmetadata",
      "play",
      "pause",
      "volumechange",
      "error",
      "emptied",
    ];
    events.forEach((name) => e.addEventListener(name, refresh));
    refresh();
    return () => events.forEach((name) => e.removeEventListener(name, refresh));
  }, [media]);
  return (
    <div className="native-media-controls">
      <Button
        aria-label={state.paused ? "播放" : "暂停"}
        type="text"
        icon={state.paused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
        onClick={() => {
          const e = media.current;
          if (e) {
            if (e.paused) void e.play().catch(() => {});
            else e.pause();
          }
        }}
      />
      <span className="native-media-time">
        {clock(state.time)} / {clock(state.duration)}
      </span>
      <Slider
        aria-label="播放位置"
        min={0}
        max={Math.max(0.001, state.duration)}
        step={0.01}
        value={state.time}
        tooltip={{ formatter: (v) => clock(v || 0) }}
        onChange={(t) => {
          if (media.current) media.current.currentTime = t;
        }}
      />
      <Button
        type="text"
        aria-label={state.muted ? "取消静音" : "静音"}
        icon={state.muted ? <MutedOutlined /> : <SoundOutlined />}
        onClick={() => {
          if (media.current) media.current.muted = !media.current.muted;
        }}
      />
      <Tooltip title={state.error || `原生播放 · ${state.decoder || "libmpv"}`}>
        <small className={state.error ? "native-media-error" : ""}>
          {state.error ? "播放失败" : "libmpv"}
        </small>
      </Tooltip>
    </div>
  );
}

export const VideoPlayer = forwardRef<
  HTMLVideoElement,
  React.VideoHTMLAttributes<HTMLVideoElement> & { subtitle?: string; slave?: boolean; audioOnly?: boolean }
>(function VideoPlayer(props, ref) {
  const { src, controls, autoPlay, muted, subtitle = "", slave = false, audioOnly = false, ...rest } = props;
  const media = useRef<HTMLVideoElement>(null);
  useImperativeHandle(ref, () => media.current!);
  const native = !!window.ottoDesktop?.player;
  useLayoutEffect(() => {
    if (!native || !media.current) return;
    const element = media.current,
      player = attachNativeMedia(element, !audioOnly)!;
    let previous = "",
      hidden = false;
    const geometry = () => {
      const r = element.getBoundingClientRect();
      let left=Math.max(0,r.left),top=Math.max(0,r.top),right=Math.min(innerWidth,r.right),bottom=Math.min(innerHeight,r.bottom);
      let visible =
        !!element.getClientRects().length &&
        r.width > 1 &&
        r.height > 1 &&
        !document.hidden;
      // Native views sit above Chromium: clip scrolling panes and hide for overlays.
      const overlaps = (b: DOMRect) =>
        b.right > r.left &&
        b.left < r.right &&
        b.bottom > r.top &&
        b.top < r.bottom;
      for (const overlay of document.querySelectorAll(
        ".ant-modal-wrap, .ant-drawer-content-wrapper, .ant-select-dropdown, .ant-dropdown, .ant-popover, .otto-descendant-menu",
      )) {
        if (
          !overlay.contains(element) &&
          overlay.getClientRects().length &&
          getComputedStyle(overlay).visibility !== "hidden" &&
          overlaps(overlay.getBoundingClientRect())
        )
          visible = false;
      }
      for (
        let parent = element.parentElement;
        parent;
        parent = parent.parentElement
      ) {
        const css = getComputedStyle(parent),
          box = parent.getBoundingClientRect();
        if (/(auto|scroll|hidden|clip)/.test(css.overflowY)) {
          top=Math.max(top,box.top+parent.clientTop);bottom=Math.min(bottom,box.top+parent.clientTop+parent.clientHeight);
        }
        if (/(auto|scroll|hidden|clip)/.test(css.overflowX)) {
          left=Math.max(left,box.left+parent.clientLeft);right=Math.min(right,box.left+parent.clientLeft+parent.clientWidth);
        }
      }
      visible=visible&&right-left>1&&bottom-top>1;
      const b = {
        x: r.left,
        y: r.top,
        width: r.width,
        height: r.height,
        visible,
        clip:{x:left,y:top,width:Math.max(0,right-left),height:Math.max(0,bottom-top)},
      };
      const key = JSON.stringify(b);
      // Retry until create() has finished, then keep geometry in sync with scrolling/layout.
      if (key !== previous && player.geometry(b)) previous = key;
      if (!element.getClientRects().length && !hidden) element.pause();
      hidden = !element.getClientRects().length;
    };
    const timer = setInterval(geometry, 80);
    geometry();
    return () => {
      clearInterval(timer);
      player.destroy();
    };
  }, [native,audioOnly]);
  useLayoutEffect(() => {
    if (native && media.current) {
      media.current.src = src || "";
      media.current.muted = !!muted;
      if (autoPlay && media.current.getClientRects().length)
        void media.current.play().catch(() => {});
    }
  }, [native, src, autoPlay, muted]);
  useEffect(() => {
    if (native && media.current) setNativeSubtitle(media.current, subtitle);
  }, [native, src, subtitle]);
  return (
    <div className={native ? "native-player" : "browser-player"}>
      <video
        {...rest}
        tabIndex={native ? 0 : props.tabIndex}
        aria-label={native ? "原生视频画面" : props["aria-label"]}
        onKeyDown={
          native
            ? (e) => {
                props.onKeyDown?.(e);
                const m = media.current;
                if (!m || slave) return;
                if (e.code === "Space") {
                  e.preventDefault();
                  if (m.paused) void m.play().catch(() => {});
                  else m.pause();
                }
                if (e.code === "ArrowLeft" || e.code === "ArrowRight") {
                  e.preventDefault();
                  m.currentTime += e.code === "ArrowLeft" ? -5 : 5;
                }
              }
            : props.onKeyDown
        }
        ref={media}
        src={native ? undefined : src}
        controls={!native && controls}
        autoPlay={!native && autoPlay}
        muted={!native && muted}
        onClick={
          native
            ? (e) => {
                props.onClick?.(e);
                const m = media.current;
                if (m && !slave) {
                  if (m.paused) void m.play().catch(() => {});
                  else m.pause();
                }
              }
            : props.onClick
        }
      />
      {native && controls && <MediaControls media={media} />}
    </div>
  );
});

export const NativeAudio = forwardRef<
  HTMLAudioElement,
  React.AudioHTMLAttributes<HTMLAudioElement>
>(function NativeAudio(props, ref) {
  const { src, controls, autoPlay, muted, ...rest } = props;
  const media = useRef<HTMLAudioElement>(null),
    native = !!window.ottoDesktop?.player;
  useImperativeHandle(ref, () => media.current!);
  useLayoutEffect(() => {
    if (!native || !media.current) return;
    const player = attachNativeMedia(media.current)!;
    return () => player.destroy();
  }, [native]);
  useLayoutEffect(() => {
    if (native && media.current) {
      media.current.src = src || "";
      media.current.muted = !!muted;
      if (autoPlay) void media.current.play().catch(() => {});
    }
  }, [native, src, autoPlay, muted]);
  return (
    <>
      <audio
        {...rest}
        ref={media}
        src={native ? undefined : src}
        controls={!native && controls}
        autoPlay={!native && autoPlay}
        muted={!native && muted}
      />
      {native && controls && <MediaControls media={media} />}
    </>
  );
});
