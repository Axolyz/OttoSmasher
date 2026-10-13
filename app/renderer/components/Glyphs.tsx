// 列表行的小图（用途视图，规格 07 §7.9；UI_PLAN §2.2）：节奏字形（音块在整句里的位置）、迷你折线（音高曲线 / 包络）。
// 只是显示，颜色跟随文字颜色（currentColor），由调用方用性质色或淡色。
export function RhythmGlyph(props: { blocks: number[][]; width?: number; label: string }) {
  const w = props.width ?? 64;
  const h = 8;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={props.label} style={{ flex: "none" }}>
      <rect x={0} y={h / 2 - 0.5} width={w} height={1} fill="currentColor" opacity={0.25} />
      {props.blocks.map(([a, b], i) => {
        const x = Math.max(0, Math.min(1, a!)) * w;
        const x2 = Math.max(0, Math.min(1, b!)) * w;
        return <rect key={i} x={x} y={1} width={Math.max(2, x2 - x - 1)} height={h - 2} rx={2} fill="currentColor" opacity={0.85} />;
      })}
    </svg>
  );
}

/** 折线：null = 未知（断开，不画成 0） */
/** 小曲线。``minSpan`` 给了就不再把最低到最高撑满：以中位为中心至少显示这么大的范围（音高传 6 个半音，所有者 2026-10-13），
 *  再画一条淡中位线——起伏很小的线看起来就是平的。 */
export function Sparkline(props: { values: Array<number | null>; width?: number; height?: number; label: string; log?: boolean; minSpan?: number }) {
  const w = props.width ?? 64;
  const h = props.height ?? 12;
  const vs = props.values.map((v) => (v == null || !Number.isFinite(v) ? null : props.log ? Math.log10(Math.max(v, 1e-9)) : v));
  const known = vs.filter((v): v is number => v != null);
  if (!known.length) return null;
  let lo = Math.min(...known);
  let hi = Math.max(...known);
  const mid = [...known].sort((a, b) => a - b)[Math.floor(known.length / 2)]!;
  if (props.minSpan && hi - lo < props.minSpan) {
    lo = Math.min(lo, mid - props.minSpan / 2);
    hi = lo + props.minSpan;
    if (hi < Math.max(...known)) {
      hi = Math.max(...known);
      lo = hi - props.minSpan;
    }
  }
  const span = hi - lo || 1;
  const midY = (h - 1 - ((mid - lo) / span) * (h - 2)).toFixed(1);
  const step = vs.length > 1 ? w / (vs.length - 1) : w;
  const parts: string[] = [];
  let open = false;
  vs.forEach((v, i) => {
    if (v == null) {
      open = false;
      return;
    }
    const x = (i * step).toFixed(1);
    const y = (h - 1 - ((v - lo) / span) * (h - 2)).toFixed(1);
    parts.push(`${open ? "L" : "M"}${x} ${y}`);
    open = true;
  });
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={props.label} style={{ flex: "none" }}>
      {props.minSpan ? <line x1={0} x2={w} y1={midY} y2={midY} stroke="currentColor" strokeOpacity={0.25} strokeWidth={1} /> : null}
      <path d={parts.join(" ")} fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
