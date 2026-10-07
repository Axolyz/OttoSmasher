// 原片时间线（UI_PLAN §4、§6.2；ARCHITECTURE §13：整集时间线用自绘画布，按视口向 Core 取峰值）。
// - 峰值：整段一份粗的（总览条与兜底），视口一份细的（点数 = 像素宽，≤32000）；还没生成时等 peaks.ready。
// - 手势：单击移动播放头；拖动（>3 px）新建选区，拖两端调整，不能整体拖动；双击从此处播放；
//   滚轮以指针为中心缩放，Shift+滚轮平移；总览条点击/拖动跳到该处。
// - 两层画布：波形与刻度（视口或峰值变化时重画）、选区与播放头（每帧）。
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import { beginDragOut } from "../dragout";
import { clock } from "../format";
import { errorText, t } from "../i18n";
import s from "./Sources.module.css";

export interface Sel {
  a: number;
  b: number;
}

interface PeaksWire {
  state: "ready" | "pending";
  start?: number;
  step?: number;
  min?: Uint8Array;
  max?: Uint8Array;
  count?: number;
}

interface Peaks {
  start: number;
  step: number;
  min: Float32Array;
  max: Float32Array;
}

export interface TimelineHandle {
  fit(): void;
  zoomTo(a: number, b: number): void;
  view(): [number, number];
}

const MIN_SPAN = 0.05;
const RULER_H = 20;
const OVERVIEW_H = 18;
const HANDLE_PX = 5;
const STEPS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

function toFloats(b: Uint8Array | undefined): Float32Array {
  if (!b) return new Float32Array(0);
  const copy = new Uint8Array(b.byteLength);
  copy.set(b);
  return new Float32Array(copy.buffer);
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

async function fetchPeaks(assetId: string, a: number, b: number, points: number): Promise<Peaks | "pending"> {
  const r = await call<PeaksWire>("peaks.get", { assetId, start: a, end: b, points: Math.max(1, Math.min(32000, Math.round(points))) });
  if (r.state !== "ready") return "pending";
  return { start: r.start!, step: r.step!, min: toFloats(r.min), max: toFloats(r.max) };
}

function drawPeaks(ctx: CanvasRenderingContext2D, p: Peaks, v0: number, v1: number, w: number, top: number, h: number) {
  const span = v1 - v0;
  const mid = top + h / 2;
  const amp = h / 2 - 1;
  const first = Math.max(0, Math.floor((v0 - p.start) / p.step));
  const last = Math.min(p.min.length - 1, Math.ceil((v1 - p.start) / p.step));
  for (let i = first; i <= last; i++) {
    const t0 = p.start + i * p.step;
    const x0 = ((t0 - v0) / span) * w;
    const x1 = ((t0 + p.step - v0) / span) * w;
    const y0 = mid - p.max[i]! * amp;
    const y1 = mid - p.min[i]! * amp;
    ctx.fillRect(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));
  }
}

export const Timeline = forwardRef<
  TimelineHandle,
  {
    assetId: string | null;
    /** 时间线长度（原片秒） */
    duration: number;
    /** 当前音源的资产：原片秒 = 局部秒 + offset；只覆盖 [offset, offset + assetDuration]（分离声部可能只覆盖一段） */
    offset?: number;
    assetDuration?: number;
    playhead: () => number | null;
    playing: boolean;
    selection: Sel | null;
    onSelection: (s: Sel | null) => void;
    onSeek: (t: number) => void;
    onPlayFrom: (t: number) => void;
    /** ⌥ 拖出选区：返回生成好的文件（按下时冻结选区） */
    onDragOut?: (sel: Sel) => Promise<string[]>;
  }
