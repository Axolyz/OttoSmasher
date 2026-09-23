import { VideoPlayer } from "./NativePlayer";
import { Help } from "./Ui";
import { UButton, USelect, UInput } from "./Ui";
import React, { useEffect, useRef, useState } from "react";
import { MediaTimeline } from "./MediaTimeline";
import { request } from "./Workspace";

export function SoundTracks({
  sources,
  initialSource,
  refreshKey,
  onMessage,
}: any) {
  const [tracks, setTracks] = useState<any[]>([]),
    [source, setSource] = useState(initialSource || "");
  const [track, setTrack] = useState(""),
    [range, setRange] = useState([0, 60]);
  const [preview, setPreview] = useState<any>(null),
    [busy, setBusy] = useState(false);
  const [position, setPosition] = useState(0);
  const video = useRef<HTMLVideoElement>(null),
    playhead = useRef(0),
    playing = useRef(false),
    generation = useRef(0);
  useEffect(() => {
    if (initialSource) setSource(initialSource);
  }, [initialSource]);
  useEffect(() => {
    generation.current++;
    setTrack("");
    setPreview(null);
    setRange([0, sources.find((s: any) => s.id === source)?.duration || 1]);
  }, [source, sources]);
  useEffect(() => {
    if (source)
      request(`/api/sound/tracks?source_id=${source}`)
        .then(setTracks)
        .catch(onMessage);
    else setTracks([]);
  }, [source, refreshKey]);
  useEffect(() => {
    if (!preview?.waveform_url || preview.waveform) return;
    let stale = false;
    request(preview.waveform_url)
      .then((waveform) => {
        if (!stale) setPreview((p: any) => (p ? { ...p, waveform } : p));
      })
      .catch(onMessage);
    return () => {
      stale = true;
    };
  }, [preview?.url]);
  const current = tracks.find((t) => t.artifact_id === track);
  const duration = sources.find((s: any) => s.id === source)?.duration || 0;
  const prepare = async (id = track, limits = range) => {
    if (!source) return;
    const version = ++generation.current;
    playhead.current = video.current
      ? (preview?.origin || 0) + video.current.currentTime
      : limits[0];
    playing.current = !!video.current && !video.current.paused;
    video.current?.pause();
    setBusy(true);
    try {
      const p = await request("/api/sound/track-preview", {
        source_id: source,
        artifact_id: id || undefined,
        start: limits[0],
        end: limits[1],
      });
      if (generation.current !== version) return;
      setPreview(p);
      setTrack(id);
      setRange(limits);
    } catch (e) {
      onMessage(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel">
      <h3>原片画面＋连续音轨对照</h3>
      <Help>
        参考轨不会进入采样库。可播放完整覆盖范围，也可先试听一段；切换音轨保留播放位置。
      </Help>
      <div className="row">
        <USelect
          aria-label="音轨审阅原片"
          value={source}
          disabled={busy}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="">选择原片</option>
          {sources.map((s: any) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </USelect>
        <USelect
          aria-label="连续参考音轨"
          value={track}
          disabled={busy}
          onChange={(e) => {
            const id = e.target.value,
              t = tracks.find((x) => x.artifact_id === id);
            const bounds = t ? [t.start, t.end] : [0, duration];
            const lo = Math.max(range[0], bounds[0]),
              hi = Math.min(range[1], bounds[1]);
            prepare(id, hi > lo ? [lo, hi] : bounds);
          }}
        >
          <option value="">原混音</option>
          {tracks.map((t) => (
            <option key={t.artifact_id} value={t.artifact_id}>
              {t.title} · {t.start.toFixed(1)}–{t.end.toFixed(1)}s
            </option>
          ))}
        </USelect>
      </div>
      <div className="row">
        <label>
          开始秒
          <UInput
            type="number"
            disabled={busy}
            value={range[0]}
            onChange={(e) => setRange([+e.target.value, range[1]])}
          />
        </label>
        <label>
          结束秒
          <UInput
            type="number"
            disabled={busy}
            value={range[1]}
            onChange={(e) => setRange([range[0], +e.target.value])}
          />
        </label>
        <UButton disabled={busy || !source} onClick={() => prepare()}>
          加载该范围
        </UButton>
        <UButton
          disabled={busy || !source}
          onClick={() =>
            prepare(track, [current?.start || 0, current?.end || duration])
          }
        >
          加载完整覆盖范围
        </UButton>
        {busy && <span>正在打开音轨…</span>}
      </div>
      {preview && (
        <>
          <p>
            当前声音：{current?.title || "原混音"} · 原片{" "}
            {preview.origin.toFixed(2)}–
            {(preview.origin + preview.duration).toFixed(2)} 秒
          </p>
          <div className="source-video">
            <VideoPlayer
              ref={video}
              onTimeUpdate={() =>
                setPosition((video.current?.currentTime || 0) + preview.origin)
              }
              controls
              src={preview.url}
              style={{ width: "100%", maxWidth: 900 }}
              onLoadedMetadata={() => {
                if (video.current) {
                  video.current.currentTime = Math.max(
                    0,
                    Math.min(
                      preview.duration,
                      playhead.current - preview.origin,
                    ),
                  );
                  if (playing.current && video.current.getClientRects().length)
                    video.current.play().catch(onMessage);
                }
              }}
            />
            <div className="subtitle-overlay">
              {(preview.subtitles || [])
                .filter((c: any) => c.start <= position && position < c.end)
                .map((c: any) => (
                  <div key={c.id}>{c.original}</div>
                ))}
            </div>
          </div>
          <MediaTimeline
            media={video}
            waveform={preview.waveform}
            origin={preview.origin}
            onError={onMessage}
          />
        </>
      )}
      {source && !tracks.length && (
        <p>
          此来源还没有连续参考轨。上方选电影分离模型，再点击“只分离连续参考轨”。
        </p>
      )}
    </section>
  );
}
