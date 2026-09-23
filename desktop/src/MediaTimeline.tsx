import { NativeAudio } from "./NativePlayer";
import React, { useEffect, useRef, useState } from "react";
import { audioTimeline } from "./AudioTimeline";

/** Bind the same media element used by video/A-B sync; never create a second audio clock. */
export function MediaTimeline({
  media,
  waveform,
  origin = 0,
  onSelection,
  onError,
}: {
  media: React.RefObject<HTMLMediaElement | null>;
  waveform: any;
  origin?: number;
  onSelection?: (range: number[]) => void;
  onError?: (e: unknown) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    callbacks = useRef({ onSelection, onError });
  callbacks.current = { onSelection, onError };
  useEffect(() => {
    if (!host.current || !media.current || !waveform) return;
    const w = audioTimeline({
      container: host.current,
      media: media.current,
      peaks: waveform.peaks,
      duration: waveform.duration,
      origin,
      visualizationKey: waveform.visualization_key,
      onSelectionChange: (r: number[]) => callbacks.current.onSelection?.(r),
    });
    w.on("error", (e: Error) => callbacks.current.onError?.(e));
    return () => w.destroy();
  }, [waveform, origin, media]);
  return <div ref={host} className="shared-media-timeline" />;
}

/** Short rendered auditions have their own (target) clock, separate from source phone labels. */
export function AudioPlayer({
  url,
  mediaRef,
  autoPlay = false,
}: {
  url: string;
  mediaRef?: React.RefObject<HTMLAudioElement | null>;
  autoPlay?: boolean;
}) {
  const fallback = useRef<HTMLAudioElement>(null),
    host = useRef<HTMLDivElement>(null);
  const media = mediaRef || fallback;
  const [transport, setTransport] = useState(false);
  useEffect(() => {
    const element = media.current;
    if (!host.current || !element || !url) return;
    setTransport(false);
    let w: ReturnType<typeof audioTimeline> | undefined;
    const load = () => {
      if (w || !host.current) return;
      // Unknown long external media must remain streamable, without full browser decoding.
      if (element.duration > 120) {
        setTransport(true);
        return;
      }
      w = audioTimeline({
        container: host.current,
        media: element,
        url,
        height: 72,
      });
      w.on("error", () => {
        setTransport(true);
      });
      if (autoPlay && host.current?.getClientRects().length)
        void element.play().catch(() => {});
    };
    element.addEventListener("loadedmetadata", load);
    if (element.readyState >= 1) load();
    return () => {
      element.removeEventListener("loadedmetadata", load);
      w?.destroy();
    };
  }, [url, media, autoPlay]);
  if (!url) return null;
  return (
    <div className="audition-timeline">
      <NativeAudio
        ref={media}
        src={url}
        preload="metadata"
        controls={transport}
      />
      <div ref={host} />
    </div>
  );
}
