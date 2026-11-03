// 采样库（UI_PLAN §2；阶段 2 最小版 + 阶段 3.0 组件对齐）：顶栏用途切换、查找栏（文字 + ★）、结果头（浏览、分页）与状态行、
// 统一列表（CollectionList：UI_PLAN §6.1 的全部集合规则）、批量条、可拖动的分栏、右侧舞台。
// 本页自己的键（集合区）：Space 试听焦点的原声 · B 试听默认卡拍（近快；单音没有）· 1/2/3/0 设性质（勾选集或焦点，可撤销；改完留在原位，刷新后归位）·
// S 星标 · ⌘F 聚焦查找栏的文字。条件变化清空勾选并提示；翻页保留勾选。
import { ArrowUpRight, ChevronDown, ChevronLeft, ChevronRight, Crosshair, MoreHorizontal, Plus, SquareStack, Star } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlayerState } from "../../shared/protocol";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import { useThumb } from "../api/thumbs";
import { RhythmGlyph, Sparkline } from "../components/Glyphs";
import type { EffectiveTag, FacetCondition, FacetValues, SampleGlyph, Nature, ResultPage, ResultRow, RhythmPlan, RhythmSound, SampleFilter, SamplePage, SampleRow, SavedFilter, SearchFinished } from "../api/types";
import { BatchBar } from "../components/BatchBar";
import { Button } from "../components/Button";
import { CollectionList } from "../components/CollectionList";
import { type ChipItem, Chips, ClosableTabs, EmptyState, Segmented } from "../components/Controls";
import { TextField } from "../components/Fields";
import { Menu, type MenuItems, type MenuSpec, useContextMenu } from "../components/Menu";
import { NATURES, NATURE_KEYS, NatureDot, NaturePicker } from "../components/NaturePicker";
import { AnchoredPanel } from "../components/Panel";
import { ConfirmDialog } from "../components/Overlay";
import { SplitPane } from "../components/SplitPane";
import { Thumb } from "../components/Thumb";
import { beginDragOut } from "../dragout";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { ImportDialog } from "../shell/ImportDialog";
import { useCommands } from "../state/commands";
import { type PaletteCommand, type PaletteSection, fromMenu } from "../components/CommandPalette";
import { TopSlot } from "../shell/TopSlot";
import { useUndo } from "../shell/useUndo";
import { exportWords } from "../exportWords";
import { type AuditionVersion, useApp } from "../state/store";
import { PromoteDialog } from "./PromoteDialog";
import { EMPTY_FIND, type FindState, FindBar, ScopeRow, normScope, scopeSize } from "./FindBar";
import { ManageFiltersDialog, SaveFilterDialog, ScopeExprDialog } from "./FilterDialogs";
import { BatchDialog, type BatchKind } from "./BatchDialogs";
import s from "./Library.module.css";
import { StageRhythm } from "./StageRhythm";
import { StageSpeech } from "./StageSpeech";
import { StageInfo } from "./StageInfo";
import { StagePicture } from "./StagePicture";
import { VideoDialog, type VideoRequest } from "./VideoDialog";
import { IndependDialog } from "./IndependDialog";
import { VisualDialog, type VisualTarget } from "../sources/VisualDialog";
import { Composer, type ComposerMode } from "./search/Composer";
import { HitChips, HitLine } from "./search/HitLine";
import { metricFilter, newMetricsDraft } from "./search/MetricsComposer";
import { newPitchDraft, pitchBlocks, pitchParams } from "./search/PitchComposer";
import ss from "./search/Search.module.css";
import { newSpeechDraft, speechQuery } from "./search/SpeechComposer";
import { BROWSE, useResults } from "./search/useResults";

const PAGE = 100;
/** 分页（07 §7.1）：一屏一页（默认，按列表高度）或固定 20 / 50 / 100 */
type PageSize = "fit" | 20 | 50 | 100;
const PAGE_SIZES: PageSize[] = ["fit", 20, 50, 100];
type Sort = "created" | "name" | "duration";
const SORTS: Sort[] = ["created", "name", "duration"];
/** 一屏一页时估的行高（缩略图 64 + 上下内边距）；渲染后按实际行高修正 */
const ROW_GUESS = 78;

/** 导出文件名“音轨”段的固定词（随界面语言，规格 12 §12.1） */
const trackWords = exportWords;
type Purpose = "all" | Nature;
const PURPOSES: Purpose[] = ["all", "speech", "pitched", "unpitched", "unclassified"];
const KEY_OF: Record<Nature, string> = { speech: "1", pitched: "2", unpitched: "3", unclassified: "0" };
/** 单音（调谐/非调谐）没有卡拍、没有 REAPER 交接（所有者 2026-10-06） */
const isSingle = (n: Nature) => n === "pitched" || n === "unpitched";

/** 列表项：浏览时是采样；固定结果里另带成员（失效的、原片音轨行用占位资料） */
type Item = SampleRow & { _res?: ResultRow; dead?: boolean };

function stubRow(id: string, name: string, assetId: string): SampleRow {
  return {
    id, asset_id: assetId, start: 0, end: 0, duration: 0, name, nature: "unclassified", starred: false, rating: null, language: null, created_via: "manual",
    created_at: "", version: 0, source_id: "", asset_origin: "", stream_ordinal: null, work: "", episode: "",
    source_name: "", source_path: "", source_start: null, source_end: null, back_asset_id: null, media_state: "available", independent: false, people: [], analysis: "none",
  } as SampleRow;
}

function toItem(r: ResultRow): Item {
  if (r.sample) return { ...r.sample, _res: r, dead: r.state === "deleted" || r.state === "changed" };
  if (r.asset) {
    const label = [r.asset.work, r.asset.episode].filter(Boolean).join(" ") || (r.asset.path.split(/[\\/]/).pop() ?? "");
    return { ...stubRow(`asset:${r.asset.id}`, label, r.asset.id), _res: r };
  }
  return { ...stubRow(r.sampleId ?? `gone:${r.rank}`, t("search.row.deleted"), ""), _res: r, dead: true };
}

/** 检索按钮的默认方式随用途（UI_PLAN §2.1）：语音/未分类 → 节奏检索；调谐 → 音高检索；非调谐 → 瞬态筛选 */
const HUNT: Record<string, ComposerMode> = { all: "speech", speech: "speech", unclassified: "speech", pitched: "pitch", unpitched: "transient" };

/** 试听选项：舞台上的临时方案、纯 mora 与声音（所有者 2026-10-08）；列表与右键 = 近快、原节奏、原声 */
interface AuditionOpts {
  sound?: RhythmSound;
  plan?: RhythmPlan;
  mora?: boolean;
  longVowel?: boolean;
}

/** 有效标签的显示（04 §4.2.9 分面）：“人物 京子”“作品 Yuru Yuri”；其他标签原样显示为“#标签”；只有本地标签能在这里删 */
function tagChip(tg: EffectiveTag): ChipItem {
  const value = tg.facet === "other" ? `#${tg.tag}` : tg.tag.slice(tg.tag.indexOf(":") + 1);
  return {
    id: tg.tag,
    k: tg.facet === "other" ? undefined : t(`facet.${tg.facet}`),
    v: value,
    readOnly: tg.provenance !== "local",
    lang: tg.facet === "person" ? "ja" : undefined,
    // 统一的来源小标记（07 §7.4）：本地 / 区段 / 原片 / 自动
    mark: t(`tag.prov.${tg.provenance}`),
    title: tg.tag,
  };
}
/** 标签 → 范围行的分面值（人物取名字；其他分面取冒号后；“其他”= 完整标签） */
function facetValue(tg: EffectiveTag): string {
  return tg.facet === "other" ? tg.tag : tg.tag.slice(tg.tag.indexOf(":") + 1);
}

