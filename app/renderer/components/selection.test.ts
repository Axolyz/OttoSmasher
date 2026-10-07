import { describe, expect, it } from "vitest";
import { actionTarget, extendChecked, headerState, menuTarget, stepFocus, toggleChecked, toggleHeader } from "./selection";

const order = ["a", "b", "c", "d", "e"];
const dead = (id: string) => id !== "c"; // c 是失效项

describe("勾选规则（UI_PLAN §6.1）", () => {
  it("切换：失效项不能被勾上，但已勾的可以去掉", () => {
    expect([...toggleChecked(new Set(), "b")]).toEqual(["b"]);
    expect([...toggleChecked(new Set(["b"]), "b")]).toEqual([]);
    expect([...toggleChecked(new Set(), "c", dead)]).toEqual([]);
    expect([...toggleChecked(new Set(["c"]), "c", dead)]).toEqual([]);
  });

  it("Shift 扩展：锚点到目标之间并入，跳过失效项，保留页外已勾选", () => {
    const r = extendChecked(new Set(["x-page2"]), order, "b", "e", dead);
    expect([...r].sort()).toEqual(["b", "d", "e", "x-page2"]);
    // 反方向同样
    expect([...extendChecked(new Set(), order, "d", "a")].sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("Shift 扩展：锚点不在本页 → 只切换目标", () => {
    expect([...extendChecked(new Set(), order, "zz", "b")]).toEqual(["b"]);
    expect([...extendChecked(new Set(), order, null, "b")]).toEqual(["b"]);
  });

  it("↑↓：跳过失效项，到头不动", () => {
    expect(stepFocus(order, "b", 1, dead)).toBe("d");
    expect(stepFocus(order, "d", -1, dead)).toBe("b");
    expect(stepFocus(order, "e", 1)).toBeNull();
    expect(stepFocus(order, "a", -1)).toBeNull();
    expect(stepFocus(order, null, 1)).toBe("a");
    expect(stepFocus(order, null, -1)).toBe("e");
  });

  it("表头三态与切换（跨所有分页）", () => {
    const all = ["a", "b", "d"];
    expect(headerState(new Set(), all)).toBe("none");
    expect(headerState(new Set(["a"]), all)).toBe("some");
    expect(headerState(new Set(all), all)).toBe("all");
    expect([...toggleHeader(new Set(["a"]), all)].sort()).toEqual(all);
    expect([...toggleHeader(new Set(all), all)]).toEqual([]);
    expect(headerState(new Set(), [])).toBe("none");
  });

  it("右键对象：在勾选集里且 ≥2 才作用于勾选集", () => {
    expect(menuTarget(new Set(["a", "b"]), "a")).toEqual({ ids: ["a", "b"], multi: true });
    expect(menuTarget(new Set(["a", "b"]), "c")).toEqual({ ids: ["c"], multi: false });
    expect(menuTarget(new Set(["a"]), "a")).toEqual({ ids: ["a"], multi: false });
  });

  it("删除对象：有勾选 → 勾选集；否则焦点", () => {
    expect(actionTarget(new Set(["a", "b"]), "c")).toEqual(["a", "b"]);
    expect(actionTarget(new Set(), "c")).toEqual(["c"]);
    expect(actionTarget(new Set(), null)).toEqual([]);
  });
});
