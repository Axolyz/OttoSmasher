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
import { type Boundary, type EditBand, boundaries, boundaryNear, limits, moveBoundary } from "./bounds";
import { bandAt, bandsAt, snapExtend } from "./snap";
import s from "./Sources.module.css";

/** 图层上的一个区间（原片秒） */
export interface LayerBand {
  a: number;
  b: number;
  label: string;
  /** 颜色：台词 / 音效 / OP·ED / 区段 / 派生采样 */
  tone: "line" | "sfx" | "oped" | "seg" | "derived" | "vowel" | "consonant" | "pause";
  /** 派生轨：采样 ID */
  id?: string;
}
export interface Layer {
  id: string;
  label: string;
  bands: LayerBand[];
}

/** 叠在波形上的曲线（F0）：第 i 个值在 t0 + i × step（原片秒）；NaN = 不画（不可靠帧） */
export interface Curve {
  t0: number;
  step: number;
  values: Float32Array;
}

export interface Sel {
  a: number;
  b: number;
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
const LANE_H = 16;
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
  const r = await call("peaks.get", { assetId, start: a, end: b, points: Math.max(1, Math.min(32000, Math.round(points))) });
  if (r.state !== "ready") return "pending";
  return { start: r.start!, step: r.step!, min: toFloats(r.min), max: toFloats(r.max) };
}

