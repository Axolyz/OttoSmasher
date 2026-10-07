import { describe, expect, it } from "vitest";
import { basename, clock, seconds, stem } from "./format";

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
});
