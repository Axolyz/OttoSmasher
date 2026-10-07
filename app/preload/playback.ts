// 正式播放器（ARCHITECTURE §10.1；规格 05 §5.3.1、16 R22.1–R22.5、R22.7）。
//
// - 两个引擎：原片播放器（画面 + 声音，画布）与试听播放器（只有声音）；全应用同时只有一个声音。
// - 页面只给原片/资产 ID 和时间，路径由 Core 解析（核对过快照）；这里不接受页面给的路径。
// - 范围截停交给引擎：暂停 → 设 end → 精确跳转 → 继续（实测 libmpv 0.36 按这个顺序逐次精确截停）；
//   任何普通跳转、播放/暂停先清除范围（end=none）。循环用 ab-loop。
// - 代次：每个请求加一；文件加载完成前的跳转/播放挂起，加载完成后按“最新请求”执行（幂等，旧加载的事件不会放错区间）；
//   结束只通知一次；旧代次的状态不再发出。
// - 时钟：原片播放器报原片秒，试听播放器报区间本地秒；约每 50 ms 推一次，两次之间由界面插值。
// - 跳转发出后到引擎报 playback-restart 之前，丢弃 time-pos / eof-reached（否则跳转前的旧位置会漏出来，
//   例如往回播一个范围时旧位置已越过新终点 → 误判结束）；结束以引擎的 eof-reached 为准，显示时间贴到范围终点。
//   这两条借鉴旧版 mpv 桥（所有者 2026-10-07 允许只看旧版 mpv 部分代码）。
import { ipcRenderer } from "electron";
import type { CoreErrorWire, CoreResult, PlayerName, PlayerState } from "../shared/protocol";
import { AudioPlayer, CanvasPlayer, type MpvEvent, type MpvLike } from "./player";

const PUSH_MS = 50;
// 自动化测试用 OTTO_MPV_AO=null 静音输出（仍按实时推进），不在所有者的电脑上出声
const AO: Record<string, string> = process.env.OTTO_MPV_AO ? { ao: process.env.OTTO_MPV_AO } : {};
const MPV_OPTIONS = { hwdec: "videotoolbox-copy", "sws-fast": "yes", "zimg-fast": "yes", ...AO };

async function core<T>(method: string, params: Record<string, unknown>): Promise<T> {
  const r = (await ipcRenderer.invoke("core:request", method, params)) as CoreResult<T>;
  if (!r.ok) throw r.e;
  return r.r;
}

interface Range {
  a: number; // 文件秒
  b: number;
  loop: boolean;
  gen: number; // 发出这个范围的代次：只有它能被标为“结束”
}

