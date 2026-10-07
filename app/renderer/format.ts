// 全应用一种固定格式（ARCHITECTURE §7：数字、时长、日期不随界面语言变）。

/** 时钟：`M:SS.mmm`，满一小时 `H:MM:SS.mmm`；未知显示 `—`（未知不是零，P7）。 */
export function clock(t: number | null | undefined, decimals = 3): string {
  if (t == null || !Number.isFinite(t)) return "—";
  const neg = t < 0;
  const scale = 10 ** decimals;
  let units = Math.round(Math.abs(t) * scale);
  const frac = units % scale;
  units = (units - frac) / scale;
  const s = units % 60;
  const m = Math.floor(units / 60) % 60;
  const h = Math.floor(units / 3600);
  const sec = String(s).padStart(2, "0") + (decimals ? "." + String(frac).padStart(decimals, "0") : "");
  const body = h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  return neg ? "-" + body : body;
}

/** 秒数，三位小数：`1.800 s` 由调用方加单位。 */
export function seconds(t: number | null | undefined): string {
  return t == null || !Number.isFinite(t) ? "—" : t.toFixed(3);
}

export function basename(path: string): string {
  const i = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return i >= 0 ? path.slice(i + 1) : path;
}

export function stem(path: string): string {
  const b = basename(path);
  const i = b.lastIndexOf(".");
  return i > 0 ? b.slice(0, i) : b;
}
