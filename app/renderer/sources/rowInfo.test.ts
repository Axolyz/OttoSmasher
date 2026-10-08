import { describe, expect, it } from "vitest";
import type { SourceRow } from "../api/types";
import { durationText, noSubtitles, relDir } from "./rowInfo";

const row = (o: Partial<SourceRow>): SourceRow =>
  ({ path: "/g/se/battle/hit.ogg", import_root: "/g", has_video: false, subtitle_path: null, duration: 0.17, ...o }) as SourceRow;

describe("source row info", () => {
  it("relative folder under the import root", () => {
    expect(relDir(row({}))).toBe("se/battle");
    expect(relDir(row({ path: "/g/hit.ogg" }))).toBe("");
    expect(relDir(row({ path: "/gx/hit.ogg" }))).toBe("");
    expect(relDir(row({ import_root: null }))).toBe("");
    expect(relDir(row({ path: "C:\\g\\se\\hit.ogg", import_root: "C:\\g" }))).toBe("se");
  });
  it("duration: seconds under a minute, clock above", () => {
    expect(durationText(0.17)).toContain("0.17");
    expect(durationText(1436)).toBe("23:56");
  });
  it("no subtitles = no file and no markers", () => {
    expect(noSubtitles(row({}))).toBe(true);
    expect(noSubtitles(row({ subtitle_path: "/a.srt" }))).toBe(false);
    expect(noSubtitles(row({ counts: { lines: 0, hasMarkers: true, oped: 0, samples: 0 } }))).toBe(false);
  });
});
