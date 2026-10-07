// Electron 主进程：窗口、Core 进程管理、IPC 转发、退出流程（ARCHITECTURE §2）。
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { BrowserWindow, app, dialog, ipcMain, session } from "electron";
import zhCN from "../renderer/i18n/locales/zh-CN.json";
import { PSEUDO, createT } from "../shared/i18n";
import type { CoreStatus } from "../shared/protocol";
import { CoreClient } from "./core-client";
import { resolvePaths } from "./paths";

const paths = resolvePaths();
const locale = process.env.OTTO_LOCALE ?? "zh-CN";
const t = createT(zhCN as Record<string, string>, { pseudo: locale === PSEUDO });
const devServer = process.env.OTTO_DEV_SERVER; // 开发期 Vite 地址
const isDev = process.env.OTTO_DEV === "1";

const core = new CoreClient({
  python: paths.python,
  workspace: paths.workspace,
  supportDir: paths.supportDir,
  dev: isDev,
  cwd: paths.repo ?? undefined,
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

ipcMain.handle("core:request", (_e, method: string, params: Record<string, unknown>) => core.request(method, params ?? {}));
ipcMain.handle("core:status", () => core.status);
ipcMain.handle("core:restart", async () => {
  if (core.status.state === "ready") return;
  core.start();
});
core.on("event", (ev) => broadcast("core:event", ev));
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
  if (process.platform === "darwin" && paths.repo) app.dock?.setIcon(join(paths.repo, "assets", "brand", "logo-1024.png"));
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
