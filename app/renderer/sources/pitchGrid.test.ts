import { describe, expect, it } from "vitest";
import { pitchGrid, pitchRange } from "./pitchGrid";

describe("pitchGrid", () => {
  it("范围窄（6 个半音占 120 像素）：每个半音一条线，音名也逐个标", () => {
    const g = pitchGrid(68, 74, 20);
    expect(g.map((x) => x.midi)).toEqual([68, 69, 70, 71, 72, 73, 74]);
    expect(g.every((x) => x.label)).toBe(true);
    expect(g.find((x) => x.midi === 72)!.c).toBe(true);
  });
  it("跨三个八度（36 个半音占 120 像素）：线距 ≥ 6、音名距 ≥ 16，C 一定有线", () => {
    const px = 120 / 36;
    const g = pitchGrid(48, 84, px);
    const ms = g.map((x) => x.midi);
    for (let i = 1; i < ms.length; i++) expect((ms[i]! - ms[i - 1]!) * px).toBeGreaterThanOrEqual(6 - 1e-9);
    const ls = g.filter((x) => x.label).map((x) => x.midi);
    for (let i = 1; i < ls.length; i++) expect((ls[i]! - ls[i - 1]!) * px).toBeGreaterThanOrEqual(16 - 1e-9);
    for (const c of [48, 60, 72, 84]) expect(ms).toContain(c);
  });
});

describe("pitchRange", () => {
  it("起伏很小时至少 6 个半音、以中位为中心", () => {
    const [a, b] = pitchRange([70.85, 70.9, 71.0, 71.03, 70.57])!;
    expect(b - a).toBeCloseTo(6, 6);
    expect((a + b) / 2).toBeCloseTo(70.9, 1);
  });
  it("起伏大时照实际范围加余量", () => {
    const [a, b] = pitchRange([60, 70, 72])!;
    expect(a).toBeLessThan(60);
    expect(b).toBeGreaterThan(72);
  });
});
