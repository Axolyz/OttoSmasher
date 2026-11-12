// Electron 主进程：窗口、Core 进程管理、IPC 转发、退出流程（ARCHITECTURE §2）。
import { appendFileSync, existsSync, lstatSync, mkdirSync, readFileSync, readlinkSync, statSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { BrowserWindow, ClipboardItem, Menu, app, clipboard, dialog, ipcMain, nativeImage, session, shell } from "electron";
import en from "../renderer/i18n/locales/en.json";
import zhCN from "../renderer/i18n/locales/zh-CN.json";
import { PSEUDO, createT, englishPlurals } from "../shared/i18n";
import type { CoreEvent, CoreStatus, OttoInfo } from "../shared/protocol";
import { type PickKind, type PickMode, needsChoice, pickProperties } from "./file-pick";
import { CoreClient } from "./core-client";
import { OTTO_SHIM_MARK, ensureOttoLink, ottoShim } from "./otto-link";
import { resolvePaths } from "./paths";

const paths = resolvePaths();
// 界面语言：环境变量（测试）优先；否则上次用的语言，第一次跟随系统。工作区的设置 general.ui_language 打开后由界面告诉这里（app:setLanguage）。
const CATALOGS: Record<string, Record<string, string>> = { "zh-CN": zhCN as Record<string, string>, en: en as Record<string, string> };
const envLocale = process.env.OTTO_LOCALE;
let locale = envLocale ?? "zh-CN";
const makeT = () => createT(CATALOGS[locale] ?? CATALOGS["zh-CN"]!, { pseudo: locale === PSEUDO, finish: locale === "en" ? englishPlurals : undefined });
let t = makeT();
const systemLocale = () => (app.getLocale().toLowerCase().startsWith("zh") ? "zh-CN" : "en");
const localeFile = () => join(app.getPath("userData"), "ui-language.json");
function loadLocale(): void {
  if (envLocale) return;
  let saved: unknown;
  try {
    saved = JSON.parse(readFileSync(localeFile(), "utf8"));
  } catch {
    saved = null; // 第一次运行
  }
  locale = typeof saved === "string" && CATALOGS[saved] ? saved : systemLocale();
  t = makeT();
}
ipcMain.on("app:locale", (e) => {
  e.returnValue = locale;
});
ipcMain.handle("app:setLanguage", (e, choice: string) => {
  if (envLocale) return;
  const next = choice === "auto" ? systemLocale() : choice;
  if (!CATALOGS[next]) return;
  writeFileSync(localeFile(), JSON.stringify(next));
  if (next === locale) return;
  locale = next;
  registerInstance();
  t = makeT();
  e.sender.reload();
});
const devServer = process.env.OTTO_DEV_SERVER; // 开发期 Vite 地址
const isDev = process.env.OTTO_DEV === "1";
// macOS：不进程序坞、不抢前台。要在应用就绪前设
if (process.env.OTTO_TEST_BACKGROUND && process.platform === "darwin") app.setActivationPolicy("accessory");

if (paths.repo) {
  // 源码运行（开发）与发布版只在“身份”上区分，行为一样（所有者 2026-10-31）：名字、界面缓存文件夹、程序坞角标；
  // 工作区等其余差别也都在这个分支里（见 DEVELOPMENT「开发版与发布版并存」）
  app.setName("OttoSmasher Dev");
  app.setPath("userData", process.env.OTTO_USER_DATA ?? join(app.getPath("appData"), "OttoSmasher Dev")); // 测试用 OTTO_USER_DATA 隔开
} else {
  // 发布版：Core 用随包的 Python 与媒体工具；用户环境里的 Python 变量不能漏进来（15 §15.8 冒烟：清空 Python/Conda 环境变量）
  for (const k of ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"]) delete process.env[k];
  process.env.PYTHONNOUSERSITE = "1";
  // 字节码打包时已经编译好；运行时不往 .app 里写 __pycache__（会改动签过名的内容）
  process.env.PYTHONDONTWRITEBYTECODE = "1";
  process.env.OTTO_RESOURCES = paths.resources;
  const exe = process.platform === "win32" ? ".exe" : "";
  process.env.OTTO_FFMPEG = join(paths.resources, "bin", `ffmpeg${exe}`);
  process.env.OTTO_FFPROBE = join(paths.resources, "bin", `ffprobe${exe}`);
  process.env.OTTO_RUBBERBAND = join(paths.resources, "bin", `rubberband${exe}`);
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

ipcMain.on("app:rendererError", (_e, detail: Record<string, unknown>) => {
  const text = (v: unknown) => String(v ?? "").slice(0, 8000);
  logDesktopEvent("renderer-error", { message: text(detail?.message), stack: text(detail?.stack), componentStack: text(detail?.componentStack) });
});
ipcMain.on("app:reload", (e) => e.sender.reload());

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
    title: paths.repo ? "OttoSmasher Dev" : "OttoSmasher",
    webPreferences: {
      preload: paths.preload,
      contextIsolation: true,
      // preload 不放进沙箱：它要加载 mpv 渲染桥（原生扩展）。页面世界仍然没有 Node，只能用白名单 API（ARCHITECTURE §2.5）
      sandbox: false,
      nodeIntegration: false,
      additionalArguments: [`--otto-build=${paths.repo ? "source" : "packaged"}`],
    },
  });
  // 自动测试不打扰开发者（e2e/helpers.ts）：窗口照常显示和渲染，但全透明、鼠标穿透、不激活
  win.once("ready-to-show", () => {
    if (process.env.OTTO_TEST_BACKGROUND) {
      win.setOpacity(0);
      win.setIgnoreMouseEvents(true);
      win.setSkipTaskbar(true); // 不出现在 Windows 任务栏
      if (process.platform === "darwin") win.setHiddenInMissionControl(true); // 不出现在调度中心，免得手动切到透明窗口
      win.showInactive();
    } else win.show();
  });
  // Windows has no application menu, so native zoom accelerators need an explicit handler.
  win.webContents.on("before-input-event", (event, input) => {
    const modifier = process.platform === "darwin" ? input.meta : input.control;
    if (input.type !== "keyDown" || !modifier || input.alt) return;
    if (!["-", "=", "+", "0"].includes(input.key)) return;
    event.preventDefault();
    const step = input.key === "-" ? -1 : 1;
    win.webContents.setZoomLevel(input.key === "0" ? 0 : win.webContents.getZoomLevel() + step);
  });
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
ipcMain.handle("files:pick", async (e, kind: PickKind) => {
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
  // 导入和模型：文件或文件夹（规格 06 §6.6），先问选哪种，两个平台一致
  let mode: PickMode | undefined;
  if (needsChoice(kind)) {
    const options = { type: "question" as const, message: t("files.chooseTitle"), buttons: [t("files.chooseFiles"), t("files.chooseFolder"), t("common.cancel")], defaultId: 0, cancelId: 2 };
    const { response } = win ? await dialog.showMessageBox(win, options) : await dialog.showMessageBox(options);
    if (response === 2) return [];
    mode = response === 0 ? "files" : "folder";
  }
  const properties = pickProperties(kind, mode);
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

// 命令行 otto（设置 › 命令行与 agent）：源码版 = 仓库的 tools/otto；发布版 = 包里的启动器。
// “装成命令”= 在 ~/.local/bin 放一个指向它的链接（像 VS Code 的“在 PATH 中安装 code 命令”）；发布版启动时自动做（otto-link.ts）。
// Windows：普通用户不能建符号链接，在 %LOCALAPPDATA%\\Microsoft\\WindowsApps（Win10 起默认在 PATH 上）写一个转发脚本（ROADMAP L47）。
function ottoInfo(): OttoInfo {
  const win = process.platform === "win32";
  const path = join(paths.resources, paths.repo ? "tools" : "bin", win ? "otto.cmd" : "otto");
  const link = win ? (process.env.LOCALAPPDATA ? join(process.env.LOCALAPPDATA, "Microsoft", "WindowsApps", "otto.cmd") : null) : join(homedir(), ".local", "bin", "otto");
  let linked = false;
  let conflict = false;
  if (win && link && existsSync(link)) {
    const text = readFileSync(link, "utf8");
    if (text.includes(path)) linked = true;
    else if (!text.startsWith(OTTO_SHIM_MARK)) conflict = true;
  } else if (link && existsSync(link)) {
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
  if (process.platform === "win32") {
    writeFileSync(info.link, ottoShim(info.path), "utf8");
    return ottoInfo();
  }
  mkdirSync(join(homedir(), ".local", "bin"), { recursive: true });
  try {
    if (lstatSync(info.link).isSymbolicLink()) unlinkSync(info.link); // 旧的链接（例如仓库换了位置）
  } catch {
    // 不存在
  }
  symlinkSync(info.path, info.link);
  return ottoInfo();
});

/** 发布版启动时把 otto 装好，不用用户点；别的程序占了这个名字就留给设置里提示 */
function autoInstallOtto(): void {
  if (paths.repo || process.env.OTTO_NO_SELF_INSTALL) return;
  const info = ottoInfo();
  if (!info.path || !info.link) return;
  try {
    const r = ensureOttoLink(info.path, info.link, process.platform === "win32");
    if (r !== "current") logDesktopEvent("otto-link", { result: r, link: info.link });
  } catch (err) {
    logDesktopEvent("otto-link-failed", { error: String(err) });
  }
}

// 运行中的应用登记自己在哪，otto 和 agent 靠它找（core/ottosmasher/cli/instances.py 读）。不放连接密钥：密钥在工作区的 agent-endpoint.json 里
const instanceFile = join(
  process.env.OTTO_REGISTRY_DIR ??
    (process.platform === "win32"
      ? join(process.env.APPDATA ?? join(homedir(), "AppData", "Roaming"), "OttoSmasher", "instances")
      : join(homedir(), "Library", "Application Support", "OttoSmasher", "instances")),
  `${process.pid}.json`,
);
function registerInstance(): void {
  const location = paths.repo ?? (process.platform === "win32" ? process.execPath : resolve(paths.resources, "..", ".."));
  try {
    mkdirSync(dirname(instanceFile), { recursive: true });
    writeFileSync(
      instanceFile,
      JSON.stringify({ pid: process.pid, build: paths.repo ? "source" : "packaged", app: location, otto: ottoInfo().path, workspace: paths.workspace, version: app.getVersion(), locale, startedAt: new Date().toISOString() }),
    );
  } catch (err) {
    logDesktopEvent("instance-register-failed", { error: String(err) });
  }
}
function unregisterInstance(): void {
  try {
    unlinkSync(instanceFile);
  } catch {
    // 已经没了；崩溃留下的由读的一方清理
  }
}
app.on("will-quit", unregisterInstance);

// 拖出（规格 12 §12.2）：页面生成好文件、鼠标仍按着时请求系统拖拽。只接受已存在的普通文件。
let dragIcon: Electron.NativeImage | null = null;
ipcMain.on("files:startDrag", (e, files: unknown) => {
  if (!Array.isArray(files) || !files.length) return;
  const ok = files.filter((f): f is string => typeof f === "string" && existsSync(f) && statSync(f).isFile());
  if (ok.length !== files.length) return;
  if (process.platform === "darwin" && ok.some((path) => path.normalize("NFD") !== path)) {
    try {
      const win = BrowserWindow.fromWebContents(e.sender);
      if (!win) return;
      const bridgePath = join(app.getAppPath(), "app", "native", "mpv-bridge", "build", "Release", "mpv_bridge.node");
      const bridge = require(bridgePath) as { startFileDrag(handle: Buffer, urls: string[]): void };
      bridge.startFileDrag(win.getNativeWindowHandle(), ok.map((path) => pathToFileURL(path).href));
    } catch (err) {
      logDesktopEvent("file-drag-failed", { error: String(err) });
      dialog.showErrorBox(t("dragout.failedTitle"), t("dragout.failedDetail"));
    }
    return;
  }
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
  // Windows 上 Electron 默认在窗口顶部放一条 File / Edit / View 菜单；应用的操作都在界面里，不要它（macOS 的菜单在系统栏，保留）
  if (process.platform !== "darwin") Menu.setApplicationMenu(null);
  // 开发期 Dock 图标用所有者的 logo（发布版的 .icns/.ico 在阶段 10 生成）
  if (process.platform === "darwin" && paths.repo) {
    app.dock?.setIcon(join(paths.repo, "assets", "brand", "logo-1024.png")); // 发布版用 .app 自己的图标
    app.dock?.setBadge("Dev");
  }
  loadLocale();
  installCsp();
  autoInstallOtto();
  registerInstance();
  core.start();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  app.quit();
});
