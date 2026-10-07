// 全应用一种固定格式（ARCHITECTURE §7：数字、时长、日期不随界面语言变）。

/** 时钟：`M:SS.mmm`，满一小时 `H:MM:SS.mmm`；未知显示 `—`（未知不是零，P7）。 */
export function clock(t: number | null | undefined, decimals = 3): string {
  if (t == null || !Number.isFinite(t)) return "—";
  const scale = 10 ** decimals;
  let units = Math.round(Math.abs(t) * scale);
  // 舍入后为 0 时不带负号（播放头在 0 之前一点点时曾显示 “-0:00.000”）
  const neg = t < 0 && units > 0;
  const frac = units % scale;
  units = (units - frac) / scale;
  const s = units % 60;
  const m = Math.floor(units / 60) % 60;
  const h = Math.floor(units / 3600);
  const sec = String(s).padStart(2, "0") + (decimals ? "." + String(frac).padStart(decimals, "0") : "");
  const body = h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  return neg ? "-" + body : body;
}

/**
 * 解析时间输入（选区起止的精确输入）：`H:MM:SS.mmm`、`M:SS.mmm`、`SS.mmm` 或纯秒数；
 * 秒和分超过 59 只在最高一级允许（`90` = 90 秒，`1:90` 不合法）。不合法返回 null。
 */
export function parseClock(text: string): number | null {
  const s = text.trim().replace(/[\uFF0C,]/g, "."); // 全角逗号也当小数点
  if (!/^\d+(:\d{1,2}){0,2}(\.\d*)?$/.test(s)) return null;
  const parts = s.split(":");
  const last = Number(parts.pop());
  if (!Number.isFinite(last) || (parts.length && last >= 60)) return null;
  let total = last;
  let mul = 60;
  for (let i = parts.length - 1; i >= 0; i--) {
    const v = Number(parts[i]);
    if (i > 0 && v >= 60) return null;
    total += v * mul;
    mul *= 60;
  }
  return total;
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
