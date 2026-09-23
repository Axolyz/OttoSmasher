export type TimeInterval = { start: number; end: number };
/** Snap against the raw gesture, not a previously expanded preview. */
export function snapIntervals(a: number, b: number, intervals: TimeInterval[]) {
  let start = Math.min(a, b),
    end = Math.max(a, b);
  for (const r of intervals)
    if (r.start < Math.max(a, b) && r.end > Math.min(a, b)) {
      start = Math.min(start, r.start);
      end = Math.max(end, r.end);
    }
  return { start, end };
}
