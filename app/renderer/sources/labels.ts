// 时间线标签的排布（所有者 2026-10-13）：所有图层同一条规则——避让 + 折行。
// 1. 期望位置 = 区间中心；先在自己的区间宽度里放（一行，或折几行：有空格在空格处折，否则按字符折，pau → pa / u；从底部往上排）；
// 2. 自己的区间里放不下（要截短）时，伸进旁边的空白：能用的范围 = 前一个区间的中心到后一个区间的中心，一行放得下就一行，否则按这个宽度折；
// 3. 与已放的标签重叠时在能用的范围里挪开（宽区间的标签往旁边让给窄区间，比如元音让给短辅音），挤得放不下就在剩下的空位里重新折；
// 4. 超过最多行数就在最后一行末尾加“…”；连“一个字 + …”都放不下才省略（悬停看全文）。
// 纯函数：坐标都是像素；量文字宽度的函数由调用方给（画布的 measureText）。

export interface LabelIn {
  /** 区间左右（像素） */
  a: number;
  b: number;
  text: string;
}

export interface LabelOut {
  /** 标签框左边与宽度（像素） */
  x: number;
  w: number;
  /** 从上到下的各行 */
  lines: string[];
  /** 文字被截短了（加了“…”） */
  cut: boolean;
}

export interface LabelOpts {
  measure: (s: string) => number;
  maxLines: number;
  /** 标签之间至少留的空隙（像素） */
  gap?: number;
  /** 可画的左右边界（像素） */
  minX?: number;
  maxX?: number;
}

const ELLIPSIS = "…";

/** 把一段文字按宽度折行（最多 maxLines 行，超出在最后一行加“…”）；宽度连“一个字 + …”都不够 → null */
export function wrapText(text: string, width: number, maxLines: number, measure: (s: string) => number): { lines: string[]; cut: boolean } | null {
  const t = text.replace(/\s+/g, " ").trim();
  if (!t) return { lines: [], cut: false };
  if (measure(t) <= width) return { lines: [t], cut: false };
  const chars = [...t];
  if (measure(chars[0]! + ELLIPSIS) > width && measure(chars[0]!) > width) return null;
  // 有空格按词，否则按字符；单个词比一行还宽时在词里按字符折
  const tokens = t.includes(" ") ? t.split(" ").flatMap((w, i) => (i ? [" ", w] : [w])) : chars;
  const lines: string[] = [];
  let cur = "";
  const push = () => {
    lines.push(cur.trim());
    cur = "";
  };
  for (const tok of tokens) {
    if (measure(cur + tok) <= width) {
      cur += tok;
      continue;
    }
    if (tok === " ") {
      push();
      continue;
    }
    if (cur.trim()) push();
    if (measure(tok) <= width) {
      cur = tok;
      continue;
    }
    for (const ch of tok) {
      if (measure(cur + ch) <= width) cur += ch;
      else {
        if (cur) push();
        cur = ch;
      }
    }
  }
  if (cur.trim()) push();
  const max = Math.max(1, maxLines);
  if (lines.length <= max) return { lines, cut: false };
  const kept = lines.slice(0, max);
  let last = kept[max - 1]!;
  while (last && measure(last + ELLIPSIS) > width) last = [...last].slice(0, -1).join("");
  if (!last && max === 1 && measure(ELLIPSIS) > width) return null;
  kept[max - 1] = last.trimEnd() + ELLIPSIS;
  return { lines: kept, cut: true };
}

function widest(lines: string[], measure: (s: string) => number): number {
  return lines.reduce((m, l) => Math.max(m, measure(l)), 0);
}

/** 一层标签的排布：输入按区间先后排好（a 递增）；返回与输入一一对应（放不下 = null） */
export function layoutLabels(items: LabelIn[], opts: LabelOpts): Array<LabelOut | null> {
  const { measure, maxLines } = opts;
  const gap = opts.gap ?? 4;
  const minX = opts.minX ?? -Infinity;
  const maxX = opts.maxX ?? Infinity;
  const n = items.length;
  const c = items.map((it) => (it.a + it.b) / 2);
  // 能用的范围：相邻区间的中心之间（第一个、最后一个到边界）
  const lo = items.map((_, i) => Math.max(minX, i > 0 ? c[i - 1]! : minX));
  const hi = items.map((_, i) => Math.min(maxX, i < n - 1 ? c[i + 1]! : maxX));
  const fit = (i: number, width: number): LabelOut | null => {
    const r = wrapText(items[i]!.text, Math.max(0, width), maxLines, measure);
    if (!r || !r.lines.length) return null;
    const w = widest(r.lines, measure);
    return { x: c[i]! - w / 2, w, lines: r.lines, cut: r.cut };
  };
  // 先定每个标签的形状（标签尽量留在自己的区间上）：自己的区间里放得下（一行或折几行、不截短）就这样；
  // 否则伸进旁边的空白（能用的范围），一行放得下就一行，还不行就按能用的宽度折
  const out: Array<LabelOut | null> = items.map((it, i) => {
    const own = fit(i, it.b - it.a);
    if (own && !own.cut) return own;
    return fit(i, hi[i]! - lo[i]!);
  });
  const clampTo = (i: number) => {
    const o = out[i]!;
    o.x = Math.min(Math.max(o.x, lo[i]!), hi[i]! - o.w);
  };
  for (let i = 0; i < n; i++) if (out[i]) clampTo(i);
  // 往右推：不和左边已放的重叠
  let prevEnd = -Infinity;
  for (let i = 0; i < n; i++) {
    const o = out[i];
    if (!o) continue;
    if (o.x < prevEnd + gap) o.x = prevEnd + gap;
    prevEnd = o.x + o.w;
  }
  // 往左推：超出右边界或压到右边的，往左让（宽区间的标签让给窄的）
  let nextStart = Infinity;
  for (let i = n - 1; i >= 0; i--) {
    const o = out[i];
    if (!o) continue;
    const limit = Math.min(hi[i]!, nextStart - gap);
    if (o.x + o.w > limit) o.x = limit - o.w;
    nextStart = Math.max(o.x, lo[i]!);
  }
  // 还挤不下的：在剩下的空位里重新折行或截短；连一个字都放不下才省略
  prevEnd = -Infinity;
  for (let i = 0; i < n; i++) {
    const o = out[i];
    if (!o) continue;
    const left = Math.max(lo[i]!, prevEnd + gap);
    let right = hi[i]!;
    for (let j = i + 1; j < n; j++) {
      const q = out[j];
      if (q) {
        right = Math.min(right, q.x - gap);
        break;
      }
    }
    if (o.x < left - 0.5 || o.x + o.w > right + 0.5) {
      const r = fit(i, right - left);
      if (!r) {
        out[i] = null;
        continue;
      }
      r.x = Math.min(Math.max(c[i]! - r.w / 2, left), right - r.w);
      out[i] = r;
    }
    prevEnd = out[i]!.x + out[i]!.w;
  }
  return out;
}