class Engine {
  gen = 0; // 用户请求的代次（范围播放、试听）
  loadSeq = 0; // 加载请求的序号（与代次分开：加载还没回来时用户又点了范围播放，不能把加载取消掉）
  private path: string | null = null;
  private aid = 1;
  private loaded = false;
  private queue: Array<() => void> = [];
  private offset = 0; // 时钟：报出的时间 = 文件秒 − offset
  private range: Range | null = null;
  private endedGen = -1;
  private time: number | null = null;
  private timeAt = 0;
  private shown: number | null = null; // 上一次给出的播放头位置
  private eof = false;
  private awaitingSeek = false;
  private playing = false;
  private loading = false;
  private error: CoreErrorWire | undefined;
  private lastPush = 0;
  private pushTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    readonly name: PlayerName,
    readonly mpv: MpvLike,
    private emit: (s: PlayerState) => void,
    private onPlay: (name: PlayerName) => void,
  ) {
    for (const [prop, fmt] of [
      ["time-pos", "double"],
      ["pause", "flag"],
      ["eof-reached", "flag"],
    ] as const)
      mpv.observe(prop, fmt);
    mpv.on((ev) => this.onEvent(ev));
  }

  /** 每帧取播放位置：用引擎逐帧推来的最新 time-pos（不节流）加上到现在的流逝时间。
   *  不在这里同步读 mpv 属性——那会等 mpv 内部的锁，打开文件、跳转时会把页面卡住（实测）。跳转未完成时返回目标位置。 */
  position(): number | null {
    if (!this.loaded || this.time == null) return null;
    if (this.awaitingSeek || !this.playing) return (this.shown = this.time);
    let t = this.time + (performance.now() - this.timeAt) / 1000;
    // 引擎按视频帧（约 42 ms 一次）报位置，外推偶尔略超前、下一次报告又拉回：正常播放中不小幅后退，原地等真实位置追上
    if (this.shown != null && t < this.shown && this.shown - t < 0.08) t = this.shown;
    const end = this.range && !this.range.loop ? this.range.b - this.offset : Infinity;
    return (this.shown = Math.min(t, end));
  }

  /** 新请求：代次加一，清掉上一个请求挂起的动作。 */
  begin(): number {
    this.gen += 1;
    this.queue = [];
    this.error = undefined;
    this.endedGen = -1;
    this.push(true);
    return this.gen;
  }

  load(path: string, aid: number): void {
    if (this.path === path && this.loaded) {
      if (aid !== this.aid) {
        this.mpv.set("aid", String(aid));
        this.aid = aid;
      }
      return;
    }
    this.path = path;
    this.aid = aid;
    this.loaded = false;
    this.loading = true;
    this.mpv.set("pause", "yes");
    this.mpv.set("end", "none");
    this.mpv.command(["loadfile", path, "replace", `aid=${aid},pause=yes`]);
    this.push(true);
  }

  /** 加载完成后再执行（R22.4：加载前的跳转/播放挂起）。 */
  whenLoaded(fn: () => void): void {
    if (this.loaded) fn();
    else this.queue.push(fn);
  }

  fail(gen: number, e: CoreErrorWire): void {
    if (gen !== this.gen) return;
    this.error = e;
    this.loading = false;
    this.push(true);
  }

  setOffset(o: number): void {
    this.offset = o;
  }

  playRange(a: number, b: number, loop: boolean): void {
    const gen = this.gen;
    this.whenLoaded(() => {
      if (gen !== this.gen) return;
      this.range = { a, b, loop, gen };
      this.mpv.set("pause", "yes");
      if (loop) {
        this.mpv.set("end", "none");
        this.mpv.set("ab-loop-a", String(a));
        this.mpv.set("ab-loop-b", String(b));
      } else {
        this.mpv.set("ab-loop-a", "no");
        this.mpv.set("ab-loop-b", "no");
        this.mpv.set("end", String(b));
      }
      this.seekTo(a);
      this.start();
    });
  }

  /** 普通播放：清除范围后继续。 */
  play(): void {
    this.whenLoaded(() => {
      this.clearRange();
      if (this.mpv.get("eof-reached") === "yes") this.seekTo((this.time ?? 0) + this.offset);
      this.start();
    });
  }

  pause(): void {
    this.whenLoaded(() => {
      this.mpv.set("pause", "yes");
    });
  }

  seek(t: number): void {
    const gen = this.gen;
    this.whenLoaded(() => {
      if (gen !== this.gen) return;
      this.clearRange();
      this.seekTo(t + this.offset);
    });
  }

  step(dir: 1 | -1): void {
    this.whenLoaded(() => {
      this.clearRange();
      this.mpv.command([dir > 0 ? "frame-step" : "frame-back-step"]);
    });
  }

  stop(): void {
    this.begin();
    this.mpv.set("pause", "yes");
    this.clearRange();
    this.push(true);
  }

  /** 精确跳转（文件秒）：先把时钟放到目标，直到引擎报 playback-restart 前不认位置事件。 */
  private seekTo(fileT: number): void {
    this.awaitingSeek = true;
    this.eof = false;
    this.time = fileT - this.offset;
    this.mpv.command(["seek", String(fileT), "absolute+exact"]);
  }

  private start(): void {
    this.onPlay(this.name);
    this.mpv.set("pause", "no");
  }

  private clearRange(): void {
    if (!this.range) return;
    this.range = null;
    this.mpv.set("end", "none");
    this.mpv.set("ab-loop-a", "no");
    this.mpv.set("ab-loop-b", "no");
  }

  private onEvent(ev: MpvEvent): void {
    if (ev.type === "file-loaded") {
      if (this.mpv.get("path") !== this.path) return; // 旧加载
      this.loaded = true;
      this.loading = false;
      const q = this.queue;
      this.queue = [];
      for (const fn of q) fn();
      this.push(true);
    } else if (ev.type === "end-file" && ev.error && !this.loaded) {
      this.fail(this.gen, { code: "playback-failed", args: { detail: ev.error } });
    } else if (ev.type === "playback-restart") {
      this.awaitingSeek = false;
      this.push(true);
    } else if (ev.type === "property-change") {
      if (this.awaitingSeek && (ev.name === "time-pos" || ev.name === "eof-reached")) return; // 跳转前的旧值
      if (ev.name === "time-pos") {
        this.time = typeof ev.value === "number" ? ev.value - this.offset : null;
        this.timeAt = performance.now();
        this.push(false);
      } else if (ev.name === "pause") {
        if (this.playing && ev.value === true && this.time != null) this.time += (performance.now() - this.timeAt) / 1000;
        this.timeAt = performance.now();
        this.playing = ev.value === false;
        this.push(true);
      } else if (ev.name === "eof-reached") {
        this.eof = ev.value === true;
        this.push(true);
      }
    }
  }

  private push(now: boolean): void {
    const t = Date.now();
    if (!now && t - this.lastPush < PUSH_MS) {
      if (!this.pushTimer) this.pushTimer = setTimeout(() => this.push(true), PUSH_MS - (t - this.lastPush));
      return;
    }
    if (this.pushTimer) {
      clearTimeout(this.pushTimer);
      this.pushTimer = null;
    }
    this.lastPush = t;
    // 结束只通知一次：本代次发出的单次范围被引擎截停（eof-reached），显示时间贴到范围终点
    let ended = false;
    const r = this.range;
    if (r && r.gen === this.gen && !r.loop && this.eof && !this.awaitingSeek && this.endedGen !== this.gen) {
      ended = true;
      this.endedGen = this.gen;
      this.time = r.b - this.offset;
    }
    this.emit({
      player: this.name,
      gen: this.gen,
      time: this.time,
      playing: this.playing,
      loading: this.loading,
      ended,
      error: this.error,
    });
  }

  destroy(): void {
    if (this.pushTimer) clearTimeout(this.pushTimer);
    this.mpv.destroy();
  }
}

