// 原片查看器（UI_PLAN §4）：画面（原生播放画到画布，底部控制条）、台本（阶段 3）、时间线卡片（音源、适合/放大选区、波形、动作条）。
// 页面头（收起列表、当前原片、⋯）在顶栏里，由 SourcesPage 放。
// 快捷键（UI_PLAN §7，焦点在查看器时）：Space 播放/暂停 · Shift+Space 播放选区（引擎截停）· L 循环选区 ·
// I/O 播放位置设为选区开始/结束 · F 适合窗口 · Z 放大选区 · ←/→ 逐帧 · Shift+←/→ 1 ms · ⌥←/→ ±5 秒 · Esc 清除选区。
import { AudioLines, AudioWaveform, ChevronDown, Pencil, TriangleAlert, Download, Info, Pause, Play, Repeat, Split, SquarePlay, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlayerState } from "../../shared/protocol";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import { useThumb } from "../api/thumbs";
import type { AssetAlignment, AssetInfo, DerivedSample, EditOp, RangeTagRow, SamplePlanSource, SfxHint, SourceDetail, SourceRow, TextSegment } from "../api/types";
import { Button } from "../components/Button";
import { Checkbox, Segmented } from "../components/Controls";
import { Select, TimeField } from "../components/Fields";
import { Menu, type MenuEntry, type MenuItems, useContextMenu } from "../components/Menu";
import { Tip } from "../components/Overlay";
import { basename, clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { hangOffset } from "./hang";
import { ClipPanel } from "./ClipPanel";
import type { SeparationRequest as SeparationInput } from "../state/store";
import { displayName } from "./SourceList";
import { noSubtitles } from "./rowInfo";
import s from "./Sources.module.css";
import { AnnotationDialog, type AnnTarget } from "./AnnotationDialog";
import { boundaries, limits, moveBoundary } from "./bounds";
import { type Layer, type LayerBand, type Sel, Timeline, type TimelineHandle } from "./Timeline";
import { type Oped as OpedRange, Transcript } from "./Transcript";

// 图层（所有者 2026-10-09）：sub = 文本层的段；hint = 音效提示（可开关，所有轨可见）；seg = 区段标签与 OP/ED；ph = 音素；derived = 派生采样
type LayerId = "sub" | "hint" | "seg" | "ph" | "none";
type LaneId = "sub" | "hint" | "seg" | "ph" | "derived";
type Derived = DerivedSample;
const DERIVED_MENU_MAX = 40;
const LAYER_IDS: LayerId[] = ["sub", "hint", "seg", "ph", "none"];
const ENTITY: Record<string, "segment" | "sfx_hint" | "range_tag" | "oped"> = { segment: "segment", hint: "sfx_hint", tag: "range_tag", oped: "oped" };
const VOWEL_LABELS = new Set(["a", "i", "u", "e", "o", "N", "cl"]);
const toggleSet = <T,>(x: Set<T>, v: T, on: boolean) => {
  const n = new Set(x);
  if (on) n.add(v);
  else n.delete(v);
  return n;
};

function isTyping(el: Element | null): boolean {
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || (el as HTMLElement).isContentEditable);
}