>(function Timeline(props, ref) {
  const { assetId, duration } = props;
  const offset = props.offset ?? 0;
  const assetDur = props.assetDuration ?? duration;
  const covered: [number, number] = [offset, offset + assetDur];
  // 峰值按资产局部秒取，起点平移到原片秒
  const shifted = (p: Peaks): Peaks => ({ ...p, start: p.start + offset });
  const wrap = useRef<HTMLDivElement>(null);
  const base = useRef<HTMLCanvasElement>(null);
  const over = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<[number, number]>([0, Math.max(duration, MIN_SPAN)]);
  const [whole, setWhole] = useState<Peaks | null>(null);
  const [detail, setDetail] = useState<Peaks | null>(null);
  const [status, setStatus] = useState<"ok" | "pending" | string>("ok");
  const viewRef = useRef(view);
  viewRef.current = view;
  const propsRef = useRef(props);
  propsRef.current = props;

  const clampView = useCallback(
    (a: number, b: number): [number, number] => {
      const total = Math.max(duration, MIN_SPAN);
      let span = Math.min(Math.max(b - a, MIN_SPAN), total);
      let v0 = Math.max(0, Math.min(a, total - span));
      if (!Number.isFinite(v0)) v0 = 0;
      span = Math.min(span, total - v0);
      return [v0, v0 + span];
    },
    [duration],
  );

  useImperativeHandle(
    ref,
    () => ({
      fit: () => setView(clampView(0, duration)),
      zoomTo: (a, b) => {
        const pad = (b - a) * 0.08;
        setView(clampView(a - pad, b + pad));
      },
      view: () => viewRef.current,
    }),
    [clampView, duration],
  );

  // 换资产 / 时长：回到整段
  useEffect(() => {
    setView(clampView(0, duration));
    setWhole(null);
    setDetail(null);
  }, [assetId, duration, clampView]);

  // 尺寸
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // 峰值：整段（粗）与视口（细）
  const [nonce, setNonce] = useState(0);
  useCoreEvent("peaks.ready", (d) => {
    if (assetId && (d as { assetIds: string[] }).assetIds.includes(assetId)) setNonce((n) => n + 1);
  });
  useCoreEvent("peaks.failed", (d) => {
    const ev = d as { assetIds: string[]; error: { code: string; args: Record<string, unknown> } };
    if (assetId && ev.assetIds.includes(assetId)) setStatus(errorText(ev.error));
  });
  useEffect(() => {
    if (!assetId || !size.w || duration <= 0) return;
    let live = true;
    fetchPeaks(assetId, 0, assetDur, size.w * Math.min(1, assetDur / duration))
      .then((p) => {
        if (!live) return;
        if (p === "pending") setStatus("pending");
        else {
          setWhole(shifted(p));
          setStatus("ok");
        }
      })
      .catch((e) => live && setStatus(e instanceof CoreFailure ? errorText(e.wire) : String(e)));
    return () => {
      live = false;
    };
  }, [assetId, duration, assetDur, offset, size.w, nonce]);
  useEffect(() => {
    if (!assetId || !size.w || !whole) return;
    let live = true;
    const timer = setTimeout(() => {
      const dpr = window.devicePixelRatio || 1;
      const a = Math.max(view[0], covered[0]) - offset;
      const b = Math.min(view[1], duration, covered[1]) - offset;
      if (!(b > a)) return setDetail(null);
      fetchPeaks(assetId, a, b, size.w * dpr * ((b - a) / (view[1] - view[0])))
        .then((p) => live && p !== "pending" && setDetail(shifted(p)))
        .catch(() => {});
    }, 60);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [assetId, view, size.w, whole, duration, offset, assetDur]);

  const waveTop = RULER_H;
  const waveH = Math.max(10, size.h - RULER_H - OVERVIEW_H);

  // 底层：刻度 + 波形 + 总览条
  useEffect(() => {
    const c = base.current;
    if (!c || !size.w) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size.w * dpr;
    c.height = size.h * dpr;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    const [v0, v1] = view;
    const span = v1 - v0;
    // 刻度
    const step = STEPS.find((st) => (st / span) * size.w >= 80) ?? 600;
    const dec = step < 0.01 ? 3 : step < 0.1 ? 2 : step < 1 ? 1 : 0;
    ctx.fillStyle = cssVar("--muted");
    ctx.strokeStyle = cssVar("--line");
    ctx.font = `11px ${cssVar("--font-mono")}`;
    ctx.beginPath();
    for (let tt = Math.ceil(v0 / step) * step; tt <= v1; tt += step) {
      const x = Math.round(((tt - v0) / span) * size.w) + 0.5;
      ctx.moveTo(x, RULER_H - 6);
      ctx.lineTo(x, RULER_H);
      ctx.fillText(clock(tt, dec), x + 3, 12);
    }
    ctx.stroke();
    ctx.fillStyle = cssVar("--line2");
    ctx.fillRect(0, waveTop + waveH / 2, size.w, 1);
    // 波形：先画粗的兜底，再画细的
    ctx.fillStyle = cssVar("--wave");
    const cv0 = Math.max(v0, covered[0]);
    const cv1 = Math.min(v1, duration, covered[1]);
    if (detail && detail.start <= cv0 + span * 0.01 && detail.start + detail.step * detail.min.length >= cv1 - span * 0.01) {
      drawPeaks(ctx, detail, v0, v1, size.w, waveTop, waveH);
    } else if (whole) {
      drawPeaks(ctx, whole, v0, v1, size.w, waveTop, waveH);
    }
    // 当前音源没有覆盖的部分：淡色遮罩（只覆盖部分范围的分离声部）
    if (covered[0] > v0 || covered[1] < Math.min(v1, duration)) {
      ctx.fillStyle = cssVar("--s2");
      ctx.globalAlpha = 0.7;
      if (covered[0] > v0) ctx.fillRect(0, waveTop, ((Math.min(covered[0], v1) - v0) / span) * size.w, waveH);
      if (covered[1] < v1) ctx.fillRect(((Math.max(covered[1], v0) - v0) / span) * size.w, waveTop, size.w, waveH);
      ctx.globalAlpha = 1;
    }
    // 总览条
    const oy = size.h - OVERVIEW_H;
    ctx.fillStyle = cssVar("--s2");
    ctx.fillRect(0, oy, size.w, OVERVIEW_H);
    if (whole) {
      ctx.fillStyle = cssVar("--wave2");
      drawPeaks(ctx, whole, 0, duration, size.w, oy + 1, OVERVIEW_H - 2);
    }
    ctx.strokeStyle = cssVar("--accent");
    ctx.lineWidth = 1;
    ctx.strokeRect((v0 / duration) * size.w + 0.5, oy + 0.5, Math.max(3, (span / duration) * size.w) - 1, OVERVIEW_H - 1);
  }, [size, view, whole, detail, duration, waveTop, waveH, covered[0], covered[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  // 上层：选区 + 播放头（每帧），播放时视口跟随
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const c = over.current;
      const p = propsRef.current;
      if (c && size.w) {
        const dpr = window.devicePixelRatio || 1;
        if (c.width !== size.w * dpr) {
          c.width = size.w * dpr;
          c.height = size.h * dpr;
        }
        const ctx = c.getContext("2d")!;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, size.w, size.h);
        const [v0, v1] = viewRef.current;
        const x = (tt: number) => ((tt - v0) / (v1 - v0)) * size.w;
        if (p.selection) {
          const xa = x(p.selection.a);
          const xb = x(p.selection.b);
          ctx.fillStyle = cssVar("--accentbg");
          ctx.fillRect(xa, waveTop, xb - xa, waveH);
          ctx.fillStyle = cssVar("--accent");
          ctx.fillRect(Math.round(xa) - 1, waveTop, 2, waveH);
          ctx.fillRect(Math.round(xb) - 1, waveTop, 2, waveH);
        }
        const ph = p.playhead();
        if (ph != null) {
          const px = x(ph);
          ctx.fillStyle = cssVar("--text");
          ctx.fillRect(Math.round(px), RULER_H - 4, 1, size.h - RULER_H - OVERVIEW_H + 4);
          const ox = (ph / duration) * size.w;
          ctx.fillRect(Math.round(ox), size.h - OVERVIEW_H, 1, OVERVIEW_H);
          if (p.playing && (ph > v1 || ph < v0)) {
            const span = v1 - v0;
            setView(clampView(ph - span * 0.1, ph + span * 0.9));
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [size, duration, waveTop, waveH, clampView]);

  // 手势
  const timeAt = (clientX: number) => {
    const r = wrap.current!.getBoundingClientRect();
    const [v0, v1] = viewRef.current;
    return Math.max(0, Math.min(duration, v0 + ((clientX - r.left) / r.width) * (v1 - v0)));
  };
  const drag = useRef<null | { kind: "new" | "a" | "b" | "overview"; x0: number; t0: number; moved: boolean }>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    if (e.altKey) {
      // ⌥ 拖出：只在选区内按下才接管（规格 12 §12.2），选区在按下时冻结
      const sel = propsRef.current.selection;
      const tt = timeAt(e.clientX);
      const r0 = wrap.current!.getBoundingClientRect();
      if (sel && propsRef.current.onDragOut && tt >= sel.a && tt <= sel.b && e.clientY - r0.top < r0.height - OVERVIEW_H) {
        const frozen = { ...sel };
        const fn = propsRef.current.onDragOut;
        beginDragOut(e, () => fn(frozen));
      }
      return;
    }
    const r = wrap.current!.getBoundingClientRect();
    const y = e.clientY - r.top;
    (e.target as Element).setPointerCapture(e.pointerId);
    if (y >= r.height - OVERVIEW_H) {
      drag.current = { kind: "overview", x0: e.clientX, t0: 0, moved: true };
      const tt = ((e.clientX - r.left) / r.width) * duration;
      const [v0, v1] = viewRef.current;
      setView(clampView(tt - (v1 - v0) / 2, tt + (v1 - v0) / 2));
      return;
    }
    const tt = timeAt(e.clientX);
    const sel = propsRef.current.selection;
    if (sel) {
      const [v0, v1] = viewRef.current;
      const px = (q: number) => r.left + ((q - v0) / (v1 - v0)) * r.width;
      if (Math.abs(e.clientX - px(sel.a)) <= HANDLE_PX) {
        drag.current = { kind: "a", x0: e.clientX, t0: tt, moved: false };
        return;
      }
      if (Math.abs(e.clientX - px(sel.b)) <= HANDLE_PX) {
        drag.current = { kind: "b", x0: e.clientX, t0: tt, moved: false };
        return;
      }
    }
    drag.current = { kind: "new", x0: e.clientX, t0: tt, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) {
      // 光标提示：选区两端可拖
      const sel = propsRef.current.selection;
      const el = wrap.current;
      if (el && sel) {
        const r = el.getBoundingClientRect();
        const [v0, v1] = viewRef.current;
        const px = (q: number) => r.left + ((q - v0) / (v1 - v0)) * r.width;
        const near = Math.abs(e.clientX - px(sel.a)) <= HANDLE_PX || Math.abs(e.clientX - px(sel.b)) <= HANDLE_PX;
        el.style.cursor = near ? "ew-resize" : "text";
      }
      return;
    }
    if (d.kind === "overview") {
      const r = wrap.current!.getBoundingClientRect();
      const tt = ((e.clientX - r.left) / r.width) * duration;
      const [v0, v1] = viewRef.current;
      setView(clampView(tt - (v1 - v0) / 2, tt + (v1 - v0) / 2));
      return;
    }
    if (!d.moved && Math.abs(e.clientX - d.x0) <= 3) return;
    d.moved = true;
    const tt = timeAt(e.clientX);
    const sel = propsRef.current.selection;
    if (d.kind === "new") propsRef.current.onSelection({ a: Math.min(d.t0, tt), b: Math.max(d.t0, tt) });
    else if (sel) {
      const a = d.kind === "a" ? tt : sel.a;
      const b = d.kind === "b" ? tt : sel.b;
      propsRef.current.onSelection({ a: Math.min(a, b), b: Math.max(a, b) });
      if (a > b) d.kind = d.kind === "a" ? "b" : "a";
    }
  };
  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.kind === "new" && !d.moved) propsRef.current.onSeek(d.t0);
    const sel = propsRef.current.selection;
    if (sel && sel.b - sel.a < 0.001) propsRef.current.onSelection(null); // 太短的选区当作没选
  };
  const onDoubleClick = (e: React.MouseEvent) => propsRef.current.onPlayFrom(timeAt(e.clientX));

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const [v0, v1] = viewRef.current;
      const span = v1 - v0;
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        const dx = (e.shiftKey ? e.deltaY || e.deltaX : e.deltaX) / r.width;
        setView(clampView(v0 + dx * span, v1 + dx * span));
        return;
      }
      const f = Math.exp(e.deltaY * 0.002);
      const at = v0 + ((e.clientX - r.left) / r.width) * span;
      const ns = Math.max(MIN_SPAN, span * f);
      const k = (at - v0) / span;
      setView(clampView(at - k * ns, at - k * ns + ns));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [clampView]);

  return (
    <div
      ref={wrap}
      className={s.timeline}
      data-testid="timeline"
      data-view={`${view[0].toFixed(3)},${view[1].toFixed(3)}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={onDoubleClick}
    >
      <canvas ref={base} className={s.tlCanvas} />
      <canvas ref={over} className={s.tlCanvas} />
      {status !== "ok" ? (
        <div className={s.tlStatus} data-testid="timeline-status">
          {status === "pending" ? t("sources.timeline.pending") : status}
        </div>
      ) : null}
    </div>
  );
});
