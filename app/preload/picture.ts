// 舞台画面（UI_PLAN §3；规格 12 §12.4、L16）：第三个 mpv（只有画面、静音），跟着试听播放器走。
// - 页面给采样 ID（不给路径）；这里向 Core 要有效画面（visuals.forSample：采样 > 原片 > 原片自带的视频流）。
// - 音频是唯一主时钟：试听报出的区间本地秒 → 资产局部秒 → 经映射的原片秒 → 画面时间（同步 = 原片秒 + 偏移；循环 = 本地秒 mod 时长）；
//   画面与应有位置的偏差超过 0.08 秒才重定位；试听暂停 / 结束时画面暂停，不靠逐帧反复跳转维持同步。
// - 图片不用 mpv（页面直接显示缩略图）。卡拍试听的时间不在资产时间轴上：画面不跟（保持静帧）。
import { ipcRenderer } from "electron";
import type { CoreResult, PlayerState } from "../shared/protocol";
import { CanvasPlayer, type MpvEvent } from "./player";

const DRIFT = 0.08;

interface Binding {
  mode: "sync" | "image" | "loop" | "materialized_clip";
  offset: number;
  path: string;
  ordinal: number;
  duration: number | null;
  state: "ok" | "missing" | "changed";
}
interface Plan {
  sampleId: string;
  binding: Binding | null;
  start: number;
  end: number;
  mapping: number[][] | null;
}

async function core<T>(method: string, params: Record<string, unknown>): Promise<T> {
  const r = (await ipcRenderer.invoke("core:request", method, params)) as CoreResult<T>;
  if (!r.ok) throw r.e;
  return r.r;
}

/** 分段线性映射（本地秒 → 原片秒）；越界 → null */
function mapTo(knots: number[][] | null, t: number): number | null {
  if (!knots || knots.length < 2) return null;
  for (let i = 1; i < knots.length; i++) {
    const [l0, s0] = knots[i - 1] as [number, number];
    const [l1, s1] = knots[i] as [number, number];
    if (t >= l0 - 1e-9 && t <= l1 + 1e-9) return s0 + ((t - l0) / (l1 - l0 || 1)) * (s1 - s0);
  }
  return null;
}

export class StagePicture {
  private player: CanvasPlayer | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private plan: Plan | null = null;
  private loadedPath = "";
  private pos: number | null = null;
  private following: { a: number } | null = null;
  private playing = false;

  /** 页面的舞台画布 canvas[data-otto-stage-video] 挂载 / 换了 */
  private attach(): boolean {
    const c = document.querySelector<HTMLCanvasElement>("canvas[data-otto-stage-video]");
    if (!c) return false;
    if (this.player && c === this.canvas && c.isConnected) return true;
    this.player?.destroy();
    this.canvas = c;
    this.loadedPath = "";
    this.player = new CanvasPlayer(c, { hwdec: "videotoolbox-copy", aid: "no", mute: "yes", "loop-file": "no", "keep-open": "yes" }, 1280 * 720);
    this.player.observe("time-pos", "double");
    this.player.on((ev: MpvEvent) => {
      if (ev.type === "property-change" && ev.name === "time-pos") this.pos = typeof ev.value === "number" ? ev.value : null;
    });
    return true;
  }

  /** 舞台换了采样：取它的有效画面；没有画面 / 图片 / 文件有问题 → 不用 mpv */
  async show(sampleId: string | null): Promise<void> {
    this.following = null;
    this.playing = false;
    if (!sampleId) {
      this.plan = null;
      this.player?.set("pause", "yes");
      return;
    }
    const plan = await core<Plan>("visuals.forSample", { id: sampleId });
    this.plan = { ...plan, sampleId };
    const b = plan.binding;
    if (!b || b.mode === "image" || b.state !== "ok" || !this.attach()) return;
    this.player!.set("pause", "yes");
    this.player!.set("loop-file", b.mode === "loop" ? "inf" : "no");
    if (this.loadedPath !== b.path) {
      this.loadedPath = b.path;
      this.player!.command(["loadfile", b.path, "replace", `vid=${b.ordinal + 1},aid=no,pause=yes`]);
    }
    // 静帧：采样起点那一刻
    this.seekTo(this.timeAt(plan.start));
  }

  /** 资产局部秒 → 画面时间 */
  private timeAt(local: number): number | null {
    const p = this.plan;
    const b = p?.binding;
    if (!p || !b) return null;
    if (b.mode === "loop") {
      const d = b.duration ?? 0;
      return d > 0 ? (((local - p.start) % d) + d) % d : 0;
    }
    const src = mapTo(p.mapping, local);
    return src == null ? null : src + b.offset;
  }

  private seekTo(t: number | null): void {
    if (t == null || !this.player) return;
    this.player.command(["seek", String(Math.max(0, t)), "absolute+exact"]);
  }

  /** 试听开始：这次试听是不是舞台这个采样的原声（资产局部秒 a 起） */
  follow(sampleId: string | undefined, a: number): void {
    const b = this.plan?.binding;
    this.following = sampleId && sampleId === this.plan?.sampleId && b && b.mode !== "image" && b.state === "ok" ? { a } : null;
  }

  stopFollowing(): void {
    this.following = null;
    if (this.playing) this.player?.set("pause", "yes");
    this.playing = false;
  }

  /** 试听播放器的状态（约每 50 ms）：区间本地秒 */
  onAudition(st: PlayerState): void {
    const f = this.following;
    if (!f || !this.player) return;
    if (st.ended || st.error) return this.stopFollowing();
    if (st.time == null || st.loading) return; // 还在加载
    const want = this.timeAt(f.a + st.time);
    if (want == null) return;
    if (!st.playing) {
      if (this.playing) this.player.set("pause", "yes");
      this.playing = false;
      return;
    }
    if (!this.playing || this.pos == null || Math.abs(this.pos - want) > DRIFT) this.seekTo(want);
    if (!this.playing) this.player.set("pause", "no");
    this.playing = true;
  }

  destroy(): void {
    this.player?.destroy();
    this.player = null;
  }
}
