// Electron 主进程：窗口、Core 进程管理、IPC 转发、退出流程（ARCHITECTURE §2）。
import { appendFileSync, existsSync, lstatSync, mkdirSync, readlinkSync, statSync, symlinkSync, unlinkSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { BrowserWindow, ClipboardItem, app, clipboard, dialog, ipcMain, nativeImage, session, shell } from "electron";
import zhCN from "../renderer/i18n/locales/zh-CN.json";
import { PSEUDO, createT } from "../shared/i18n";
import type { CoreEvent, CoreStatus, OttoInfo } from "../shared/protocol";
import { CoreClient } from "./core-client";
import { resolvePaths } from "./paths";

const paths = resolvePaths();
const locale = process.env.OTTO_LOCALE ?? "zh-CN";
const t = createT(zhCN as Record<string, string>, { pseudo: locale === PSEUDO });
const devServer = process.env.OTTO_DEV_SERVER; // 开发期 Vite 地址
const isDev = process.env.OTTO_DEV === "1";

if (!paths.repo) {
  // 发布版：Core 用随包的 Python 与媒体工具；用户环境里的 Python 变量不能漏进来（15 §15.8 冒烟：清空 Python/Conda 环境变量）
  for (const k of ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"]) delete process.env[k];
  process.env.PYTHONNOUSERSITE = "1";
  process.env.OTTO_RESOURCES = paths.resources;
  process.env.OTTO_FFMPEG = join(paths.resources, "bin", "ffmpeg");
  process.env.OTTO_FFPROBE = join(paths.resources, "bin", "ffprobe");
  process.env.OTTO_RUBBERBAND = join(paths.resources, "bin", "rubberband");
}

const core = new CoreClient({
  python: paths.python,
  workspace: paths.workspace,
  supportDir: paths.supportDir,
  dev: isDev,
  cwd: paths.resources,
});

function logDesktopEvent(kind: string, detail: Record<string, unknown>): void {
  // 规格 13 §13.5：桌面端事件（渲染进程崩溃、无响应）写进工作区日志
  try {
    const dir = join(paths.workspace, "Data", "Logs");
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, "desktop-events.log"), `${new Date().toISOString()} ${kind} ${JSON.stringify(detail)}\n`);
  } catch {
    // 日志写不进去不影响运行
  }
}

function broadcast(channel: string, payload: unknown): void {
  for (const w of BrowserWindow.getAllWindows()) w.webContents.send(channel, payload);
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 850,
    minHeight: 600,
    backgroundColor: "#0e1014",
    show: false,
    title: "OttoSmasher",
    webPreferences: {
      preload: paths.preload,
      contextIsolation: true,
      // preload 不放进沙箱：它要加载 mpv 渲染桥（原生扩展）。页面世界仍然没有 Node，只能用白名单 API（ARCHITECTURE §2.5）
      sandbox: false,
      nodeIntegration: false,
      additionalArguments: [`--otto-locale=${locale}`],
    },
  });
  win.once("ready-to-show", () => win.show());
  win.webContents.on("render-process-gone", (_e, details) => {
    logDesktopEvent("render-process-gone", { ...details });
    if (details.reason !== "clean-exit") win.reload();
  });
  win.on("unresponsive", () => logDesktopEvent("unresponsive", {}));
  // 不允许打开新窗口或跳到外部地址（规格 16 R22.7）
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e, url) => {
    if (!devServer || !url.startsWith(devServer)) e.preventDefault();
  });
  if (devServer) void win.loadURL(devServer);
  else void win.loadFile(paths.rendererIndex);
  return win;
}

function installCsp(): void {
  const devSrc = devServer ? ` ${devServer} ws://localhost:5173` : "";
  const csp = [
    "default-src 'self'" + devSrc,
    "script-src 'self'" + devSrc + (devServer ? " 'unsafe-inline'" : ""),
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "connect-src 'self'" + devSrc,
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-src 'none'",
  ].join("; ");
  session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
    cb({ responseHeaders: { ...details.responseHeaders, "Content-Security-Policy": [csp] } });
  });
}

if (isDev) {
  // mpv 渲染桥探针：文件路径只来自主进程（环境变量或对话框），页面不能指定路径
  ipcMain.handle("probe:pick", async () => {
    if (process.env.OTTO_PROBE_FILE) return process.env.OTTO_PROBE_FILE;
    const win = BrowserWindow.getFocusedWindow();
    const res = win ? await dialog.showOpenDialog(win, { properties: ["openFile"] }) : await dialog.showOpenDialog({ properties: ["openFile"] });
    return res.canceled ? null : (res.filePaths[0] ?? null);
  });
  ipcMain.handle("probe:metrics", () =>
    app.getAppMetrics().map((m) => ({ type: m.type, cpu: m.cpu.percentCPUUsage, memoryMB: Math.round(m.memory.workingSetSize / 1024) })),
  );
}