export function LibraryPage() {
  const ready = useApp((st) => st.core.state === "ready");
  const page = useApp((st) => st.page);
  const toast = useApp((st) => st.toast);
  const requestSpeech = useApp((st) => st.requestSpeech);
  const requestFlatten = useApp((st) => st.requestFlatten);
  const requestSeparation = useApp((st) => st.requestSeparation);
  const openSample = useApp((st) => st.openSample);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  const setSourceJump = useApp((st) => st.setSourceJump);
  const undo = useUndo();
  const [purpose, setPurpose] = useState<Purpose>("all");
  // 检索浮层与固定结果（UI_PLAN §2.1、§2.4）
  const bpm = useApp((st) => st.bpm);
  const [composer, setComposer] = useState<ComposerMode | null>(null);
  const [speechDraft, setSpeechDraft] = useState(newSpeechDraft);
  const [pitchDraft, setPitchDraft] = useState(newPitchDraft);
  const [metricsDraft, setMetricsDraft] = useState(() => newMetricsDraft("transient"));
  const [resPage, setResPage] = useState<ResultPage | null>(null);
  const [focusHit, setFocusHit] = useState<{ id: string; index: number } | null>(null);
  const [pad, setPad] = useState(false);
  const [hitPlaying, setHitPlaying] = useState<string | null>(null);
  const [clipTick, setClipTick] = useState(0);
  const hitMenu = useContextMenu("hit-menu");
  const [importPaths, setImportPaths] = useState<string[] | null>(null);
  const [promoteFor, setPromoteFor] = useState<SampleRow | null>(null);
  const [tagOpen, setTagOpen] = useState(false);
  const [tagDraft, setTagDraft] = useState("");
  const [drop, setDrop] = useState(false);
  const pickImport = async () => {
    const paths = await window.otto.files.pick("import");
    if (paths.length) setImportPaths(paths);
  };
  // 查找栏 + 范围行（UI_PLAN §2.3）、排序、分页；重启恢复（勾选不恢复）
  const [find, setFind] = useState<FindState>(EMPTY_FIND);
  const [sort, setSort] = useState<Sort>("created");
  const [pageSize, setPageSize] = useState<PageSize>("fit");
  const [fitRows, setFitRows] = useState(20);
  const [filters, setFilters] = useState<SavedFilter[]>([]);
  const [facets, setFacets] = useState<FacetValues | null>(null);
  const [filterDialog, setFilterDialog] = useState<"save" | "manage" | "expr" | null>(null);
  const [batch, setBatch] = useState<{ kind: BatchKind; ids: string[] } | null>(null);
  const [visualFor, setVisualFor] = useState<VisualTarget | null>(null);
  const [videoFor, setVideoFor] = useState<VideoRequest | null>(null);
  const [independFor, setIndependFor] = useState<string[] | null>(null);
  const [picWide, setPicWide] = useState(false);
  const plusRef = useRef<HTMLInputElement>(null);
  const listBox = useRef<HTMLDivElement>(null);
  const libraryScope = useApp((st) => st.libraryScope);
  const setLibraryScope = useApp((st) => st.setLibraryScope);
  const limit = pageSize === "fit" ? fitRows : pageSize;
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<SamplePage | null>(null);
  /** 列表行的副信息（用途视图）：每次换页 / 刷新后按本页的采样取一次 */
  const [glyphs, setGlyphs] = useState<Record<string, SampleGlyph>>({});
  const [focus, setFocus] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<string | null>(null);
  /** 正在试听的版本与声音（"original:voice"、"stretched:voice+click" …） */
  const setNowPlaying = useApp((st) => st.setNowPlaying);
  const stageRhythm = useApp((st) => st.stageRhythm);
  const [playingVer, setPlayingVer] = useState<string | null>(null);
  // 播放条停止或播完（nowPlaying 变成空）→ 本页的“正在试听”也清掉
  const nowPlaying = useApp((st) => st.nowPlaying);
  useEffect(() => {
    if (!nowPlaying) {
      setPlaying(null);
      setPlayingVer(null);
    }
  }, [nowPlaying]);
  const [deleteIds, setDeleteIds] = useState<string[] | null>(null);
  const [focusRow, setFocusRow] = useState<SampleRow | null>(null);
  const [split, setSplit] = useState(0.5);
  const splitRestored = useRef(false);
  const auditionGen = useRef(-1);

  /** 检索范围 = 当前浏览范围（用途 + 查找栏 + 范围行 + 临时原片块）；单音指标是浏览里的即时筛选，另外加在列表查询上 */
  const scope = useMemo<SampleFilter>(
    () => ({
      natures: purpose === "all" ? undefined : [purpose],
      starred: find.starred,
      text: find.text,
      expr: find.expr,
      tags: scopeSize(find.tags) ? find.tags : undefined,
      sourceId: find.source?.sourceId,
    }),
    [purpose, find.starred, find.text, find.expr, find.tags, find.source],
  );
  const metrics = useMemo(() => metricFilter(metricsDraft), [metricsDraft]);
  const query = useMemo(() => ({ ...scope, metrics }), [scope, metrics]);

  const load = useCallback(
    async (off: number) => {
      try {
        const r = await call("samples.list", { ...query, sort, offset: off, limit });
        setData(r);
        return r;
      } catch (e) {
        toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
        return null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query, sort, limit],
  );

  // 保存筛选器与分面的值（范围行「＋」聚焦时刷新计数）
  const loadFilters = useCallback(() => void call("filters.list", {}).then(setFilters, () => {}), []);
  const loadFacets = useCallback(() => void call("tags.facets", {}).then(setFacets, () => {}), []);
  useEffect(() => {
    if (ready) loadFilters();
  }, [ready, loadFilters]);
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).saved_filter) loadFilters();
  });

  // 一屏一页：按列表可见高度与实际行高算一页几行
  useEffect(() => {
    const el = listBox.current;
    if (!el) return;
    const measure = () => {
      const row = el.querySelector<HTMLElement>('[data-testid="sample-row"]');
      const h = row && !row.querySelector("[data-top]") ? row.offsetHeight : ROW_GUESS;
      setFitRows(Math.max(5, Math.floor(el.clientHeight / Math.max(40, h || ROW_GUESS))));
    };
    measure();
    const ro = new ResizeObserver(() => measure());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 从原片页「派生采样」跳过来：查找栏出现临时“原片：…”块（不存）
  useEffect(() => {
    if (!libraryScope) return;
    setFind((f) => ({ ...f, source: libraryScope }));
    setLibraryScope(null);
  }, [libraryScope, setLibraryScope]);

  // 分栏比例：重启恢复（UI_PLAN §2）
  useEffect(() => {
    if (!ready) return;
    void call("ui.get", { page: "library" }).then((v) => {
      if (typeof v.split === "number") setSplit(v.split);
      const f = v.find as Partial<FindState> & { purpose?: Purpose; sort?: Sort; pageSize?: PageSize } | undefined;
      if (f && typeof f === "object") {
        setFind({ ...EMPTY_FIND, text: f.text ?? "", expr: f.expr ?? "", starred: !!f.starred, tags: normScope(f.tags), preset: f.preset ?? null });
        if (f.purpose && PURPOSES.includes(f.purpose)) setPurpose(f.purpose);
        if (f.sort && SORTS.includes(f.sort)) setSort(f.sort);
        if (f.pageSize && PAGE_SIZES.includes(f.pageSize)) setPageSize(f.pageSize);
      }
      splitRestored.current = true;
    });
  }, [ready]);
  useEffect(() => {
    if (!splitRestored.current) return;
    const id = setTimeout(() => void call("ui.set", { page: "library", key: "split", value: split }), 300);
    return () => clearTimeout(id);
  }, [split]);
  useEffect(() => {
    if (!splitRestored.current) return;
    const { source: _s, ...keep } = find;
    const id = setTimeout(() => void call("ui.set", { page: "library", key: "find", value: { ...keep, purpose, sort, pageSize } }), 300);
    return () => clearTimeout(id);
  }, [find, purpose, sort, pageSize]);

  // 条件变化：回到第一页，清空勾选并提示（UI_PLAN §6.1）
  const firstQuery = useRef(true);
  useEffect(() => {
    if (!ready) return;
    setOffset(0);
    void load(0);
    if (firstQuery.current) {
      firstQuery.current = false;
      return;
    }
    setChecked((c) => {
      if (c.size) toast({ text: t("library.checkCleared", { n: c.size }) });
      return new Set();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, query]);
  // 排序、每页行数变了：回到第一页重读（勾选保留）
  const firstPaging = useRef(true);
  useEffect(() => {
    if (!ready) return;
    if (firstPaging.current) {
      firstPaging.current = false;
      return;
    }
    setOffset(0);
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sort, limit]);

  // 切回本页时刷新（资料可能在别处变了：新截取、删除原片）
  useEffect(() => {
    if (page === "library" && ready) void load(offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  // 「刷新浏览列表」：按当前条件重读当前页（勾选与焦点保留）
  const refreshTick = useApp((st) => st.refreshTick);
  useEffect(() => {
    if (refreshTick && ready) void load(offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // ⌘F：聚焦查找栏的文字（UI_PLAN §7）
  useEffect(() => {
    if (page !== "library") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        // ⌘F 聚焦查找栏的文字；⌘⇧F 聚焦范围行的「＋」（UI_PLAN §7）
        if (e.shiftKey) plusRef.current?.focus();
        else document.querySelector<HTMLInputElement>('[data-testid="library-search"]')?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [page]);

  // 截取后打开新采样
  useEffect(() => {
    if (!openSample || !ready) return;
    void (async () => {
      // 清空条件（新采样一定看得见），翻到它所在的那一页（按新建在前）
      const all = await call("samples.ids", {});
      const at = Math.max(0, all.indexOf(openSample));
      const off = Math.floor(at / limit) * limit;
      const r = await call("samples.list", { offset: off, limit, sort: "created" });
      setPurpose("all");
      setFind(EMPTY_FIND);
      setSort("created");
      setOffset(off);
      setData(r);
      setFocus(openSample);
      setOpenSample(null);
    })();
  }, [openSample, ready, setOpenSample]);

  // 焦点采样的资料（舞台）
  useEffect(() => {
    if (!focus || focus.startsWith("asset:") || focus.startsWith("gone:")) return setFocusRow(null);
    const inPage = data?.rows.find((r) => r.id === focus);
    if (inPage) setFocusRow((f) => (f?.id === inPage.id ? { ...f, ...inPage } : inPage));
    // 舞台要有效标签：总是再取一次完整资料
    void call("samples.get", { id: focus }).then(setFocusRow, () => setFocusRow(null));
  }, [focus, data]);

  // 试听状态；舞台波形的播放头 = 试听区间起点 + 区间本地秒（资产局部秒）。
  // 每帧读引擎位置（与原素材页一样插值、截停后贴终点）；这次试听真正开始播放之前不画（引擎里可能还是上一次的位置）
  const auditionFrom = useRef(0);
  const auditionLive = useRef(false);
  useEffect(
    () =>
      window.otto.player.onState((st: PlayerState) => {
        if (st.player !== "audition" || st.gen !== auditionGen.current) return;
        if (st.playing && !st.loading && st.time != null) auditionLive.current = true;
        if (st.ended || st.error) setPlaying(null);
      }),
    [],
  );
  /** 这次试听最后播到的位置（播完贴在终点、停止时停在停下处）：详情区用它放光标 */
  const stagePlayhead = (): number | null => {
    if (!auditionLive.current) return null;
    const p = window.otto.player.position("audition");
    return p == null ? null : auditionFrom.current + p;
  };
  /** 在舞台波形上播放资产的一段（光标处、选区、循环） */
  const playRange = async (r: SampleRow, a: number, b: number, loop = false) => {
    try {
      setPlaying(r.id);
      setPlayingVer("original:voice");
      auditionFrom.current = a;
      auditionLive.current = false;
      auditionGen.current = -1;
      auditionGen.current = await window.otto.player.audition(r.asset_id, a, b, loop, r.id);
      setNowPlaying({ sampleId: r.id, name: r.name, version: "original", sound: "voice", plan: null, bpm: null, originalSpeed: false, duration: b - a });
    } catch (e) {
      setPlaying(null);
      setNowPlaying(null);
      toast({ text: errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });
    }
  };
  const stopAudition = () => {
    window.otto.player.stopAudition();
    setPlaying(null);
    setNowPlaying(null);
  };

  // 固定结果（04 §4.2.10）：恢复不重搜；翻页只读；检索完成 → 新标签并激活、收起浮层
  const results = useResults(ready, (r: SearchFinished) => {
    setComposer(null);
    setChecked(new Set());
    setFocusHit(null);
    if (r.stats) toast({ text: t("search.done", { n: r.stats.samples, m: r.stats.hits }) });
  });
  const inResult = results.active !== BROWSE;
  const [resOffset, setResOffset] = useState(0);
  const loadResult = useCallback(async (id: string, off: number) => {
    try {
      setResPage(await call("results.page", { id, offset: off, limit }));
    } catch {
      setResPage(null);
    }
  }, [limit]);
  useEffect(() => {
    if (!inResult) return setResPage(null);
    setResOffset(0);
    setFocusHit(null);
    void loadResult(results.active, 0);
    setChecked((c) => {
      if (c.size) toast({ text: t("library.checkCleared", { n: c.size }) });
      return new Set();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results.active, inResult]);
  const items: Item[] = inResult ? (resPage?.rows ?? []).map(toItem) : (data?.rows ?? []);
  const rows = items;
  const glyphKey = items.map((x) => x.id).join(",");
  useEffect(() => {
    const ids = items.filter((x) => !x.dead && !x.id.startsWith("asset:") && !x.id.startsWith("gone:")).map((x) => x.id);
    if (!ready || !ids.length) return setGlyphs({});
    let live = true;
    void call("samples.glyphs", { ids }).then((g) => live && setGlyphs(g), () => {});
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glyphKey, ready, refreshTick]);
  /** 试听一个采样（PB1：原声、卡拍都一步）：原声直接读绑定区间（R22.3）；卡拍与咔哒声先由 Core 渲染（方案按需计算）。
   *  再按一次同一个 = 停止。 */
  const audition = async (r: SampleRow, version: AuditionVersion = "original", opts: AuditionOpts = {}) => {
    const sound = opts.sound ?? "voice";
    const key = `${version}:${sound}`;
    if (playing === r.id && playingVer === key) {
      window.otto.player.stopAudition();
      setPlaying(null);
      setNowPlaying(null);
      return;
    }
    if (version === "stretched" && isSingle(r.nature)) {
      toast({ text: t("error.rhythm-not-for-single-sound") });
      return;
    }
    try {
      setPlaying(r.id);
      setPlayingVer(key);
      auditionLive.current = false;
      auditionGen.current = -1;
      if (version === "original" && sound === "voice") {
        auditionFrom.current = r.start;
        auditionGen.current = await window.otto.player.audition(r.asset_id, r.start, r.end, false, r.id);
        setNowPlaying({ sampleId: r.id, name: r.name, version, sound, plan: null, bpm: null, originalSpeed: false, duration: r.end - r.start });
      } else {
        const rr = await call("rhythm.render", { id: r.id, version, sound, plan: opts.plan ?? "near_fast", mora: opts.mora ?? false, longVowel: opts.longVowel ?? false });
        auditionFrom.current = version === "original" ? r.start : Number.NaN; // 卡拍后的时间不在资产时间轴上：舞台波形不画播放头
        auditionGen.current = await window.otto.player.auditionRender(rr.key);
        setNowPlaying({ sampleId: r.id, name: r.name, version, sound, plan: rr.plan, bpm: rr.bpm, originalSpeed: rr.originalSpeed, duration: rr.duration });
      }
    } catch (e) {
      setPlaying(null);
      setNowPlaying(null);
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });
    }
  };

  // 导出与交接（12 §12.1、§12.3）：舞台上的卡拍导出/交接用舞台的临时方案与纯 mora；列表、批量用默认（近快、原节奏）
  const setLastExport = useApp((st) => st.setLastExport);
  const reveal = (path: string, reused = false) => {
    setLastExport([path]);
    toast({
      text: t(reused ? "sources.exportReused" : "sources.exported", { name: path.split(/[\\/]/).pop() ?? path }),
      action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(path) },
    });
  };
  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const exportOriginal = async (ids: string[]) => {
    try {
      const paths = await call("exports.samples", { ids, words: trackWords() });
      if (paths.length === 1) reveal(paths[0]!);
      else if (paths.length) {
        setLastExport(paths);
        toast({ text: t("library.exportedN", { n: paths.length }), action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(paths[0]!) } });
      }
    } catch (e) {
      fail(e);
    }
  };
  const exportStretched = async (ids: string[], opts: AuditionOpts = {}) => {
    const done: string[] = [];
    for (const id of ids) {
      try {
        const r = await call("exports.stretched", { id, words: trackWords(), plan: opts.plan ?? "near_fast", mora: opts.mora ?? false, longVowel: opts.longVowel ?? false });
        done.push(r.path);
        if (ids.length === 1) reveal(r.path, r.reused);
      } catch (e) {
        fail(e);
      }
    }
    if (ids.length > 1 && done.length) {
      setLastExport(done);
      toast({ text: t("library.exportedN", { n: done.length }), action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(done[0]!) } });
    }
  };
  /** 批量导出视频片段：原声版，每个一个任务；没有画面的列出来（Q8） */
  const exportVideos = async (ids: string[]) => {
    let queued = 0;
    for (const id of ids) {
      try {
        const r = await call("exports.video", { id, version: "original", words: trackWords() });
        if (r.job) queued++;
      } catch (e) {
        fail(e);
      }
    }
    if (queued) toast({ text: t("video.queuedN", { n: queued }) });
  };
  /** ``baked``：卡好拍的声音 + 起音拉伸标记；false = 未烘焙原声 + 卡拍拉伸标记（12 §12.3）；不给 = 按设置（⌘C） */
  const copyReaper = async (ids: string[], opts: AuditionOpts = {}, baked?: boolean) => {
    const r = await window.otto.reaper.copy({ ids, words: trackWords(), plan: opts.plan ?? "near_fast", mora: opts.mora ?? false, longVowel: opts.longVowel ?? false, baked });
    if (!r.ok) return toast({ text: errorText(r.e), tone: "error" });
    toast({ text: t(r.r.count > 1 ? "reaper.copiedN" : "reaper.copied", { n: r.r.count }) });
  };
  const reaperTemplate = async (ids: string[], opts: AuditionOpts = {}) => {
    try {
      const r = await call("reaper.template", { ids, words: trackWords(), plan: opts.plan ?? "near_fast", mora: opts.mora ?? false, longVowel: opts.longVowel ?? false });
      reveal(r.path);
    } catch (e) {
      fail(e);
    }
  };
  /** 「交接 ▾」与右键里的导出项：整个采样（单音只有原声） */
  const handoffItems = (r: SampleRow, opts: AuditionOpts = {}): MenuItems =>
    isSingle(r.nature)
      ? [
          { id: "wav", label: t("handoff.wav"), run: () => void exportOriginal([r.id]) },
          { id: "video", label: t("video.menu"), run: () => setVideoFor({ sample: r, ...opts }) },
        ]
      : [
          { id: "wav", label: t("handoff.wav"), run: () => void exportOriginal([r.id]) },
          { id: "stretched", label: t("handoff.stretchedWav"), run: () => void exportStretched([r.id], opts) },
          { id: "video", label: t("video.menu"), run: () => setVideoFor({ sample: r, ...opts }) },
          "-",
          { id: "reaperBaked", label: t("handoff.reaperBaked"), run: () => void copyReaper([r.id], opts, true) },
          { id: "reaper", label: t("handoff.reaper"), run: () => void copyReaper([r.id], opts, false) },
          { id: "rtt", label: t("handoff.rtt"), run: () => void reaperTemplate([r.id], opts) },
        ];

  const edit = async (ids: string[], fields: Record<string, unknown>, label: string) => {
    const targets = rows.filter((r) => ids.includes(r.id));
    const missing = ids.filter((id) => !targets.some((r) => r.id === id));
    const extra = await Promise.all(missing.map((id) => call("samples.get", { id })));
    const all = [...targets, ...extra];
    try {
      await call("edits.apply", {
        batch: { label: { code: label, args: { n: all.length } }, ops: all.map((r) => ({ entity: "sample", id: r.id, version: r.version, fields })) },
      });
      // 就地更新，不重排（改完该行留在原位，刷新后按新条件归位）
      setData((d) => d && { ...d, rows: d.rows.map((r) => (ids.includes(r.id) ? { ...r, ...fields, version: r.version + 1 } : r)) });
      if (inResult) void loadResult(results.active, resOffset);
      setFocusRow((f) => (f && ids.includes(f.id) ? { ...f, ...fields, version: f.version + 1 } : f));
      if (focus && ids.includes(focus)) void call("samples.get", { id: focus }).then(setFocusRow, () => {});
      toast({ text: t("library.edited", { n: all.length }), action: { label: t("common.undo"), run: () => void undo().then(() => load(offset)) } });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
      void load(offset);
    }
  };

  // 舞台跟着资料变化（撤销、提升、原片属性、文本层的段与区段标签、读到的分析）重读焦点采样；列表不自动重排（P8：底部提示“刷新浏览列表”）
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (focus && (c.sample?.includes(focus) || c.measure?.includes(focus) || c.segment || c.range_tag || c.source || c.asset)) {
      void call("samples.get", { id: focus }).then(setFocusRow, () => {});
    }
  });

  const addLocalTag = () => {
    const v = tagDraft.trim();
    if (!v || !focusRow) return;
    const local = (focusRow.tags ?? []).filter((x) => x.provenance === "local").map((x) => x.tag);
    if (!local.includes(v)) void edit([focusRow.id], { local_tags: [...local, v] }, "sample-tags");
    setTagOpen(false);
    setTagDraft("");
  };
  // 舞台标签的菜单（UI_PLAN §3、§8）：加入范围；继承的去来源（07 §7.4：继承标签点一下跳到来源）；本地的移除
  const tagMenu = useContextMenu("tag-menu");
  const tagAt = useRef<{ clientX: number; clientY: number } | null>(null);
  const goSource = (ref: { sourceId: string | null; start?: number; end?: number }) => {
    if (!ref.sourceId) return;
    setSourceJump({ sourceId: ref.sourceId, a: ref.start ?? 0, b: ref.end ?? 0 });
    setPage("sources");
  };
  const openTagMenu = (r: SampleRow, tg: EffectiveTag) => {
    const at = tagAt.current ?? (() => {
      const b = document.querySelector('[data-testid="stage-tags"]')?.getBoundingClientRect();
      return { clientX: b?.left ?? 0, clientY: b?.bottom ?? 0 };
    })();
    tagAt.current = null;
    tagMenu.open(at, {
      head: t("menu.on", { name: tg.tag }),
      items: [
        {
          id: "to-scope",
          label: t("tag.toScope"),
          run: () =>
            setFind((f) => {
              const v = facetValue(tg);
              const i = f.tags.facets.findIndex((x) => x.facet === tg.facet);
              const facets =
                i < 0
                  ? [...f.tags.facets, { facet: tg.facet as FacetCondition["facet"], values: [v], single: false }]
                  : f.tags.facets.map((x, k) => (k === i && !x.values.includes(v) ? { ...x, values: [...x.values, v] } : x));
              return { ...f, tags: { ...f.tags, facets } };
            }),
        },
        ...(tg.provenance === "local"
          ? [{ id: "remove", label: t("tag.removeLocal"), run: () => void edit([r.id], { local_tags: (r.tags ?? []).filter((x) => x.provenance === "local" && x.tag !== tg.tag).map((x) => x.tag) }, "sample-tags") }]
          : [
              {
                id: "go-source",
                label: t(`tag.goSource.${tg.provenance}`),
                run: () =>
                  void call("tags.ofSamples", { ids: [r.id] }).then((xs) => {
                    const src = xs.find((x) => x.tag === tg.tag)?.sources[0];
                    if (src) goSource(src);
                  }, fail),
              },
            ]),
      ],
    });
  };
  const refreshAfterPromote = () => {
    void load(offset);
    if (focus) void call("samples.get", { id: focus }).then(setFocusRow, () => {});
  };

  const checkAllMatching = async () => {
    if (!inResult) return setChecked(new Set(await call("samples.ids", query)));
    // 固定结果：全部成员（跨页），失效的不勾
    const ids: string[] = [];
    for (let off = 0; ; off += PAGE) {
      const p = await call("results.page", { id: results.active, offset: off, limit: PAGE });
      ids.push(...p.rows.filter((r) => r.state !== "deleted" && r.state !== "changed" && r.sampleId).map((r) => r.sampleId!));
      if (off + PAGE >= p.total) break;
    }
    setChecked(new Set(ids));
  };

  const total = inResult ? (resPage?.total ?? 0) : (data?.total ?? 0);
  const filtered = !!(find.text || find.expr || find.starred || find.source || scopeSize(find.tags) || purpose !== "all" || metrics);
  /** 「更新」：把范围行写回当前选用的筛选器（可撤销） */
  const updatePreset = async () => {
    const f = filters.find((x) => x.id === find.preset);
    if (!f) return;
    try {
      await call("edits.apply", {
        batch: { label: { code: "filter-update", args: { name: f.name } }, ops: [{ entity: "saved_filter", id: f.id, version: f.version, fields: { conditions: find.tags } }] } as never,
      });
      toast({ text: t("scope.updated", { name: f.name }), action: { label: t("common.undo"), run: () => void undo() } });
    } catch (e) {
      fail(e);
    }
    loadFilters();
  };
  const curOffset = inResult ? resOffset : offset;
  const pages = Math.max(1, Math.ceil(total / limit));
  const pageNo = Math.floor(curOffset / limit) + 1;
  const goto = (p: number) => {
    const off = (Math.max(1, Math.min(pages, p)) - 1) * limit;
    if (inResult) {
      setResOffset(off);
      void loadResult(results.active, off);
      return;
    }
    setOffset(off);
    void load(off);
  };

  // ---- 检索
  const runSearch = async () => {
    if (composer === "speech") await results.start(() => call("search.speech", { query: speechQuery(speechDraft), scope }), "speech");
    else if (composer === "pitch")
      await results.start(() => call("search.pitch", { blocks: pitchBlocks(pitchDraft), params: pitchParams(pitchDraft), mode: pitchDraft.mode, scope }), "pitch");
  };
  /** 「再搜一次」：用这个结果当时的条件再搜（生成新标签；范围用当时的快照） */
  const again = async () => {
    const h = resPage?.result;
    if (!h) return;
    const q = h.query as Record<string, unknown>;
    const sc = (h.scope as { scope?: SampleFilter }).scope ?? {};
    if (h.kind === "speech") await results.start(() => call("search.speech", { query: q as never, scope: sc }), "speech");
    else await results.start(() => call("search.pitch", { blocks: q.blocks as never, params: q.params as never, mode: q.mode as "samples", scope: sc }), "pitch");
  };
  const resultTitle = (h: { kind: string; createdAt: string; stats: { samples: number } }) =>
    t(h.kind === "speech" ? "search.tab.speech" : "search.tab.pitch", { time: new Date(h.createdAt).toTimeString().slice(0, 5), n: h.stats.samples });

  // ---- 命中（09 §9.7、10 §10.2.6）
  const hitRef = (r: ResultRow, i: number) => ({ resultId: results.active, rank: r.rank, index: i });
  const locate = (it: Item, i: number) => {
    const r = it._res;
    if (!r) return;
    if (!r.sample) {
      const h = r.hits[i]!;
      if (r.asset && h.sourceStart != null && h.sourceEnd != null) {
        setSourceJump({ sourceId: r.asset.sourceId, assetId: r.asset.id, a: h.sourceStart, b: h.sourceEnd });
        setPage("sources");
      }
      return;
    }
    if (r.state !== "ok") return toast({ text: t(r.state === "stale" ? "error.hit-stale" : "search.row.invalid") });
    setFocus(it.id);
    setFocusHit({ id: it.id, index: i });
  };
  const playHit = async (it: Item, i: number, version: "original" | "stretched") => {
    const r = it._res;
    if (!r) return;
    const key = `${r.rank}:${i}:${version}`;
    if (hitPlaying === key) {
      window.otto.player.stopAudition();
      setHitPlaying(null);
      setNowPlaying(null);
      return;
    }
    try {
      const info = await call("hits.resolve", hitRef(r, i));
      setHitPlaying(key);
      setPlaying(null);
      if (version === "original") {
        const p = pad && info.kind === "speech" ? 0.3 : 0;
        const dur = p ? (await call("assets.get", { id: info.assetId })).duration : info.end;
        const a = Math.max(0, info.start - p);
        const b = Math.min(dur, info.end + p);
        auditionFrom.current = a;
        auditionGen.current = await window.otto.player.audition(info.assetId, a, b);
        setNowPlaying({ sampleId: info.sampleId ?? "", name: it.name, version: "original", sound: "voice", plan: null, bpm: null, originalSpeed: false, duration: b - a });
      } else {
        if (!info.stretch) return toast({ text: t("error.hit-no-stretch") });
        const rr = await call("hits.render", { ...hitRef(r, i), version: "stretched", sound: "voice" });
        auditionFrom.current = Number.NaN;
        auditionGen.current = await window.otto.player.auditionRender(rr.key);
        setNowPlaying({ sampleId: info.sampleId ?? "", name: it.name, version: "stretched", sound: "voice", plan: rr.plan, bpm: rr.bpm, originalSpeed: rr.originalSpeed, duration: rr.duration });
      }
    } catch (e) {
      setHitPlaying(null);
      fail(e);
    }
  };
  const exportHit = async (r: ResultRow, i: number, version: "original" | "stretched") => {
    try {
      const x = await call("hits.export", { ...hitRef(r, i), version, words: trackWords() });
      reveal(x.path, x.reused);
    } catch (e) {
      fail(e);
    }
  };
  /** 命中导出视频片段（L30、L36）：同一个对话框；语音命中可选卡拍版（命中证据的方案），画面按命中所在采样的有效画面 */
  const videoHit = (it: Item, r: ResultRow, i: number) => {
    if (!r.sample) return;
    const h = r.hits[i]!;
    const base = r.sample.start;
    const label = t("video.hitLabel", { name: it.name, a: (h.start - base).toFixed(2), b: (h.end - base).toFixed(2) });
    setVideoFor({ sample: r.sample, hit: { ...hitRef(r, i), label, stretch: (resPage?.result.kind ?? "speech") === "speech" } });
  };
  const reaperHit = async (r: ResultRow, i: number, baked: boolean) => {
    const x = await window.otto.reaper.copy({ ids: [], hits: [hitRef(r, i)], words: trackWords(), baked });
    if (!x.ok) return toast({ text: errorText(x.e), tone: "error" });
    toast({ text: t("reaper.copied", { n: 1 }) });
  };
  const openHitMenu = (it: Item, i: number, e: { clientX: number; clientY: number }) => {
    const r = it._res;
    if (!r) return;
    const h = r.hits[i]!;
    const kind = resPage?.result.kind ?? "speech";
    const base = r.sample ? r.sample.start : 0;
    const common: MenuItems = [
      { id: "locate", label: t("search.hit.locate"), shortcut: "Enter", run: () => locate(it, i) },
      { id: "loop", label: t("search.hit.listen"), run: () => void playHit(it, i, "original") },
      ...(r.sample ? [{ id: "back", label: t("library.backToSource"), disabled: r.sample.source_start == null, run: () => backToSource(r.sample!) }] : []),
      "-",
      ...(r.sample
        ? [
            { id: "save", label: t("search.hit.save"), run: () => { locate(it, i); setClipTick((x) => x + 1); } },
            { id: "flatten", label: t("search.hit.flatten"), run: () => requestFlatten({ kind: "single", assetId: r.sample!.asset_id, start: h.start, end: h.end, entry: "single", sampleId: r.sample!.id }) },
          ]
        : []),
    ];
    const speechOnly: MenuItems =
      kind === "speech" && r.sample
        ? [
            "-",
            { id: "wav", label: t("handoff.wav"), run: () => void exportHit(r, i, "original") },
            { id: "stretched", label: t("handoff.stretchedWav"), run: () => void exportHit(r, i, "stretched") },
            { id: "reaperBaked", label: t("handoff.reaperBaked"), run: () => void reaperHit(r, i, true) },
            { id: "reaper", label: t("handoff.reaper"), run: () => void reaperHit(r, i, false) },
          ]
        : [];
    const videoItem: MenuItems = r.sample ? [{ id: "video", label: t("video.menu"), run: () => videoHit(it, r, i) }] : [];
    hitMenu.open(e, { head: t("search.hit.menuHead", { a: (h.start - base).toFixed(2), b: (h.end - base).toFixed(2), name: it.name }), items: [...common, ...speechOnly, ...videoItem] });
  };
  const focusItem = items.find((x) => x.id === focus) ?? null;
  const stageHit = focusHit && focusRow && focusHit.id === focusRow.id && focusItem?._res ? focusItem._res.hits[focusHit.index] ?? null : null;

  const removeConfirmed = async () => {
    if (!deleteIds) return;
    try {
      const r = await call("samples.delete", { ids: deleteIds });
      toast({ text: t("library.deleted", { n: r.deleted }) });
      setChecked((c) => new Set([...c].filter((id) => !deleteIds.includes(id))));
      if (focus && deleteIds.includes(focus)) setFocus(null);
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setDeleteIds(null);
      void load(offset);
    }
  };

  // 「返回原素材」（所有者 2026-10-12）：每次都换到采样来自的整轨（沿加工链往上第一条整轨），跳到它的原素材起止，在“采样”车道上突出它
  const backToSource = (r: SampleRow) => {
    if (r.source_start == null || r.source_end == null) return;
    setSourceJump({ sourceId: r.source_id, assetId: r.back_asset_id ?? undefined, a: r.source_start, b: r.source_end, highlight: r.id });
    setPage("sources");
  };

  // 菜单（UI_PLAN §6.1、§8）：右键、舞台 ⋯、批量操作 ▾ 共用同一组动作
  const natureItems = (ids: string[]): MenuItems =>
    NATURES.map((n) => ({ id: `nature-${n}`, label: t(`nature.${n}`), shortcut: KEY_OF[n], run: () => void edit(ids, { nature: n }, "sample-nature") }));
  // 批量局部分离（所有者 2026-11-03）：同一条音轨上的采样并成一个任务（模型只加载一次）；每个声部照旧建一个采样
  const separateMany = async (ids: string[]) => {
    const all = await Promise.all(ids.map(async (id) => rows.find((r) => r.id === id) ?? call("samples.get", { id })));
    const byAsset = new Map<string, number[][]>();
    for (const x of all) byAsset.set(x.asset_id, [...(byAsset.get(x.asset_id) ?? []), [x.start, x.end]]);
    const jobs = [...byAsset].map(([assetId, ranges]) => ({ assetId, ranges }));
    requestSeparation({ assetId: jobs[0]!.assetId, trackLabel: "", duration: 0, selection: null, scope: "sel", batch: { kind: "samples", n: ids.length, jobs } });
  };
  const groupItems = (ids: string[]): MenuItems => [
    { id: "tags-add", label: t("library.addTags"), run: () => setBatch({ kind: "tags-add", ids }) },
    { id: "tags-remove", label: t("library.removeTags"), run: () => setBatch({ kind: "tags-remove", ids }) },
    { id: "nature", label: t("library.setNature"), items: natureItems(ids) },
    { id: "star", label: t("library.starOn"), shortcut: "S", run: () => void edit(ids, { starred: true }, "sample-star") },
    { id: "unstar", label: t("library.starOff"), run: () => void edit(ids, { starred: false }, "sample-star") },
    { id: "edit", label: t("library.editInfo"), run: () => setBatch({ kind: "edit", ids }) },
    { id: "independ", label: t("indep.menuN", { n: ids.length }), run: () => setIndependFor(ids) },
    "-",
    { id: "speech", label: t("speech.menuN", { n: ids.length }), run: () => requestSpeech({ entry: "samples", ids }) },
    { id: "flatten", label: t("flatten.menuN", { n: ids.length }), run: () => requestFlatten({ kind: "batch", ids }) },
    { id: "separate", label: t("sep.menuSamplesN", { n: ids.length }), run: () => void separateMany(ids) },
    "-",
    {
      id: "export",
      label: t("handoff.export"),
      items: [
        { id: "wav", label: t("handoff.wavN", { n: ids.length }), run: () => void exportOriginal(ids) },
        { id: "stretched", label: t("handoff.stretchedWavN", { n: ids.length }), run: () => void exportStretched(ids) },
        { id: "video", label: t("video.menuN", { n: ids.length }), run: () => void exportVideos(ids) },
      ],
    },
    {
      id: "reaper",
      label: t("handoff.reaperMenu"),
      items: [
        { id: "reaperBaked", label: t("handoff.reaperBakedN", { n: ids.length }), run: () => void copyReaper(ids, {}, true) },
        { id: "reaper", label: t("handoff.reaperN", { n: ids.length }), run: () => void copyReaper(ids, {}, false) },
        { id: "rtt", label: t("handoff.rttN", { n: ids.length }), run: () => void reaperTemplate(ids) },
      ],
    },
    "-",
    { id: "delete", label: t("library.deleteDots"), danger: true, shortcut: "⌫", run: () => setDeleteIds(ids) },
  ];
  /** 舞台上的临时选择（方案、纯 mora）只作用于舞台上的试听与交接（所有者 2026-10-08） */
  const stageOpts = (id: string): AuditionOpts =>
    stageRhythm.sampleId === id ? { plan: stageRhythm.plan, mora: stageRhythm.mora, longVowel: stageRhythm.longVowel } : {};
  /** ``entry``：舞台的 ⋯ 是“采样详情”入口（拉平默认首元音起 + 交界左），列表右键是其他单个入口（11 §11.2） */
  const sampleMenu = (r: SampleRow, ids: string[], multi: boolean, entry: "detail" | "single" = "single"): MenuSpec =>
    multi
      ? { head: t("menu.checkedN", { n: ids.length }), items: groupItems(ids) }
      : {
          head: t("menu.on", { name: r.name }),
          items: [
            { id: "audition", label: t("library.auditionOriginal"), shortcut: "Space", run: () => void audition(r) },
            ...(isSingle(r.nature) ? [] : [{ id: "auditionStretched", label: t("library.auditionStretched"), shortcut: "B", run: () => void audition(r, "stretched") }]),
            "-",
            { id: "tags-add", label: t("library.addTags"), run: () => setBatch({ kind: "tags-add", ids: [r.id] }) },
            { id: "tags-remove", label: t("library.removeTags"), run: () => setBatch({ kind: "tags-remove", ids: [r.id] }) },
            { id: "nature", label: t("library.setNature"), items: natureItems([r.id]) },
            { id: "star", label: r.starred ? t("library.starOff") : t("library.starOn"), shortcut: "S", run: () => void edit([r.id], { starred: !r.starred }, "sample-star") },
            { id: "edit", label: t("library.editInfo"), run: () => setBatch({ kind: "edit", ids: [r.id] }) },
            { id: "visual", label: t("visual.menu"), run: () => setVisualFor({ ownerType: "sample", id: r.id, name: r.name }) },
            { id: "independ", label: t("indep.menu"), disabled: r.independent, run: () => setIndependFor([r.id]) },
            "-",
            { id: "back", label: t("library.backToSource"), disabled: r.source_start == null || r.media_state === "released", run: () => backToSource(r) },
            { id: "speech", label: t("speech.menu"), run: () => requestSpeech({ entry: "samples", ids: [r.id] }) },
            { id: "flatten", label: t("flatten.menu"), run: () => requestFlatten({ kind: "single", assetId: r.asset_id, start: r.start, end: r.end, entry, sampleId: r.id }) },
            "-",
            ...handoffItems(r, entry === "detail" ? stageOpts(r.id) : {}),
            "-",
            { id: "delete", label: t("library.deleteDots"), danger: true, shortcut: "⌫", run: () => setDeleteIds([r.id]) },
          ],
        };

  // 命令面板（⌘K）：作用对象 = 已勾选集，没有勾选就是当前查看的采样（菜单与右键同一份）；再加本页的检索、用途视图、筛选器、导入
  useCommands("library", "library", () => {
    const out: PaletteSection[] = [];
    if (checked.size) {
      const title = t("menu.checkedN", { n: checked.size });
      out.push({ id: "library-target", title, items: fromMenu("library-target", title, groupItems([...checked])) });
    } else if (focusRow) {
      const title = t("cmd.currentSample", { name: focusRow.name });
      out.push({ id: "library-target", title, items: fromMenu("library-target", title, sampleMenu(focusRow, [focusRow.id], false, "detail").items) });
    }
    const g = t("nav.library");
    const items: PaletteCommand[] = [
      ...(["speech", "pitch", "timbre", "transient"] as const).map((k) => ({
        key: `library/search-${k}`, label: t("cmd.search", { kind: t(`search.kind.${k}`) }), group: g, run: () => setComposer(k),
      })),
      ...PURPOSES.map((x) => ({
        key: `library/purpose-${x}`, label: t("cmd.purpose", { name: x === "all" ? t("library.all") : t(`nature.${x}`) }), group: g, disabled: purpose === x, run: () => setPurpose(x),
      })),
      { key: "library/starred", label: find.starred ? t("cmd.starredOff") : t("library.starredOnly"), group: g, run: () => setFind((f) => ({ ...f, starred: !f.starred })) },
      ...filters.map((f) => ({
        key: `library/filter-${f.id}`, label: t("cmd.filter", { name: f.name }), group: g, disabled: find.preset === f.id,
        run: () => setFind((x) => ({ ...x, preset: f.id, tags: normScope(f.conditions) })),
      })),
      { key: "library/scope-clear", label: t("scope.clear"), group: g, disabled: !scopeSize(find.tags), run: () => setFind((f) => ({ ...f, preset: null, tags: EMPTY_FIND.tags })) },
      { key: "library/scope-expr", label: t("cmd.scopeExpr"), group: g, run: () => setFilterDialog("expr") },
      { key: "library/scope-save", label: t("scope.saveAsDots"), group: g, disabled: !scopeSize(find.tags), run: () => setFilterDialog("save") },
      { key: "library/scope-manage", label: t("scope.manageDots"), group: g, disabled: !filters.length, run: () => setFilterDialog("manage") },
      { key: "library/import", label: t("cmd.import"), group: g, run: () => void pickImport() },
    ];
    out.push({ id: "library", title: g, items });
    return out;
  });

  // ⌘C（所有者 2026-10-08 选丙）：采样库里复制 REAPER 交接——勾选集，没有勾选就是当前采样；哪种按设置「导出」。
  // macOS 上应用菜单的「拷贝」先接走按键、变成页面的 copy 事件；按键直接到页面时（Windows 或没有菜单时）听 keydown。两路去重。
  // 输入框里、或页面上选中了文字时照常复制文字；舞台上的方案与临时纯 mora 只作用于当前采样（勾选集用默认）。
  const lastCopy = useRef(0);
  useEffect(() => {
    if (page !== "library") return;
    const run = (ev: Event): void => {
      const el = document.activeElement as HTMLElement | null;
      if (el?.closest("input, textarea, [contenteditable=true], [role=dialog]") || (window.getSelection()?.toString() ?? "") !== "") return;
      const ids = checked.size ? [...checked] : focusRow ? [focusRow.id] : [];
      if (!ids.length) return;
      ev.preventDefault();
      if (performance.now() - lastCopy.current < 500) return;
      lastCopy.current = performance.now();
      void copyReaper(ids, ids.length === 1 ? stageOpts(ids[0]!) : {});
    };
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "c") run(e);
    };
    document.addEventListener("copy", run);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("copy", run);
      window.removeEventListener("keydown", onKey);
    };
  });

  const onKey = (e: React.KeyboardEvent, it: SampleRow | null): boolean => {
    if (e.metaKey || e.ctrlKey || e.altKey) return false;
    const ids = checked.size ? [...checked] : it ? [it.id] : [];
    if (e.key === " ") {
      if (it) void audition(it);
      return true;
    }
    if (e.key === "b" || e.key === "B") {
      if (it) void audition(it, "stretched");
      return true;
    }
    if (e.key in NATURE_KEYS) {
      if (ids.length) void edit(ids, { nature: NATURE_KEYS[e.key] }, "sample-nature");
      return true;
    }
    if (e.key === "s" || e.key === "S") {
      if (ids.length) {
        const all = rows.filter((r) => ids.includes(r.id));
        void edit(ids, { starred: !all.every((r) => r.starred) }, "sample-star");
      }
      return true;
    }
    return false;
  };

  const list = (
    <section className={s.left}>
      <FindBar find={find} setFind={setFind} />
      <ScopeRow
        find={find}
        setFind={setFind}
        filters={filters}
        facets={facets}
        loadFacets={loadFacets}
        onSaveAs={() => setFilterDialog("save")}
        onUpdate={() => void updatePreset()}
        onManage={() => setFilterDialog("manage")}
        onEditExpr={() => setFilterDialog("expr")}
        plusRef={plusRef}
      />
      <div className={s.resultHead}>
        <ClosableTabs
          label={t("search.results")}
          closeLabel={t("search.closeResult")}
          value={results.active}
          onChange={results.setActive}
          onClose={(id) => void results.close(id)}
          items={[
            { id: BROWSE, label: t("library.browse"), count: inResult ? undefined : total, testId: "tab-browse" },
            ...results.tabs.map((h) => ({ id: h.id, label: resultTitle(h), closable: true, testId: "result-tab" })),
          ]}
        />
        <Button size="sm" variant="flat" icon={<Plus />} onPress={() => void pickImport()} data-testid="library-import">
          {t("import.button")}
        </Button>
        <Button size="sm" variant="flat" icon={<ChevronLeft />} isDisabled={pageNo <= 1} onPress={() => goto(pageNo - 1)} aria-label={t("pager.prev")} />
        <span className="num">
          {pageNo} / {pages}
        </span>
        <Button size="sm" variant="flat" icon={<ChevronRight />} isDisabled={pageNo >= pages} onPress={() => goto(pageNo + 1)} aria-label={t("pager.next")} />
        <span className={ss.hunt}>
          <Button
            size="sm"
            variant={composer ? "primary" : "secondary"}
            icon={<Crosshair />}
            onPress={() => setComposer((c) => (c ? null : HUNT[purpose]!))}
            data-testid="hunt-open"
          >
            {t(`search.hunt.${HUNT[purpose]}`)}
          </Button>
          <Menu
            head={t("search.kindMenu")}
            items={(["speech", "pitch", "timbre", "transient"] as const).map((k) => ({ id: k, label: t(`search.kind.${k}`), run: () => setComposer(k) }))}
            placement="bottom end"
            trigger={<Button size="sm" variant={composer ? "primary" : "secondary"} icon={<ChevronDown />} aria-label={t("search.kindMenu")} data-testid="hunt" />}
          />
        </span>
      </div>
      <div className={s.status}>
        {inResult && resPage ? (
          <>
            <span data-testid="result-status">
              {t("search.status", { n: resPage.result.stats.samples, m: resPage.result.stats.hits, ms: resPage.result.stats.ms, k: resPage.result.stats.noAnalysis })}
            </span>
            {resPage.result.stats.stale ? <span className={ss.approx}>· {t("search.statusStale", { n: resPage.result.stats.stale })}</span> : null}
            {resPage.result.kind === "speech" && resPage.result.stats.bpm != null ? <span>· {t("search.statusBpm", { bpm: resPage.result.stats.bpm })}</span> : null}
            <span className={s.grow} />
            <Button size="sm" variant="flat" onPress={() => void again()} isDisabled={!!results.running} data-testid="search-again">
              {t("search.again")}
            </Button>
          </>
        ) : (
          <>
            <span data-testid="library-total">{t("library.total", { n: total })}</span>
            <span>·</span>
            <Menu
              head={t("library.sortHead")}
              items={[
                ...SORTS.map((k) => ({ id: `sort-${k}`, label: `${sort === k ? "✓ " : ""}${t(`library.sort.${k}`)}`, run: () => setSort(k) })),
                "-",
                ...PAGE_SIZES.map((k) => ({ id: `size-${k}`, label: `${pageSize === k ? "✓ " : ""}${k === "fit" ? t("library.pageFit") : t("library.pageN", { n: k })}`, run: () => setPageSize(k) })),
              ]}
              trigger={
                <Button size="sm" variant="flat" data-testid="library-sort">
                  {t(`library.sort.${sort}`)}
                  <ChevronDown size={12} />
                </Button>
              }
            />
            {metrics ? (
              <>
                <span data-testid="metrics-active">· {t("search.metrics.active", { kind: t(`search.kind.${metrics.mode}`), n: metrics.conditions.length })}</span>
                <Button size="sm" variant="flat" onPress={() => setMetricsDraft(newMetricsDraft(metricsDraft.mode))}>
                  {t("search.metrics.clear")}
                </Button>
              </>
            ) : null}
          </>
        )}
      </div>
      <div className={s.listBox} ref={listBox}>
      <CollectionList<Item>
        label={t("library.listLabel")}
        items={rows}
        textValue={(r) => r.name}
        focus={focus}
        onFocus={setFocus}
        checked={checked}
        onChecked={setChecked}
        onCheckAll={() => void checkAllMatching()}
        onPrimary={(id) => {
          const r = rows.find((x) => x.id === id);
          if (r?._res && (r.dead || !r._res.sample)) return r._res.asset ? locate(r, 0) : toast({ text: t("search.row.deletedKeep") });
          if (r) void audition(r);
        }}
        onDelete={setDeleteIds}
        onKey={onKey}
        menu={(r, target) => (r._res && (r.dead || !r._res.sample) ? null : sampleMenu(r, target.ids, target.multi))}
        checkLabel={(r) => t("library.check", { name: r.name })}
        testId="sample-list"
        rowTestId="sample-row"
        // 行里的试听按钮跟着这些状态变（所有者 2026-10-30：播完按钮停在“停止”，因为行被缓存、没重画）
        renderDeps={[playing, playingVer, hitPlaying]}
        rowData={(r): Record<string, string> => (r._res ? { "data-nature": r.nature, "data-top": "" } : { "data-nature": r.nature })}
        onRowPointerDown={(e, r) => {
          // ⌥ 拖出原声、⌥⇧ 拖出卡拍（所有者 2026-10-08 选丙）；在勾选集里且 ≥2 → 整个勾选集；按钮、复选框上按下不接管（规格 12 §12.2）
          if ((e.target as Element).closest("button, input, label")) return;
          const ids = checked.has(r.id) && checked.size >= 2 ? [...checked] : [r.id];
          const version = e.shiftKey ? "stretched" : "original";
          const versions = Object.fromEntries(ids.map((id) => [id, version] as const));
          beginDragOut(e, () => call("exports.samples", { ids, words: trackWords(), versions }));
        }}
        empty={
          data ? (
            <EmptyState
              icon={<SquareStack />}
              title={t(total || filtered ? "library.noMatch" : "library.empty.title")}
              body={total || filtered ? undefined : t("library.empty.body")}
            />
          ) : null
        }
        renderItem={(r) =>
          r._res && !r._res.sample ? (
            <div className={ss.assetRow}>
              <span className={s.name} data-user-data="">
                {r._res.asset ? r.name : t("search.row.deleted")}
              </span>
              {r._res.asset ? (
                <span className={s.meta}>
                  {r._res.asset.stemName ?? t(`track.origin.${r._res.asset.origin}`)} · {t("search.row.sourceHits")}
                </span>
              ) : (
                <span className={ss.dead}>{t("search.row.deletedKeep")}</span>
              )}
              {r._res.asset ? (
                <HitLine hits={r._res.hits} kind="pitch" start={0} duration={Math.max(...r._res.hits.map((h) => h.end), 1)} focusIndex={null}
                  onLocate={(i) => locate(r, i)} onMenu={(i, e) => openHitMenu(r, i, e)} />
              ) : null}
            </div>
          ) : (
          <>
            <SampleThumb
              id={r.id}
              play={{
                playing: playing === r.id,
                onPress: () => void audition(r),
                onSecondary: isSingle(r.nature) ? undefined : () => void audition(r, "stretched"),
                label: playing === r.id ? t("library.stop") : t(isSingle(r.nature) ? "library.audition" : "library.auditionBoth"),
                testId: "sample-play",
              }}
            />
            <div className={s.body} data-nature={r.nature}>
              <div className={s.nameLine}>
                <NatureDot nature={r.nature} />
                <span className={s.name} lang={r.language ?? "ja"} title={r.name} data-user-data="">
                  {r.name}
                </span>
              </div>
              <div className={s.meta}>
                {purpose !== "all" && r.nature !== purpose && !r._res ? (
                  // 用途视图里一步归类后：就地写“已归类为…”，不立即消失（R8.10），刷新或翻页后移出
                  <span className={s.reclass} data-testid="row-reclassified">
                    {t("library.reclassified", { nature: t(`nature.${r.nature}`) })}
                  </span>
                ) : null}
                <RowExtra r={r} g={glyphs[r.id]} />
                {r.independent ? <span className={s.badge}>{t("indep.badge")}</span> : null}
                {r.people.length ? (
                  <span className={s.who} lang="ja" data-user-data="">
                    {r.people.join(t("settings.subtitle.speakerSep"))}
                  </span>
                ) : null}
                <span className={s.src} data-user-data="">
                  {r.source_name} · {clock(r.source_start)}
                </span>
                <span className={`${s.dur} num`}>{t("format.sec", { v: seconds(r.duration) })}</span>
              </div>
              {r._res ? (
                <>
                  {r._res.state !== "ok" ? <span className={ss.dead} data-testid="row-state">{t(`search.row.${r._res.state}`)}</span> : null}
                  <HitLine
                    hits={r._res.hits}
                    kind={resPage?.result.kind ?? "speech"}
                    start={r.start}
                    duration={r.duration}
                    focusIndex={focusHit?.id === r.id ? focusHit.index : null}
                    disabled={r._res.state !== "ok"}
                    onLocate={(i) => locate(r, i)}
                    onMenu={(i, e) => openHitMenu(r, i, e)}
                  />
                  {focus === r.id && r._res.state === "ok" ? (
                    <HitChips
                      hits={r._res.hits}
                      kind={resPage?.result.kind ?? "speech"}
                      start={r.start}
                      focusIndex={focusHit?.id === r.id ? focusHit.index : null}
                      playing={hitPlaying && hitPlaying.startsWith(`${r._res.rank}:`) ? Number(hitPlaying.split(":")[1]) : null}
                      pad={pad}
                      onPad={setPad}
                      onPlay={(i, v) => void playHit(r, i, v)}
                      onLocate={(i) => locate(r, i)}
                      onMenu={(i, e) => openHitMenu(r, i, e)}
                    />
                  ) : null}
                </>
              ) : null}
            </div>
            <button
              type="button"
              className={s.star}
              data-on={r.starred || undefined}
              onClick={() => void edit([r.id], { starred: !r.starred }, "sample-star")}
              aria-label={t("library.star")}
              aria-pressed={r.starred}
            >
              <Star size={14} />
            </button>
          </>
          )
        }
        footer={
          <BatchBar
            count={checked.size}
            total={total}
            onCheckAll={() => void checkAllMatching()}
            items={groupItems([...checked])}
            onClear={() => setChecked(new Set())}
            testId="library-checked"
          />
        }
      />
      </div>
    </section>
  );

  const stage = (
    <section className={s.stage} data-testid="stage">
      {focusRow ? (
        <>
          <div className={s.stageHead}>
            <h2 className={s.stageTitle} lang={focusRow.language ?? "ja"} data-testid="stage-title" data-user-data="">
              {focusRow.name}
            </h2>
            <Button
              variant="flat"
              size="sm"
              icon={<Star className={focusRow.starred ? s.starOn : undefined} />}
              onPress={() => void edit([focusRow.id], { starred: !focusRow.starred }, "sample-star")}
              aria-label={t("library.star")}
              aria-pressed={focusRow.starred}
            />
            <Menu
              head={t("handoff.head", { name: focusRow.name })}
              items={handoffItems(focusRow, stageOpts(focusRow.id))}
              placement="bottom end"
              trigger={
                <Button variant="secondary" size="sm" data-testid="stage-handoff">
                  {t("handoff.menu")}
                  <ChevronDown size={13} />
                </Button>
              }
            />
            <Menu {...sampleMenu(focusRow, [focusRow.id], false, "detail")} placement="bottom end" trigger={<Button variant="flat" size="sm" icon={<MoreHorizontal />} aria-label={t("menu.more")} />} />
          </div>
          <div className={s.stageTop} data-wide={picWide || undefined}>
          <StagePicture
            sampleId={focusRow.id}
            wide={picWide}
            onWide={setPicWide}
            onToggle={() => void audition(focusRow)}
            onBind={() => setVisualFor({ ownerType: "sample", id: focusRow.id, name: focusRow.name })}
          />
          <div className={s.stageTopInfo}>
          <div className={s.stageMeta}>
            <span className={s.natBadge} data-nature={focusRow.nature}>
              <NatureDot nature={focusRow.nature} />
              {t(`nature.${focusRow.nature}`)}
            </span>
            <span className="num">{t("format.sec", { v: seconds(focusRow.duration) })}</span>
            <span data-user-data="">
              {focusRow.source_name} · {clock(focusRow.source_start)}
            </span>
            <Button
              size="sm"
              variant="flat"
              icon={<ArrowUpRight />}
              onPress={() => backToSource(focusRow)}
              isDisabled={focusRow.source_start == null || focusRow.media_state === "released"}
              title={focusRow.media_state === "released" ? t("indep.noBack") : undefined}
              data-testid="back-to-source"
            >
              {t("library.backToSource")}
            </Button>
            {focusRow.independent ? <span className={s.badge} data-testid="stage-independent">{t("indep.badge")}</span> : null}
            {focusRow.media_state === "released" ? <span className={s.mutedText}>{t("indep.released")}</span> : null}
          </div>
          {/* 标签行（03 §3.6）：有效标签，只有本地的可删；「+」加本地标签；「提升为区段标签…」（R5.6） */}
          <div className={s.tagRowWrap} onPointerDownCapture={(e) => (tagAt.current = { clientX: e.clientX, clientY: e.clientY })}>
          <Chips
            label={t("library.tags")}
            testId="stage-tags"
            items={(focusRow.tags ?? []).map((tg) => tagChip(tg))}
            onAction={(tag) => {
              const tg = (focusRow.tags ?? []).find((x) => x.tag === tag);
              if (tg) openTagMenu(focusRow, tg);
            }}
            onRemove={(tag) => {
              const local = (focusRow.tags ?? []).filter((x) => x.provenance === "local" && x.tag !== tag).map((x) => x.tag);
              void edit([focusRow.id], { local_tags: local }, "sample-tags");
            }}
            trailing={
              <>
                <AnchoredPanel
                  title={t("library.addTag")}
                  isOpen={tagOpen}
                  onOpenChange={(o) => {
                    setTagOpen(o);
                    setTagDraft("");
                  }}
                  width={300}
                  testId="add-tag-panel"
                  trigger={<Button size="sm" variant="flat" icon={<Plus />} aria-label={t("library.addTag")} data-testid="add-tag" />}
                  footer={
                    <Button size="sm" variant="primary" isDisabled={!tagDraft.trim()} onPress={addLocalTag}>
                      {t("library.addTagOk")}
                    </Button>
                  }
                >
                  <TextField value={tagDraft} onChange={setTagDraft} onSubmit={addLocalTag} autoFocus label={t("library.addTag")} placeholder={t("ann.tagHint")} testId="add-tag-input" />
                </AnchoredPanel>
                {(focusRow.tags ?? []).some((x) => x.provenance === "local") ? (
                  <Button size="sm" variant="flat" onPress={() => setPromoteFor(focusRow)} data-testid="promote">
                    {t("promote.menu")}
                  </Button>
                ) : null}
              </>
            }
          />
          </div>
          </div>
          </div>
          {focusItem?._res && focusHit?.id === focusRow.id ? (
            <div className={s.stageActions}>
              <span className={s.hitNav} data-testid="hit-nav">
                <Button size="sm" variant="flat" icon={<ChevronLeft />} isDisabled={focusHit.index <= 0} onPress={() => locate(focusItem, focusHit.index - 1)} aria-label={t("search.hit.prev")} />
                <span className="num">{t("search.hit.nav", { i: focusHit.index + 1, n: focusItem._res.hits.length })}</span>
                <Button size="sm" variant="flat" icon={<ChevronRight />} isDisabled={focusHit.index >= focusItem._res.hits.length - 1} onPress={() => locate(focusItem, focusHit.index + 1)} aria-label={t("search.hit.next")} />
              </span>
            </div>
          ) : null}
          <StageSpeech
            sample={focusRow}
            playhead={() => (playing === focusRow.id && playingVer?.startsWith("original:") ? stagePlayhead() : null)}
            playing={playing === focusRow.id && !!playingVer?.startsWith("original:")}
            onPlayRange={(a, b, loop) => void playRange(focusRow, a, b, loop)}
            onStop={stopAudition}
            lastPlayed={stagePlayhead}
            onStretched={isSingle(focusRow.nature) ? undefined : () => void audition(focusRow, "stretched", stageOpts(focusRow.id))}
            stretchedPlaying={playing === focusRow.id && playingVer === "stretched:voice"}
            hit={stageHit ? { a: stageHit.start, b: stageHit.end, approx: !!stageHit.evidence && !stageHit.evidence.strict, key: `${results.active}:${focusHit?.index}` } : null}
            clipTick={clipTick}
          />
          {isSingle(focusRow.nature) ? null : (
            <StageRhythm
              sample={focusRow}
              playingKey={playing === focusRow.id ? playingVer : null}
              onAudition={(version, sound) => void audition(focusRow, version, { ...stageOpts(focusRow.id), sound })}
            />
          )}
          <StageInfo
            sample={focusRow}
            onEdit={(fields, label) => void edit([focusRow.id], fields, label)}
            onOpen={(id) => setOpenSample(id)}
            onOpenStep={(st, assetId) => {
              setSourceJump({ sourceId: focusRow.source_id, assetId: assetId ?? undefined, a: st.sourceStart, b: st.sourceEnd, highlight: focusRow.id });
              setPage("sources");
            }}
            extra={
              <div className={s.field}>
                <span className={s.fieldLabel}>{t("info.picture")}</span>
                <Button size="sm" variant="flat" onPress={() => setVisualFor({ ownerType: "sample", id: focusRow.id, name: focusRow.name })} data-testid="stage-visual">
                  {t("visual.menu")}
                </Button>
              </div>
            }
          />
        </>
      ) : (
        <EmptyState title={t("library.pickHint")} size="inline" />
      )}
    </section>
  );

  return (
    <div
      className={s.page}
      data-testid="page-library"
      data-drop={drop || undefined}
      onDragOver={(e) => {
        // 拖文件/文件夹进采样库 = 导入（06 §6.6）；页面内的拖拽不接
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDrop(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDrop(false);
      }}
      onDrop={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        setDrop(false);
        const paths = [...e.dataTransfer.files].map((f) => window.otto.files.pathOf(f)).filter(Boolean);
        if (paths.length) setImportPaths(paths);
      }}
    >
      <TopSlot page="library">
        <Segmented<Purpose>
          variant="lens"
          value={purpose}
          onChange={setPurpose}
          label={t("library.purpose")}
          options={PURPOSES.map((p) => ({
            id: p,
            label: p === "all" ? t("library.all") : t(`nature.${p}`),
            mark: p !== "all" ? <NatureDot nature={p} /> : undefined,
            data: { "data-testid": `purpose-${p}` },
          }))}
        />
      </TopSlot>
      <VisualDialog target={visualFor} onClose={() => setVisualFor(null)} />
      <IndependDialog ids={independFor} onClose={() => setIndependFor(null)} />
      <VideoDialog
        req={videoFor}
        onClose={() => setVideoFor(null)}
        onBind={(r) => {
          setVideoFor(null);
          setVisualFor({ ownerType: "sample", id: r.id, name: r.name });
        }}
      />
      <BatchDialog
        kind={batch?.kind ?? null}
        ids={batch?.ids ?? []}
        onClose={() => setBatch(null)}
        onDone={() => {
          void load(offset);
          if (focus) void call("samples.get", { id: focus }).then(setFocusRow, () => {});
        }}
        onGoSource={(ref) => {
          setBatch(null);
          if (ref.sourceId && ref.start != null && ref.end != null) {
            setSourceJump({ sourceId: ref.sourceId, a: ref.start, b: ref.end });
            setPage("sources");
          } else if (ref.sourceId) {
            setSourceJump({ sourceId: ref.sourceId, a: 0, b: 0 });
            setPage("sources");
          }
        }}
      />
      <SaveFilterDialog
        isOpen={filterDialog === "save"}
        scope={find.tags}
        filters={filters}
        onClose={() => setFilterDialog(null)}
        onSaved={(id) => {
          loadFilters();
          setFind((f) => ({ ...f, preset: id }));
        }}
      />
      <ManageFiltersDialog isOpen={filterDialog === "manage"} filters={filters} onClose={() => setFilterDialog(null)} onChanged={loadFilters} />
      <ScopeExprDialog
        isOpen={filterDialog === "expr"}
        value={find.tags.expr}
        onClose={() => setFilterDialog(null)}
        onApply={(expr) => setFind((f) => ({ ...f, tags: { ...f.tags, expr } }))}
      />
      <PromoteDialog sample={promoteFor} onClose={() => setPromoteFor(null)} onDone={refreshAfterPromote} />
      <ImportDialog
        paths={importPaths}
        defaultWhole
        defaultNature={purpose === "all" ? "unclassified" : purpose}
        onClose={() => setImportPaths(null)}
        onImported={(r) => r.sampleIds[0] && setOpenSample(r.sampleIds[0])}
      />
      {composer ? (
        <Composer
          mode={composer}
          setMode={setComposer}
          speech={speechDraft}
          setSpeech={setSpeechDraft}
          pitch={pitchDraft}
          setPitch={setPitchDraft}
          metrics={metricsDraft}
          setMetrics={setMetricsDraft}
          scope={scope}
          bpm={bpm}
          running={!!results.running}
          onFind={() => void runSearch()}
          onCancel={results.cancel}
          onClose={() => setComposer(null)}
        />
      ) : null}
      {hitMenu.node}
      {tagMenu.node}
      <SplitPane left={list} right={stage} ratio={split} onRatio={setSplit} label={t("library.splitter")} />
      <ConfirmDialog
        isOpen={!!deleteIds}
        title={t("library.deleteTitle", { n: deleteIds?.length ?? 0 })}
        confirmLabel={t("library.delete")}
        danger
        onConfirm={() => void removeConfirmed()}
        onClose={() => setDeleteIds(null)}
        testId="sample-delete"
      >
        <div>{t("library.deleteWill")}</div>
        <div className={s.keep}>{t("library.deleteKeeps")}</div>
      </ConfirmDialog>
    </div>
  );
}

/** 第二行的副信息（UI_PLAN §2.2）：语音 / 未分类 = 节奏字形 + 音块数；调谐 = 音名 + 音高曲线；非调谐 = 起音时间 + 包络；
 *  还没有这些测量时显示建立方式与分析状态（例如“手动截取 · 未分析”）。 */
function RowExtra(props: { r: SampleRow; g: SampleGlyph | undefined }) {
  const { r, g } = props;
  const status = (
    <span data-testid="row-analysis" data-analysis={r.analysis}>
      {t(`library.via.${r.created_via}`)} · {t(`library.analysis.${r.analysis}`)}
    </span>
  );
  if (!g) return status;
  if (g.blocks)
    return (
      <span className={s.extra} data-analysis={r.analysis} data-testid="row-analysis">
        <span className={s.extraGlyph} data-nature={r.nature}>
          <RhythmGlyph blocks={g.blocks} label={t("library.blocks", { n: g.blocks.length })} />
        </span>
        <span>{t("library.blocks", { n: g.blocks.length })}</span>
        {r.analysis === "partial" || r.analysis === "manual" ? <span>· {t(`library.analysis.${r.analysis}`)}</span> : null}
      </span>
    );
  if (r.nature === "pitched")
    return (
      <span className={s.extra}>
        {g.note ? (
          <b className={s.note2} data-nature="pitched">
            {g.note}
          </b>
        ) : null}
        {g.curve ? (
          <span className={s.extraGlyph} data-nature="pitched">
            <Sparkline values={g.curve} minSpan={6} label={t("library.pitchCurve")} />
          </span>
        ) : null}
      </span>
    );
  return (
    <span className={s.extra}>
      {g.attackMs != null ? <span className="num">{t("library.attack", { ms: g.attackMs })}</span> : null}
      {g.envelope ? (
        <span className={s.extraGlyph} data-nature="unpitched">
          <Sparkline values={g.envelope} log label={t("library.envelope")} />
        </span>
      ) : null}
    </span>
  );
}

function SampleThumb(props: { id: string; play: { playing: boolean; onPress: () => void; onSecondary?: () => void; label: string; testId?: string } }) {
  return <Thumb url={useThumb("sample", props.id)} play={props.play} testId="sample-thumb" />;
}