export class Playback {
  private sourceEng: Engine | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private auditionEng: Engine | null = null;
  private listeners = new Set<(s: PlayerState) => void>();

  private emit = (s: PlayerState) => {
    for (const l of this.listeners) l(s);
  };

  /** 全应用一个声音：一个开始播放，另一个暂停。 */
  private exclusive = (name: PlayerName) => {
    const other = name === "source" ? this.auditionEng : this.sourceEng;
    other?.mpv.set("pause", "yes");
  };

  onState(cb: (s: PlayerState) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  /** 原片播放器绑定到页面里的 canvas[data-otto-video]（画面是普通 DOM 元素）。 */
  attachVideo(): boolean {
    const canvas = document.querySelector<HTMLCanvasElement>("canvas[data-otto-video]");
    if (this.sourceEng && canvas === this.canvas && canvas?.isConnected) return true;
    if (!canvas) return false;
    // 画布换了（页面重新挂载）：旧引擎连同它的画面一起结束，绑到新画布上
    this.sourceEng?.destroy();
    this.canvas = canvas;
    this.sourceEng = new Engine("source", new CanvasPlayer(canvas, MPV_OPTIONS), this.emit, this.exclusive);
    return true;
  }

  private auditionEngine(): Engine {
    if (!this.auditionEng) this.auditionEng = new Engine("audition", new AudioPlayer(AO), this.emit, this.exclusive);
    return this.auditionEng;
  }

  private sourceEngine(): Engine {
    if (!this.attachVideo()) throw { code: "player-not-attached", args: {} } as CoreErrorWire;
    return this.sourceEng!;
  }

  async openSource(sourceId: string, ordinal?: number): Promise<{ duration: number; hasVideo: boolean }> {
    const e = this.sourceEngine();
    const seq = ++e.loadSeq;
    const gen = e.begin();
    try {
      const h = await core<{ path: string; aid: number; duration: number; hasVideo: boolean }>("playback.resolveSource", {
        sourceId,
        ordinal,
      });
      if (seq === e.loadSeq) {
        e.setOffset(0);
        e.load(h.path, h.aid);
      }
      return { duration: h.duration, hasVideo: h.hasVideo };
    } catch (err) {
      e.fail(gen, err as CoreErrorWire);
      throw err;
    }
  }

  sourcePlay(): void {
    this.sourceEngine().play();
  }
  sourcePause(): void {
    this.sourceEngine().pause();
  }
  sourceSeek(t: number): number {
    const e = this.sourceEngine();
    const gen = e.begin();
    e.seek(t);
    return gen;
  }
  sourceStep(dir: 1 | -1): void {
    this.sourceEngine().step(dir);
  }
  /** 原片秒区间；过期的请求不能改终点（R22.5）。 */
  sourcePlayRange(a: number, b: number, loop = false): number {
    const e = this.sourceEngine();
    const gen = e.begin();
    e.playRange(a, b, loop);
    return gen;
  }

  /** 试听：资产区间（局部秒），引擎在终点截停；时钟报区间本地秒。 */
  async audition(assetId: string, start: number, end: number, loop = false): Promise<number> {
    const e = this.auditionEngine();
    const gen = e.begin();
    try {
      const h = await core<{ path: string; aid: number; fileStart: number; fileEnd: number }>("playback.resolveAsset", {
        assetId,
        start,
        end,
      });
      if (gen !== e.gen) return gen;
      e.setOffset(h.fileStart);
      e.load(h.path, h.aid);
      e.playRange(h.fileStart, h.fileEnd, loop);
      return gen;
    } catch (err) {
      e.fail(gen, err as CoreErrorWire);
      throw err;
    }
  }

  position(player: PlayerName): number | null {
    const e = player === "source" ? this.sourceEng : this.auditionEng;
    return e ? e.position() : null;
  }

  stopAudition(): void {
    this.auditionEng?.stop();
  }

  destroy(): void {
    this.sourceEng?.destroy();
    this.auditionEng?.destroy();
  }
}
