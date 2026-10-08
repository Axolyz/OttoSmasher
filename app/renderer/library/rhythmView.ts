// 舞台上节奏视图的共享读取（节奏与卡拍面板、语音面板的「分组与停顿」用同一份）：
// 键 = 采样 + 版本 + 全局 BPM + 临时纯 mora；同一个键正在读时不重复请求。资料变了（data.changed 带这个采样）就重读。
import { useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import type { RhythmView } from "../api/types";
import { useApp } from "../state/store";

const inflight = new Map<string, Promise<RhythmView>>();

function fetchView(id: string, mora: boolean, longVowel: boolean, key: string): Promise<RhythmView> {
  let p = inflight.get(key);
  if (!p) {
    p = call("rhythm.view", { id, mora, longVowel }).finally(() => inflight.delete(key));
    inflight.set(key, p);
  }
  return p;
}

export function useRhythmView(sampleId: string, sampleVersion: number): { view: RhythmView | null; error: unknown; reload: () => void } {
  const bpm = useApp((st) => st.bpm);
  const sr = useApp((st) => st.stageRhythm);
  const mora = sr.sampleId === sampleId && sr.mora;
  const longVowel = sr.sampleId === sampleId && sr.longVowel;
  const [view, setView] = useState<RhythmView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);
  const key = `${sampleId}:${sampleVersion}:${bpm}:${mora}:${longVowel}:${tick}`;
  useEffect(() => {
    let live = true;
    fetchView(sampleId, mora, longVowel, key).then(
      (v) => {
        if (!live) return;
        setView(v);
        setError(null);
      },
      (e) => {
        if (!live) return;
        setView(null);
        setError(e);
      },
    );
    return () => {
      live = false;
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setView(null), [sampleId]);
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (c.sample?.includes(sampleId) || c.measure?.includes(sampleId) || c.setting) setTick((x) => x + 1);
  });
  return { view: view && view.sampleId === sampleId ? view : null, error, reload: () => setTick((x) => x + 1) };
}
