import { describe, expect, it } from "vitest";
import { needsChoice, pickProperties } from "./file-pick";

describe("文件对话框", () => {
  it("导入和模型都先问选文件还是文件夹，其他入口不用问", () => {
    expect(needsChoice("import")).toBe(true);
    expect(needsChoice("models")).toBe(true);
    expect(needsChoice("media")).toBe(false);
    expect(needsChoice("folder")).toBe(false);
  });

  it("选了哪种就只给哪种，不会同时要求文件和文件夹（Windows 上那样只能选文件夹）", () => {
    expect(pickProperties("import", "files")).toEqual(["openFile", "multiSelections"]);
    expect(pickProperties("import", "folder")).toEqual(["openDirectory", "multiSelections"]);
    expect(pickProperties("models", "files")).toEqual(["openFile", "multiSelections"]);
    expect(pickProperties("folder")).toEqual(["openDirectory", "createDirectory"]);
    expect(pickProperties("media")).toEqual(["openFile", "multiSelections"]);
    expect(pickProperties("subtitle")).toEqual(["openFile"]);
  });
});
