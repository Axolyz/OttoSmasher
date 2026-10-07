// 资产能不能挂到原片时间轴（规格 05 §5.4）：未变速 = 每个控制点的 原片秒 − 局部秒 相同（容差 20 ms，与 Core 的 playback.hang_offset 一致）。
const TOLERANCE = 0.02;

/** 原片秒 = 局部秒 + 偏移；变速了返回 null */
export function hangOffset(mapping: number[][] | null | undefined): number | null {
  if (!mapping?.length) return null;
  const offs = mapping.map(([loc, src]) => (src ?? 0) - (loc ?? 0));
  return Math.max(...offs) - Math.min(...offs) <= TOLERANCE ? offs[0]! : null;
}
