import { describe, expect, it } from "vitest";
import { layoutLabels, wrapText } from "./labels";

// 量宽度：每个字 7 像素
const measure = (s: string) => [...s].length * 7;
const opts = { measure, maxLines: 3, gap: 4, minX: 0, maxX: 1000 };

function noOverlap(out: ReturnType<typeof layoutLabels>) {
  const boxes = out.filter((o) => o).map((o) => [o!.x, o!.x + o!.w] as const);
  for (let i = 1; i < boxes.length; i++) expect(boxes[i]![0]).toBeGreaterThanOrEqual(boxes[i - 1]![1]);
}

describe("wrapText", () => {
  it("一行放得下不折；按字符折；有空格按词折", () => {
    expect(wrapText("pau", 30, 3, measure)).toEqual({ lines: ["pau"], cut: false });
    expect(wrapText("pau", 14, 3, measure)).toEqual({ lines: ["pa", "u"], cut: false });
    expect(wrapText("ab cd ef", 40, 3, measure)).toEqual({ lines: ["ab cd", "ef"], cut: false });
  });
  it("超过最多行数在最后一行加“…”；连一个字都放不下 → null", () => {
    const r = wrapText("一二三四五六七八九十", 21, 2, measure)!;
    expect(r.cut).toBe(true);
    expect(r.lines).toEqual(["一二三", "四五…"]);
    expect(wrapText("一二三", 5, 3, measure)).toBeNull();
    expect(wrapText("一二三四", 14, 1, measure)).toEqual({ lines: ["一…"], cut: true });
  });
});

describe("layoutLabels", () => {
  it("夹在两个元音中间的短辅音（区间比标签窄）仍显示一行，元音标签让位，互不重叠", () => {
    // a 0–60 | k 60–64（只有 4 像素）| a 64–120
    const out = layoutLabels([{ a: 0, b: 60, text: "a" }, { a: 60, b: 64, text: "k" }, { a: 64, b: 120, text: "a" }], opts);
    expect(out.every((o) => o && o.lines.length === 1 && !o.cut)).toBe(true);
    noOverlap(out);
    // k 的标签贴着自己的区间（中心 62）
    expect(Math.abs(out[1]!.x + out[1]!.w / 2 - 62)).toBeLessThan(8);
  });
  it("一连串都很窄时，挤不下的省略，但留下的互不重叠", () => {
    const items = Array.from({ length: 40 }, (_, i) => ({ a: i * 3, b: i * 3 + 3, text: "ny" }));
    const out = layoutLabels(items, opts);
    noOverlap(out);
    expect(out.some((o) => o === null)).toBe(true);
    expect(out.some((o) => o !== null)).toBe(true);
  });
  it("长字幕在自己的区间宽度里折行，最多行数到了加“…”；最多 1 行时截短", () => {
    const text = "結衣：家の中 えっ何してるの";
    const out = layoutLabels([{ a: 100, b: 170, text }, { a: 300, b: 400, text: "次" }], opts);
    expect(out[0]!.lines.length).toBeGreaterThan(1);
    expect(out[0]!.lines.length).toBeLessThanOrEqual(3);
    expect(out[0]!.w).toBeLessThanOrEqual(70);
    // 最多 1 行：自己的区间里要截短时，先伸进旁边的空白；空白也不够才截短
    const spill = layoutLabels([{ a: 100, b: 170, text }, { a: 300, b: 400, text: "次" }], { ...opts, maxLines: 1 });
    expect(spill[0]!.lines).toEqual([text]);
    const one = layoutLabels([{ a: 100, b: 170, text: text + text + text }, { a: 172, b: 260, text: "次の段もある" }], { ...opts, maxLines: 1 });
    expect(one[0]!.lines).toHaveLength(1);
    expect(one[0]!.cut).toBe(true);
    noOverlap(one);
  });
  it("pau 比区间宽、旁边又没空：折成两行", () => {
    const out = layoutLabels([{ a: 0, b: 14, text: "a" }, { a: 14, b: 28, text: "pau" }, { a: 28, b: 42, text: "a" }], { ...opts, gap: 1 });
    expect(out[1]!.lines).toEqual(["pa", "u"]);
    noOverlap(out);
  });
});
