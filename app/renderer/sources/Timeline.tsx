// 原片时间线（UI_PLAN §4、§6.2；ARCHITECTURE §13：整集时间线用自绘画布，按视口向 Core 取峰值）。
// - 峰值：整段一份粗的（总览条与兜底），视口一份细的（点数 = 像素宽，≤32000）；还没生成时等 peaks.ready。
// - 手势：单击移动播放头；拖动（>3 px）新建选区，拖两端调整，不能整体拖动；双击从此处播放；
//   滚轮以指针为中心缩放，Shift+滚轮平移；总览条点击/拖动跳到该处。
// - 两层画布：波形与刻度（视口或峰值变化时重画）、选区与播放头（每帧）。
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import { beginDragOut } from "../dragout";
import { clock } from "../format";
import { errorText, t } from "../i18n";
import { useSettingValue } from "../state/settings";
import { type Boundary, type EditBand, boundaries, boundaryNear, limits, moveBoundary } from "./bounds";
import { midiOf, noteName } from "../pitch";
import { type LabelIn, type LabelOut, layoutLabels } from "./labels";
import { pitchGrid, pitchRange } from "./pitchGrid";
import { bandAt, bandsAt, snapExtend } from "./snap";
import s from "./Sources.module.css";

/** 图层上的一个区间（原片秒） */
export interface LayerBand {
  a: number;
  b: number;
  label: string;
  /** 颜色：台词 / 音效 / OP·ED / 区段 / 采样 */
  tone: "line" | "sfx" | "oped" | "seg" | "derived" | "vowel" | "consonant" | "pause";
  /** 采样车道：采样 ID */
  id?: string;
  /** 突出显示（「返回原素材」带来的那个采样） */
  strong?: boolean;
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
const SPECTRUM_MAX = 30;

/** "#rrggbb" / "rgb(r, g, b)" → [r, g, b] */
function cssRgb(v: string): [number, number, number] {
  const m = v.trim().match(/^#([0-9a-f]{6})$/i);
  if (m) return [parseInt(m[1]!.slice(0, 2), 16), parseInt(m[1]!.slice(2, 4), 16), parseInt(m[1]!.slice(4, 6), 16)];
  const n = v.match(/\d+(\.\d+)?/g)?.map(Number) ?? [200, 200, 200];
  return [n[0] ?? 200, n[1] ?? 200, n[2] ?? 200];
}
const RULER_H = 20;
const OVERVIEW_H = 18;
const LANE_H = 16;
/** 车道里一行标签的高度（车道只排一行） */
const LANE_LINE = 12;
/** 覆盖层标签一行的高度 */
const OVER_LINE = 13;
const LABEL_FONT_OVER = 11;
const LABEL_FONT_LANE = 10;

let measureCtx: CanvasRenderingContext2D | null = null;
function measurer(px: number): (s: string) => number {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  const font = `${px}px ${cssVar("--font-ja")}`;
  return (str: string) => {
    if (!measureCtx) return str.length * px * 0.6;
    measureCtx.font = font;
    return measureCtx.measureText(str).width;
  };
}

/** 一层可见区间的标签排布（labels.ts：避让 + 折行；所有者 2026-10-13） */
function layoutBands(bands: LayerBand[], X: (t: number) => number, w: number, v0: number, v1: number, fontPx: number, maxLines: number) {
  const vis = bands.filter((b) => b.b >= v0 && b.a <= v1 && b.label).sort((p, q) => p.a - q.a || p.b - q.b);
  const items: LabelIn[] = vis.map((b) => ({ a: Math.max(0, X(b.a)), b: Math.min(w, X(b.b)), text: b.label }));
  const out = layoutLabels(items, { measure: measurer(fontPx), maxLines, gap: 4, minX: 2, maxX: w - 2 });
  return vis.map((band, i) => ({ band, label: out[i] ?? null }));
}

/** 画一个排好的标签：各行在标签框里居中，最后一行的基线在 baseline，往上逐行；描一圈底色免得压在波形上看不清 */
function drawLabel(ctx: CanvasRenderingContext2D, l: LabelOut, baseline: number, lineH: number, color: string, halo: string) {
  const n = l.lines.length;
  ctx.lineJoin = "round";
  ctx.lineWidth = 3;
  l.lines.forEach((line, k) => {
    const y = baseline - (n - 1 - k) * lineH;
    const x = l.x + (l.w - ctx.measureText(line).width) / 2;
    ctx.strokeStyle = halo;
    ctx.strokeText(line, x, y);
    ctx.fillStyle = color;
    ctx.fillText(line, x, y);
  });
  ctx.lineWidth = 1;
}
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
    /** 检索命中框（UI_PLAN §2.4：定位命中后画在波形上；绿 = 严格、琥珀 = 近似） */
    hitBox?: { a: number; b: number; approx?: boolean } | null;
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
    /** 频谱细看（规格 05 §5.3.2、L19）：视口 ≤ 30 秒时把波形换成所选音频的频谱（固定 −90–0 dB）；null = 波形 */
    spectrum?: "log" | "linear" | "mel" | null;
    /** 目标音（MIDI；拉平成品）：音高线上画一条虚线 */
    pitchTarget?: number | null;
    /** 覆盖层标签最多显示几行；不给 = 设置 general.label_max_lines（默认 3）。车道上的标签只排一行（避让 + 截短） */
    labelMaxLines?: number;
    /** 可视范围（默认 [0, duration]）：缩放、平移、总览条、选区都只在这里面（详情区 = 采样范围 + 余量，所有者 2026-10-12） */
    bounds?: [number, number];
    /** 同一原片切音轨时保留视口；其他入口默认随资产重置。 */
    viewKey?: string;
    /** 焦点区间：之外的部分淡色遮住（详情区里采样自己的范围；余量里照常能框选） */
    focus?: Sel | null;
    /** 右键：光标处的时间、覆盖层上的区间、车道（若在车道上）与其区间 */
    onContextMenu?: (t: number, hits: { overlay: LayerBand[]; lane: { id: string; bands: LayerBand[] } | null }, at: { clientX: number; clientY: number }) => void;
  }
>(function Timeline(props, ref) {
  const { assetId, duration } = props;
  const offset = props.offset ?? 0;
  const assetDur = props.assetDuration ?? duration;
  const covered: [number, number] = [offset, offset + assetDur];
  const lo = Math.max(0, props.bounds?.[0] ?? 0);
  const hi = Math.min(duration, props.bounds?.[1] ?? duration);
  const extent = Math.max(hi - lo, MIN_SPAN);
  // 峰值按资产局部秒取，起点平移到原片秒
  const shifted = (p: Peaks): Peaks => ({ ...p, start: p.start + offset });
  const wrap = useRef<HTMLDivElement>(null);
  const base = useRef<HTMLCanvasElement>(null);
  const over = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<[number, number]>([lo, lo + extent]);
  const [whole, setWhole] = useState<Peaks | null>(null);
  const [detail, setDetail] = useState<Peaks | null>(null);
  const [status, setStatus] = useState<"ok" | "pending" | string>("ok");
  const viewRef = useRef(view);
  viewRef.current = view;
  const propsRef = useRef(props);
  propsRef.current = props;

  const clampView = useCallback(
    (a: number, b: number): [number, number] => {
      let span = Math.min(Math.max(b - a, MIN_SPAN), extent);
      let v0 = Math.max(lo, Math.min(a, lo + extent - span));
      if (!Number.isFinite(v0)) v0 = lo;
      span = Math.min(span, lo + extent - v0);
      return [v0, v0 + span];
    },
    [lo, extent],
  );

  useImperativeHandle(
    ref,
    () => ({
      fit: () => setView(clampView(lo, hi)),
      zoomTo: (a, b) => {
        const pad = (b - a) * 0.08;
        setView(clampView(a - pad, b + pad));
      },
      view: () => viewRef.current,
    }),
    [clampView, lo, hi],
  );

  // 换资产 / 时长重取峰值；视图身份、时长或可视范围变化时回到整段。
  // 两件事分开：详情区换到同一条轨上的另一个采样只换可视范围，峰值不能丢（丢了不会重取，波形就没了）
  useEffect(() => {
    setWhole(null);
    setDetail(null);
  }, [assetId, duration]);
  useEffect(() => {
    setView(clampView(lo, hi));
  }, [props.viewKey ?? assetId, duration, clampView]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // 频谱：视口（≤30 秒、在资产覆盖范围里的部分）实算；视口变了合并 120 ms 再取
  const [spec, setSpec] = useState<{ a: number; b: number; img: HTMLCanvasElement } | null>(null);
  const [specMsg, setSpecMsg] = useState<string | null>(null);
  useEffect(() => {
    const scale = props.spectrum;
    if (!scale || !assetId || !size.w) {
      setSpec(null);
      setSpecMsg(null);
      return;
    }
    const a = Math.max(view[0], covered[0]);
    const b = Math.min(view[1], duration, covered[1]);
    if (!(b > a)) return setSpec(null);
    if (b - a > SPECTRUM_MAX) {
      setSpec(null);
      setSpecMsg(t("timeline.spectrumZoom", { max: SPECTRUM_MAX }));
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      const cols = Math.max(8, Math.min(2400, Math.round(((b - a) / (view[1] - view[0])) * size.w)));
      const rows = Math.max(16, Math.min(512, Math.round(size.h - RULER_H - OVERVIEW_H)));
      call("spectrum.get", { assetId, start: a - offset, end: b - offset, cols, rows, scale })
        .then((r) => {
          if (!live) return;
          const data = r.data;
          const c = document.createElement("canvas");
          c.width = r.cols;
          c.height = r.rows;
          const g = c.getContext("2d")!;
          const img = g.createImageData(r.cols, r.rows);
          // 单色：强度 = 不透明度，颜色取波形色（设计令牌）；第 0 行是最低频，画在最下面
          const rgb = cssRgb(cssVar("--wave"));
          for (let y = 0; y < r.rows; y++) {
            const src = (r.rows - 1 - y) * r.cols;
            for (let x = 0; x < r.cols; x++) {
              const v = data[src + x]!;
              const o = (y * r.cols + x) * 4;
              img.data[o] = rgb[0];
              img.data[o + 1] = rgb[1];
              img.data[o + 2] = rgb[2];
              img.data[o + 3] = v;
            }
          }
          g.putImageData(img, 0, 0);
          setSpec({ a, b, img: c });
          setSpecMsg(null);
        })
        .catch((e) => live && (setSpec(null), setSpecMsg(e instanceof CoreFailure ? errorText(e.wire) : String(e))));
    }, 120);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [props.spectrum, assetId, view, size.w, size.h, duration, offset, assetDur]); // eslint-disable-line react-hooks/exhaustive-deps

  const lanes = props.lanes ?? [];
  const maxLinesSetting = useSettingValue<number>("general.label_max_lines", 3);
  const maxLines = Math.max(1, Math.min(6, Math.round(props.labelMaxLines ?? maxLinesSetting)));
  // 车道的标签只排一行（避让 + 截短；所有者 2026-10-13：车道折行会让车道随平移忽高忽低、整页跟着跳），车道高度固定
  const laneLayouts = useMemo(() => {
    const [v0, v1] = view;
    const span = v1 - v0 || 1;
    const X = (tt: number) => ((tt - v0) / span) * size.w;
    return lanes.map((lane) => layoutBands(lane.bands, X, size.w, v0, v1, LABEL_FONT_LANE, 1));
  }, [lanes, view, size.w]);
  const laneHs = laneLayouts.map(() => LANE_H);
  const laneYs = laneHs.reduce<number[]>((acc, _h, i) => [...acc, i ? acc[i - 1]! + laneHs[i - 1]! : 0], []);
  const lanesH = laneHs.reduce((a, b) => a + b, 0);
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
    if (props.spectrum && spec) {
      // 频谱盖住这段的波形
      const xa = ((spec.a - v0) / span) * size.w;
      const xb = ((spec.b - v0) / span) * size.w;
      ctx.fillStyle = cssVar("--s1");
      ctx.fillRect(xa, waveTop, xb - xa, waveH);
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(spec.img, xa, waveTop, xb - xa, waveH);
    }
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
    }
    // 覆盖层标签：避让 + 折行，贴底往上排（可以画到区间外；被省略的悬停看全文）
    if (props.overlay) {
      const placed = layoutBands(props.overlay.bands, X, size.w, v0, v1, LABEL_FONT_OVER, maxLines);
      ctx.font = `${LABEL_FONT_OVER}px ${cssVar("--font-ja")}`;
      for (const { label } of placed) if (label) drawLabel(ctx, label, waveTop + waveH - 5, OVER_LINE, cssVar("--text"), cssVar("--bg"));
    }
    // F0 曲线：可见范围内可靠值的对数刻度（上下各留 15%）
    const cv = props.curve;
    if (cv && cv.values.length) {
      // 音高线（所有者 2026-10-13）：纵向按 MIDI 半音，最少 6 个半音、以中位为中心；刻度按疏密自适应（pitchGrid）；拉平成品画目标音虚线
      const i0 = Math.max(0, Math.floor((v0 - cv.t0) / cv.step));
      const i1 = Math.min(cv.values.length - 1, Math.ceil((v1 - cv.t0) / cv.step));
      const vis: number[] = [];
      for (let i = i0; i <= i1; i++) {
        const v = cv.values[i]!;
        if (Number.isFinite(v) && v > 0) vis.push(midiOf(v));
      }
      const target = props.pitchTarget ?? null;
      const range = pitchRange(target != null && vis.length ? [...vis, target] : vis);
      if (range) {
        const [ma, mb] = range;
        const Y = (m: number) => waveTop + waveH - ((m - ma) / (mb - ma)) * waveH;
        // 刻度线与音名（在曲线下面）
        ctx.font = `9px ${cssVar("--font")}`;
        // 只画标了音名的那几条线（所有者 2026-10-13：没标音名的线只会添乱），线比波形底色亮一些，C 再亮一点
        for (const g of pitchGrid(ma, mb, waveH / (mb - ma))) {
          if (!g.label) continue;
          const y = Math.round(Y(g.midi)) + 0.5;
          ctx.strokeStyle = cssVar(g.c ? "--sub" : "--muted");
          ctx.globalAlpha = g.c ? 0.45 : 0.32;
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(size.w, y);
          ctx.stroke();
          ctx.globalAlpha = 1;
          if (y - 11 > waveTop) {
            ctx.lineJoin = "round";
            ctx.lineWidth = 3;
            ctx.strokeStyle = cssVar("--bg");
            ctx.strokeText(noteName(g.midi), 4, y - 2);
            ctx.lineWidth = 1;
            ctx.fillStyle = cssVar(g.c ? "--sub" : "--muted");
            ctx.fillText(noteName(g.midi), 4, y - 2);
          }
        }
        if (target != null) {
          const y = Math.round(Y(target)) + 0.5;
          ctx.strokeStyle = cssVar("--gold");
          ctx.globalAlpha = 0.8;
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(size.w, y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.globalAlpha = 1;
          const label = t("pitch.target", { note: noteName(Math.round(target)) });
          const w = ctx.measureText(label).width;
          ctx.lineWidth = 3;
          ctx.strokeStyle = cssVar("--bg");
          ctx.strokeText(label, size.w - w - 6, y - 3);
          ctx.lineWidth = 1;
          ctx.fillStyle = cssVar("--gold");
          ctx.fillText(label, size.w - w - 6, y - 3);
        }
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
          if (pen) ctx.lineTo(x, Y(midiOf(v)));
          else ctx.moveTo(x, Y(midiOf(v)));
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
      const y = laneTop + laneYs[i]!;
      const LH = laneHs[i]!;
      ctx.fillStyle = cssVar("--s1");
      ctx.fillRect(0, y, size.w, LH);
      for (const band of lane.bands) {
        if (band.b < v0 || band.a > v1) continue;
        const xa = Math.max(0, X(band.a));
        const xb = Math.min(size.w, X(band.b));
        ctx.fillStyle = toneColor(band.tone);
        ctx.globalAlpha = band.strong ? 0.8 : 0.35;
        ctx.fillRect(xa, y + 2, Math.max(2, xb - xa - 1), LH - 4);
        ctx.globalAlpha = 1;
        if (band.strong) {
          ctx.strokeStyle = cssVar("--text");
          ctx.strokeRect(xa + 0.5, y + 1.5, Math.max(2, xb - xa - 1) - 1, LH - 3);
        }
      }
      ctx.font = `${LABEL_FONT_LANE}px ${cssVar("--font-ja")}`;
      for (const { label } of laneLayouts[i] ?? []) if (label) drawLabel(ctx, label, y + LH - 4, LANE_LINE, cssVar("--sub"), cssVar("--s1"));
      // 车道名：不画底框（底框会盖住车道块的末端，看起来像提前截断，所有者 2026-10-12），只给文字描一圈底色
      ctx.font = `10px ${cssVar("--font")}`;
      const w = ctx.measureText(lane.label).width;
      ctx.lineJoin = "round";
      ctx.lineWidth = 3;
      ctx.strokeStyle = cssVar("--s1");
      ctx.strokeText(lane.label, size.w - w - 4, y + LH - 4);
      ctx.lineWidth = 1;
      ctx.fillStyle = cssVar("--muted");
      ctx.fillText(lane.label, size.w - w - 4, y + LH - 4);
    });
    // 当前音源没有覆盖的部分：淡色遮罩（只覆盖部分范围的分离声部）
    if (covered[0] > v0 || covered[1] < Math.min(v1, duration)) {
      ctx.fillStyle = cssVar("--s2");
      ctx.globalAlpha = 0.7;
      if (covered[0] > v0) ctx.fillRect(0, waveTop, ((Math.min(covered[0], v1) - v0) / span) * size.w, waveH);
      if (covered[1] < v1) ctx.fillRect(((Math.max(covered[1], v0) - v0) / span) * size.w, waveTop, size.w, waveH);
      ctx.globalAlpha = 1;
    }
    // 焦点之外（详情区：采样范围之外的余量）：淡色遮罩，照常能框选
    const fc = props.focus;
    if (fc && (fc.a > v0 || fc.b < v1)) {
      ctx.fillStyle = cssVar("--s2");
      ctx.globalAlpha = 0.45;
      if (fc.a > v0) ctx.fillRect(0, waveTop, X(Math.min(fc.a, v1)), waveH);
      if (fc.b < v1) ctx.fillRect(X(Math.max(fc.b, v0)), waveTop, size.w, waveH);
      ctx.globalAlpha = 1;
    }
    // 总览条（有可视范围时只画这个范围）
    const oy = size.h - OVERVIEW_H;
    ctx.fillStyle = cssVar("--s2");
    ctx.fillRect(0, oy, size.w, OVERVIEW_H);
    if (whole) {
      ctx.fillStyle = cssVar("--wave2");
      drawPeaks(ctx, whole, lo, lo + extent, size.w, oy + 1, OVERVIEW_H - 2);
    }
    ctx.strokeStyle = cssVar("--accent");
    ctx.lineWidth = 1;
    ctx.strokeRect(((v0 - lo) / extent) * size.w + 0.5, oy + 0.5, Math.max(3, (span / extent) * size.w) - 1, OVERVIEW_H - 1);
  }, [size, view, whole, detail, duration, waveTop, waveH, covered[0], covered[1], props.overlay, props.curve, props.lanes, props.editing, props.editFocus, spec, props.spectrum, props.focus?.a, props.focus?.b, lo, extent, laneLayouts, maxLines, props.pitchTarget]); // eslint-disable-line react-hooks/exhaustive-deps

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
        if (p.hitBox) {
          const xa = x(p.hitBox.a);
          const xb = x(p.hitBox.b);
          ctx.strokeStyle = cssVar(p.hitBox.approx ? "--warn" : "--ok");
          ctx.lineWidth = 2;
          ctx.strokeRect(xa + 1, waveTop + 1, xb - xa - 2, waveH - 2);
          ctx.lineWidth = 1;
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
          const ox = ((ph - lo) / extent) * size.w;
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
  }, [size, duration, waveTop, waveH, clampView, lo, extent]);

