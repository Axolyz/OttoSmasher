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
export function Sparkline(props: { values: Array<number | null>; width?: number; height?: number; label: string; log?: boolean }) {
  const w = props.width ?? 64;
  const h = props.height ?? 12;
  const vs = props.values.map((v) => (v == null || !Number.isFinite(v) ? null : props.log ? Math.log10(Math.max(v, 1e-9)) : v));
  const known = vs.filter((v): v is number => v != null);
  if (!known.length) return null;
  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const span = hi - lo || 1;
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
      <path d={parts.join(" ")} fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