/** 画 [from, to]（原片秒，默认整个视口）里的峰值 */
function drawPeaks(ctx: CanvasRenderingContext2D, p: Peaks, v0: number, v1: number, w: number, top: number, h: number, from = v0, to = v1) {
  const span = v1 - v0;
  const mid = top + h / 2;
  const amp = h / 2 - 1;
  const first = Math.max(0, Math.floor((Math.max(v0, from) - p.start) / p.step));
  const last = Math.min(p.min.length - 1, Math.ceil((Math.min(v1, to) - p.start) / p.step) - (to < v1 ? 1 : 0));
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
    /** 选区的颜色：默认主色；gold = 拉平台的“内部拉平”内区（规格 11 §11.2） */
    selectionTone?: "accent" | "gold";
    onSeek: (t: number) => void;
    onPlayFrom: (t: number) => void;
    /** ⌥ 拖出选区：返回生成好的文件（按下时冻结选区） */
    onDragOut?: (sel: Sel) => Promise<string[]>;
    /** 覆盖层（UI_PLAN §3.1：只有一个，盖住整个波形高度；Shift 吸附只对它生效） */
    overlay?: Layer | null;
    /** F0 曲线（金色，对数刻度，按视口里的可见值自动缩放） */
    curve?: Curve | null;
    /** 其他图层：波形下方各一条车道；单击 = 选中那个区间，悬停投影到波形，双击 = 换成覆盖层 */
    lanes?: Layer[];
    onLaneDoubleClick?: (id: string) => void;
    /** 车道上单击：返回 true 表示调用方处理了（派生轨 = 打开采样），不再选中区间。bands = 该处所有区间（重叠时多个） */
    onBandPress?: (laneId: string, bands: LayerBand[], at: { clientX: number; clientY: number }) => boolean;
    /** 编辑覆盖层边界（UI_PLAN §3.1）：只有带 id 的覆盖层区间可拖；相邻共用的边界一起动，不越过邻居。编辑期间不建选区、不跳播放头 */
    editing?: boolean;
    /** 正在编辑的那条（边界表单显示它） */
    editFocus?: string | null;
    onEditBands?: (bands: LayerBand[]) => void;
    onEditFocus?: (id: string | null) => void;
    /** 右键：光标处的时间、覆盖层上的区间、车道（若在车道上）与其区间 */
    onContextMenu?: (t: number, hits: { overlay: LayerBand[]; lane: { id: string; bands: LayerBand[] } | null }, at: { clientX: number; clientY: number }) => void;
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
  // 细峰值：取视口左右各多一个视口宽的范围（平移时不用马上重取）；已有的细峰值覆盖视口且精度合适就不取；
  // 拖动中最多每 150 ms 取一次（不是等停下来才取）
  const lastDetailAt = useRef(0);
  const detailRef = useRef(detail);
  detailRef.current = detail;
  // 拖动中视口每帧都在变：不能因为视口变了就丢掉在途的结果，只丢“比已采用的更旧的”和换了资产的
  const detailSeq = useRef({ sent: 0, applied: 0 });
  const assetRef = useRef(assetId);
  assetRef.current = assetId;
  useEffect(() => {
    if (!assetId || !size.w || !whole) return;
    const dpr = window.devicePixelRatio || 1;
    const span = view[1] - view[0];
    const perPx = span / (size.w * dpr);
    const cur = detailRef.current;
    if (cur) {
      const c0 = cur.start;
      const c1 = cur.start + cur.step * cur.min.length;
      const vis0 = Math.max(view[0], covered[0]);
      const vis1 = Math.min(view[1], duration, covered[1]);
      if (c0 <= vis0 + 1e-9 && c1 >= vis1 - 1e-9 && cur.step <= perPx * 1.5 && cur.step >= perPx / 3) return;
    }
    const run = () => {
      lastDetailAt.current = performance.now();
      const a = Math.max(view[0] - span, covered[0]) - offset;
      const b = Math.min(view[1] + span, duration, covered[1]) - offset;
      if (!(b > a)) return setDetail(null);
      const my = ++detailSeq.current.sent;
      const forAsset = assetId;
      fetchPeaks(assetId, a, b, (b - a) / perPx)
        .then((p) => {
          if (p === "pending" || assetRef.current !== forAsset || my < detailSeq.current.applied) return;
          detailSeq.current.applied = my;
          setDetail(shifted(p));
        })
        .catch(() => {});
    };
    const wait = Math.max(0, Math.min(60, 150 - (performance.now() - lastDetailAt.current)));
    const timer = setTimeout(run, wait);
    return () => clearTimeout(timer);
  }, [assetId, view, size.w, whole, duration, offset, assetDur]);

  const lanes = props.lanes ?? [];
  const lanesH = lanes.length * LANE_H;
  const waveTop = RULER_H;
  const waveH = Math.max(10, size.h - RULER_H - OVERVIEW_H - lanesH);
  const laneTop = waveTop + waveH;
  const hover = useRef<LayerBand | null>(null);

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
    // 细峰值覆盖到的部分用细的，其余用整段的粗峰值（拖动平移时不整片退回粗的；R22.10）
    const d0 = detail ? detail.start : Infinity;
    const d1 = detail ? detail.start + detail.step * detail.min.length : -Infinity;
    const useDetail = detail && d0 < cv1 && d1 > cv0;
    if (whole) {
      if (!useDetail) drawPeaks(ctx, whole, v0, v1, size.w, waveTop, waveH);
      else {
        if (d0 > v0) drawPeaks(ctx, whole, v0, v1, size.w, waveTop, waveH, v0, d0);
        if (d1 < v1) drawPeaks(ctx, whole, v0, v1, size.w, waveTop, waveH, d1, v1);
      }
    }
    if (useDetail) drawPeaks(ctx, detail, v0, v1, size.w, waveTop, waveH, d0, d1);
    // 覆盖层：半透明色带盖住整个波形高度，边界线，标签贴底
    const toneColor = (tone: LayerBand["tone"]) =>
      cssVar(
        tone === "sfx" ? "--nat-unpitched" : tone === "oped" ? "--warn" : tone === "seg" ? "--nat-pitched" : tone === "derived" ? "--accent" : tone === "consonant" ? "--sub" : tone === "pause" ? "--faint" : "--nat-speech",
      );
    const X = (tt: number) => ((tt - v0) / span) * size.w;
    for (const band of props.overlay?.bands ?? []) {
      if (band.b < v0 || band.a > v1) continue;
      const xa = X(band.a);
      const xb = X(band.b);
      ctx.fillStyle = toneColor(band.tone);
      ctx.globalAlpha = 0.14;
      ctx.fillRect(xa, waveTop, xb - xa, waveH);
      ctx.globalAlpha = 0.6;
      ctx.fillRect(Math.round(xa), waveTop, 1, waveH);
      ctx.fillRect(Math.round(xb), waveTop, 1, waveH);
      ctx.globalAlpha = 1;
      ctx.font = `11px ${cssVar("--font-ja")}`;
      const tw = ctx.measureText(band.label).width;
      if (xb - xa > tw + 6) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(xa + 2, waveTop, xb - xa - 4, waveH);
        ctx.clip();
        ctx.fillStyle = cssVar("--text");
        ctx.fillText(band.label, xa + Math.max(3, (xb - xa - tw) / 2), waveTop + waveH - 5);
        ctx.restore();
      }
    }
    // F0 曲线：可见范围内可靠值的对数刻度（上下各留 15%）
    const cv = props.curve;
    if (cv && cv.values.length) {
      const i0 = Math.max(0, Math.floor((v0 - cv.t0) / cv.step));
      const i1 = Math.min(cv.values.length - 1, Math.ceil((v1 - cv.t0) / cv.step));
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = i0; i <= i1; i++) {
        const v = cv.values[i]!;
        if (Number.isFinite(v) && v > 0) {
          lo = Math.min(lo, Math.log2(v));
          hi = Math.max(hi, Math.log2(v));
        }
      }
      if (Number.isFinite(lo)) {
        const pad = Math.max(0.25, (hi - lo) * 0.15);
        const Y = (v: number) => waveTop + waveH - ((Math.log2(v) - (lo - pad)) / (hi - lo + 2 * pad)) * waveH;
        ctx.strokeStyle = cssVar("--gold");
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        let pen = false;
        for (let i = i0; i <= i1; i++) {
          const v = cv.values[i]!;
          if (!(Number.isFinite(v) && v > 0)) {
            pen = false;
            continue;
          }
          const x = X(cv.t0 + i * cv.step);
          if (pen) ctx.lineTo(x, Y(v));
          else ctx.moveTo(x, Y(v));
          pen = true;
        }
        ctx.stroke();
        ctx.lineWidth = 1;
      }
    }
    // 编辑模式：可拖的边界画成把手，正在编辑的那条描边
    if (props.editing) {
      ctx.strokeStyle = cssVar("--accent");
      ctx.lineWidth = 2;
      for (const band of props.overlay?.bands ?? []) {
        if (!band.id || band.b < v0 || band.a > v1) continue;
        const xa = X(band.a);
        const xb = X(band.b);
        if (band.id === props.editFocus) ctx.strokeRect(xa + 1, waveTop + 1, xb - xa - 2, waveH - 2);
        // 区间太窄（整集视图下几百句）时只画细线，放大后才画把手——不然整片波形被涂满
        ctx.fillStyle = cssVar("--accent");
        const wide = xb - xa >= 12;
        if (xb - xa < 4) continue; // 太密：不额外画，放大后再编辑
        for (const x of [xa, xb]) {
          ctx.fillRect(Math.round(x) - (wide ? 1 : 0), waveTop, wide ? 2 : 1, waveH);
          if (wide) ctx.fillRect(Math.round(x) - 3, waveTop, 6, 10);
        }
      }
      ctx.lineWidth = 1;
    }
    // 车道：每层一条细带
    lanes.forEach((lane, i) => {
      const y = laneTop + i * LANE_H;
      ctx.fillStyle = cssVar("--s1");
      ctx.fillRect(0, y, size.w, LANE_H);
      for (const band of lane.bands) {
        if (band.b < v0 || band.a > v1) continue;
        const xa = Math.max(0, X(band.a));
        const xb = Math.min(size.w, X(band.b));
        ctx.fillStyle = toneColor(band.tone);
        ctx.globalAlpha = 0.35;
        ctx.fillRect(xa, y + 2, Math.max(2, xb - xa - 1), LANE_H - 4);
        ctx.globalAlpha = 1;
        if (xb - xa > 24) {
          ctx.save();
          ctx.beginPath();
          ctx.rect(xa, y, xb - xa - 2, LANE_H);
          ctx.clip();
          ctx.fillStyle = cssVar("--sub");
          ctx.font = `10px ${cssVar("--font-ja")}`;
          ctx.fillText(band.label, xa + 3, y + LANE_H - 4);
          ctx.restore();
        }
      }
      ctx.font = `10px ${cssVar("--font")}`;
      const w = ctx.measureText(lane.label).width;
      ctx.fillStyle = cssVar("--s1");
      ctx.fillRect(size.w - w - 10, y, w + 10, LANE_H);
      ctx.fillStyle = cssVar("--muted");
      ctx.fillText(lane.label, size.w - w - 4, y + LANE_H - 4);
    });
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
  }, [size, view, whole, detail, duration, waveTop, waveH, covered[0], covered[1], props.overlay, props.curve, props.lanes, props.editing, props.editFocus]); // eslint-disable-line react-hooks/exhaustive-deps

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
          const gold = p.selectionTone === "gold";
          ctx.fillStyle = cssVar(gold ? "--gold" : "--accentbg");
          if (gold) ctx.globalAlpha = 0.16;
          ctx.fillRect(xa, waveTop, xb - xa, waveH);
          ctx.globalAlpha = 1;
          ctx.fillStyle = cssVar(gold ? "--gold" : "--accent");
          ctx.fillRect(Math.round(xa) - 1, waveTop, 2, waveH);
          ctx.fillRect(Math.round(xb) - 1, waveTop, 2, waveH);
        }
        const hv = hover.current;
        if (hv) {
          // 悬停车道上的区间：投影到波形（虚线 + 淡色）
          const xa = x(hv.a);
          const xb = x(hv.b);
          ctx.fillStyle = cssVar("--text");
          ctx.globalAlpha = 0.06;
          ctx.fillRect(xa, waveTop, xb - xa, waveH);
          ctx.globalAlpha = 0.7;
          ctx.setLineDash([3, 3]);
          ctx.strokeStyle = cssVar("--text");
          ctx.strokeRect(xa + 0.5, waveTop + 0.5, xb - xa - 1, waveH - 1);
          ctx.setLineDash([]);
          ctx.globalAlpha = 1;
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
  const drag = useRef<null | { kind: "new" | "a" | "b" | "overview"; x0: number; t0: number; moved: boolean; shift: boolean }>(null);
  const edge = useRef<null | { all: Boundary[]; i: number; lim: [number, number]; bands: EditBand[] }>(null);
  const editable = (): EditBand[] => (propsRef.current.overlay?.bands ?? []).filter((x) => x.id).map((x) => ({ key: x.id!, a: x.a, b: x.b }));
  const toX = (tt: number) => {
    const r = wrap.current!.getBoundingClientRect();
    const [v0, v1] = viewRef.current;
    return r.left + ((tt - v0) / (v1 - v0)) * r.width;
  };
  const laneAt = (clientY: number): number => {
    const r = wrap.current!.getBoundingClientRect();
    const y = clientY - r.top;
    return y >= laneTop && y < laneTop + lanesH ? Math.floor((y - laneTop) / LANE_H) : -1;
  };

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
    if (propsRef.current.editing && y >= waveTop && y < waveTop + waveH) {
      // 编辑模式：按在边界上 = 拖边界；按在区间里 = 让表单显示它
      const bands = editable();
      const all = boundaries(bands);
      const i = boundaryNear(all, e.clientX, toX, HANDLE_PX);
      if (i >= 0) {
        edge.current = { all, i, lim: limits(all, i, bands, duration), bands };
        propsRef.current.onEditFocus?.(all[i]!.items[0]!.key);
      } else {
        const hit = bandAt(timeAt(e.clientX), propsRef.current.overlay?.bands.filter((x) => x.id) ?? []);
        propsRef.current.onEditFocus?.(hit?.id ?? null);
      }
      return;
    }
    const li = laneAt(e.clientY);
    if (li >= 0) {
      // 车道上单击 = 选中那个区间（不移动播放头）
      const hits = bandsAt(timeAt(e.clientX), lanes[li]!.bands);
      if (hits.length && propsRef.current.onBandPress?.(lanes[li]!.id, hits, { clientX: e.clientX, clientY: e.clientY })) return;
      if (hits[0]) propsRef.current.onSelection({ a: hits[0].a, b: hits[0].b });
      return;
    }
    if (y >= r.height - OVERVIEW_H) {
      drag.current = { kind: "overview", x0: e.clientX, t0: 0, moved: true, shift: false };
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
        drag.current = { kind: "a", x0: e.clientX, t0: tt, moved: false, shift: false };
        return;
      }
      if (Math.abs(e.clientX - px(sel.b)) <= HANDLE_PX) {
        drag.current = { kind: "b", x0: e.clientX, t0: tt, moved: false, shift: false };
        return;
      }
    }
    drag.current = { kind: "new", x0: e.clientX, t0: tt, moved: false, shift: e.shiftKey };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const ed = edge.current;
    if (ed) {
      const moved = moveBoundary(ed.bands, ed.all[ed.i]!, timeAt(e.clientX), ed.lim);
      const byKey = new Map(moved.map((x) => [x.key, x]));
      propsRef.current.onEditBands?.((propsRef.current.overlay?.bands ?? []).map((x) => (x.id && byKey.has(x.id) ? { ...x, a: byKey.get(x.id)!.a, b: byKey.get(x.id)!.b } : x)));
      return;
    }
    if (propsRef.current.editing && !drag.current) {
      const r = wrap.current!.getBoundingClientRect();
      const y = e.clientY - r.top;
      const near = y >= waveTop && y < waveTop + waveH && boundaryNear(boundaries(editable()), e.clientX, toX, HANDLE_PX) >= 0;
      wrap.current!.style.cursor = near ? "ew-resize" : "default";
      return;
    }
    const d = drag.current;
    if (!d) {
      const li = laneAt(e.clientY);
      const hv = li >= 0 ? bandAt(timeAt(e.clientX), lanes[li]!.bands) : null;
      hover.current = hv;
      if (wrap.current) wrap.current.title = hv ? `${hv.label}  ${clock(hv.a)}–${clock(hv.b)}` : "";
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
    if (d.kind === "new") {
      // Shift+拖动：扩展到与覆盖层区间交叠的边界（只一次、不级联，R22.8）
      propsRef.current.onSelection(d.shift ? snapExtend(d.t0, tt, propsRef.current.overlay?.bands ?? []) : { a: Math.min(d.t0, tt), b: Math.max(d.t0, tt) });
    }
    else if (sel) {
      const a = d.kind === "a" ? tt : sel.a;
      const b = d.kind === "b" ? tt : sel.b;
      propsRef.current.onSelection({ a: Math.min(a, b), b: Math.max(a, b) });
      if (a > b) d.kind = d.kind === "a" ? "b" : "a";
    }
  };
  const onPointerUp = () => {
    edge.current = null;
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.kind === "new" && !d.moved) {
      // Shift+单击：选中光标下的整个覆盖层区间（字幕优先：覆盖层默认是字幕）
      const band = d.shift ? bandAt(d.t0, propsRef.current.overlay?.bands ?? []) : null;
      if (band) propsRef.current.onSelection({ a: band.a, b: band.b });
      else propsRef.current.onSeek(d.t0);
    }
    const sel = propsRef.current.selection;
    if (sel && sel.b - sel.a < 0.001) propsRef.current.onSelection(null); // 太短的选区当作没选
  };
  const onContextMenu = (e: React.MouseEvent) => {
    const fn = propsRef.current.onContextMenu;
    if (!fn) return;
    e.preventDefault();
    const r = wrap.current!.getBoundingClientRect();
    const y = e.clientY - r.top;
    const tt = timeAt(e.clientX);
    const li = laneAt(e.clientY);
    const overlay = y >= waveTop && y < waveTop + waveH ? bandsAt(tt, propsRef.current.overlay?.bands ?? []) : [];
    const lane = li >= 0 ? { id: lanes[li]!.id, bands: bandsAt(tt, lanes[li]!.bands) } : null;
    fn(tt, { overlay, lane }, { clientX: e.clientX, clientY: e.clientY });
  };
  const onDoubleClick = (e: React.MouseEvent) => {
    if (propsRef.current.editing) return;
    const li = laneAt(e.clientY);
    if (li >= 0) return propsRef.current.onLaneDoubleClick?.(lanes[li]!.id);
    propsRef.current.onPlayFrom(timeAt(e.clientX));
  };

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
      onPointerLeave={() => (hover.current = null)}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      data-editing={props.editing || undefined}
      style={{ height: 150 + lanesH }}
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
