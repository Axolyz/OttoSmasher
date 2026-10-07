// 原片查看器（UI_PLAN §4）：画面（原生播放画到画布，底部控制条）、台本（阶段 3）、时间线卡片（音源、适合/放大选区、波形、动作条）。
// 页面头（收起列表、当前原片、⋯）在顶栏里，由 SourcesPage 放。
// 快捷键（UI_PLAN §7，焦点在查看器时）：Space 播放/暂停 · Shift+Space 播放选区（引擎截停）· L 循环选区 ·
// I/O 播放位置设为选区开始/结束 · F 适合窗口 · Z 放大选区 · ←/→ 逐帧 · Shift+←/→ 1 ms · ⌥←/→ ±5 秒 · Esc 清除选区。
import { AudioLines, ChevronDown, Download, Info, Pause, Play, Repeat, SquarePlay, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlayerState } from "../../shared/protocol";
import { CoreFailure, call } from "../api/core";
import type { AssetInfo, SourceDetail, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { Select, TimeField } from "../components/Fields";
import { Menu } from "../components/Menu";
import { Tip } from "../components/Overlay";
import { basename, clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { ClipPanel } from "./ClipPanel";
import { displayName } from "./SourceList";
import s from "./Sources.module.css";
import { type Sel, Timeline, type TimelineHandle } from "./Timeline";

function isTyping(el: Element | null): boolean {
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || (el as HTMLElement).isContentEditable);
}

export function SourceViewer(props: { row: SourceRow }) {
  const { row } = props;
  const toast = useApp((st) => st.toast);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [assets, setAssets] = useState<AssetInfo[]>([]);
  const [ordinal, setOrdinal] = useState<number>(row.default_audio_stream);
  const [hasVideo, setHasVideo] = useState(row.has_video);
  const [sel, setSel] = useState<Sel | null>(null);
  const [state, setState] = useState<PlayerState | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [clipOpen, setClipOpen] = useState(false);
  const [muted, setMuted] = useState(false);
  const stamp = useRef({ time: null as number | null, at: 0, playing: false, gen: -1 });
  const tl = useRef<TimelineHandle>(null);
  const root = useRef<HTMLDivElement>(null);

  // 换原片：选区清空，音源回到该原片的分析音轨（查看器不重建，画布保持不变）
  useEffect(() => {
    setSel(null);
    setOrdinal(row.default_audio_stream);
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
    setSel({ a: jump.a, b: jump.b });
    if (jump.ordinal != null) setOrdinal(jump.ordinal);
    pendingZoom.current = { a: jump.a, b: jump.b };
    setZoomNonce((n) => n + 1); // 音轨已经加载时也要放大（资产没变，下面的效果不会因资产重跑）
    setJump(null);
  }, [jump, row.id, setJump]);

  // 资料
  useEffect(() => {
    let live = true;
    void Promise.all([call<SourceDetail>("sources.get", { id: row.id }), call<AssetInfo[]>("assets.listForSource", { sourceId: row.id })]).then(
      ([d, a]) => {
        if (!live) return;
        setDetail(d);
        setAssets(a);
      },
    );
    return () => {
      live = false;
    };
  }, [row.id, row.version]);

  // 播放器：打开原片（换音源时只换音轨，选区保留）
  useEffect(() => {
    let live = true;
    setOpenError(null);
    window.otto.player
      .openSource(row.id, ordinal)
      .then((r) => live && setHasVideo(r.hasVideo))
      .catch((e: { code: string; args: Record<string, unknown> }) => live && setOpenError(errorText(e)));
    return () => {
      live = false;
    };
  }, [row.id, row.version, ordinal]);

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

  const asset = useMemo(() => assets.find((a) => a.origin === "stream" && a.stream_ordinal === ordinal) ?? null, [assets, ordinal]);
  const duration = asset?.duration ?? row.duration;
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

  const playPause = () => (playing ? window.otto.player.pause() : window.otto.player.play());
  const playSel = (loop = false) => sel && window.otto.player.playRange(sel.a, sel.b, loop);
  const seekBy = (d: number) => {
    const p = playhead();
    if (p != null) window.otto.player.seek(Math.max(0, Math.min(duration, p + d)));
  };

  const exportSelection = async (r: Sel) => {
    if (!asset) throw new Error("no asset");
    const content = t("sources.exportContent", { name: displayName(row), a: clock(r.a), b: clock(r.b) });
    const out = await call<{ path: string; reused: boolean }>("exports.wav", { assetId: asset.id, start: r.a, end: r.b, content, track: t("track.original") });
    return [out.path];
  };

  const exportWav = async () => {
    if (!sel || !asset) return;
    setExporting(true);
    try {
      const content = t("sources.exportContent", { name: displayName(row), a: clock(sel.a), b: clock(sel.b) });
      const r = await call<{ path: string; reused: boolean }>("exports.wav", {
        assetId: asset.id,
        start: sel.a,
        end: sel.b,
        content,
        track: t("track.original"),
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

  const trackName = trackLabel(ordinal);
  const commitSel = (which: "a" | "b") => (v: number) => {
    const a = which === "a" ? v : (sel?.a ?? 0);
    const b = which === "b" ? v : (sel?.b ?? duration);
    if (!(a >= 0 && b <= duration + 1e-9 && b > a)) return false;
    setSel({ a, b });
    return true;
  };

  return (
    <section className={s.viewer} ref={root} tabIndex={0} onKeyDown={onKey} data-testid="source-viewer" aria-label={displayName(row)}>
      <div className={s.stageRow}>
        <div className={s.video} data-audio-only={!hasVideo || undefined} onClick={() => root.current?.focus()} onDoubleClick={playPause}>
          {/* 原片播放器的画布：整个窗口只有一个（preload 用 data-otto-video 找到它） */}
          <canvas data-otto-video="" style={{ display: hasVideo ? "block" : "none" }} />
          {!hasVideo ? (
            <div className={s.audioOnly}>
              <AudioLines size={28} strokeWidth={1.3} />
              {t("sources.audioOnly")}
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
        <div className={s.transcript} data-testid="transcript">
          <div className={s.transcriptHead}>{t("sources.transcript")}</div>
          <div>{row.subtitle_path ? t("sources.transcriptPending", { name: basename(row.subtitle_path) }) : t("sources.noSubtitleHint")}</div>
        </div>
      </div>

      <div className={s.tlCard}>
        <div className={s.tlBar}>
          <Select
            value={String(ordinal)}
            onChange={(v) => setOrdinal(Number(v))}
            label={t("sources.audioSource")}
            prefix={t("sources.audioSource")}
            options={audioStreams.map((x) => ({ id: String(x.ordinal), label: trackLabel(x.ordinal) }))}
          />
          {openError ? <span className={s.warn}>{openError}</span> : null}
          <span className={s.grow} />
          <Button size="sm" variant="flat" onPress={() => tl.current?.fit()} title={t("sources.fitTip")}>
            {t("sources.fit")}
          </Button>
          <Button size="sm" variant="flat" onPress={() => sel && tl.current?.zoomTo(sel.a, sel.b)} isDisabled={!sel} title={t("sources.zoomSelTip")}>
            {t("sources.zoomSel")}
          </Button>
          <Tip content={t("sources.timelineHelp")}>
            <Button variant="flat" size="sm" icon={<Info />} aria-label={t("sources.timelineHelpLabel")} />
          </Tip>
        </div>
        <Timeline
          ref={tl}
          assetId={asset?.id ?? null}
          duration={duration}
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
            <ClipPanel assetId={asset?.id ?? null} track={trackName} sel={sel} isOpen={clipOpen} onOpenChange={setClipOpen} />
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
    </section>
  );
}
