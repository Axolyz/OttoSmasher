// Native engine adapter. Only this module knows about the addon or local descriptors.
const path = require("node:path");
const fs = require("node:fs");
const { rangeCommands, clearRangeCommands } = require("./playback-range.cjs");
const { subtitleCommand } = require("./subtitles.cjs");
const { ipcMain, BrowserWindow } = require("electron");
module.exports = function install(root, origin, trusted) {
  let addon, loadError;
  try {
    addon = require(process.env.OTTO_PLAYER_ADDON || path.join(root, ".runtime/player.node"));
  } catch (e) {
    loadError = String(e);
  }
  const owners = new Map();
  const own = (e, id) => {
    trusted(e);
    const p = owners.get(id);
    if (!p || p.sender !== e.sender) throw Error("Unknown player");
    return p;
  };
  const destroy = (id) => {
    if (owners.has(id)) {
      addon.destroy(id);
      owners.delete(id);
    }
  };
  ipcMain.handle("otto:player:create", (e, video) => {
    trusted(e);
    if (!addon)
      throw Error(
        "libmpv 未就绪，请运行 scripts/setup_player.py：" + loadError,
      );
    if ([...owners.values()].filter((p) => p.sender === e.sender).length >= 24)
      throw Error("播放器数量超出限制");
    const id = addon.create(
      BrowserWindow.fromWebContents(e.sender).getNativeWindowHandle(),
      !!video,
    );
    owners.set(id, {
      sender: e.sender,
      generation: 0,
      start: 0,
      end: null,
      loaded: false,
      external: false,
      subtitle: "",
      requestId: 0,
      range: null,
    });
    return id;
  });
  ipcMain.handle("otto:player:load", async (e, id, url) => {
    const p = own(e, id);
    const generation = ++p.generation;
    p.loading = true;
    addon.command(id, ["set", "pause", "yes"]);
    const u = new URL(url, origin);
    if (
      u.origin !== origin ||
      !u.pathname.startsWith("/api/") ||
      u.username ||
      u.password
    )
      throw Error("仅支持宿主提供的媒体");
    let spec = {
      path: u.href,
      start: 0,
      end: null,
      audio_path: null,
      aid: null,
      audio_delay: 0,
    };
    if (/^\/api\/helper\/native-player\/[a-f0-9]{24}$/.test(u.pathname)) {
      const response = await fetch(u);
      if (!response.ok) throw Error(await response.text());
      spec = await response.json();
    }
    if (!owners.has(id) || p.generation !== generation) return;
    addon.poll(id); // discard the previous source's queued notifications
    Object.assign(p, {
      ...spec,
      range: null,
      requestId: 0,
      awaitingSeek: false,
      loaded: false,
      loading: false,
      state: {},
      external: !!spec.audio_path,
    });
    addon.command(id, ["set", "pause", "yes"]);
    addon.command(id, [
      "set",
      "audio-delay",
      String(spec.audio_path ? spec.audio_delay : 0),
    ]);
    const opts = ["start=" + spec.start, "pause=yes"];
    if (spec.end != null) opts.push("end=" + spec.end);
    if (spec.audio_path) opts.push("aid=no");
    else if (spec.aid != null) opts.push("aid=" + spec.aid);
    addon.command(id, ["loadfile", spec.path, "replace", "-1", opts.join(",")]);
    return {
      start: spec.start,
      duration: spec.end == null ? null : spec.end - spec.start,
      generation,
    };
  });
  ipcMain.handle("otto:player:control", (e, id, action, value) => {
    const p = own(e, id);
    if (value && typeof value === "object" && action !== "subtitle") {
      if (value.generation !== p.generation || value.requestId <= p.requestId) return;
      if (action === "range") rangeCommands(p, value); // validate before mutating
      addon.poll(id);
      p.requestId = value.requestId;
      p.awaitingSeek = ["range", "seek"].includes(action);
      if (action !== "range") value = value.value;
    }
    const n = Number(value);
    if (action === "range") {
      p.range = { start: value.start, end: value.end, loop: !!value.loop };
      for (const command of rangeCommands(p, value)) addon.command(id, command);
      return;
    }
    if (action === "seek" || action === "clear-range") {
      p.range = null;
      for (const command of clearRangeCommands(p)) addon.command(id, command);
      if (action === "clear-range") return;
    }
    if (["seek", "volume", "rate"].includes(action) && !Number.isFinite(n))
      throw Error("Invalid player value");
    if (action === "seek")
      addon.command(id, [
        "seek",
        String(Math.max(p.start, Math.min(p.end ?? Infinity, p.start + n))),
        "absolute+exact",
      ]);
    else if (action === "play" || action === "pause")
      addon.command(id, ["set", "pause", action === "pause" ? "yes" : "no"]);
    else if (action === "volume")
      addon.command(id, [
        "set",
        "volume",
        String(Math.max(0, Math.min(100, n))),
      ]);
    else if (action === "muted")
      addon.command(id, ["set", "mute", value ? "yes" : "no"]);
    else if (action === "rate")
      addon.command(id, [
        "set",
        "speed",
        String(Math.max(0.05, Math.min(16, n))),
      ]);
    else if (action === "stop") addon.command(id, ["stop"]);
    else if (action === "subtitle") {
      const command = subtitleCommand(value);
      p.subtitle = value;
      addon.command(id, command);
    } else throw Error("Unsupported player action");
  });
  ipcMain.on("otto:player:geometry", (e, id, b) => {
    try {
      own(e, id);
      if (![b.x, b.y, b.width, b.height].every(Number.isFinite)) return;
      const z = e.sender.getZoomFactor();
      addon.geometry(
        id,
        b.x * z,
        b.y * z,
        Math.max(1, b.width * z),
        Math.max(1, b.height * z),
        !!b.visible,
      );
    } catch {}
  });
  ipcMain.handle("otto:player:destroy", (e, id) => {
    own(e, id);
    destroy(id);
  });
  const timer = setInterval(() => {
    for (const [id, p] of owners) {
      if (p.sender.isDestroyed()) {
        destroy(id);
        continue;
      }
      try {
        const changes = addon.poll(id);
        if (p.loading) continue;
        if (changes.loaded === "yes") {
          if (p.external) {
            addon.command(id, ["audio-add", p.audio_path, "select"]);
            addon.command(id, ["seek", String(p.start), "absolute+exact"]);
            p.external = false;
          }
          p.loaded = true;
          addon.command(id, subtitleCommand(p.subtitle || ""));
        }
        if (changes.restarted === "yes") p.awaitingSeek = false;
        if (p.awaitingSeek) {
          delete changes["time-pos"];
          delete changes["eof-reached"];
        }
        if (p.range && !p.range.loop && changes["eof-reached"] === "yes") {
          // The engine has already stopped. This only fixes the displayed clock.
          changes["time-pos"] = String(p.start + p.range.end);
          changes.pause = "yes";
        }
        Object.assign(p.state || (p.state = {}), changes);
        // Metadata may arrive one poll before FILE_LOADED. Deliver it with readiness.
        if (changes.loaded === "yes") Object.assign(changes, p.state);
        if ((p.loaded || changes.error) && Object.keys(changes).length)
          p.sender.send("otto:player:state", {
            id,
            generation: p.generation,
            requestId: p.requestId,
            changes,
            start: p.start,
            duration: p.end == null ? null : p.end - p.start,
          });
      } catch (e) {
        p.sender.send("otto:player:state", { id, error: String(e) });
      }
    }
  }, 50);
  timer.unref();
  if (process.env.OTTO_PLAYER_QA === "1") {
    const debug = setInterval(
      () =>
        fs.writeFileSync(
          path.join(root, ".runtime/player-states.json"),
          JSON.stringify(
            [...owners].map(([id, p]) => ({
              id,
              path: p.path,
              start: p.start,
              end: p.end,
              state: p.state,
            })),
            null,
            2,
          ),
        ),
      1000,
    );
    debug.unref();
  }
  return {
    attach(window) {
      window.webContents.on(
        "did-start-navigation",
        (_e, _url, inPlace, main) => {
          if (main && !inPlace)
            for (const [id, p] of owners)
              if (p.sender === window.webContents) destroy(id);
        },
      );
      window.on("closed", () => {
        for (const [id, p] of owners) if (p.sender.isDestroyed()) destroy(id);
      });
    },
  };
};