  // 手势
  const timeAt = (clientX: number) => {
    const r = wrap.current!.getBoundingClientRect();
    const [v0, v1] = viewRef.current;
    return Math.max(lo, Math.min(lo + extent, duration, v0 + ((clientX - r.left) / r.width) * (v1 - v0)));
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
    if (!(y >= laneTop && y < laneTop + lanesH)) return -1;
    const k = laneYs.findIndex((ly, i) => y - laneTop >= ly && y - laneTop < ly + laneHs[i]!);
    return k;
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
      const tt = lo + ((e.clientX - r.left) / r.width) * extent;
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
      // 悬停看全文（车道上的区间，或波形上覆盖层的区间——标签被省略或截短时靠它）
      const yy = e.clientY - wrap.current!.getBoundingClientRect().top;
      const ov = !hv && yy >= waveTop && yy < waveTop + waveH ? bandAt(timeAt(e.clientX), propsRef.current.overlay?.bands ?? []) : null;
      const tip = hv ?? ov;
      if (wrap.current) wrap.current.title = tip ? `${tip.label}  ${clock(tip.a)}–${clock(tip.b)}` : "";
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
      const tt = lo + ((e.clientX - r.left) / r.width) * extent;
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
      data-peaks={whole ? "ready" : undefined}
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
      ) : props.spectrum && specMsg ? (
        <div className={s.tlStatus} data-testid="spectrum-status">
          {specMsg}
        </div>
      ) : null}
    </div>
  );
});
