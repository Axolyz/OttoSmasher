import { describe, expect, it } from "vitest";
import { type PaletteCommand, fromMenu, rankCommands } from "./CommandPalette";

const cmd = (key: string, label: string, group = "g", extra: Partial<PaletteCommand> = {}): PaletteCommand => ({ key, label, group, run: () => {}, ...extra });

describe("命令面板", () => {
  it("子菜单展开成“父 › 子”，分隔线和没有动作的项去掉", () => {
    const out = fromMenu("t", "当前", [
      { id: "a", label: "试听", run: () => {} },
      "-",
      { id: "n", label: "设性质", items: [{ id: "s", label: "语音", shortcut: "1", run: () => {} }] },
      { id: "x", label: "没有动作" },
    ]);
    expect(out.map((c) => [c.key, c.label, c.shortcut])).toEqual([
      ["t/a", "试听", undefined],
      ["t/n/s", "设性质 › 语音", "1"],
    ]);
  });

  it("每个词都要出现；名称开头匹配排最前，不可用的排最后；按分组名也能找到", () => {
    const all = [cmd("1", "导出原声 WAV"), cmd("2", "语音分析…"), cmd("3", "设置 › 语音分析", "全局"), cmd("4", "语音分析（2 项）", "g", { disabled: true }), cmd("5", "前往原片", "全局")];
    expect(rankCommands(all, "语音分析").map((c) => c.key)).toEqual(["2", "3", "4"]);
    expect(rankCommands(all, "设置 语音").map((c) => c.key)).toEqual(["3"]);
    expect(rankCommands(all, "全局").map((c) => c.key)).toEqual(["3", "5"]);
    expect(rankCommands(all, "ｗａｖ").map((c) => c.key)).toEqual(["1"]); // 全角 / 大小写不计
    expect(rankCommands(all, "  ")).toBe(all);
  });
});
