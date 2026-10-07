import { describe, expect, it } from "vitest";
import type { SourceRow } from "../api/types";
import { isShort, relDir } from "./short";

const row = (o: Partial<SourceRow>): SourceRow =>
  ({ path: "/g/se/battle/hit.ogg", import_root: "/g", has_video: false, subtitle_path: null, duration: 0.17, counts: undefined, ...o }) as SourceRow;

describe("short audio sources", () => {
  it("relative folder under the import root", () => {
    expect(relDir(row({}))).toBe("se/battle");
    expect(relDir(row({ path: "/g/hit.ogg" }))).toBe("");
    expect(relDir(row({ path: "/gx/hit.ogg" }))).toBe("");
    expect(relDir(row({ import_root: null }))).toBe("");
    expect(relDir(row({ path: "C:\\g\\se\\hit.ogg", import_root: "C:\\g" }))).toBe("se");
  });
  it("short = no video, no subtitle, imported or ≤ 60 s", () => {
    expect(isShort(row({}))).toBe(true);
    expect(isShort(row({ import_root: null, duration: 600 }))).toBe(false);
    expect(isShort(row({ import_root: null, duration: 30 }))).toBe(true);
    expect(isShort(row({ has_video: true }))).toBe(false);
    expect(isShort(row({ subtitle_path: "/g/a.srt" }))).toBe(false);
  });
});
