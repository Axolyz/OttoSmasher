import { describe, expect, it } from "vitest";
import { basename, clock, parseClock, seconds, stem } from "./format";

describe("format", () => {
  it("clock", () => {
    expect(clock(0)).toBe("0:00.000");
    expect(clock(80.2)).toBe("1:20.200");
    expect(clock(3725.0004)).toBe("1:02:05.000");
    expect(clock(59.9996)).toBe("1:00.000");
    expect(clock(null)).toBe("—");
    expect(clock(NaN)).toBe("—");
    expect(clock(1.25, 1)).toBe("0:01.3");
  });
  it("seconds / paths", () => {
    expect(seconds(1.8)).toBe("1.800");
    expect(basename("/a/b [x]/c ♪.mkv")).toBe("c ♪.mkv");
    expect(stem("C:\\a\\b.c.mkv")).toBe("b.c");
  });
  it("clock：舍入为 0 时没有负号", () => {
    expect(clock(-0.0001)).toBe("0:00.000");
    expect(clock(-0.0004, 3)).toBe("0:00.000");
    expect(clock(-1.5)).toBe("-0:01.500");
  });

  it("parseClock：时钟与秒数，越界与乱写返回 null", () => {
    expect(parseClock("1:20.200")).toBeCloseTo(80.2, 9);
    expect(parseClock("1:02:05.5")).toBeCloseTo(3725.5, 9);
    expect(parseClock("90")).toBe(90);
    expect(parseClock(" 12,5 ")).toBeCloseTo(12.5, 9);
    expect(parseClock("0:07.")).toBe(7);
    expect(parseClock("1:90")).toBeNull();
    expect(parseClock("1:70:00")).toBeNull();
    expect(parseClock("")).toBeNull();
    expect(parseClock("abc")).toBeNull();
    expect(parseClock("-3")).toBeNull();
    expect(parseClock(clock(1436.435)!)).toBeCloseTo(1436.435, 9);
  });
});
