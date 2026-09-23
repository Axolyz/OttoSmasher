const { contextBridge, ipcRenderer, webUtils } = require("electron");
contextBridge.exposeInMainWorld("ottoDesktop", {
  player: {
    create: (video) => ipcRenderer.invoke("otto:player:create", video),
    load: (id, url) => ipcRenderer.invoke("otto:player:load", id, url),
    control: (id, action, value) =>
      ipcRenderer.invoke("otto:player:control", id, action, value),
    geometry: (id, bounds) =>
      ipcRenderer.send("otto:player:geometry", id, bounds),
    destroy: (id) => ipcRenderer.invoke("otto:player:destroy", id),
    subscribe: (cb) => {
      const listener = (_e, state) => cb(state);
      ipcRenderer.on("otto:player:state", listener);
      return () => ipcRenderer.removeListener("otto:player:state", listener);
    },
  },
  onNavigate: (callback) => {
    const listener = (_e, value) => callback(value);
    ipcRenderer.on("otto:navigate", listener);
    return () => ipcRenderer.removeListener("otto:navigate", listener);
  },
  newWindow: (view, material) =>
    ipcRenderer.invoke("otto:new-window", view, material),
  open: (view, material) => ipcRenderer.invoke("otto:open", view, material),
  filePath: (file) => webUtils.getPathForFile(file),
  pickFile: (kind) => ipcRenderer.invoke("otto:pick-file", kind),
  pick: () => ipcRenderer.invoke("otto:pick"),
  reveal: (path) => ipcRenderer.invoke("otto:path", path),
  copy: (path) => ipcRenderer.invoke("otto:clipboard", path),
  drag: (path) => ipcRenderer.send("otto:drag", path),
});

ipcRenderer.on("otto:error", (_event, error) =>
  window.dispatchEvent(new CustomEvent("otto:native-error", { detail: error })),
);
