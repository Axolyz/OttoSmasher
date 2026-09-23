import { VideoPlayer } from "./NativePlayer";
import Hls from "hls.js";
import { UButton } from "./Ui";
import {
  Button,
  Dropdown,
  Modal,
  Select,
  Input,
  InputNumber,
  Space,
  Form,
  Alert,
  ConfigProvider,
} from "antd";
import { MoreOutlined } from "@ant-design/icons";
import { Help, uiDefault } from "./Ui";
import { UiRoot } from "./Ui";
import Workspace, { request } from "./Workspace";
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import WaveSurfer from "wavesurfer.js";
import { audioTimeline, isAnnotation } from "./AudioTimeline";
import Regions from "wavesurfer.js/dist/plugins/regions.esm.js";
import "./style.css";

import type { PlayerBridge } from "./NativeMedia";

declare global {
  interface Window {
    ottoDesktop?: {
      player?: PlayerBridge;
      newWindow?: (view: string, material?: string) => Promise<void>;
      open: (v: string, m?: string) => Promise<void>;
      onNavigate?: (
        cb: (value: { view: string; material?: string }) => void,
      ) => () => void;
      pick: () => Promise<string[]>;
      pickFile?: (kind: string) => Promise<string>;
      filePath: (f: File) => string;
      reveal: (p: string) => Promise<void>;
      copy: (p: string) => Promise<void>;
      drag: (p: string) => void;
    };
  }
}
type Material = {
  id: string;
  title: string;
  notes: string;
  rating: number;
  path: string;
  source_id: string;
  source_title: string;
  source_duration: number;
  source_metadata: string;
  audio_stream: number;
  start: number;
  end: number;
  cue_id: string | null;
  scope_id: string | null;
  analysis_kind: string | null;
  rhythm_available: boolean;
  available: boolean;
  collections: string[];
  tags: { tag: string; origin: string }[];
  versions: Version[];
  preferred_version: string | null;
};
type Version = {
  id: string;
  path: string;
  operation: string;
  available: boolean;
};
type Info = {
  total: number;
  collections: { id: string; name: string }[];
  sources: { id: string; title: string }[];
  tags: string[];
};
const params = new URLSearchParams(location.search),
  view = params.get("view") || "library";
async function api(url: string, body?: unknown) {
  const r = await fetch(
    "/api/helper" + url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const d = await r.json();
  if (!r.ok)
    throw Error(
      typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail),
    );
  return d;
}
const sec = (v: number) =>
  `${Math.floor(v / 60)}:${(v % 60).toFixed(3).padStart(6, "0")}`;
const title = (p: string) => p.split("/").at(-1) || p;
export function ask(label: string, value = ""): Promise<string | null> {
  return new Promise((resolve) => {
    let next = value;
    const dialog = Modal.confirm({
      title: label,
      icon: null,
      content: (
        <Input
          autoFocus
          defaultValue={value}
          onChange={(e) => {
            next = e.target.value;
          }}
          onPressEnter={() => {
            dialog.destroy();
            resolve(next);
          }}
        />
      ),
      onOk: () => resolve(next),
      onCancel: () => resolve(null),
      okText: "确定",
      cancelText: "取消",
    });
  });
}

