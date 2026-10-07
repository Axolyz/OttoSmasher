// 时间线 Shift 吸附（UI_PLAN §6.2、规格 16 R22.8）：只看覆盖层（可见图层）的区间；正长度交叠，端点相接不算。
// - Shift+单击：选中光标下的整个区间（有重叠时取最短的那条——最具体）；
// - Shift+拖动：拖出的范围与哪些区间交叠，就扩展到它们的边界——只扩一次、不级联，正反向对称。
//   例：[1,2] [1.9,4] [3,5]：(1.1,1.5)→(1,2)；(2.5,1.5)→(1,4)；(6,7) 不变。

export interface Band {
  a: number;
  b: number;
}

const EPS = 1e-9;
const overlaps = (a0: number, a1: number, b0: number, b1: number) => a0 < b1 - EPS && a1 > b0 + EPS;

export function snapExtend(x: number, y: number, bands: readonly Band[]): Band {
  const lo = Math.min(x, y);
  const hi = Math.max(x, y);
  let a = lo;
  let b = hi;
  for (const band of bands) {
    if (!overlaps(lo, hi, band.a, band.b)) continue;
    a = Math.min(a, band.a);
    b = Math.max(b, band.b);
  }
  return { a, b };
}

export function bandAt<T extends Band>(t: number, bands: readonly T[]): T | null {
  let best: T | null = null;
  for (const band of bands) {
    if (t >= band.a - EPS && t <= band.b + EPS && (!best || band.b - band.a < best.b - best.a)) best = band;
  }
  return best;
}

/** 时间 t 处的所有区间（重叠时都给，短的在前）：派生轨重叠时弹出选择菜单用 */
export function bandsAt<T extends Band>(t: number, bands: readonly T[]): T[] {
  return bands.filter((band) => t >= band.a - EPS && t <= band.b + EPS).sort((x, y) => x.b - x.a - (y.b - y.a));
}
