// 白名单 API（ARCHITECTURE §2.5）：渲染进程只能经这里调用 Core 的公开命令，不能直接碰文件或进程。
import { contextBridge, ipcRenderer } from "electron";
import type { CoreEvent, CoreStatus, OttoApi } from "../shared/protocol";

const localeArg = process.argv.find((a) => a.startsWith("--otto-locale="));

const api: OttoApi = {
  core: {
    request: (method, params) => ipcRenderer.invoke("core:request", method, params ?? {}),
    onEvent(cb) {
      const h = (_e: unknown, ev: CoreEvent) => cb(ev);
      ipcRenderer.on("core:event", h);
      return () => ipcRenderer.removeListener("core:event", h);
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
  },
};

contextBridge.exposeInMainWorld("otto", api);
