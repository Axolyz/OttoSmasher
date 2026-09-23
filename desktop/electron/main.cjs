const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  shell,
  nativeImage,
} = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
if (process.env.OTTO_APP_USER_DATA) app.setPath("userData", path.resolve(process.env.OTTO_APP_USER_DATA));
let root = path.resolve(__dirname, "../..");
let codeRoot = root;
let packagedRuntime;
let ownedService;
let bootWindow;
const appIcon = path.join(app.isPackaged ? path.join(process.resourcesPath, "software") : root, "ottosmasher.png");
app.setAppUserModelId("org.ottosmasher.desktop");
const port = Number(process.env.OTTO_DESKTOP_PORT || (app.isPackaged ? 18766 : 18765));
const origin = `http://127.0.0.1:${port}`;
const views = new Set(["search", "library", "cut", "sources", "workflows"]);
let starting;
async function service() {
  const alive = async () => {
    try {
      const r = await fetch(origin + "/api/helper/info");
      if (!r.ok) return false;
      const info = await r.json();
      return info.root === root && (!packagedRuntime || info.build_id === packagedRuntime.buildId);
    } catch {
      return false;
    }
  };
  if (await alive()) return;
  if (!starting)
    starting = (async () => {
      fs.mkdirSync(path.join(root, "data/logs"), { recursive: true });
      const log = fs.openSync(
        path.join(root, "data/logs/desktop-service.log"),
        "a",
      );
      const py =
        packagedRuntime?.python || process.env.OTTO_PYTHON ||
        path.join(root, process.platform === "win32" ? ".runtime/envs/core/python.exe" : ".runtime/envs/core/bin/python");
      const child = spawn(
        py,
        ["-m", "ottosmasher.cli", "serve", "--port", String(port)],
        {
          cwd: root,
          env: {
            ...process.env,
            OTTO_ROOT: root,
            PYTHONPATH: path.join(codeRoot, "src"),
            ...(packagedRuntime?.env || {}),
          },
          detached: true,
          stdio: ["ignore", log, log],
        },
      );
      ownedService = child;
      child.on("error", (e) => console.error(e));
      child.unref();
      fs.closeSync(log);
      for (let i = 0; i < 120; i++) {
        if (await alive()) return;
        await new Promise((r) => setTimeout(r, 250));
      }
      throw Error("本地服务没有启动，请查看 data/logs/desktop-service.log");
    })();
  return starting;
}
async function open(view = "library", material = "", separate = false) {
  if (view === "search") view = "library";
  const existing = BrowserWindow.getAllWindows().find((w) => !w.isDestroyed() && w !== bootWindow);
  if (existing && !separate) {
    existing.show();
    existing.focus();
    if (material)
      existing.webContents.send("otto:navigate", { view, material });
    return existing;
  }
  if (!views.has(view)) throw Error("Unknown window");
  await service();
  const w = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 850,
    minHeight: 600,
    title: `OttoSmasher · ${view}`,
    icon: appIcon,
    backgroundColor: "#121719",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  player.attach(w);
  w.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  w.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(origin + "/")) e.preventDefault();
  });
  await w.webContents.session.clearCache();
  await w.loadURL(
    `${origin}/helper/?view=${view}&material=${encodeURIComponent(material)}`,
  );
  if (process.env.OTTO_DESKTOP_QA === "1")
    w.webContents.openDevTools({ mode: "detach" });
  return w;
}
function trusted(e) {
  if (!e.senderFrame.url.startsWith(origin + "/helper/"))
    throw Error("Untrusted window");
}
let player;
if (!app.isPackaged) player = require("./player.cjs")(root, origin, trusted);
ipcMain.handle("otto:open", async (e, v, m) => {
  trusted(e);
  const w = BrowserWindow.fromWebContents(e.sender);
  w.webContents.send("otto:navigate", { view: v, material: m });
});
ipcMain.handle("otto:new-window", async (e, v, m) => {
  trusted(e);
  return void (await open(v, m, true));
});
ipcMain.handle("otto:pick", async (e) => {
  trusted(e);
  const r = await dialog.showOpenDialog(
    BrowserWindow.fromWebContents(e.sender),
    {
      properties: ["openFile", "multiSelections"],
      filters: [
        {
          name: "媒体",
          extensions: [
            "mkv",
            "mp4",
            "mov",
            "wav",
            "flac",
            "mp3",
            "m4a",
            "ogg",
            "webm",
          ],
        },
      ],
    },
  );
  return r.filePaths;
});
ipcMain.handle("otto:pick-file", async (event, kind) => {
  trusted(event);
  const r = await dialog.showOpenDialog({
    properties:
      ["openFile"],
    filters:
      kind === "subtitle"
        ? [{ name: "字幕", extensions: ["srt", "ass"] }]
        : [{ name: "文件", extensions: ["*"] }],
  });
  return r.canceled ? "" : r.filePaths[0];
});
ipcMain.handle("otto:path", async (e, p) => {
  trusted(e);
  if (!fs.existsSync(p)) throw Error("文件不存在");
  shell.showItemInFolder(p);
});
ipcMain.handle("otto:clipboard", async (e, p) => {
  trusted(e);
  require("electron").clipboard.writeText(p);
});
ipcMain.on("otto:drag", (e, p) => {
  try {
    trusted(e);
    const file = fs.realpathSync(p);
    if (!fs.statSync(file).isFile()) return;
    const icon = nativeImage
      .createFromDataURL(
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
      )
      .resize({ width: 32, height: 32 });
    e.sender.startDrag({ file, icon });
  } catch (error) {
    e.sender.send("otto:error", String(error));
  }
});
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", (_e, argv) => {
    const arg = argv.find((a) => a.startsWith("--view="));
    open(arg?.split("=")[1] || "library").catch(console.error);
  });
  app
    .whenReady()
    .then(async () => {
      if (app.isPackaged) {
        if (!process.argv.includes("--packaged-smoke")) {
          bootWindow = new BrowserWindow({width: 460, height: 220, resizable: false,
            title: "OttoSmasher", backgroundColor: "#171b21",
            webPreferences: {sandbox: true, contextIsolation: true, nodeIntegration: false}});
          await bootWindow.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(
            '<body style="background:#171b21;color:#e6e9ef;font:16px system-ui;padding:28px"><h2>OttoSmasher</h2><p>正在准备本地运行库…</p><p style="font-size:13px;color:#aab4c4">首次启动需要解包和校验；完成后将自动进入工作站。</p></body>'));
        }
        packagedRuntime = await require("./distribution.cjs").prepare(app);
        root = packagedRuntime.root;
        codeRoot = packagedRuntime.codeRoot;
        Object.assign(process.env, packagedRuntime.env);
        player = require("./player.cjs")(root, origin, trusted);
      }
      if (process.argv.includes("--packaged-smoke")) {
        await service();
        const result = await require("./packaged-smoke.cjs")(packagedRuntime, origin);
        fs.writeFileSync(process.env.OTTO_SMOKE_REPORT, JSON.stringify(result, null, 2));
        app.quit();
        return;
      }
      if (process.platform === "darwin") app.dock?.setIcon(nativeImage.createFromPath(appIcon));
      const window = await open(
        process.argv.find((a) => a.startsWith("--view="))?.split("=")[1] ||
          "library",
      );
      bootWindow?.destroy();
      return window;
    })
    .catch((e) => {
      if (process.argv.includes("--packaged-smoke")) { console.error(e); stopOwnedService(); app.exit(1); }
      else dialog.showErrorBox("启动失败", String(e));
    });
  function stopOwnedService() {
    if (app.isPackaged && ownedService?.pid) {
      if (process.platform === "win32") spawn("taskkill", ["/PID", String(ownedService.pid), "/T", "/F"], {windowsHide: true});
      else { try { process.kill(-ownedService.pid, "SIGTERM"); } catch {} }
    }
  }
  app.on("before-quit", stopOwnedService);
  app.on("window-all-closed", () => app.quit());
}
