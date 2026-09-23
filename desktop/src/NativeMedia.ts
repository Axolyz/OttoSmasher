/** HTML media-shaped clock adapter. Chromium never loads desktop playback media. */
export type PlayerBridge = {
  create(video: boolean): Promise<number>;
  load(
    id: number,
    url: string,
  ): Promise<
    { generation: number; start: number; duration: number | null } | undefined
  >;
  control(id: number, action: string, value?: unknown): Promise<void>;
  geometry(
    id: number,
    bounds: {
      x: number;
      y: number;
      width: number;
      height: number;
      visible: boolean;
    },
  ): void;
  destroy(id: number): Promise<void>;
  subscribe(cb: (state: any) => void): () => void;
};
type NativeController = {
  load(url: string): void;
  subtitle(text: string): void;
  playRange(start: number, end: number, loop: boolean): Promise<void>;
  clearRange(): void;
  geometry(bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    visible: boolean;
  }): boolean;
  destroy(): void;
};
type NativeElement = HTMLMediaElement & { ottoNative?: NativeController };
export function setNativeSubtitle(element: HTMLMediaElement, text: string) {
  (element as NativeElement).ottoNative?.subtitle(text);
}
export function attachNativeMedia(
  element: HTMLMediaElement,
  video = false,
): NativeController | undefined {
  const existing = (element as NativeElement).ottoNative;
  if (existing) return existing;
  const bridge = window.ottoDesktop?.player;
  if (!bridge) return undefined;
  let id = 0,
    disposed = false,
    source = "",
    loadToken = 0,
    generation = 0;
  let time = 0,
    duration = NaN,
    paused = true,
    ended = false,
    ready = 0;
  let volume = 1,
    muted = false,
    rate = 1,
    error: MediaError | null = null,
    seeking = false;
  let requestId = 0;
  let activeRange: { start: number; end: number; loop: boolean } | null = null;
  let pendingRange: (() => Promise<void>) | null = null;
  let pendingSeek: number | null = null,
    wantsPlay = false;
  let fixedDuration: number | null = null,
    origin = 0;
  let clockAt = performance.now(),
    buffering = false;
  const currentClock = () => {
    const advance =
      ready && !paused && !seeking && !buffering
        ? Math.min(0.25, Math.max(0, (performance.now() - clockAt) / 1000)) *
          rate
        : 0;
    return Math.min(
      activeRange?.end ?? (Number.isFinite(duration) ? duration : Infinity),
      time + advance,
    );
  };
  const emit = (name: string) => {
    if (!disposed) element.dispatchEvent(new Event(name));
  };
  const fail = (e: unknown) => {
    if (disposed) return;
    error = { code: 4, message: String(e) } as MediaError;
    wantsPlay = false;
    paused = true;
    emit("error");
    emit("pause");
    window.dispatchEvent(
      new CustomEvent("otto:native-error", { detail: String(e) }),
    );
  };
  const created = bridge.create(video).then((value) => {
    id = value;
    if (disposed) void bridge.destroy(id).catch(() => {});
    return value;
  });
  void created.catch(fail);
  const command = async (action: string, value?: unknown) => {
    const playerId = await created;
    if (!disposed) await bridge.control(playerId, action, value);
  };
  const send = (action: string, value?: unknown) => {
    void command(action, value).catch(fail);
  };
  const unsubscribe = bridge.subscribe((state) => {
    if (
      disposed ||
      state.id !== id ||
      (generation && state.generation !== generation) ||
      (state.requestId != null && state.requestId < requestId)
    )
      return;
    const c = state.changes || {};
    if (state.error || c.error) {
      fail(state.error || c.error);
      return;
    }
    if (c["hwdec-current"]) element.dataset.decoder = c["hwdec-current"];
    if (c["video-codec"]) element.dataset.codec = c["video-codec"];
    origin = state.start ?? origin;
    fixedDuration = state.duration ?? fixedDuration;
    if (c.duration != null || fixedDuration != null) {
      const d = fixedDuration ?? Number(c.duration);
      if (Number.isFinite(d) && d !== duration) {
        duration = d;
        emit("durationchange");
      }
    }
    if (c.loaded === "yes") {
      ready = 4;
      error = null;
      ended = false;
      send("muted", muted);
      send("volume", volume * 100);
      send("rate", rate);
      if (pendingSeek != null) {
        send("seek", pendingSeek);
        pendingSeek = null;
      }
      emit("loadedmetadata");
      emit("loadeddata");
      emit("canplay");
      if (pendingRange) {
        const run = pendingRange;
        pendingRange = null;
        void run().catch(fail);
      } else if (wantsPlay) send("play");
    }
    if (c["time-pos"] != null && ready) {
      time = Math.max(0, Number(c["time-pos"]) - origin);
      clockAt = performance.now();
      if (Number.isFinite(duration)) time = Math.min(time, duration);
      emit("timeupdate");
      if (seeking) {
        seeking = false;
        emit("seeked");
      }
    }
    if (c["paused-for-cache"] != null) {
      time = currentClock();
      clockAt = performance.now();
      buffering = c["paused-for-cache"] === "yes";
    }
    if (c.pause != null) {
      const next = c.pause === "yes";
      if (paused !== next) {
        time = currentClock();
        clockAt = performance.now();
        paused = next;
        emit(paused ? "pause" : "play");
        if (!paused) emit("playing");
      }
    }
    if (c["eof-reached"] === "yes" && ready && !ended) {
      if (activeRange && !activeRange.loop) {
        time = activeRange.end;
        clockAt = performance.now();
        emit("timeupdate");
      }
      ended = true;
      paused = true;
      wantsPlay = false;
      emit("pause");
      emit("ended");
    }
  });
  const load = (url: string) => {
    const absolute = url ? new URL(url, location.href).href : "";
    if (absolute === source && !error) return;
    source = absolute;
    const token = ++loadToken;
    activeRange = null;
    pendingRange = null;
    requestId = 0;
    ready = 0;
    time = 0;
    duration = NaN;
    fixedDuration = null;
    origin = 0;
    ended = false;
    paused = true;
    error = null;
    pendingSeek = null;
    wantsPlay = false;
    emit("emptied");
    emit("loadstart");
    void created
      .then(async (playerId) => {
        if (disposed || token !== loadToken) return;
        if (!source) {
          await bridge.control(playerId, "stop");
          return;
        }
        const info = await bridge.load(playerId, source);
        if (disposed || token !== loadToken || !info) return;
        generation = info.generation;
        origin = info.start;
        fixedDuration = info.duration;
        if (info.duration != null) duration = info.duration;
      })
      .catch(fail);
  };
  const descriptors: PropertyDescriptorMap = {
    src: { get: () => source, set: load },
    currentSrc: { get: () => source },
    currentTime: {
      get: currentClock,
      set: (v: number) => {
        if (!Number.isFinite(v)) return;
        activeRange = null;
        pendingRange = null;
        time = Math.max(
          0,
          Number.isFinite(duration) ? Math.min(v, duration) : v,
        );
        clockAt = performance.now();
        ended = false;
        seeking = true;
        emit("seeking");
        emit("timeupdate");
        if (ready)
          send("seek", { value: time, generation, requestId: ++requestId });
        else pendingSeek = time;
      },
    },
    duration: { get: () => duration },
    paused: { get: () => paused },
    ended: { get: () => ended },
    readyState: { get: () => ready },
    seeking: { get: () => seeking },
    error: { get: () => error },
    volume: {
      get: () => volume,
      set: (v: number) => {
        volume = Math.max(0, Math.min(1, v));
        send("volume", volume * 100);
        emit("volumechange");
      },
    },
    muted: {
      get: () => muted,
      set: (v: boolean) => {
        muted = !!v;
        send("muted", muted);
        emit("volumechange");
      },
    },
    playbackRate: {
      get: () => rate,
      set: (v: number) => {
        rate = v;
        send("rate", rate);
        emit("ratechange");
      },
    },
    play: {
      value: async () => {
        wantsPlay = true;
        if (error) throw Error(error.message);
        if (ready) {
          if (ended) {
            element.currentTime = 0;
            ended = false;
          }
          await command("play");
        }
      },
    },
    pause: {
      value: () => {
        wantsPlay = false;
        send("pause");
      },
    },
    load: {
      value: () => {
        const url = source;
        source = "";
        load(url);
      },
    },
    canPlayType: { value: () => "" }, // Keep WaveSurfer's original URL; mpv cannot open renderer blob: URLs.
  };
  for (const value of Object.values(descriptors)) value.configurable = true;
  Object.defineProperties(element, descriptors);
  element.dataset.engine = "libmpv";
  const pauseAll = () => element.pause();
  window.addEventListener("otto:pause-media", pauseAll);
  const controller = {
    playRange: async (start: number, end: number, loop: boolean) => {
      if (
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        start < 0 ||
        end <= start
      )
        throw Error("无效播放范围");
      activeRange = { start, end, loop };
      const run = async () => {
        time = start;
        clockAt = performance.now();
        ended = false;
        seeking = true;
        wantsPlay = true;
        emit("seeking");
        emit("timeupdate");
        await command("range", {
          start,
          end,
          loop,
          generation,
          requestId: ++requestId,
        });
      };
      if (ready) await run();
      else pendingRange = run;
    },
    clearRange: () => {
      activeRange = null;
      pendingRange = null;
      send("clear-range", { generation, requestId: ++requestId });
    },
    subtitle: (text: string) => send("subtitle", text),
    load,
    geometry: (bounds: {
      x: number;
      y: number;
      width: number;
      height: number;
      visible: boolean;
    }) => {
      if (id && !disposed) {
        bridge.geometry(id, bounds);
        return true;
      }
      return false;
    },
    destroy: () => {
      if (disposed) return;
      disposed = true;
      ++loadToken;
      unsubscribe();
      window.removeEventListener("otto:pause-media", pauseAll);
      if (id) void bridge.destroy(id).catch(() => {});
      for (const key of Object.keys(descriptors)) delete (element as any)[key];
      delete (element as NativeElement).ottoNative;
    },
  };
  (element as NativeElement).ottoNative = controller;
  return controller;
}