// 文件对话框与“在 Finder 中显示”（页面拿不到 Node；路径只来自系统对话框或 Core 的记录）
const MEDIA_EXT = ["mkv", "mp4", "mov", "webm", "m4v", "avi", "ts", "m2ts", "wav", "flac", "mp3", "m4a", "aac", "ogg", "opus", "aif", "aiff", "wma"];
const PICTURE_EXT = ["mp4", "mov", "mkv", "webm", "m4v", "avi", "gif", "png", "jpg", "jpeg", "webp", "bmp"];
ipcMain.handle("files:pick", async (e, kind: "media" | "media-one" | "subtitle" | "import" | "folder" | "picture" | "reimport" | "models") => {
  const win = BrowserWindow.fromWebContents(e.sender) ?? undefined;
  // picture：画面绑定（视频 / 动图 / 图片，规格 12 §12.4）；reimport：回导的成品（任何音频，规格 06 §6.7）
  const filters =
    kind === "subtitle"
      ? [{ name: "Subtitles", extensions: ["srt", "ass"] }]
      : kind === "models"
        ? [{ name: "ONNX", extensions: ["onnx"] }, { name: "*", extensions: ["*"] }]
      : kind === "picture"
        ? [{ name: "Pictures", extensions: PICTURE_EXT }, { name: "*", extensions: ["*"] }]
        : [{ name: "Media", extensions: MEDIA_EXT }, { name: "*", extensions: ["*"] }];
  // 采样库导入：文件或整个文件夹（规格 06 §6.6；macOS 的对话框可以同时选文件和文件夹）
  // folder：原片文件夹（阶段 3.13），只选一个文件夹
  // models：从文件导入模型权重（文件或文件夹，Core 按 SHA-256 认）
  const properties: Array<"openFile" | "openDirectory" | "multiSelections" | "createDirectory"> =
    kind === "import" || kind === "models"
      ? ["openFile", "openDirectory", "multiSelections"]
      : kind === "folder"
        ? ["openDirectory", "createDirectory"]
        : kind === "media"
          ? ["openFile", "multiSelections"]
          : ["openFile"];
  const res = win ? await dialog.showOpenDialog(win, { properties, filters }) : await dialog.showOpenDialog({ properties, filters });
  return res.canceled ? [] : res.filePaths;
});
ipcMain.handle("files:reveal", (_e, path: string) => {
  if (typeof path === "string" && existsSync(path)) shell.showItemInFolder(path);
});

// 外部网页：只开这里列出的固定地址（页面不能让主进程打开任意网址，规格 15 §15.6）
const LINKS: Record<string, string> = {
  "pymss-studio": "https://github.com/pymss-project/pymss-studio/releases",
};
ipcMain.handle("links:open", (_e, id: string) => {
  const url = typeof id === "string" ? LINKS[id] : undefined;
  if (url) void shell.openExternal(url);
});

// 命令行 otto（设置 › 命令行与 agent）：源码版 = 仓库的 tools/otto；发布版的启动器还没做（ROADMAP L46，阶段 10）。
// “装成命令”= 在 ~/.local/bin 放一个指向它的链接（像 VS Code 的“在 PATH 中安装 code 命令”）；Windows 未实现（未验收）。
function ottoInfo(): OttoInfo {
  const path = join(paths.resources, paths.repo ? "tools" : "bin", process.platform === "win32" ? "otto.cmd" : "otto");
  const link = process.platform === "win32" ? null : join(homedir(), ".local", "bin", "otto");
  let linked = false;
  let conflict = false;
  if (link && existsSync(link)) {
    const st = lstatSync(link);
    if (st.isSymbolicLink()) linked = readlinkSync(link) === path;
    else conflict = true;
  }
  return { path: existsSync(path) ? path : null, link, linked, conflict };
}
ipcMain.handle("agent:ottoInfo", () => ottoInfo());
ipcMain.handle("agent:installOtto", () => {
  const info = ottoInfo();
  if (!info.path || !info.link || info.conflict || info.linked) return info;
  mkdirSync(join(homedir(), ".local", "bin"), { recursive: true });
  try {
    if (lstatSync(info.link).isSymbolicLink()) unlinkSync(info.link); // 旧的链接（例如仓库换了位置）
  } catch {
    // 不存在
  }
  symlinkSync(info.path, info.link);
  return ottoInfo();
});

