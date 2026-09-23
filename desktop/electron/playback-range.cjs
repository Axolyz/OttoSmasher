// All endpoints are in the selected media's local clock. mpv receives source seconds.
function rangeCommands(spec, value) {
  const { start, end, loop = false } = value;
  if (
    ![start, end].every(Number.isFinite) ||
    start < 0 ||
    end <= start ||
    (spec.end != null && end > spec.end - spec.start + 1e-6)
  )
    throw Error("Invalid playback range");
  const a = spec.start + start,
    b = spec.start + end;
  return [
    ["set", "pause", "yes"],
    ["set", "ab-loop-a", "no"],
    ["set", "ab-loop-b", "no"],
    ["set", "end", String(b)],
    ...(loop
      ? [
          ["set", "ab-loop-a", String(a)],
          ["set", "ab-loop-b", String(b)],
          ["set", "ab-loop-count", "inf"],
        ]
      : []),
    ["seek", String(a), "absolute+exact"],
    ["set", "pause", "no"],
  ];
}
function clearRangeCommands(spec) {
  return [
    ["set", "ab-loop-a", "no"],
    ["set", "ab-loop-b", "no"],
    ["set", "end", spec.end == null ? "none" : String(spec.end)],
  ];
}
module.exports = { rangeCommands, clearRangeCommands };