export function SourceViewer(props: { row: SourceRow; onImportSubtitles: () => void; onSeparate: (input: SeparationInput) => void }) {
  const { row } = props;
  const toast = useApp((st) => st.toast);
  const requestFlatten = useApp((st) => st.requestFlatten);
  const requestSpeech = useApp((st) => st.requestSpeech);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  // 当前音源：资产 ID（容器音轨或分离声部）；null = 该原片的分析音轨
  const [assetSel, setAssetSel] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<[number, number] | null>(null);
  const [hasVideo, setHasVideo] = useState(row.has_video);
  const [sel, setSel] = useState<Sel | null>(null);
  const [state, setState] = useState<PlayerState | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [clipOpen, setClipOpen] = useState(false);
  // 从段 / 提示建一个采样（场景 F：看片时直接从这句建）：小面板贴着右键位置出现
  const [clipFrom, setClipFrom] = useState<{ from: SamplePlanSource; at: { x: number; y: number } } | null>(null);
  const [muted, setMuted] = useState(false);
  const stamp = useRef({ time: null as number | null, at: 0, playing: false, gen: -1 });
  const tl = useRef<TimelineHandle>(null);
  const root = useRef<HTMLDivElement>(null);

  // 换原片：选区清空，音源回到该原片的分析音轨（查看器不重建，画布保持不变）
  useEffect(() => {
    setSel(null);
    setAssetSel(null);
    setDetail(null);
    setAssets([]);
    stamp.current = { time: null, at: 0, playing: false, gen: -1 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.id]);

  // 「返回原片 ↗」带来的区间：选区 = 该区间，音源 = 该采样的音轨，时间线放大到它并把播放头放到起点
  const jump = useApp((st) => st.sourceJump);
  const setJump = useApp((st) => st.setSourceJump);
  const pendingZoom = useRef<Sel | null>(null);
  const [zoomNonce, setZoomNonce] = useState(0);
  useEffect(() => {
    if (!jump || jump.sourceId !== row.id) return;
    if (!(jump.b > jump.a)) return setJump(null); // 只打开原片（例如“去来源”到原片属性），不设选区
    setSel({ a: jump.a, b: jump.b });
    if (jump.assetId) setAssetSel(jump.assetId);
    pendingZoom.current = { a: jump.a, b: jump.b };
    setZoomNonce((n) => n + 1); // 音轨已经加载时也要放大（资产没变，下面的效果不会因资产重跑）
    setJump(null);
  }, [jump, row.id, setJump]);

  // 文本层的段（台本、画面内字幕、时间线）、音效提示、区段标签、OP/ED、派生采样；导入、编辑后刷新
  const [segs, setSegs] = useState<TextSegment[]>([]);
  const [hints, setHints] = useState<SfxHint[]>([]);
  const [rtags, setRtags] = useState<RangeTagRow[]>([]);
  const [opeds, setOpeds] = useState<OpedRange[]>([]);
  const [derived, setDerived] = useState<Derived[]>([]);
  const [annNonce, setAnnNonce] = useState(0);
  const [phNonce, setPhNonce] = useState(0);
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (c.segment || c.sfx_hint || c.range_tag || c.oped || c.source || c.sample) setAnnNonce((n) => n + 1);
    if (c.measure) setPhNonce((n) => n + 1); // 语音分析结果、人工修正（属于“段 + 资产”，不一定有采样）
  });
  // 只按内容调整（所有者 2026-10-07：原片只有一种）：没有视频又没有字幕时上面一行缩矮
  const compact = !hasVideo && noSubtitles(row);
  const [overlayId, setOverlayId] = useState<LayerId>("sub");
  const [laneIds, setLaneIds] = useState<Set<LaneId>>(new Set(["hint", "seg", "ph", "derived"]));
  // 音素层（08 §8.8）：当前音源资产上各段的可用分析（分析属于“段 + 资产”，所有者 2026-10-09；多段同时显示）；
  // 原片页「语音分析」直接分析台词段，不需要先建采样。资产局部秒 + offset = 原片秒
  const [aligned, setAligned] = useState<AssetAlignment[]>([]);
  const phOffset = useRef(0);
  // 资料（分离完成等资产变化时刷新音源列表）。音源与偏移要在图层（layer）之前定下来：资产作用域的区段标签用到它们
  const [assetsNonce, setAssetsNonce] = useState(0);
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).asset) setAssetsNonce((n) => n + 1);
  });
  useEffect(() => {
    let live = true;
    void Promise.all([call("sources.get", { id: row.id }), call("assets.listForSource", { sourceId: row.id })]).then(
      ([d, a]) => {
        if (!live) return;
        setDetail(d);
        setAssets(a);
      },
    );
    return () => {
      live = false;
    };
  }, [row.id, row.version, assetsNonce]);

  const mainAsset = useMemo(
    () => assets.find((a) => a.origin === "stream" && a.stream_ordinal === row.default_audio_stream) ?? assets.find((a) => a.origin === "stream") ?? null,
    [assets, row.default_audio_stream],
  );
  const asset = useMemo(() => assets.find((a) => a.id === assetSel) ?? mainAsset, [assets, assetSel, mainAsset]);
  // 原片秒 = 局部秒 + offset（只列未变速的资产）
  const offset = asset ? (hangOffset(asset.mapping) ?? 0) : 0;
  phOffset.current = offset;
  useEffect(() => {
    if (!asset) return setAligned([]);
    let live = true;
    void call("speech.forAsset", { assetId: asset.id, start: 0, end: asset.duration }).then(
      (r) => live && setAligned(r),
      () => live && setAligned([]),
    );
    return () => {
      live = false;
    };
  }, [asset?.id, annNonce, phNonce]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let live = true;
    void call("textLayer.list", { sourceId: row.id, assetId: asset?.id ?? null }).then((r) => {
      if (!live) return;
      setSegs(r.segments);
      setHints(r.hints);
      setRtags(r.tags);
      setOpeds(r.opeds);
      setDerived(r.derived);
    });
    return () => {
      live = false;
    };
  }, [row.id, asset?.id, annNonce, phNonce]);

  const layer = (id: LaneId): Layer => {
    if (id === "ph")
      return {
        id,
        label: t("layers.ph"),
        bands: aligned.flatMap((r) =>
          r.phones.map((p) => ({
            a: p.start + phOffset.current,
            b: p.end + phOffset.current,
            label: p.label,
            tone: p.label === "pau" ? ("pause" as const) : VOWEL_LABELS.has(p.label) ? ("vowel" as const) : ("consonant" as const),
          })),
        ),
      };
    // 派生轨（03 §3.9、R7.6）：该原片的所有用户采样，按原片时间；单击打开（跳到采样库），重叠时弹出选择菜单
    if (id === "derived")
      return { id, label: t("layers.derived"), bands: derived.map((d) => ({ a: d.start, b: d.end, label: d.name, tone: "derived", id: d.id })) };
    // 文本层的段：标签 = 段文本（说话人在前，R5.5 只显示名字）
    if (id === "sub")
      return {
        id,
        label: t("layers.sub"),
        bands: segs.map((a) => ({
          a: a.start,
          b: a.end,
          label: a.speakers.length
            ? t("layers.segLabel", { names: a.speakers.join(t("settings.subtitle.speakerSep")), text: a.text.replace(/\n/g, " ") })
            : a.text.replace(/\n/g, " "),
          tone: "line" as const,
          id: `segment:${a.id}`,
        })),
      };
    // 音效提示（作用于整个原片，所有轨可见）
    if (id === "hint") return { id, label: t("layers.hint"), bands: hints.map((h) => ({ a: h.start, b: h.end, label: h.text, tone: "sfx" as const, id: `hint:${h.id}` })) };
    // 区段标签（用户显式画的；资产作用域的只在那条资产上显示）、OP/ED
    return {
      id,
      label: t("layers.seg"),
      bands: [
        ...rtags
          .filter((g) => g.scope !== "asset" || g.scopeAssetId === asset?.id)
          .map((g) => ({
            a: g.scope === "asset" ? g.start + offset : g.start,
            b: g.scope === "asset" ? g.end + offset : g.end,
            label: g.label || g.tags.join(t("settings.subtitle.speakerSep")),
            tone: "seg" as const,
            id: `tag:${g.id}`,
          })),
        ...opeds.map((o) => ({ a: o.start, b: o.end, label: o.kind, tone: "oped" as const, id: `oped:${o.id}` })),
      ],
    };
  };
  // 编辑覆盖层边界（UI_PLAN §3.1、03 §3.5.4）：工作副本在本地，保存 = 一次可撤销的编辑（只改时间标注 / OP/ED，不移动采样 R4.11）
  const [editBands, setEditBands] = useState<LayerBand[] | null>(null);
  const [editFocus, setEditFocus] = useState<string | null>(null);
  const editing = editBands != null;
  // 短音频原片没有字幕：只有派生采样车道
  const baseOverlay = overlayId === "none" ? null : layer(overlayId);
  const overlay = baseOverlay && editBands ? { ...baseOverlay, bands: editBands } : baseOverlay;
  const lanes = (["sub", "hint", "seg", "ph", "derived"] as const)
    .filter((id) => laneIds.has(id) && id !== overlayId && (id !== "derived" || derived.length > 0) && (id !== "ph" || aligned.length > 0) && (id !== "hint" || hints.length > 0))
    .map(layer);

  const startEdit = () => {
    if (!baseOverlay) return;
    setEditBands(baseOverlay.bands);
    setEditFocus(null);
  };
  const stopEdit = () => {
    setEditBands(null);
    setEditFocus(null);
  };
  const editRef = (id: string) => {
    const [kind, key] = id.split(":") as [string, string];
    const version =
      kind === "segment"
        ? segs.find((a) => a.id === key)?.version
        : kind === "hint"
          ? hints.find((a) => a.id === key)?.version
          : kind === "tag"
            ? rtags.find((a) => a.id === key)?.version
            : opeds.find((o) => o.id === key)?.version;
    return { entity: ENTITY[kind]!, id: key, version };
  };
  const saveEdit = async () => {
    if (!editBands || !baseOverlay) return;
    const before = new Map(baseOverlay.bands.map((b) => [b.id, b]));
    const ops: EditOp[] = [];
    const done = new Set<string>();
    for (const b of editBands) {
      const o = b.id ? before.get(b.id) : undefined;
      if (!b.id || !o || done.has(b.id) || (o.a === b.a && o.b === b.b)) continue;
      done.add(b.id);
      const r = editRef(b.id);
      const fields: Record<string, number> = {};
      // 资产作用域的区段标签存资产局部秒
      const shift = b.id.startsWith("tag:") && rtags.find((g) => `tag:${g.id}` === b.id)?.scope === "asset" ? offset : 0;
      if (o.a !== b.a) fields.start = b.a - shift;
      if (o.b !== b.b) fields.end = b.b - shift;
      ops.push({ entity: r.entity, id: r.id, version: r.version, fields });
    }
    if (!ops.length) return stopEdit();
    try {
      await call("edits.apply", { batch: { label: { code: "bounds-edit", args: { n: ops.length } }, ops } });
      stopEdit();
      toast({ text: t("edit.boundsSaved", { n: ops.length }), action: { label: t("edit.boundsUndo"), run: () => void undo() } });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const focusBand = editing ? (editBands.find((b) => b.id === editFocus) ?? null) : null;
  // 表单里改开始/结束：与拖动同一套规则（共用边界一起动、不越过邻居）
  const commitEdge = (side: "a" | "b") => (v: number) => {
    if (!editBands || !focusBand?.id) return false;
    const eb = editBands.filter((x) => x.id).map((x) => ({ key: x.id!, a: x.a, b: x.b }));
    const all = boundaries(eb);
    const i = all.findIndex((x) => x.items.some((it) => it.key === focusBand.id && it.side === side));
    if (i < 0) return false;
    const lim = limits(all, i, eb, duration);
    if (v < lim[0] - 1e-9 || v > lim[1] + 1e-9) return false;
    const moved = new Map(moveBoundary(eb, all[i]!, v, lim).map((x) => [x.key, x]));
    setEditBands(editBands.map((x) => (x.id && moved.has(x.id) ? { ...x, a: moved.get(x.id)!.a, b: moved.get(x.id)!.b } : x)));
    return true;
  };
  useEffect(() => stopEdit(), [row.id, overlayId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 编辑框（段 / 提示 / 区段标签）与右键菜单（03 §3.5.4：波形右键与选区操作栏同源，另含“设为开始 / 设为结束”）
  const [annTarget, setAnnTarget] = useState<AnnTarget | null>(null);
  const tlMenu = useContextMenu("timeline-menu");
  const segMenu = useContextMenu("segment-menu");
  const undo = useUndo();

  const setPage = useApp((st) => st.setPage);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const openSample = (id: string) => {
    setOpenSample(id);
    setPage("library");
  };
  const pick = useContextMenu("derived-pick");
  const setLibraryScope = useApp((st) => st.setLibraryScope);
  const derivedItems = (list: Derived[]): MenuItems => [
    // 在采样库里列出这个原片的全部派生采样：查找栏出现临时“原片：…”块（UI_PLAN §2.3、L16）
    { id: "in-library", label: t("sources.derivedInLibrary", { n: derived.length }), run: () => { setLibraryScope({ sourceId: row.id, name: displayName(row) }); setPage("library"); } },
    "-",
    ...list.map((d) => ({ id: d.id, label: t("sources.derivedItem", { name: d.name, at: clock(d.start) }), run: () => openSample(d.id) })),
  ];

  // 播放器：打开原片（换音源时只换音轨 / 外挂声部，选区保留）
  useEffect(() => {
    let live = true;
    setOpenError(null);
    window.otto.player
      .openSource(row.id, asset ? undefined : row.default_audio_stream, asset?.id)
      .then((r) => {
        if (!live) return;
        setHasVideo(r.hasVideo);
        setCoverage(r.coverage);
      })
      .catch((e: { code: string; args: Record<string, unknown> }) => live && setOpenError(errorText(e)));
    return () => {
      live = false;
    };
  }, [row.id, row.version, asset?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(
    () =>
      window.otto.player.onState((st) => {
        if (st.player !== "source") return;
        if (st.gen < stamp.current.gen) return; // 旧代次
        stamp.current = { time: st.time, at: performance.now(), playing: st.playing, gen: st.gen };
        setState(st);
        if (st.error) setOpenError(errorText(st.error));
      }),
    [],
  );
  // 播放头：每帧直接读引擎位置；读不到时才用最近一次推送外推
  const playhead = useCallback(() => {
    const live = window.otto.player.position("source");
    if (live != null) return live;
    const c = stamp.current;
    if (c.time == null) return null;
    return c.playing ? c.time + (performance.now() - c.at) / 1000 : c.time;
  }, []);

  // 时间线长度 = 原片（分析音轨）时长；分离声部画在它的覆盖范围上
  const duration = mainAsset?.duration ?? row.duration;
  const cov: [number, number] = coverage ?? [0, duration];
  const partial = cov[0] > 1e-3 || cov[1] < duration - 1e-3;
  const covers = (a: number, b: number) => a >= cov[0] - 1e-6 && b <= cov[1] + 1e-6;
  const local = (r: Sel): Sel => ({ a: r.a - offset, b: r.b - offset });
  const selLocal = sel && covers(sel.a, sel.b) ? local(sel) : null;
  const outOfCover = () => toast({ text: t("sources.outOfCoverage", { a: clock(cov[0]), b: clock(cov[1]) }), tone: "error" });
  useEffect(() => {
    const z = pendingZoom.current;
    if (!z || !asset) return;
    pendingZoom.current = null;
    // 时间线换资产时会回到整段，等它先完成再放大
    setTimeout(() => {
      tl.current?.zoomTo(z.a, z.b);
      window.otto.player.seek(z.a);
    }, 0);
  }, [asset, zoomNonce]);
  const audioStreams = (detail?.streams ?? []).filter((x) => x.kind === "audio");
  const playing = state?.playing ?? false;

  const playPause = () => {
    if (playing) return window.otto.player.pause();
    const p = playhead() ?? 0;
    // 只覆盖部分范围的声部：越界明确报错，不回退原混音（05 §5.4）
    if (partial && !(p >= cov[0] - 1e-6 && p < cov[1])) return outOfCover();
    window.otto.player.play();
  };
  const playSel = (loop = false) => {
    if (!sel) return;
    if (!covers(sel.a, sel.b)) return outOfCover();
    window.otto.player.playRange(sel.a, sel.b, loop);
  };
  const seekBy = (d: number) => {
    const p = playhead();
    if (p != null) window.otto.player.seek(Math.max(0, Math.min(duration, p + d)));
  };

  const exportSelection = async (r: Sel) => {
    if (!asset) throw new Error("no asset");
    if (!covers(r.a, r.b)) throw new CoreFailure({ code: "out-of-coverage", args: { a: clock(cov[0]), b: clock(cov[1]) } });
    const content = t("sources.exportContent", { name: displayName(row), a: clock(r.a), b: clock(r.b) });
    const l = local(r);
    const out = await call("exports.wav", { assetId: asset.id, start: l.a, end: l.b, content, track: exportTrack });
    return [out.path];
  };

  /** 拉平台（11 §11.1：原片页选区操作栏与波形右键；默认整段 + 段内自动）。外选区是当前音源资产的局部秒 */
  const flattenSel = () => {
    if (!sel || !asset) return;
    if (!selLocal) return outOfCover();
    requestFlatten({ kind: "single", assetId: asset.id, start: selLocal.a, end: selLocal.b, entry: "single" });
  };

  const exportWav = async () => {
    if (!sel || !asset) return;
    if (!selLocal) return outOfCover();
    setExporting(true);
    try {
      const content = t("sources.exportContent", { name: displayName(row), a: clock(sel.a), b: clock(sel.b) });
      const r = await call("exports.wav", {
        assetId: asset.id,
        start: selLocal.a,
        end: selLocal.b,
        content,
        track: exportTrack,
      });
      toast({
        text: t(r.reused ? "sources.exportReused" : "sources.exported", { name: basename(r.path) }),
        action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(r.path) },
      });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setExporting(false);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (isTyping(document.activeElement)) return;
    const k = e.key;
    const handled = () => {
      e.preventDefault();
      e.stopPropagation();
    };
    if (editing && k === "Escape") {
      // Esc = 放弃（UI_PLAN §3.1）
      handled();
      stopEdit();
      toast({ text: t("edit.boundsDiscarded") });
      return;
    }
    if (k === " " && e.shiftKey) {
      handled();
      playSel(false);
    } else if (k === " ") {
      handled();
      playPause();
    } else if (k === "l" || k === "L") {
      handled();
      playSel(true);
    } else if (k === "i" || k === "I" || k === "o" || k === "O") {
      handled();
      const p = playhead();
      if (p == null) return;
      const isIn = k.toLowerCase() === "i";
      const a = isIn ? p : sel?.a ?? 0;
      const b = isIn ? sel?.b ?? duration : p;
      if (b > a) setSel({ a, b });
    } else if (k === "f" || k === "F") {
      handled();
      tl.current?.fit();
    } else if ((k === "z" || k === "Z") && !e.metaKey && !e.ctrlKey) {
      handled();
      if (sel) tl.current?.zoomTo(sel.a, sel.b);
    } else if (k === "ArrowLeft" || k === "ArrowRight") {
      handled();
      const dir = k === "ArrowRight" ? 1 : -1;
      if (e.altKey) seekBy(dir * 5);
      else if (e.shiftKey) seekBy(dir * 0.001);
      else window.otto.player.step(dir as 1 | -1);
    } else if (k === "Escape" && sel) {
      handled();
      setSel(null);
    }
  };

  const trackLabel = (o: number) => {
    const st = audioStreams.find((x) => x.ordinal === o);
    const parts = [t("sources.trackN", { n: o + 1 }), st?.language ?? t("sources.langUnknown"), st?.title ?? st?.codec ?? ""];
    return parts.filter(Boolean).join(" · ");
  };

  /** 音源下拉里的名字：容器音轨“第 n 条音轨 · 语言 · 编码”；其他“模型 · 声部”，只覆盖部分范围的写出范围 */
  const assetLabel = (a: AssetInfo) => {
    if (a.origin === "stream") return trackLabel(a.stream_ordinal ?? 0);
    const base = [a.production?.model ?? t(`track.origin.${a.origin}`), a.stem_name ?? ""].filter(Boolean).join(" · ");
    const off = hangOffset(a.mapping) ?? 0;
    return a.isFullTrack ? base : t("sources.partialTrack", { name: base, a: clock(off), b: clock(off + a.duration) });
  };
  // 只列能挂到原片时间轴（未变速）的资产：容器音轨在前，然后整轨，最后部分覆盖的
  const sourceOptions = assets
    .filter((a) => hangOffset(a.mapping) != null)
    .sort((x, y) => Number(x.origin !== "stream") - Number(y.origin !== "stream") || Number(!x.isFullTrack) - Number(!y.isFullTrack));
  const trackName = asset ? assetLabel(asset) : "";
  // 导出文件名的“音轨”段（规格 12 §12.1）：原混音 / 声部名
  const exportTrack = asset && asset.origin !== "stream" ? (asset.stem_name ?? t(`track.origin.${asset.origin}`)) : t("track.original");
  const setViewerAsset = useApp((st) => st.setViewerAsset);
  useEffect(() => setViewerAsset(asset ? { sourceId: row.id, id: asset.id, label: trackName } : null), [row.id, asset?.id, trackName, setViewerAsset]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => setViewerAsset(null), [setViewerAsset]);
  const ph = playhead();
  // 画内字幕 = 文本层的段（所有者 2026-10-09）
  // 容许 1 毫秒：单击台本行跳到段开头时，引擎报回的位置可能比开头早一点点
  const subtitleNow = ph == null ? null : segs.filter((a) => ph >= a.start - 1e-3 && ph < a.end).map((a) => a.text).join("\n") || null;
  // 段与提示的菜单：台本行、画内字幕、时间线上的段 / 提示右键共用（场景 F）
  const cur = asset ? { id: asset.id, label: trackName } : undefined;
  const short = (x: string) => {
    const v = x.replace(/\n/g, " ");
    return v.length > 18 ? `${v.slice(0, 18)}…` : v;
  };
  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const undoable = (text: string) => toast({ text, action: { label: t("common.undo"), run: () => void undo() } });
  const removeSeg = (g: TextSegment) =>
    call("edits.apply", { batch: { label: { code: "segment-delete", args: {} }, ops: [{ entity: "segment", id: g.id, version: g.version, fields: { deleted: true } }] } }).then(
      () => undoable(g.usedBy ? t("seg.deletedUsed", { n: g.usedBy }) : t("seg.deleted")),
      fail,
    );
  const removeHint = (h: SfxHint) =>
    call("edits.apply", { batch: { label: { code: "hint-delete", args: {} }, ops: [{ entity: "sfx_hint", id: h.id, version: h.version, fields: { deleted: true } }] } }).then(
      () => undoable(t("hint.deleted")),
      fail,
    );
  const mergeNext = (g: TextSegment, next: TextSegment) => call("segments.merge", { ids: [g.id, next.id] }).then(() => undoable(t("seg.merged")), fail);
  const segItems = (g: TextSegment, at: { x: number; y: number }, tt: number | null): MenuEntry[] => {
    const i = segs.findIndex((x) => x.id === g.id);
    const next = i >= 0 ? segs[i + 1] : undefined;
    const splitAt = tt != null && tt > g.start + 0.02 && tt < g.end - 0.02 ? tt : (g.start + g.end) / 2;
    return [
      { id: `seg-clip:${g.id}`, label: t("seg.menu.clip"), disabled: editing, run: () => setClipFrom({ from: { kind: "segments", sourceId: row.id, ids: [g.id] }, at }) },
      { id: `seg-speech:${g.id}`, label: t("seg.menu.speech"), run: () => requestSpeech({ entry: "segments", ids: [g.id], currentAsset: cur }) },
      { id: `seg-edit:${g.id}`, label: t("seg.menu.edit"), disabled: editing, run: () => setAnnTarget({ mode: "edit-segment", seg: g }) },
      { id: `seg-split:${g.id}`, label: t("seg.menu.split"), disabled: editing || g.end - g.start < 0.05, run: () => setAnnTarget({ mode: "split-segment", seg: g, at: splitAt }) },
      { id: `seg-merge:${g.id}`, label: t("seg.menu.mergeNext"), disabled: editing || !next, run: () => void (next && mergeNext(g, next)) },
      { id: `seg-delete:${g.id}`, label: g.usedBy ? t("seg.menu.deleteUsed", { n: g.usedBy }) : t("seg.menu.delete"), danger: true, disabled: editing, run: () => void removeSeg(g) },
    ];
  };
  const hintItems = (h: SfxHint, at: { x: number; y: number }): MenuEntry[] => [
    { id: `hint-clip:${h.id}`, label: t("hint.menu.clip"), disabled: editing, run: () => setClipFrom({ from: { kind: "hints", sourceId: row.id, ids: [h.id] }, at }) },
    { id: `hint-edit:${h.id}`, label: t("hint.menu.edit"), disabled: editing, run: () => setAnnTarget({ mode: "edit-hint", hint: h }) },
    { id: `hint-delete:${h.id}`, label: t("hint.menu.delete"), danger: true, disabled: editing, run: () => void removeHint(h) },
  ];
  /** 命中的段与提示：只有一个时动作直接列出（菜单头写明是哪一个），多个时各一个子菜单 */
  const objectMenu = (gs: TextSegment[], hs: SfxHint[], at: { x: number; y: number }, tt: number | null): { head?: string; items: MenuItems } => {
    if (gs.length + hs.length === 1)
      return gs.length
        ? { head: t("seg.menu.head", { text: short(gs[0]!.text) }), items: segItems(gs[0]!, at, tt) }
        : { head: t("hint.menu.head", { text: short(hs[0]!.text) }), items: hintItems(hs[0]!, at) };
    return {
      items: [
        ...gs.map((g) => ({ id: `seg:${g.id}`, label: t("seg.menu.sub", { text: short(g.text) }), items: segItems(g, at, tt) })),
        ...hs.map((h) => ({ id: `hint:${h.id}`, label: t("hint.menu.sub", { text: short(h.text) }), items: hintItems(h, at) })),
      ],
    };
  };
  // 一键「导入到文本层」：按默认选项直接导入（OP/ED 有错时不登记 OP/ED，提示去逐对确认）
  const quickImport = async () => {
    try {
      const r = await call("subtitles.importDefault", { sourceId: row.id });
      const n = { segments: r.created.segments, hints: r.created.hints, oped: r.created.oped };
      if (r.opedErrors) toast({ text: t("subimport.quickDoneOpedError", n), action: { label: t("subimport.quickOpedConfirm"), run: props.onImportSubtitles } });
      else undoable(t("subimport.quickDone", n));
    } catch (e) {
      fail(e);
    }
  };
  const commitSel = (which: "a" | "b") => (v: number) => {
    const a = which === "a" ? v : (sel?.a ?? 0);
    const b = which === "b" ? v : (sel?.b ?? duration);
    if (!(a >= 0 && b <= duration + 1e-9 && b > a)) return false;
    setSel({ a, b });
    return true;
  };

  return (
    <section
      className={s.viewer}
      ref={root}
      tabIndex={0}
      onKeyDown={onKey}
      data-testid="source-viewer"
      data-compact={compact || undefined}
      aria-label={displayName(row)}
    >
      {/* 原片播放器的画布整个窗口只有一个（preload 用 data-otto-video 找到它） */}
      <div className={s.stageRow}>
        <div className={s.video} data-audio-only={!hasVideo || !!openError || undefined} onClick={() => root.current?.focus()} onDoubleClick={playPause}>
          {/* 原片播放器的画布：整个窗口只有一个（preload 用 data-otto-video 找到它） */}
          <canvas data-otto-video="" style={{ display: hasVideo && !openError ? "block" : "none" }} />
          {openError ? (
            <div className={s.audioOnly} data-testid="video-error">
              <TriangleAlert size={26} strokeWidth={1.4} />
              {t("sources.cannotOpen")}
            </div>
          ) : null}
          {!hasVideo && !openError && row.has_picture ? <BoundPicture sourceId={row.id} /> : null}
          {!hasVideo && !openError && !row.has_picture ? (
            <div className={s.audioOnly}>
              <AudioLines size={28} strokeWidth={1.3} />
              {t("sources.audioOnly")}
            </div>
          ) : null}
          {/* 画面内字幕（规格 03 §3.4：纯文本画在画面内部底部，不执行样式指令） */}
          {subtitleNow ? (
            <div
              className={s.videoSub}
              lang="ja"
              data-testid="video-subtitle"
              data-user-data=""
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                const p = playhead();
                const gs = p == null ? [] : segs.filter((a) => p >= a.start && p < a.end).slice(0, 5);
                if (gs.length) segMenu.open(e, objectMenu(gs, [], { x: e.clientX, y: e.clientY }, p));
              }}
            >
              {subtitleNow}
            </div>
          ) : null}
          {/* 画面控制条（规格 03 §3.4：播放/暂停、时间、静音；音源名） */}
          <div className={s.videoBar} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
            <Button size="sm" variant="flat" icon={playing ? <Pause /> : <Play />} onPress={playPause} aria-label={playing ? t("player.pause") : t("player.play")} />
            <span className="num mono" data-testid="video-time">
              {clock(playhead(), 2)}
            </span>
            <span className={s.grow} />
            <span className={s.videoTrack} data-user-data="">
              {t("sources.sourceIs", { track: trackName })}
            </span>
            <Button
              size="sm"
              variant="flat"
              icon={muted ? <VolumeX /> : <Volume2 />}
              onPress={() => {
                window.otto.player.setMuted(!muted);
                setMuted(!muted);
              }}
              aria-label={muted ? t("player.unmute") : t("player.mute")}
              aria-pressed={muted}
              data-testid="mute"
            />
          </div>
        </div>
        <Transcript
          segs={segs}
          opeds={opeds}
          playhead={playhead()}
          sel={sel}
          hasSubtitleFile={!!row.subtitle_path}
          canQuickImport={!!row.subtitle_path && !segs.length}
          onImport={props.onImportSubtitles}
          onQuickImport={() => void quickImport()}
          onMenu={(g, at) => segMenu.open({ clientX: at.x, clientY: at.y }, objectMenu([g], [], at, null))}
          onSelect={(a, b, mode) => {
            // 单击 = 选区设为该段并跳到开头（不播放）；Shift 单击 = 扩展到该段
            if (mode === "extend" && sel) setSel({ a: Math.min(sel.a, a), b: Math.max(sel.b, b) });
            else {
              setSel({ a, b });
              window.otto.player.seek(a);
            }
            root.current?.focus({ preventScroll: true });
          }}
          onPlay={(a, b) => {
            setSel({ a, b });
            if (!covers(a, b)) return outOfCover();
            window.otto.player.playRange(a, b);
          }}
        />
      </div>

      <div className={s.tlCard}>
        <div className={s.tlBar}>
          <Select
            value={asset?.id ?? ""}
            onChange={(v) => setAssetSel(v)}
            label={t("sources.audioSource")}
            prefix={t("sources.audioSource")}
            options={sourceOptions.map((a) => ({ id: a.id, label: assetLabel(a) }))}
          />
          <span className={s.grow} />
          <Button size="sm" variant="flat" icon={<Pencil />} isDisabled={!baseOverlay || editing || overlayId === "ph"} onPress={startEdit} data-testid="edit-bounds">
            {baseOverlay ? t("edit.button", { layer: t(`layers.${overlayId}`) }) : t("edit.buttonNone")}
          </Button>
          <Button size="sm" variant="flat" onPress={() => tl.current?.fit()} title={t("sources.fitTip")}>
            {t("sources.fit")}
          </Button>
          <Button size="sm" variant="flat" onPress={() => sel && tl.current?.zoomTo(sel.a, sel.b)} isDisabled={!sel} title={t("sources.zoomSelTip")}>
            {t("sources.zoomSel")}
          </Button>
          <Menu
            head={t("sources.derivedHead", { n: derived.length })}
            items={
              derived.length > DERIVED_MENU_MAX
                ? [...derivedItems(derived.slice(0, DERIVED_MENU_MAX)), "-", { id: "more", label: t("sources.derivedMore", { n: derived.length - DERIVED_MENU_MAX }), disabled: true }]
                : derivedItems(derived)
            }
            placement="bottom end"
            testId="derived-menu"
            trigger={
              <Button size="sm" variant="flat" isDisabled={!derived.length} data-testid="derived-button">
                {t("sources.derivedN", { n: derived.length })}
              </Button>
            }
          />
          <Tip content={t("sources.timelineHelp")}>
            <Button variant="flat" size="sm" icon={<Info />} aria-label={t("sources.timelineHelpLabel")} />
          </Tip>
        </div>
        {openError ? (
          <div className={s.tlError} data-testid="open-error">
            {openError}
          </div>
        ) : null}
        {editing ? (
          <div className={s.editBar} data-testid="edit-bar">
            <b>{t("edit.editing", { layer: t(`layers.${overlayId}`) })}</b>
            {focusBand ? (
              <>
                <span className={s.editName} lang="ja" data-user-data="">
                  {focusBand.label}
                </span>
                <TimeField value={focusBand.a} onCommit={commitEdge("a")} label={t("sources.selStart")} testId="edit-start" />
                <span className={s.arrow}>→</span>
                <TimeField value={focusBand.b} onCommit={commitEdge("b")} label={t("sources.selEnd")} testId="edit-end" />
              </>
            ) : (
              <span className={`${s.muted} ${s.editHint}`}>{t("edit.hint")}</span>
            )}
            <span className={s.grow} />
            <Button
              size="sm"
              variant="flat"
              onPress={() => {
                stopEdit();
                toast({ text: t("edit.boundsDiscarded") });
              }}
              data-testid="edit-discard"
            >
              {t("edit.discard")}
            </Button>
            <Button size="sm" variant="primary" onPress={() => void saveEdit()} data-testid="edit-save">
              {t("edit.saveBounds")}
            </Button>
          </div>
        ) : (
        <div className={s.layerBar} data-testid="layer-bar">
          <span className={s.groupLabel}>{t("layers.overlay")}</span>
          <Segmented<LayerId>
            size="sm"
            value={overlayId}
            onChange={setOverlayId}
            label={t("layers.overlay")}
            options={LAYER_IDS.map((id) => ({ id, label: t(`layers.${id}`) }))}
          />
          <span className={s.groupLabel}>{t("layers.lanes")}</span>
          {(["sub", "hint", "seg", "ph", "derived"] as const).map((id) => (
            <Checkbox key={id} isSelected={laneIds.has(id)} isDisabled={overlayId === (id as LayerId)} onChange={(on) => setLaneIds((x) => toggleSet(x, id, on))} label={t(`layers.${id}`)}>
              {t(`layers.${id}`)}
            </Checkbox>
          ))}
          <span className={`${s.muted} ${s.layerHint}`}>{t("layers.help")}</span>
        </div>
        )}
        <Timeline
          ref={tl}
          overlay={overlay}
          lanes={lanes}
          onLaneDoubleClick={(id) => id !== "derived" && setOverlayId(id as LayerId)}
          editing={editing}
          editFocus={editFocus}
          onEditBands={setEditBands}
          onEditFocus={setEditFocus}
          onContextMenu={(tt, hits, at) => {
            const ids = [...new Set([...hits.overlay, ...(hits.lane?.bands ?? [])].map((b) => b.id ?? ""))];
            const hit = <T extends { id: string }>(prefix: string, list: T[]) =>
              ids
                .filter((x) => x.startsWith(prefix))
                .map((x) => list.find((o) => `${prefix}${o.id}` === x))
                .filter((o): o is T => !!o)
                .slice(0, 5);
            const gs = hit("segment:", segs);
            const hs = hit("hint:", hints);
            const tgs = hit("tag:", rtags);
            const obj = gs.length + hs.length ? objectMenu(gs, hs, { x: at.clientX, y: at.clientY }, tt) : null;
            const derivedHits = hits.lane?.id === "derived" ? hits.lane.bands.slice(0, 5) : [];
            const setEdge = (side: "a" | "b") => {
              const a = side === "a" ? tt : (sel?.a ?? 0);
              const b = side === "b" ? tt : (sel?.b ?? duration);
              if (b > a) setSel({ a, b });
            };
            tlMenu.open(at, {
              head: obj?.head ? `${t("sources.atTime", { t: clock(tt) })} · ${obj.head}` : t("sources.atTime", { t: clock(tt) }),
              items: [
                { id: "in", label: t("sources.setStart"), shortcut: "I", run: () => setEdge("a") },
                { id: "out", label: t("sources.setEnd"), shortcut: "O", run: () => setEdge("b") },
                "-",
                { id: "clip", label: t("clip.menu"), disabled: !sel || !asset || editing, run: () => setClipOpen(true) },
                { id: "flatten", label: t("flatten.menuSel"), disabled: !sel || !asset || editing, run: () => flattenSel() },
                { id: "wav", label: t("sources.exportWav"), disabled: !sel || !asset, run: () => void exportWav() },
                "-",
                { id: "add-seg", label: t("seg.menu.add"), disabled: !sel || editing, run: () => sel && setAnnTarget({ mode: "create-segment", sourceId: row.id, start: sel.a, end: sel.b }) },
                { id: "add-hint", label: t("hint.menu.add"), disabled: !sel || editing, run: () => sel && setAnnTarget({ mode: "create-hint", sourceId: row.id, start: sel.a, end: sel.b }) },
                { id: "tag", label: t("ann.createMenu"), disabled: !sel || editing, run: () => sel && setAnnTarget({ mode: "create-tag", sourceId: row.id, start: sel.a, end: sel.b }) },
                ...(obj ? (["-", ...obj.items] as MenuItems) : []),
                ...(tgs.length
                  ? (["-", ...tgs.map((g) => ({
                      id: `tag:${g.id}`,
                      label: t("ann.editTagMenu", { name: g.label || g.tags.join(" ") }),
                      disabled: editing,
                      run: () => setAnnTarget({ mode: "edit-tag", tag: g, shift: g.scope === "asset" ? offset : 0 }),
                    }))] as MenuItems)
                  : []),
                ...derivedHits.map((b) => ({ id: `smp:${b.id}`, label: t("sources.openSample", { name: b.label }), run: () => openSample(b.id!) })),
              ],
            });
          }}
          onBandPress={(laneId, bands, at) => {
            if (laneId !== "derived") return false;
            if (bands.length === 1) openSample(bands[0]!.id!);
            else pick.open(at, { head: t("sources.derivedPick", { n: bands.length }), items: derivedItems(bands.map((b) => derived.find((d) => d.id === b.id)!)) });
            return true;
          }}
          assetId={asset?.id ?? null}
          duration={duration}
          offset={offset}
          assetDuration={asset?.duration ?? duration}
          playhead={playhead}
          playing={playing}
          selection={sel}
          onSelection={setSel}
          onSeek={(tt) => {
            window.otto.player.seek(tt);
            root.current?.focus();
          }}
          onPlayFrom={(tt) => {
            window.otto.player.seek(tt);
            window.otto.player.play();
          }}
          onDragOut={exportSelection}
        />
        {pick.node}
        {tlMenu.node}
        {segMenu.node}
        <div className={s.actions}>
          <div className={s.group}>
            <Button variant="flat" icon={playing ? <Pause /> : <Play />} onPress={playPause} data-testid="play-pause">
              {playing ? t("player.pause") : t("player.play")}
            </Button>
            <Button variant="flat" icon={<SquarePlay />} onPress={() => playSel(false)} isDisabled={!sel} data-testid="play-selection">
              {t("player.selection")}
            </Button>
            <Button variant="flat" icon={<Repeat />} onPress={() => playSel(true)} isDisabled={!sel} aria-label={t("player.loop")} title={t("player.loop")} />
          </div>
          <div className={s.group} data-testid="readout" data-a={sel?.a ?? ""} data-b={sel?.b ?? ""}>
            <span className={s.groupLabel}>{t("sources.selection")}</span>
            <TimeField value={sel?.a ?? null} onCommit={commitSel("a")} label={t("sources.selStart")} isDisabled={!sel} testId="sel-start" />
            <span className={s.arrow}>→</span>
            <TimeField value={sel?.b ?? null} onCommit={commitSel("b")} label={t("sources.selEnd")} isDisabled={!sel} testId="sel-end" />
            <span className={`${s.dur} num`}>{sel ? t("format.sec", { v: seconds(sel.b - sel.a) }) : ""}</span>
          </div>
          <div className={s.group}>
            <ClipPanel assetId={asset?.id ?? null} track={trackName} sel={selLocal} isOpen={clipOpen} onOpenChange={setClipOpen} />
            {clipFrom ? (
              <ClipPanel
                from={clipFrom.from}
                at={clipFrom.at}
                assetId={asset?.id ?? null}
                track={trackName}
                sel={null}
                isOpen
                onOpenChange={(o) => !o && setClipFrom(null)}
                currentAsset={cur ?? null}
                // 看片时逐句建：留在原片页，提示里可以打开
                afterSave={(id, name) => toast({ text: t("clip.savedHere", { name }), action: { label: t("clip.open"), run: () => openSample(id) } })}
              />
            ) : null}
            <Button variant="flat" icon={<AudioWaveform />} isDisabled={!sel || !asset || editing} onPress={flattenSel} data-testid="flatten">
              {t("flatten.action")}
            </Button>
            <Button
              variant="flat"
              icon={<Split />}
              isDisabled={!asset}
              onPress={() => asset && props.onSeparate({ assetId: asset.id, trackLabel: trackName, duration: asset.duration, selection: selLocal, scope: selLocal ? "sel" : "full" })}
              data-testid="separate"
            >
              {t("sep.action")}
            </Button>
            <Menu
              head={sel ? t("sources.selectionIs", { a: clock(sel.a), b: clock(sel.b) }) : undefined}
              items={[{ id: "wav", label: t("sources.exportWav"), run: () => void exportWav() }]}
              placement="top start"
              trigger={
                <Button variant="flat" icon={<Download />} isDisabled={!sel || !asset || exporting} data-testid="export-menu">
                  {t("sources.export")}
                  <ChevronDown size={13} />
                </Button>
              }
            />
          </div>
          <span className={s.grow} />
          <span className={s.hint}>{t("sources.dragHint")}</span>
        </div>
      </div>
      <AnnotationDialog target={annTarget} duration={duration} onClose={() => setAnnTarget(null)} />
    </section>
  );
}

/** 没有视频流、但绑定了画面（同名图片 / 动图 / 视频，规格 12）：画面区显示它的静帧（同步视频的播放随阶段 9） */
function BoundPicture(props: { sourceId: string }) {
  const url = useThumb("source", props.sourceId, "poster");
  return url ? <img className={s.boundPicture} src={url} alt="" draggable={false} data-testid="bound-picture" /> : null;
}
