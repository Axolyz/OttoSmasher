import { describe, expect, it } from "vitest";
import { boundaries, boundaryNear, limits, moveBoundary } from "./bounds";

const B = [
  { key: "x", a: 1, b: 2 },
  { key: "y", a: 2, b: 3 },
  { key: "z", a: 4, b: 5 },
];

describe("overlay boundary editing", () => {
  it("merges shared boundaries", () => {
    const all = boundaries(B);
    expect(all.map((b) => b.t)).toEqual([1, 2, 3, 4, 5]);
    expect(all[1]!.items).toEqual([
      { key: "x", side: "b" },
      { key: "y", side: "a" },
    ]);
  });
  it("moves shared boundary together and never crosses neighbours", () => {
    const all = boundaries(B);
    const lim = limits(all, 1, B, 10);
    expect(lim[0]).toBeCloseTo(1.01);
    expect(lim[1]).toBeCloseTo(2.99);
    const moved = moveBoundary(B, all[1]!, 9, lim);
    expect(moved[0]!.b).toBeCloseTo(2.99);
    expect(moved[1]!.a).toBeCloseTo(2.99);
    expect(moved[2]).toBe(B[2]); // 没动的原样
    // z 的起点：左邻是 y 的终点 3，右边不能越过自己的终点
    const lz = limits(all, 3, B, 10);
    expect(lz[0]).toBe(3);
    expect(lz[1]).toBeCloseTo(4.99);
    // 最后一条边界不超过时长
    expect(limits(all, 4, B, 5.5)[1]).toBe(5.5);
  });
  it("overlapping bands keep boundary order", () => {
    const o = [
      { key: "p", a: 1, b: 5 },
      { key: "q", a: 3, b: 7 },
    ];
    const all = boundaries(o);
    expect(limits(all, 1, o, 10)).toEqual([1, 5]); // q 的起点在 p 的起点与终点之间
  });
  it("finds the nearest boundary within px", () => {
    const all = boundaries(B);
    const toX = (t: number) => t * 100;
    expect(boundaryNear(all, 203, toX, 5)).toBe(1);
    expect(boundaryNear(all, 250, toX, 5)).toBe(-1);
  });
});
