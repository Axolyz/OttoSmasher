// 采样库（UI_PLAN §2；阶段 2 最小版 + 阶段 3.0 组件对齐）：顶栏用途切换、查找栏（文字 + ★）、结果头（浏览、分页）与状态行、
// 统一列表（CollectionList：UI_PLAN §6.1 的全部集合规则）、批量条、可拖动的分栏、右侧舞台。
// 本页自己的键（集合区）：Space 试听焦点的原声 · B 试听默认卡拍（近快；单音没有）· 1/2/3/0 设性质（勾选集或焦点，可撤销；改完留在原位，刷新后归位）·
// S 星标 · ⌘F 聚焦查找栏的文字。条件变化清空勾选并提示；翻页保留勾选。
import { ArrowUpRight, ChevronDown, ChevronLeft, ChevronRight, MoreHorizontal, Play, Plus, Square, SquareStack, Star } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlayerState } from "../../shared/protocol";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import { useThumb } from "../api/thumbs";
import type { EffectiveTag, Nature, RhythmPlan, RhythmSound, SamplePage, SampleRow } from "../api/types";
import { BatchBar } from "../components/BatchBar";
import { Button } from "../components/Button";
import { CollectionList } from "../components/CollectionList";
import { type ChipItem, Chips, EmptyState, Segmented } from "../components/Controls";
import { TextField } from "../components/Fields";
import { Menu, type MenuItems, type MenuSpec } from "../components/Menu";
import { NATURES, NATURE_KEYS, NatureDot, NaturePicker } from "../components/NaturePicker";
import { AnchoredPanel } from "../components/Panel";
import { ConfirmDialog } from "../components/Overlay";
import { SplitPane } from "../components/SplitPane";
import { Thumb } from "../components/Thumb";
import { beginDragOut } from "../dragout";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { ImportDialog } from "../shell/ImportDialog";
import { TopSlot } from "../shell/TopSlot";
import { useUndo } from "../shell/useUndo";
import { exportWords } from "../exportWords";
import { type AuditionVersion, useApp } from "../state/store";
import { PromoteDialog } from "./PromoteDialog";
import s from "./Library.module.css";
import { StageRhythm } from "./StageRhythm";
import { StageSpeech } from "./StageSpeech";

const PAGE = 100;

/** 导出文件名“音轨”段的固定词（随界面语言，规格 12 §12.1） */
const trackWords = exportWords;
type Purpose = "all" | Nature;
const PURPOSES: Purpose[] = ["all", "speech", "pitched", "unpitched", "unclassified"];
const KEY_OF: Record<Nature, string> = { speech: "1", pitched: "2", unpitched: "3", unclassified: "0" };
/** 单音（调谐/非调谐）没有卡拍、没有 REAPER 交接（所有者 2026-10-06） */
const isSingle = (n: Nature) => n === "pitched" || n === "unpitched";

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
  };
}