// 拖出（规格 12 §12.2）：页面生成好文件、鼠标仍按着时请求系统拖拽。只接受已存在的普通文件。
let dragIcon: Electron.NativeImage | null = null;
ipcMain.on("files:startDrag", (e, files: unknown) => {
  if (!Array.isArray(files) || !files.length) return;
  const ok = files.filter((f): f is string => typeof f === "string" && existsSync(f) && statSync(f).isFile());
  if (ok.length !== files.length) return;
  if (!dragIcon) {
    // 1×1 透明图：Electron 把拖拽图居中放在指针上，有的软件按图的左上角而不是指针放文件——
    // 原来 48 点的图标在 HiFiShifter 里落在指针左上方（所有者 2026-10-30；Logic Pro 按指针，没问题）。图小到 1 点，左上角就是指针。
    // macOS 不接受空图（createEmpty 会让 startDrag 抛错），所以用一个透明像素。
    dragIcon = nativeImage.createFromBitmap(Buffer.alloc(4), { width: 1, height: 1 });
  }
  e.sender.startDrag({ file: ok[0]!, files: ok, icon: dragIcon });
});

// 原生剪贴板类型（Electron 44：自定义的系统格式写成 osclipboard;format=…）
const REAPER_FORMAT = 'electron application/osclipboard;format="REAPERMedia"';

async function readRaw(format: string): Promise<Buffer | null> {
  for (const item of await clipboard.read()) {
    if (!item.types.includes(format)) continue;
    const blob = (await item.getType(format)) as Blob;
    return Buffer.from(await blob.arrayBuffer());
  }
  return null;
}

// REAPER 交接（规格 12 §12.3）：条目文本由 Core 生成（页面不能往剪贴板写任意内容）；写入 REAPERMedia 后回读校验。
// 剪贴板类型 REAPERMedia、各行 NUL 分隔、末尾两个 NUL（REAPER 7.x macOS 实测格式）；Windows 未实测 → 未验收。
ipcMain.handle("reaper:copy", async (_e, params: Record<string, unknown>) => {
  const r = await core.request<{ clipboard: string; files: string[]; manifest: string; count: number }>("reaper.handoff", params ?? {});
  if (!r.ok) return r;
  const buf = Buffer.from(r.r.clipboard, "utf8");
  try {
    await clipboard.write([new ClipboardItem({ [REAPER_FORMAT]: new Blob([buf]) })]);
    const back = await readRaw(REAPER_FORMAT);
    if (!back || !back.equals(buf)) {
      return { ok: false, e: { code: "reaper-clipboard-failed", args: { reason: `read back ${back?.length ?? 0}/${buf.length} bytes` } } };
    }
  } catch (err) {
    return { ok: false, e: { code: "reaper-clipboard-failed", args: { reason: String(err) } } };
  }
  return { ok: true, r: { files: r.r.files, manifest: r.r.manifest, count: r.r.count } };
});

ipcMain.handle("core:request", (e, method: string, params: Record<string, unknown>) => core.request(method, params ?? {}, e.sender.id));
ipcMain.handle("core:status", () => core.status);
ipcMain.handle("core:restart", async () => {
  if (core.status.state === "ready") return;
  core.start();
});
// 资料变化：发请求的那个窗口收到 own = true（自己的操作不提示“资料已更新”，P8 / L13）
core.on("event", (ev: CoreEvent) => {
  if (ev.origin === undefined) return broadcast("core:event", ev);
  const { origin, ...rest } = ev;
  for (const w of BrowserWindow.getAllWindows()) w.webContents.send("core:event", { ...rest, own: w.webContents.id === origin });
});
core.on("status", (st: CoreStatus) => broadcast("core:status", st));
core.on("unexpected-exit", (code) => logDesktopEvent("core-exited", { code }));

let quitting = false;
app.on("before-quit", (e) => {
  if (quitting) return;
  e.preventDefault();
  void (async () => {
    let cancel = true;
    const r = await core.request<{ active: number }>("app.prepareQuit");
    const active = r.ok ? r.r.active : 0;
    if (active > 0) {
      const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
      const opts = {
        type: "warning" as const,
        message: t("quit.confirm.title", { n: active }),
        detail: t("quit.confirm.detail"),
        buttons: [t("quit.confirm.quit"), t("common.cancel")],
        defaultId: 1,
        cancelId: 1,
      };
      const res = win ? await dialog.showMessageBox(win, opts) : await dialog.showMessageBox(opts);
      if (res.response !== 0) return;
      cancel = true;
    }
    quitting = true;
    await core.stop(cancel);
    app.quit();
  })();
});

app.whenReady().then(() => {
  // 开发期 Dock 图标用所有者的 logo（发布版的 .icns/.ico 在阶段 10 生成）
  if (process.platform === "darwin" && paths.repo) app.dock?.setIcon(join(paths.repo, "assets", "brand", "logo-1024.png")); // 发布版用 .app 自己的图标
  installCsp();
  core.start();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  app.quit();
});
