// 覆盖层边界编辑（UI_PLAN §3.1、规格 03 §3.5.4「编辑字幕／区段边界」；原型 boundaries()）：
// - 同一时刻的起点/终点合成一条边界（相邻区间共用的边界一起移动）；
// - 一条边界只能在左右相邻的两条边界之间移动（不越过邻居，次序不变），并且它所属的每个区间保持至少 MIN 秒长；
// - 范围限制在 [0, 时长]。

export interface EditBand {
  key: string;
  a: number;
  b: number;
}
export interface Boundary {
  t: number;
  items: Array<{ key: string; side: "a" | "b" }>;
}

export const MIN_LEN = 0.01;
const SAME = 1e-6;

export function boundaries(bands: readonly EditBand[]): Boundary[] {
  const pts = bands.flatMap((x) => [
    { t: x.a, key: x.key, side: "a" as const },
    { t: x.b, key: x.key, side: "b" as const },
  ]);
  pts.sort((p, q) => p.t - q.t);
  const out: Boundary[] = [];
  for (const p of pts) {
    const last = out[out.length - 1];
    if (last && Math.abs(last.t - p.t) < SAME) last.items.push({ key: p.key, side: p.side });
    else out.push({ t: p.t, items: [{ key: p.key, side: p.side }] });
  }
  return out;
}

/** 边界 i 可以移动的范围 [lo, hi] */
export function limits(all: readonly Boundary[], i: number, bands: readonly EditBand[], duration: number): [number, number] {
  const byKey = new Map(bands.map((x) => [x.key, x]));
  let lo = i > 0 ? all[i - 1]!.t : 0;
  let hi = i < all.length - 1 ? all[i + 1]!.t : duration;
  for (const it of all[i]!.items) {
    const band = byKey.get(it.key)!;
    if (it.side === "a") hi = Math.min(hi, band.b - MIN_LEN);
    else lo = Math.max(lo, band.a + MIN_LEN);
  }
  return [Math.max(0, lo), Math.min(duration, hi)];
}

/** 把边界移到 t（先夹到范围内），返回新的区间列表（没动的区间原样返回） */
export function moveBoundary(bands: readonly EditBand[], b: Boundary, t: number, lim: [number, number]): EditBand[] {
  const v = Math.max(lim[0], Math.min(lim[1], t));
  const touched = new Map(b.items.map((x) => [x.key, x.side]));
  return bands.map((x) => {
    const side = touched.get(x.key);
    return side ? { ...x, [side]: v } : x;
  });
}

/** 找光标附近（px 以内）的边界下标；没有 → -1 */
export function boundaryNear(all: readonly Boundary[], x: number, toX: (t: number) => number, px: number): number {
  let best = -1;
  let dist = px;
  all.forEach((b, i) => {
    const d = Math.abs(toX(b.t) - x);
    if (d <= dist) {
      best = i;
      dist = d;
    }
  });
  return best;
}
