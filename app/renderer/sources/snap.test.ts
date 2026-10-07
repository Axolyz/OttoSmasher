import { describe, expect, it } from "vitest";
import { bandAt, bandsAt, snapExtend } from "./snap";

const B = [
  { a: 1, b: 2 },
  { a: 1.9, b: 4 },
  { a: 3, b: 5 },
];

describe("Shift 吸附（R22.8）", () => {
  it("正反向对称、只扩一次不级联", () => {
    expect(snapExtend(1.1, 1.5, B)).toEqual({ a: 1, b: 2 });
    expect(snapExtend(2.5, 1.5, B)).toEqual({ a: 1, b: 4 });
    expect(snapExtend(1.5, 2.5, B)).toEqual({ a: 1, b: 4 });
    expect(snapExtend(6, 7, B)).toEqual({ a: 6, b: 7 });
  });
  it("端点相接不算交叠", () => {
    expect(snapExtend(5, 6, B)).toEqual({ a: 5, b: 6 });
  });
  it("单击取光标下最具体的区间", () => {
    expect(bandAt(1.95, B)).toEqual({ a: 1, b: 2 });
    expect(bandAt(3.5, B)).toEqual({ a: 3, b: 5 });
    expect(bandAt(1.5, B)).toEqual({ a: 1, b: 2 });
    expect(bandAt(5.5, B)).toBeNull();
  });
});

describe("bandsAt", () => {
  it("returns every overlapping band, shortest first", () => {
    const bands = [
      { a: 0, b: 10, id: "long" },
      { a: 2, b: 4, id: "short" },
      { a: 5, b: 6, id: "other" },
    ];
    expect(bandsAt(3, bands).map((b) => b.id)).toEqual(["short", "long"]);
    expect(bandsAt(7, bands).map((b) => b.id)).toEqual(["long"]);
    expect(bandsAt(11, bands)).toEqual([]);
  });
});
