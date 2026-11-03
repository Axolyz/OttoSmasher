// 白名单 API（ARCHITECTURE §2.5）：渲染进程只能经这里调用 Core 的公开命令，不能直接碰文件或进程。
import { contextBridge, ipcRenderer, webUtils } from "electron";
import type { CoreEvent, CoreStatus, OttoApi, PlayerApi, ProbeApi } from "../shared/protocol";
import { CanvasPlayer } from "./player";
import { Playback } from "./playback";

const localeArg = process.argv.find((a) => a.startsWith("--otto-locale="));
const buildArg = process.argv.find((a) => a.startsWith("--otto-build="));
const playback = new Playback();
window.addEventListener("beforeunload", () => playback.destroy());

// Core 返回的错误以 {code, args} 的普通对象跨过 contextBridge（不是 Error 实例）
const player: PlayerApi = {
  attachVideo: () => playback.attachVideo(),
  openSource: (sourceId, ordinal, assetId) => playback.openSource(sourceId, ordinal, assetId),
  play: () => playback.sourcePlay(),
  pause: () => playback.sourcePause(),
  seek: (t) => playback.sourceSeek(t),
  step: (dir) => playback.sourceStep(dir),
  setMuted: (m) => playback.sourceMute(m),
  playRange: (a, b, loop) => playback.sourcePlayRange(a, b, loop),
  audition: (assetId, start, end, loop, sampleId) => playback.audition(assetId, start, end, loop, sampleId),
  showPicture: (sampleId) => playback.picture.show(sampleId),
  pictureAt: (sampleId, local) => playback.picture.at(sampleId, local),
  auditionRender: (key, loop) => playback.auditionRender(key, loop),
  stopAudition: () => playback.stopAudition(),
  position: (p) => playback.position(p),
  onState: (cb) => playback.onState((s) => cb({ ...s })),
};

const api: OttoApi = {
  core: {
    request: (method, params) => ipcRenderer.invoke("core:request", method, params ?? {}),
    onEvent(cb) {
      // 页面里订阅的地方很多：只挂一个 IPC 监听，再分发给各订阅者（避免 MaxListeners 警告）
      coreEventSubs.add(cb);
      return () => {
        coreEventSubs.delete(cb);
      };
    },
    onStatus(cb) {
      const h = (_e: unknown, st: CoreStatus) => cb(st);
      ipcRenderer.on("core:status", h);
      return () => ipcRenderer.removeListener("core:status", h);
    },
    status: () => ipcRenderer.invoke("core:status"),
    restart: () => ipcRenderer.invoke("core:restart"),
  },
  app: {
    platform: process.platform,
    locale: localeArg ? localeArg.slice("--otto-locale=".length) : "zh-CN",
    build: buildArg?.slice("--otto-build=".length) === "packaged" ? "packaged" : "source",
  },
  player,
  files: {
    pick: (kind) => ipcRenderer.invoke("files:pick", kind),
    reveal: (path) => ipcRenderer.invoke("files:reveal", path),
    pathOf: (file) => webUtils.getPathForFile(file),
    startDrag: (files) => ipcRenderer.send("files:startDrag", files),
  },
  links: {
    open: (id) => ipcRenderer.invoke("links:open", id),
  },
  agent: {
    ottoInfo: () => ipcRenderer.invoke("agent:ottoInfo"),
    installOtto: () => ipcRenderer.invoke("agent:installOtto"),
  },
  reaper: {
    copy: (params) => ipcRenderer.invoke("reaper:copy", params),
  },
};

const coreEventSubs = new Set<(ev: CoreEvent) => void>();
ipcRenderer.on("core:event", (_e: unknown, ev: CoreEvent) => {
  for (const cb of [...coreEventSubs]) {
    try {
      cb(ev);
    } catch (err) {
      console.error(err);
    }
  }
});

contextBridge.exposeInMainWorld("otto", api);

// 阶段 1 的 mpv 渲染桥探针（只在开发模式下暴露）。页面不能给出文件路径：路径由主进程决定（对话框或环境变量）。
if (process.env.OTTO_DEV === "1") {
  let player: CanvasPlayer | null = null;
  const probe: ProbeApi = {
    attach() {
      if (player) return true;
      const canvas = document.querySelector<HTMLCanvasElement>("canvas[data-mpv-canvas]");
      if (!canvas) return false;
      // 探针可用环境变量调 mpv 选项与渲染像素上限，用来比较方案
      const extra = process.env.OTTO_PROBE_MPV ? (JSON.parse(process.env.OTTO_PROBE_MPV) as Record<string, string>) : {};
      const maxPixels = process.env.OTTO_PROBE_MAXPIX ? Number(process.env.OTTO_PROBE_MAXPIX) : Infinity;
      player = new CanvasPlayer(canvas, { hwdec: "auto-copy", "sws-fast": "yes", ...extra }, maxPixels);
      for (const name of ["pause", "time-pos", "duration", "hwdec-current"]) player.observe(name, name === "pause" ? "flag" : name === "hwdec-current" ? "string" : "double");
      return true;
    },
    async open() {
      const path = (await ipcRenderer.invoke("probe:pick")) as string | null;
      if (!path || !player) return false;
      player.command(["loadfile", path]);
      return true;
    },
    control(action, value) {
      if (!player) return;
      if (action === "toggle") player.command(["cycle", "pause"]);
      else if (action === "seek") player.command(["seek", String(value ?? 0), "absolute+exact"]);
      else if (action === "seekRel") player.command(["seek", String(value ?? 0), "relative+exact"]);
      else if (action === "step") player.command(["frame-step"]);
      else if (action === "backStep") player.command(["frame-back-step"]);
    },
    stats() {
      if (!player) return null;
      const num = (k: string) => {
        const v = player!.get(k);
        return v === null ? null : Number(v);
      };
      return {
        ...player.stats(),
        hwdec: player.get("hwdec-current"),
        timePos: num("time-pos"),
        paused: player.get("pause") === "yes",
        frameDrops: num("frame-drop-count"),
        decoderDrops: num("decoder-frame-drop-count"),
        voDelayed: num("vo-delayed-frame-count"),
        videoFps: num("container-fps"),
        estimatedVfFps: num("estimated-vf-fps"),
      };
    },
    metrics: () => ipcRenderer.invoke("probe:metrics"),
    onEvent(cb) {
      return player ? player.on((ev) => cb({ ...ev })) : () => {};
    },
  };
  contextBridge.exposeInMainWorld("ottoProbe", probe);
}
