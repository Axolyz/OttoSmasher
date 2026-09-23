import React from "react";
export function RhythmMapping({ plan: p }: { plan: any }) {
  const t = p.visual_timing;
  if (!t?.points?.length) return null;
  const points = t.points,
    duration = Math.max(t.source_duration, t.target_duration, 0.01);
  const x = (v: number) => 62 + (v / duration) * 675;
  const tick =
    duration <= 2
      ? 0.25
      : duration <= 6
        ? 0.5
        : duration <= 15
          ? 1
          : Math.ceil(duration / 8);
  return (
    <svg
      className="rhythm-mapping"
      viewBox="0 0 760 125"
      role="img"
      aria-label="原句与卡拍共用秒数比例的节奏映射"
    >
      <text x="2" y="35">
        原句
      </text>
      <text x="2" y="83">
        卡拍
      </text>
      <path
        d={`M62 40H${x(t.source_duration)} M62 88H${x(t.target_duration)}`}
        stroke="#678493"
      />
      <text x="62" y="120">
        原句 {t.source_duration.toFixed(3)}s → 卡拍{" "}
        {t.target_duration.toFixed(3)}s · 同比例秒数轴
      </text>
      {Array.from(
        { length: Math.min(30, Math.floor(duration / tick) + 1) },
        (_, i) => (
          <g key={i}>
            <path d={`M${x(i * tick)} 35V94`} stroke="#52616f" opacity=".3" />
            <text x={x(i * tick)} y="106">
              {+(i * tick).toFixed(2)}s
            </text>
          </g>
        ),
      )}
      {points.map((u: any, i: number) => (
        <g key={i}>
          <title>
            {u.label}: {u.source_seconds.toFixed(3)}s →{" "}
            {u.target_seconds.toFixed(3)}s
          </title>
          <path
            d={`M${x(u.source_seconds)} 40L${x(u.target_seconds)} 88`}
            stroke={`hsl(${(i * 43) % 360} 60% 64%)`}
            opacity=".65"
          />
          <circle cx={x(u.source_seconds)} cy="40" r="3" fill="#81bfff" />
          <circle cx={x(u.target_seconds)} cy="88" r="3" fill="#ffcd64" />
          <text x={x(u.source_seconds)} y={i % 2 ? 15 : 28} textAnchor="middle">
            {u.label || i + 1}
          </text>
        </g>
      ))}
    </svg>
  );
}
