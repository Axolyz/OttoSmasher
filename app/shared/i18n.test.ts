import { describe, expect, it } from "vitest";
import { createT, format, pseudoize } from "./i18n";

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
