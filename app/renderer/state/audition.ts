// 试听入口共用当前请求与结束处理（ARCHITECTURE §10.1）。
import { create } from "zustand";
import type { PlayerState } from "../../shared/protocol";
import { CoreFailure } from "../api/core";
import type { HitRefParams, RhythmRendered, RhythmSound } from "../api/types";
import { errorText } from "../i18n";
import { useApp } from "./store";

export type AuditionVersion = "original" | "stretched";

type AuditionTarget =
  | { kind: "sample"; sampleId: string }
  | { kind: "hit"; ref: HitRefParams }
  | { kind: "stem"; assetId: string }
  | { kind: "flatten" };

interface AuditionRequest {
  target: AuditionTarget;
  name: string;
  version?: AuditionVersion;
  sound?: RhythmSound;
}

type AuditionAudio =
  | { assetId: string; start: number; end: number; loop?: boolean } // 资产局部秒
  | (Pick<RhythmRendered, "key" | "duration" | "plan" | "bpm" | "originalSpeed"> & { assetStart?: number });

export type AuditionDetails = Pick<RhythmRendered, "duration" | "plan" | "bpm" | "originalSpeed"> & {
  assetStart: number | null; // 只有能从试听本地秒换算到资产局部秒时才有值
};

interface Audition {
  request: Required<AuditionRequest>;
  details: AuditionDetails | null;
}

export const useAudition = create<{ current: Audition | null }>(() => ({ current: null }));

let gen: number | null = null;
let started = false;
let lastSample: { id: string; position: number | null } | null = null;

/** 试听本地秒。在引擎开始本次播放之前，上一段的时间不能拿来画播放头。 */
export function auditionPosition(): number | null {
  return started ? window.otto.player.position("audition") : null;
}

export function sampleAuditionPosition(sampleId: string): number | null {
  const current = useAudition.getState().current;
  const target = current?.request.target;
  if (target?.kind !== "sample" || target.sampleId !== sampleId || current?.details?.assetStart == null) return null;
  const pos = auditionPosition();
  return pos == null ? null : current.details.assetStart + pos;
}

export function lastSampleAuditionPosition(sampleId: string): number | null {
  return lastSample?.id === sampleId ? lastSample.position : null;
}

function finish(position: number | null): void {
  const current = useAudition.getState().current;
  const target = current?.request.target;
  if (target?.kind === "sample" && current?.request.version === "original") {
    const start = current.details?.assetStart;
    lastSample = { id: target.sampleId, position: start == null || position == null ? null : start + position };
  }
  gen = null;
  started = false;
  useAudition.setState({ current: null });
}

function reportError(e: unknown): void {
  const wire = e instanceof CoreFailure ? e.wire : e;
  const text = wire && typeof wire === "object" && "code" in wire && typeof wire.code === "string"
    ? errorText({ code: wire.code, args: "args" in wire ? wire.args as Record<string, unknown> : undefined })
    : String(wire);
  useApp.getState().toast({ text, tone: "error" });
}

export function onAuditionState(state: PlayerState): void {
  if (state.player !== "audition" || gen == null || state.gen < gen) return;
  if (state.gen > gen) {
    finish(auditionPosition()); // 原片接管时，引擎先结束当前试听
  } else if (state.error) {
    stopAudition();
    reportError(state.error);
  } else if (state.ended) {
    finish(state.time);
  } else if (state.playing && !state.loading && state.time != null) {
    started = true;
  }
}

export function stopAudition(): void {
  finish(auditionPosition());
  window.otto.player.stopAudition();
}

/** 准备可以异步完成。只让仍是当前的请求启动播放器或报告失败。 */
export async function startAudition(
  { target, name, version = "original", sound = "voice" }: AuditionRequest,
  prepare: () => AuditionAudio | Promise<AuditionAudio>,
): Promise<void> {
  if (useAudition.getState().current) stopAudition();
  const request = { target, name, version, sound };
  const isCurrent = () => useAudition.getState().current?.request === request;
  useAudition.setState({ current: { request, details: null } });
  try {
    const audio = await prepare();
    if (!isCurrent()) return;
    const details = "assetId" in audio
      ? { duration: audio.end - audio.start, plan: null, bpm: null, originalSpeed: false, assetStart: audio.start }
      : { duration: audio.duration, plan: audio.plan, bpm: audio.bpm, originalSpeed: audio.originalSpeed, assetStart: audio.assetStart ?? null };
    useAudition.setState({ current: { request, details } });
    const onBegin = (value: number) => {
      if (isCurrent()) gen = value;
    };
    if ("assetId" in audio) {
      const sampleId = target.kind === "sample" ? target.sampleId : undefined;
      await window.otto.player.audition(audio.assetId, audio.start, audio.end, audio.loop, sampleId, onBegin);
    } else {
      await window.otto.player.auditionRender(audio.key, false, onBegin);
    }
  } catch (e) {
    if (isCurrent()) {
      stopAudition();
      reportError(e);
    }
  }
}