export function Cutter({
  material: r,
  onSave,
  onMessage,
  onFile,
  onImport,
}: {
  material: Material | null;
  onSave: (id: string) => void;
  onMessage: (e: unknown) => void;
  onFile: (p: string) => void;
  onImport: () => void;
}) {
  const [action, setAction] = useState("");
  const [selectionTitle, setSelectionTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const element = useRef<HTMLVideoElement>(null),
    container = useRef<HTMLDivElement>(null),
    ws = useRef<WaveSurfer | null>(null);
  const [start, setStart] = useState(0),
    [end, setEnd] = useState(1),
    [position, setPosition] = useState(0),
    [stream, setStream] = useState(0),
    [context, setContext] = useState<any[]>([]);
  const [url, setUrl] = useState(""),
    [origin, setOrigin] = useState(0),
    [busy, setBusy] = useState(false),
    [previewRange, setPreviewRange] = useState([0, 1]);
  const [audioRole, setAudioRole] = useState("vocals"),
    [referencePeaks, setReferencePeaks] = useState<any>(null);
  const [waveformUrl, setWaveformUrl] = useState("");
  const [effectTracks, setEffectTracks] = useState<any[]>([]);
  const subtitleList = useRef<HTMLDivElement>(null);
  const subtitleFollowPause = useRef(0);
  const [separationMode, setSeparationMode] = useState("vocals");
  const [separationRange, setSeparationRange] = useState("whole");
  const [cinematicRoute, setCinematicRoute] = useState("bandit-v2");
  const [cinematicModels, setCinematicModels] = useState<any[]>([]);
  useEffect(() => {
    if (action !== "separate") return;
    request("/api/sound/info")
      .then((x) =>
        setCinematicModels(
          x.models.filter((m: any) => ["bandit-v2"].includes(m.id)),
        ),
      )
      .catch(onMessage);
  }, [action]);
  const [vocalModel, setVocalModel] = useState(() =>
    uiDefault("vocal_model", "becruily_deux"),
  );
  useEffect(() => {
    if (action === "separate")
      setVocalModel(uiDefault("vocal_model", "becruily_deux"));
  }, [action]);
  const [marks, setMarks] = useState<any[]>([]);
  const annotationsRef = useRef<any[]>([]);
  annotationsRef.current = [
    ...context.map((c) => ({
      id: "subtitle-" + c.id,
      start: Math.max(0, c.start - origin),
      end: c.end - origin,
      label: "字幕 · " + c.original.slice(0, 24),
    })),
    ...marks
      .filter((m) => m.source_id === r?.source_id && m.end > origin)
      .map((m) => ({
        id: "opening-" + m.id,
        start: Math.max(0, m.start - origin),
        end: m.end - origin,
        label: m.kind.toUpperCase(),
        color: "#d9995620",
      })),
  ];
  useEffect(() => {
    (ws.current as any)?.ottoSetAnnotations(annotationsRef.current);
  }, [context, marks, origin]);
  useEffect(() => {
    let dead = false;
    request("/api/library-tools/openings/state")
      .then((x) => {
        if (!dead) setMarks(x.regions || []);
      })
      .catch(onMessage);
    return () => {
      dead = true;
    };
  }, [r?.source_id]);
  const [selectionNature, setSelectionNature] = useState("speech");
  useEffect(() => setSelectionTitle(""), [r?.id]);
  useEffect(() => {
    if (!r) return;
    let live = true;
    const refresh = () =>
      request(`/api/sound/tracks?source_id=${r.source_id}`)
        .then((x) => {
          if (live) setEffectTracks(x);
        })
        .catch(onMessage);
    void refresh();
    window.addEventListener("otto:jobs-updated", refresh);
    const open = () => setAction("separate");
    window.addEventListener("otto:source-separate", open);
    return () => {
      live = false;
      window.removeEventListener("otto:jobs-updated", refresh);
      window.removeEventListener("otto:source-separate", open);
    };
  }, [r?.id]);
  const updating = useRef(false),
    generation = useRef(0),
    requestedProxy = useRef(false),
    loadVersion = useRef(0),
    resume = useRef({ time: 0, playing: false });
  const meta = r ? JSON.parse(r.source_metadata) : { streams: [] },
    video = meta.streams.find((s: any) => s.codec_type === "video");
  const fps = video?.avg_frame_rate?.split("/").map(Number),
    step = fps && fps[0] > 0 ? fps[1] / fps[0] : 1 / 25;
  useEffect(() => {
    if (!r) return;
    const load = ++loadVersion.current;
    resume.current = { time: r.start, playing: false };
    setStart(r.start);
    setEnd(Math.min(r.end, r.start + 60));
    setPosition(r.start);
    setStream(r.audio_stream);
    setOrigin(0);
    setUrl("");
    setAudioRole(r.cue_id ? "vocals" : "raw");
    setReferencePeaks(null);
    setWaveformUrl("");
    setContext([]);
    requestedProxy.current = false;
    setPreviewRange([r.start, r.end]);
    setBusy(true);
    let stale = false;
    request(`/api/samples/${r.id}/reference`, {
      start: r.start,
      end: r.end,
      role: r.cue_id ? "vocals" : "raw",
      streaming: true,
      audio_stream: r.audio_stream,
    })
      .then((p) => {
        if (stale || load !== loadVersion.current) return;
        setReferencePeaks(p.waveform);
        setWaveformUrl(p.waveform_url || "");
        setOrigin(p.origin);
        setUrl(p.url);
      })
      .catch((e) => {
        if (!stale && load === loadVersion.current) onMessage(e);
      })
      .finally(() => {
        if (!stale && load === loadVersion.current) setBusy(false);
      });
    return () => {
      stale = true;
    };
  }, [r?.id]);
  useEffect(() => {
    if (!r || !element.current || !container.current || !url) return;
    const n = ++generation.current;
    ws.current?.destroy();
    ws.current = null;
    (referencePeaks
      ? Promise.resolve(referencePeaks)
      : waveformUrl
        ? request(waveformUrl)
        : api(
            `/materials/${r.id}/waveform?start=${previewRange[0]}&end=${previewRange[1]}&audio_stream=${stream}`,
          )
    )
      .then(async (peaks) => {
        if (n !== generation.current || !element.current || !container.current)
          return;
        // Peaks span the preview window. A proxy uses its local clock; direct media
        // requires full-source peaks so the media element and waveform agree.
        if (
          !referencePeaks &&
          !waveformUrl &&
          origin === 0 &&
          (previewRange[0] !== 0 || previewRange[1] !== r.source_duration)
        )
          peaks = await api(
            `/materials/${r.id}/waveform?start=0&end=${r.source_duration}&bins=32000&audio_stream=${stream}`,
          );
        if (n !== generation.current) return;
        const w = audioTimeline({
          spectrumLabel: "查看音轨频谱",
          origin,
          visualizationKey: peaks.visualization_key,
          onSelectionChange: ([a, b]: number[]) => {
            if (!updating.current) {
              setStart(a + origin);
              setEnd(b + origin);
            }
          },
          container: container.current!,
          media: element.current!,
          peaks: peaks.peaks,
          peakLevels: peaks.peak_levels,
          duration: peaks.duration,
          waveColor: "#547c72",
          progressColor: "#a3edc2",
          height: 145,
          minPxPerSec: 40,
        });
        const regions = (w as any).ottoRegions as Regions;
        ws.current = w;
        w.once("ready", () =>
          regions.addRegion({
            id: "selection",
            start: Math.max(0, start - origin),
            end: end - origin,
            color: "#a3edc22b",
            drag: true,
            resize: true,
          }),
        );
        (w as any).ottoRegions = regions;
        w.once("ready", () => {
          // Streaming playback can advance while whole-source peaks are being computed.
          // Attaching the waveform must not seek the video back to its initial position.
          if (!waveformUrl)
            w.setTime(
              Math.max(
                0,
                Math.min(w.getDuration(), resume.current.time - origin),
              ),
            );
          (w as any).ottoSetAnnotations(annotationsRef.current);
        });
      })
      .catch(onMessage);
    return () => {
      generation.current++;
      ws.current?.destroy();
      ws.current = null;
    };
  }, [r?.id, url, origin, stream]);
  useEffect(() => {
    const reg = (ws.current as any)?.ottoRegions
      ?.getRegions()
      .find((x: any) => !isAnnotation(x.id));
    if (reg) {
      updating.current = true;
      reg.setOptions({ start: Math.max(0, start - origin), end: end - origin });
      updating.current = false;
    }
  }, [start, end, origin]);
  useEffect(() => {
    let dead = false;
    if (r)
      api(
        `/materials/${r.id}/context?start=${previewRange[0]}&end=${previewRange[1]}`,
      )
        .then((x) => {
          if (!dead) setContext(x);
        })
        .catch(onMessage);
    return () => {
      dead = true;
    };
  }, [r?.id, previewRange.join(",")]);
  const activeSubtitle = context.find(
    (c) => c.start <= position && position < c.end,
  )?.id;
  useEffect(() => {
    if (!activeSubtitle || Date.now() < subtitleFollowPause.current) return;
    const box = subtitleList.current;
    const item = box?.querySelector<HTMLElement>(
      `[data-cue-id="${activeSubtitle}"]`,
    );
    if (box && item) {
      const b = box.getBoundingClientRect(),
        r = item.getBoundingClientRect();
      if (r.top < b.top + 30 || r.bottom > b.bottom - 20)
        box.scrollTo({
          top:
            box.scrollTop + r.top - b.top - box.clientHeight / 2 + r.height / 2,
          behavior: "smooth",
        });
    }
  }, [activeSubtitle, position]);
  const seek = (time: number) => {
    if (element.current) {
      element.current.currentTime = Math.max(0, time - origin);
      setPosition(time);
    }
  };
  useEffect(() => {
    const el = element.current;
    if (!el || !url.endsWith(".m3u8")) return;
    if (Hls.isSupported()) {
      const hls = new Hls({
        maxBufferLength: 16,
        maxMaxBufferLength: 24,
        backBufferLength: 8,
        startPosition: Math.max(0, resume.current.time - origin),
      });
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) onMessage("播放分片失败：" + data.details);
      });
      hls.loadSource(url);
      hls.attachMedia(el);
      return () => hls.destroy();
    }
    if (el.canPlayType("application/vnd.apple.mpegurl")) el.src = url;
    else onMessage("当前播放器不支持分片播放");
  }, [url]);
  const makeProxy = async (
    a = previewRange[0],
    b = previewRange[1],
    track = stream,
    role = audioRole,
  ) => {
    if (!r) return;
    const load = ++loadVersion.current;
    resume.current = {
      time: (element.current?.currentTime || 0) + origin,
      playing: !!element.current && !element.current.paused,
    };
    if (resume.current.time < a || resume.current.time >= b)
      resume.current.time = a;
    element.current?.pause();
    setBusy(true);
    onMessage("正在准备播放；视频按需加载，波形在后台生成…");
    try {
      const p = await request(`/api/samples/${r.id}/reference`, {
        start: a,
        end: b,
        audio_stream: track,
        role,
        streaming: true,
      });
      if (load !== loadVersion.current) return;
      setReferencePeaks(p.waveform);
      setWaveformUrl(p.waveform_url || "");
      setPreviewRange([a, b]);
      setStream(track);
      setOrigin(p.origin);
      setUrl(p.url);
      setAudioRole(role);
      onMessage("播放已就绪；切点继续使用原片时间");
    } catch (e) {
      if (load === loadVersion.current) onMessage(e);
    } finally {
      if (load === loadVersion.current) setBusy(false);
    }
  };
  const saveSelection = async () => {
    if (!r) return;
    return request(`/api/samples/${r.id}/source-selection`, {
      start,
      end,
      role: audioRole,
      audio_stream: stream,
      folder_id: "",
      nature: selectionNature,
      title: selectionTitle.trim() || r.title,
    });
  };
  const save = async () => {
    const p = await saveSelection();
    if (p) {
      onSave(p.id);
      onMessage("已保存派生采样和来源");
    }
  };
  const exportFile = async (video: boolean) => {
    if (!r) return;
    setBusy(true);
    try {
      const p = await saveSelection();
      if (!p) return;
      const f = await request(`/api/samples/${p.id}/export`, { video });
      onFile(f.path);
      onMessage("导出使用选中的音源，持久保存");
    } catch (e) {
      onMessage(e);
    } finally {
      setBusy(false);
    }
  };
  if (!r)
    return (
      <main className="empty">
        <h2>打开视频或音频</h2>
        <p>无字幕文件也可以截取。</p>
        <UButton onClick={onImport}>选择媒体</UButton>
      </main>
    );
  return (
    <main
      className="cutter"
      tabIndex={0}
      onKeyDown={(e) => {
        if (
          ["INPUT", "TEXTAREA", "SELECT"].includes(
            (e.target as HTMLElement).tagName,
          )
        )
          return;
        if (e.key === " ") {
          e.preventDefault();
          element.current?.paused
            ? element.current.play()
            : element.current?.pause();
        }
        if (e.key === "i") setStart(position);
        if (e.key === "o") setEnd(position);
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          seek(
            position +
              (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 0.001 : step),
          );
        }
      }}
    >
      <div className="studio-toolbar compact">
        <Select
          aria-label="参考音源"
          value={audioRole}
          labelRender={({value, label}) => value === "vocals" ? "分离人声（自动选择）" : value === "residual" ? "去人声残差（自动选择）" : label}
          style={{ minWidth: 170, maxWidth: 300 }}
          onChange={(role) => {
            const track = effectTracks.find(
              (t: any) => role === "artifact:" + t.artifact_id,
            );
            const a = track
                ? Math.max(track.start, previewRange[0])
                : previewRange[0],
              b = track
                ? Math.min(track.end, previewRange[1])
                : previewRange[1];
            const left = a < b ? a : track.start,
              right = a < b ? b : track.end;
            setStart(left);
            setEnd(right);
            makeProxy(left, right, stream, role);
          }}
          options={[
            { value: "raw", label: "原混音" },
            ...(["vocals", "residual"].filter(role => !effectTracks.some((t: any) => t.role === role && t.complete)).map(role => ({value:role, label: role === "vocals" ? "人声（尚无完整音轨）" : "去人声残差（尚无完整音轨）"}))),
            ...effectTracks.map((t: any) => ({
              value: "artifact:" + t.artifact_id,
              label: t.title + ` (${t.start.toFixed(0)}–${t.end.toFixed(0)}s)`,
            })),
          ]}
        />
        <Select
          aria-label="音轨"
          value={stream}
          onChange={(v) => makeProxy(previewRange[0], previewRange[1], v)}
          options={meta.streams
            .filter((s: any) => s.codec_type === "audio")
            .map((s: any) => ({
              value: s.index,
              label: `音轨 ${s.index} · ${s.tags?.language || s.codec_name}`,
            }))}
        />
        <Button onClick={() => setAction("separate")}>分离音轨</Button>
        <span className="toolbar-spacer" />
        <Dropdown
          menu={{
            items: [
              {
                key: "origin",
                label: "打开原片完整范围",
                onClick: () =>
                  request("/api/samples/source-browser", {
                    source_id: r.source_id,
                  })
                    .then((p) => onSave(p.id))
                    .catch(onMessage),
              },
            ],
          }}
        >
          <Button
            type="text"
            icon={<MoreOutlined />}
            aria-label="原片播放操作"
          />
        </Dropdown>
        <Help>
          Space 播放；I / O 设置选区；方向键逐帧，Shift＋方向键按 1 ms
          移动。滚轮缩放，横向滚动平移。
        </Help>
      </div>
      {busy && (
        <p role="status">
          正在打开媒体；视频按播放位置加载，无需等待整集转换。
        </p>
      )}
      <div className="video-layout">
        <div className="source-video">
          <VideoPlayer
            key={url}
            subtitle={context
              .filter((c) => c.start <= position && position < c.end)
              .map((c) => c.original)
              .join("\n")}
            ref={element}
            src={url.endsWith(".m3u8") ? undefined : url}
            controls
            onLoadedMetadata={() => {
              seek(
                Math.max(
                  origin,
                  Math.min(
                    origin + (element.current?.duration || 0) - 0.001,
                    resume.current.time,
                  ),
                ),
              );
              if (
                resume.current.playing &&
                element.current?.getClientRects().length
              )
                void element.current?.play().catch(onMessage);
            }}
            onTimeUpdate={() => {
              const p = (element.current?.currentTime || 0) + origin;
              setPosition(p);
            }}
            onError={() => {
              if (!requestedProxy.current && audioRole === "raw") {
                requestedProxy.current = true;
                makeProxy();
              }
            }}
          />
          {!window.ottoDesktop?.player && (
            <div className="subtitle-overlay">
              {context
                .filter((c) => c.start <= position && position < c.end)
                .map((c) => (
                  <div key={c.id}>{c.original}</div>
                ))}
            </div>
          )}
        </div>
        <div
          className="context"
          ref={subtitleList}
          onWheel={() => {
            subtitleFollowPause.current = Date.now() + 3500;
          }}
        >
          <h3>字幕上下文</h3>
          {context.map((c) => (
            <UButton
              key={c.id}
              data-cue-id={c.id}
              className={
                c.start <= position && position <= c.end ? "active" : ""
              }
              onClick={() => {
                setStart(c.start);
                setEnd(c.end);
                seek(c.start);
              }}
            >
              <small>{sec(c.start)}</small>
              {c.original}
            </UButton>
          ))}
          {!context.length && <p>此范围没有字幕</p>}
        </div>
      </div>
      <div ref={container} className="waveform" />
      <div className="studio-toolbar compact">
        <InputNumber
          precision={3}
          aria-label="播放位置"
          value={+position.toFixed(3)}
          step={step}
          onChange={(v) => seek(v || 0)}
        />
        <span>秒</span>
        <span className="toolbar-spacer" />
        <InputNumber
          precision={3}
          aria-label="源开始秒"
          value={start}
          step={0.001}
          onChange={(v) => setStart(v || 0)}
        />
        <span>—</span>
        <InputNumber
          precision={3}
          aria-label="源结束秒"
          value={end}
          step={0.001}
          onChange={(v) => setEnd(v || 0)}
        />
        <Button
          type="primary"
          disabled={busy}
          onClick={() => setAction("save")}
        >
          保存选区
        </Button>
        <Dropdown
          menu={{
            items: [
              {
                key: "flatten",
                label: "拉平并保存单音…",
                onClick: () => setAction("flatten"),
              },
              {
                key: "wav",
                label: "导出选区 WAV",
                onClick: () => exportFile(false),
              },
              {
                key: "video",
                label: "导出选区视频",
                disabled: !video,
                onClick: () => exportFile(true),
              },
              {
                key: "in",
                label: "设为开始 (I)",
                onClick: () => setStart(position),
              },
              {
                key: "out",
                label: "设为结束 (O)",
                onClick: () => setEnd(position),
              },
            ],
          }}
        >
          <Button icon={<MoreOutlined />} aria-label="选区操作" />
        </Dropdown>
      </div>
      <Modal
        title={
          action === "separate"
            ? "准备分离音源"
            : action === "flatten"
              ? "拉平并保存单音"
              : "保存选区"
        }
        open={!!action}
        confirmLoading={saving}
        okButtonProps={{
          disabled:
            action === "separate" &&
            separationMode === "cinematic" &&
            !cinematicModels.find((m) => m.id === cinematicRoute)?.available,
        }}
        onCancel={() => setAction("")}
        onOk={async () => {
          setSaving(true);
          try {
            if (action === "save") {
              await save();
            } else if (action === "flatten") {
              const j = await request(`/api/samples/${r.id}/source-flatten`, {
                start,
                end,
                role: audioRole,
                audio_stream: stream,
              });
              onMessage("拉平任务已排队：" + j.id);
            } else {
              const a = separationRange === "whole" ? 0 : start;
              const b = separationRange === "whole" ? r.source_duration : end;
              if (separationMode === "cinematic") {
                await request("/api/sound/run/tracks", {
                  input: {
                    source_id: r.source_id,
                    role: "raw",
                    audio_stream: stream,
                    start: a,
                    end: b,
                    clock: "source",
                  },
                  routes: [cinematicRoute],
                });
              } else {
                await request(`/api/samples/${r.id}/separate`, {
                  start: a,
                  end: b,
                  audio_stream: stream,
                  save: false,
                  model: vocalModel,
                });
              }
              onMessage("分离任务已排队，可在任务面板查看");
            }
            setAction("");
          } catch (e) {
            onMessage(e);
          } finally {
            setSaving(false);
          }
        }}
      >
        <p>
          {action === "separate"
            ? separationRange === "whole"
              ? `整片 · ${r.source_duration.toFixed(1)}`
              : `${start.toFixed(3)}–${end.toFixed(3)}`
            : `${start.toFixed(3)}–${end.toFixed(3)}`}{" "}
          秒
        </p>
        {action === "save" && (
          <Form layout="vertical">
            <Form.Item label="名称">
              <Input
                value={selectionTitle}
                placeholder={r.title}
                onChange={(e) => setSelectionTitle(e.target.value)}
              />
            </Form.Item>
            <Form.Item label="性质">
              <Select
                value={selectionNature}
                onChange={setSelectionNature}
                options={[
                  { value: "speech", label: "语音" },
                  { value: "pitched", label: "调谐单音（未拉平）" },
                  { value: "unpitched", label: "非调谐单音" },
                ]}
              />
            </Form.Item>
          </Form>
        )}
        {action === "separate" && (
          <Form layout="vertical">
            <Form.Item label="范围">
              <Select
                value={separationRange}
                onChange={setSeparationRange}
                options={[
                  { value: "whole", label: "整片连续音轨" },
                  { value: "selection", label: "当前选区" },
                ]}
              />
            </Form.Item>
            <Form.Item label="分离方式">
              <Select
                value={separationMode}
                onChange={setSeparationMode}
                options={[
                  { value: "vocals", label: "人声 / 去人声残差" },
                  { value: "cinematic", label: "对白 / 音乐 / 音效" },
                ]}
              />
            </Form.Item>
            <Form.Item label="模型">
              {separationMode === "cinematic" ? (
                <Select
                  value={cinematicRoute}
                  onChange={setCinematicRoute}
                  options={cinematicModels.map((m) => ({
                    value: m.id,
                    label:
                      m.name +
                      (m.available ? "" : " · " + (m.reason || "不可用")),
                    disabled: !m.available,
                  }))}
                />
              ) : (
                <Select
                  style={{ width: "100%" }}
                  value={vocalModel}
                  onChange={setVocalModel}
                  options={[
                    { value: "becruily_deux", label: "becruily Deux" },
                    {
                      value: "bs_roformer_voc_hyperacev2",
                      label: "HyperACE v2",
                    },
                  ]}
                />
              )}
            </Form.Item>
            <Help>
              无需字幕或音素分析。结果会自动出现在参考音源中，不登记为采样；三轨分离不运行打击音发现。
            </Help>
          </Form>
        )}
        {action === "flatten" && (
          <Alert
            type="info"
            title="根据可靠 F0 拉平整个选段；不需要字幕。只保存最终单音，不额外创建未拉平采样。"
          />
        )}
      </Modal>
    </main>
  );
}

ConfigProvider.config({
  holderRender: (children) => <UiRoot>{children}</UiRoot>,
});
createRoot(document.getElementById("root")!).render(
  <UiRoot>
    <Workspace />
  </UiRoot>,
);
