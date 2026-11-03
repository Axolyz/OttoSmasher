import { describe, expect, it } from "vitest";
import { createT, englishPlurals, format, pseudoize, windowsKeys } from "./i18n";

describe("englishPlurals()", () => {
  it("fixes singular and (s) by the number", () => {
    expect(englishPlurals("1 lines")).toBe("1 line");
    expect(englishPlurals("2 lines")).toBe("2 lines");
    expect(englishPlurals("11 lines")).toBe("11 lines");
    expect(englishPlurals("2.1 lines")).toBe("2.1 lines");
    expect(englishPlurals("1 sample(s)")).toBe("1 sample");
    expect(englishPlurals("4 model(s) missing")).toBe("4 models missing");
    expect(englishPlurals("Imported 1 lines, 1 SFX hints, 3 entries")).toBe("Imported 1 line, 1 SFX hint, 3 entries");
    expect(englishPlurals("1 OP/ED range(s)")).toBe("1 OP/ED range");
  });
});

describe("windowsKeys()", () => {
  it("spells out the macOS key symbols", () => {
    expect(windowsKeys("⌘K")).toBe("Ctrl+K");
    expect(windowsKeys("⌘F · ⌘⇧F")).toBe("Ctrl+F · Ctrl+Shift+F");
    expect(windowsKeys("⌥/Alt+拖动选区")).toBe("Alt+拖动选区");
    expect(windowsKeys("按住拖动：⌥ 拖出原声，⌥⇧ 拖出卡拍")).toBe("按住拖动：Alt 拖出原声，Alt+Shift 拖出卡拍");
    expect(windowsKeys("Space · ⇧Space")).toBe("Space · Shift+Space");
    expect(windowsKeys("没有键符")).toBe("没有键符");
    expect(windowsKeys("Show in Finder")).toBe("Show in File Explorer");
    expect(windowsKeys("在 Finder 中显示", "文件资源管理器")).toBe("在 文件资源管理器 中显示");
  });
});

describe("t()", () => {
  const cat = { hi: "你好 {name}", "n_one": "{n} item", "n_other": "{n} items", plain: "x" };
  it("replaces parameters and keeps unknown ones", () => {
    expect(format("a {x} {y}", { x: 1 })).toBe("a 1 {y}");
    expect(createT(cat)("hi", { name: "京子" })).toBe("你好 京子");
  });
  it("chooses plural keys by n when both exist", () => {
    const t = createT(cat);
    expect(t("n", { n: 1 })).toBe("1 item");
    expect(t("n", { n: 3 })).toBe("3 items");
  });
  it("pseudo-locale brackets and lengthens every message", () => {
    const t = createT(cat, { pseudo: true });
    expect(t("plain")).toBe(pseudoize("x"));
    expect(t("plain").startsWith("[") && t("plain").endsWith("]")).toBe(true);
    expect(t("missing.key")).toBe("[!missing.key]");
  });
  it("strict mode throws on missing keys", () => {
    expect(() => createT(cat, { strict: true })("nope")).toThrow(/missing i18n key/);
  });
});
