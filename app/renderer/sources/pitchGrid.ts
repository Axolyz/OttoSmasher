// 波形上音高线的刻度（所有者 2026-10-13）：像时间刻度一样按疏密自适应，跨几个八度也不会密密麻麻。
// - 线：间隔在 1 / 2 / 3 / 6 / 12 个半音里选最小的、线距 ≥ LINE_MIN 像素的；每个 C 一定有线（加亮）；
// - 音名：只标在相距 ≥ LABEL_MIN 像素的线上（间隔在 1 / 2 / 3 / 6 / 12 / 24 / 36 里选，C 优先——这些间隔都从 C 起算）；
// - 纵向范围：可见值上下各留一点余量，最少 MIN_SPAN 个半音，以中位为中心。
export const LINE_MIN = 6;
export const LABEL_MIN = 16;
export const MIN_SPAN = 6;

export interface GridLine {
  midi: number;
  c: boolean;
  label: boolean;
}

const STEPS = [1, 2, 3, 6, 12];
const LABEL_STEPS = [1, 2, 3, 6, 12, 24, 36];

export function pitchGrid(lo: number, hi: number, pxPerSemitone: number): GridLine[] {
  if (!(hi > lo) || !(pxPerSemitone > 0)) return [];
  const step = STEPS.find((k) => k * pxPerSemitone >= LINE_MIN) ?? 12;
  const labelStep = LABEL_STEPS.find((k) => k >= step && k * pxPerSemitone >= LABEL_MIN) ?? 36;
  const out: GridLine[] = [];
  for (let m = Math.ceil(lo); m <= Math.floor(hi); m++) {
    const c = ((m % 12) + 12) % 12 === 0;
    if (m % step !== 0 && !c) continue;
    if (c && step === 12 && 12 * pxPerSemitone < LINE_MIN && m % 24 !== 0) continue; // 连 C 都太密：隔一个八度
    out.push({ midi: m, c, label: ((m % labelStep) + labelStep) % labelStep === 0 });
  }
  return out;
}

/** 纵向范围：可见音高（MIDI）的最小、最大、中位 → [下, 上]，最少 MIN_SPAN 个半音、上下各留 15% 余量 */
export function pitchRange(values: number[]): [number, number] | null {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const lo = v[0]!;
  const hi = v[v.length - 1]!;
  const mid = v[Math.floor(v.length / 2)]!;
  const pad = (hi - lo) * 0.15;
  let a = lo - pad;
  let b = hi + pad;
  if (b - a < MIN_SPAN) {
    a = Math.min(lo, mid - MIN_SPAN / 2);
    b = a + MIN_SPAN;
    if (b < hi) {
      b = hi;
      a = b - MIN_SPAN;
    }
  }
  return [a, b];
}