export function LibraryPage() {
  const ready = useApp((st) => st.core.state === "ready");
  const page = useApp((st) => st.page);
  const toast = useApp((st) => st.toast);
  const requestSpeech = useApp((st) => st.requestSpeech);
  const requestFlatten = useApp((st) => st.requestFlatten);
  const openSample = useApp((st) => st.openSample);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  const setSourceJump = useApp((st) => st.setSourceJump);
  const undo = useUndo();
  const [purpose, setPurpose] = useState<Purpose>("all");
  const [importPaths, setImportPaths] = useState<string[] | null>(null);
  const [promoteFor, setPromoteFor] = useState<SampleRow | null>(null);
  const [tagOpen, setTagOpen] = useState(false);
  const [tagDraft, setTagDraft] = useState("");
  const [drop, setDrop] = useState(false);
  const pickImport = async () => {
    const paths = await window.otto.files.pick("import");
    if (paths.length) setImportPaths(paths);
  };
  const [text, setText] = useState("");
  const [starredOnly, setStarredOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<SamplePage | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<string | null>(null);
  /** 正在试听的版本与声音（"original:voice"、"stretched:voice+click" …） */
  const setNowPlaying = useApp((st) => st.setNowPlaying);
  const rememberVersion = useApp((st) => st.rememberVersion);
  const lastVersion = useApp((st) => st.lastVersion);
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

  const query = useMemo(() => ({ natures: purpose === "all" ? undefined : [purpose], starred: starredOnly, text }), [purpose, starredOnly, text]);

  const load = useCallback(
    async (off: number) => {
      const r = await call("samples.list", { ...query, offset: off, limit: PAGE });
      setData(r);
      return r;
    },
    [query],
  );

  // 分栏比例：重启恢复（UI_PLAN §2）
  useEffect(() => {
    if (!ready) return;
    void call("ui.get", { page: "library" }).then((v) => {
      if (typeof v.split === "number") setSplit(v.split);
      splitRestored.current = true;
    });
  }, [ready]);
  useEffect(() => {
    if (!splitRestored.current) return;
    const id = setTimeout(() => void call("ui.set", { page: "library", key: "split", value: split }), 300);
    return () => clearTimeout(id);
  }, [split]);

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
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "f") {
        e.preventDefault();
        document.querySelector<HTMLInputElement>('[data-testid="library-search"]')?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [page]);

  // 截取后打开新采样
  useEffect(() => {
    if (!openSample || !ready) return;
    void (async () => {
      const r = await call("samples.list", { offset: 0, limit: PAGE });
      setPurpose("all");
      setText("");
      setStarredOnly(false);
      setOffset(0);
      setData(r);
      setFocus(openSample);
      setOpenSample(null);
    })();
  }, [openSample, ready, setOpenSample]);

  // 焦点采样的资料（舞台）
  useEffect(() => {
    if (!focus) return setFocusRow(null);
    const inPage = data?.rows.find((r) => r.id === focus);
    if (inPage) setFocusRow((f) => (f?.id === inPage.id ? { ...f, ...inPage } : inPage));
    // 舞台要有效标签：总是再取一次完整资料
    void call("samples.get", { id: focus }).then(setFocusRow, () => setFocusRow(null));
  }, [focus, data]);

  // 试听状态；舞台波形的播放头 = 试听区间起点 + 区间本地秒（资产局部秒）
  const auditionFrom = useRef(0);
  const auditionAt = useRef<number | null>(null);
  useEffect(
    () =>
      window.otto.player.onState((st: PlayerState) => {
        if (st.player !== "audition" || st.gen !== auditionGen.current) return;
        auditionAt.current = st.time == null ? null : auditionFrom.current + st.time;
        if (st.ended || st.error) {
          setPlaying(null);
          auditionAt.current = null;
        }
      }),
    [],
  );
  /** 在舞台波形上播放资产的一段（双击处、选区） */
  const playRange = async (r: SampleRow, a: number, b: number) => {
    try {
      setPlaying(r.id);
      setPlayingVer("original:voice");
      auditionFrom.current = a;
      auditionGen.current = await window.otto.player.audition(r.asset_id, a, b);
      setNowPlaying({ sampleId: r.id, name: r.name, version: "original", sound: "voice", plan: null, bpm: null, originalSpeed: false, duration: b - a });
    } catch (e) {
      setPlaying(null);
      setNowPlaying(null);
      toast({ text: errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });
    }
  };

  const rows = data?.rows ?? [];
  /** 试听一个采样（PB1：原声、卡拍都一步）：原声直接读绑定区间（R22.3）；卡拍与咔哒声先由 Core 渲染（方案按需计算）。
   *  成功开始播放才记为“最近试听的版本”（拖出跟随它，12 §12.1）。再按一次同一个 = 停止。 */
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
      if (version === "original" && sound === "voice") {
        auditionFrom.current = r.start;
        auditionGen.current = await window.otto.player.audition(r.asset_id, r.start, r.end);
        setNowPlaying({ sampleId: r.id, name: r.name, version, sound, plan: null, bpm: null, originalSpeed: false, duration: r.end - r.start });
      } else {
        const rr = await call("rhythm.render", { id: r.id, version, sound, plan: opts.plan ?? "near_fast", mora: opts.mora ?? false, longVowel: opts.longVowel ?? false });
        auditionFrom.current = version === "original" ? r.start : Number.NaN; // 卡拍后的时间不在资产时间轴上：舞台波形不画播放头
        auditionGen.current = await window.otto.player.auditionRender(rr.key);
        setNowPlaying({ sampleId: r.id, name: r.name, version, sound, plan: rr.plan, bpm: rr.bpm, originalSpeed: rr.originalSpeed, duration: rr.duration });
      }
      rememberVersion(r.id, version);
    } catch (e) {
      setPlaying(null);
      setNowPlaying(null);
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });
    }
  };

  // 导出与交接（12 §12.1、§12.3）：舞台上的卡拍导出/交接用舞台的临时方案与纯 mora；列表、批量用默认（近快、原节奏）
  const reveal = (path: string, reused = false) =>
    toast({
      text: t(reused ? "sources.exportReused" : "sources.exported", { name: path.split(/[\\/]/).pop() ?? path }),
      action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(path) },
    });
  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const exportOriginal = async (ids: string[]) => {
    try {
      const paths = await call("exports.samples", { ids, words: trackWords() });
      if (paths.length === 1) reveal(paths[0]!);
      else if (paths.length) toast({ text: t("library.exportedN", { n: paths.length }), action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(paths[0]!) } });
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
    if (ids.length > 1 && done.length) toast({ text: t("library.exportedN", { n: done.length }), action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(done[0]!) } });
  };
  /** ``baked``：卡好拍的声音 + 起音拉伸标记；否则未烘焙原声 + 卡拍拉伸标记（12 §12.3） */
  const copyReaper = async (ids: string[], opts: AuditionOpts = {}, baked = false) => {
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
      ? [{ id: "wav", label: t("handoff.wav"), run: () => void exportOriginal([r.id]) }]
      : [
          { id: "wav", label: t("handoff.wav"), run: () => void exportOriginal([r.id]) },
          { id: "stretched", label: t("handoff.stretchedWav"), run: () => void exportStretched([r.id], opts) },
          "-",
          { id: "reaperBaked", label: t("handoff.reaperBaked"), run: () => void copyReaper([r.id], opts, true) },
          { id: "reaper", label: t("handoff.reaper"), run: () => void copyReaper([r.id], opts) },
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
      setFocusRow((f) => (f && ids.includes(f.id) ? { ...f, ...fields, version: f.version + 1 } : f));
      if (focus && ids.includes(focus)) void call("samples.get", { id: focus }).then(setFocusRow, () => {});
      toast({ text: t("library.edited", { n: all.length }), action: { label: t("common.undo"), run: () => void undo().then(() => load(offset)) } });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
      void load(offset);
    }
  };

  // 舞台跟着资料变化（撤销、提升、原片属性）重读焦点采样；列表不自动重排（P8：底部提示“刷新浏览列表”）
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (focus && (c.sample?.includes(focus) || c.annotation || c.source || c.asset)) {
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
  const refreshAfterPromote = () => {
    void load(offset);
    if (focus) void call("samples.get", { id: focus }).then(setFocusRow, () => {});
  };

  const checkAllMatching = async () => setChecked(new Set(await call("samples.ids", query)));

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const pageNo = Math.floor(offset / PAGE) + 1;
  const goto = (p: number) => {
    const off = (Math.max(1, Math.min(pages, p)) - 1) * PAGE;
    setOffset(off);
    void load(off);
  };

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

  const backToSource = (r: SampleRow) => {
    if (r.source_start == null) return;
    const len = r.end - r.start;
    setSourceJump({ sourceId: r.source_id, ordinal: r.stream_ordinal, assetId: r.asset_id, a: r.source_start, b: r.source_start + len });
    setPage("sources");
  };

  // 菜单（UI_PLAN §6.1、§8）：右键、舞台 ⋯、批量操作 ▾ 共用同一组动作
  const natureItems = (ids: string[]): MenuItems =>
    NATURES.map((n) => ({ id: `nature-${n}`, label: t(`nature.${n}`), shortcut: KEY_OF[n], run: () => void edit(ids, { nature: n }, "sample-nature") }));
  const groupItems = (ids: string[]): MenuItems => [
    { id: "nature", label: t("library.setNature"), items: natureItems(ids) },
    { id: "star", label: t("library.starOn"), shortcut: "S", run: () => void edit(ids, { starred: true }, "sample-star") },
    { id: "unstar", label: t("library.starOff"), run: () => void edit(ids, { starred: false }, "sample-star") },
    "-",
    { id: "speech", label: t("speech.menuN", { n: ids.length }), run: () => requestSpeech({ entry: "samples", ids }) },
    { id: "flatten", label: t("flatten.menuN", { n: ids.length }), run: () => requestFlatten({ kind: "batch", ids }) },
    "-",
    {
      id: "export",
      label: t("handoff.export"),
      items: [
        { id: "wav", label: t("handoff.wavN", { n: ids.length }), run: () => void exportOriginal(ids) },
        { id: "stretched", label: t("handoff.stretchedWavN", { n: ids.length }), run: () => void exportStretched(ids) },
      ],
    },
    {
      id: "reaper",
      label: t("handoff.reaperMenu"),
      items: [
        { id: "reaperBaked", label: t("handoff.reaperBakedN", { n: ids.length }), run: () => void copyReaper(ids, {}, true) },
        { id: "reaper", label: t("handoff.reaperN", { n: ids.length }), run: () => void copyReaper(ids) },
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
            { id: "nature", label: t("library.setNature"), items: natureItems([r.id]) },
            { id: "star", label: r.starred ? t("library.starOff") : t("library.starOn"), shortcut: "S", run: () => void edit([r.id], { starred: !r.starred }, "sample-star") },
            "-",
            { id: "back", label: t("library.backToSource"), disabled: r.source_start == null, run: () => backToSource(r) },
            { id: "speech", label: t("speech.menu"), run: () => requestSpeech({ entry: "samples", ids: [r.id] }) },
            { id: "flatten", label: t("flatten.menu"), run: () => requestFlatten({ kind: "single", assetId: r.asset_id, start: r.start, end: r.end, entry, sampleId: r.id }) },
            "-",
            ...handoffItems(r, entry === "detail" ? stageOpts(r.id) : {}),
            "-",
            { id: "delete", label: t("library.deleteDots"), danger: true, shortcut: "⌫", run: () => setDeleteIds([r.id]) },
          ],
        };

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
      <div className={s.find}>
        <TextField value={text} onChange={setText} label={t("library.search")} placeholder={t("library.searchPlaceholder")} testId="library-search" />
        <Button
          variant={starredOnly ? "primary" : "flat"}
          icon={<Star />}
          onPress={() => setStarredOnly((v) => !v)}
          aria-label={t("library.starredOnly")}
          title={t("library.starredOnly")}
          aria-pressed={starredOnly}
        />
      </div>
      <div className={s.resultHead}>
        <span className={s.resultTab}>
          {t("library.browse")} <span className="num">{total}</span>
        </span>
        <span className={s.grow} />
        <Button size="sm" variant="flat" icon={<Plus />} onPress={() => void pickImport()} data-testid="library-import">
          {t("import.button")}
        </Button>
        <Button size="sm" variant="flat" icon={<ChevronLeft />} isDisabled={pageNo <= 1} onPress={() => goto(pageNo - 1)} aria-label={t("pager.prev")} />
        <span className="num">
          {pageNo} / {pages}
        </span>
        <Button size="sm" variant="flat" icon={<ChevronRight />} isDisabled={pageNo >= pages} onPress={() => goto(pageNo + 1)} aria-label={t("pager.next")} />
      </div>
      <div className={s.status}>
        <span data-testid="library-total">{t("library.total", { n: total })}</span>
        <span>· {t("library.sortNewest")}</span>
      </div>
      <CollectionList<SampleRow>
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
          if (r) void audition(r);
        }}
        onDelete={setDeleteIds}
        onKey={onKey}
        menu={(r, target) => sampleMenu(r, target.ids, target.multi)}
        checkLabel={(r) => t("library.check", { name: r.name })}
        testId="sample-list"
        rowTestId="sample-row"
        rowData={(r) => ({ "data-nature": r.nature })}
        onRowPointerDown={(e, r) => {
          // ⌥ 拖出：在勾选集里且 ≥2 → 整个勾选集；按钮、复选框上按下不接管（规格 12 §12.2）
          if ((e.target as Element).closest("button, input, label")) return;
          const ids = checked.has(r.id) && checked.size >= 2 ? [...checked] : [r.id];
          const versions = Object.fromEntries(ids.map((id) => [id, lastVersion[id] ?? "original"]));
          beginDragOut(e, () => call("exports.samples", { ids, words: trackWords(), versions }));
        }}
        empty={
          data ? (
            <EmptyState
              icon={<SquareStack />}
              title={t(total || text || starredOnly || purpose !== "all" ? "library.noMatch" : "library.empty.title")}
              body={total || text || starredOnly || purpose !== "all" ? undefined : t("library.empty.body")}
            />
          ) : null
        }
        renderItem={(r) => (
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
                <span data-testid="row-analysis" data-analysis={r.analysis}>
                  {t(`library.via.${r.created_via}`)} · {t(`library.analysis.${r.analysis}`)}
                </span>
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
        )}
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
          <div className={s.stageMeta}>
            <span className={s.natBadge} data-nature={focusRow.nature}>
              <NatureDot nature={focusRow.nature} />
              {t(`nature.${focusRow.nature}`)}
            </span>
            <span className="num">{t("format.sec", { v: seconds(focusRow.duration) })}</span>
            <span data-user-data="">
              {focusRow.source_name} · {clock(focusRow.source_start)}
            </span>
            <Button size="sm" variant="flat" icon={<ArrowUpRight />} onPress={() => backToSource(focusRow)} isDisabled={focusRow.source_start == null} data-testid="back-to-source">
              {t("library.backToSource")}
            </Button>
          </div>
          {/* 标签行（03 §3.6）：有效标签，只有本地的可删；「+」加本地标签；「提升为区段标签…」（R5.6） */}
          <Chips
            label={t("library.tags")}
            testId="stage-tags"
            items={(focusRow.tags ?? []).map((tg) => tagChip(tg))}
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
          <div className={s.stageActions}>
            <Button variant="secondary" icon={playing === focusRow.id ? <Square /> : <Play />} onPress={() => void audition(focusRow)} data-testid="stage-play">
              {playing === focusRow.id ? t("library.stop") : t("library.auditionOriginal")}
            </Button>
          </div>
          <StageSpeech
            sample={focusRow}
            playhead={() => (playing === focusRow.id && playingVer?.startsWith("original:") ? auditionAt.current : null)}
            playing={playing === focusRow.id && !!playingVer?.startsWith("original:")}
            onPlayRange={(a, b) => void playRange(focusRow, a, b)}
            onStretched={isSingle(focusRow.nature) ? undefined : () => void audition(focusRow, "stretched", stageOpts(focusRow.id))}
            stretchedPlaying={playing === focusRow.id && playingVer === "stretched:voice"}
          />
          {isSingle(focusRow.nature) ? null : (
            <StageRhythm
              sample={focusRow}
              playingKey={playing === focusRow.id ? playingVer : null}
              onAudition={(version, sound) => void audition(focusRow, version, { ...stageOpts(focusRow.id), sound })}
            />
          )}
          <section className={s.card}>
            <h3 className={s.cardTitle}>{t("library.info")}</h3>
            <div className={s.field}>
              <span className={s.fieldLabel}>{t("nature.label")}</span>
              <NaturePicker value={focusRow.nature} onChange={(n) => void edit([focusRow.id], { nature: n }, "sample-nature")} testId="stage-nature" />
            </div>
            {focusRow.parent_label && !focusRow.parent_sample_id ? (
              <div className={s.field}>
                <span className={s.fieldLabel}>{t("library.origin")}</span>
                <span className={s.note}>{t("library.parentDeleted", { name: focusRow.parent_label })}</span>
              </div>
            ) : null}
          </section>
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
      <PromoteDialog sample={promoteFor} onClose={() => setPromoteFor(null)} onDone={refreshAfterPromote} />
      <ImportDialog
        paths={importPaths}
        defaultWhole
        defaultNature={purpose === "all" ? "unclassified" : purpose}
        onClose={() => setImportPaths(null)}
        onImported={(r) => r.sampleIds[0] && setOpenSample(r.sampleIds[0])}
      />
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

function SampleThumb(props: { id: string; play: { playing: boolean; onPress: () => void; onSecondary?: () => void; label: string; testId?: string } }) {
  return <Thumb url={useThumb("sample", props.id)} play={props.play} testId="sample-thumb" />;
}
