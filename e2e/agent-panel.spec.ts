import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 设置 › 命令行与 agent（所有者 2026-10-30）：otto 的位置、复制给 agent 的开场白（不在测试里点“安装 otto 命令”：那会写用户主目录）
test("命令行与 agent：otto 的位置与开场白", async () => {
  const { app, page } = await launch();
  try {
    await app.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.keyboard.press("ControlOrMeta+,");
    await page.getByTestId("settings-group-agent").click();
    const path = await page.getByTestId("agent-otto-path").textContent();
    expect(path).toMatch(/tools[\\/]otto(\.cmd)?$/);
    await page.getByTestId("agent-copy-prompt").click();
    const text = await page.evaluate(() => navigator.clipboard.readText());
    expect(text).toContain("otto");
    expect(text).toContain(path!); // 开发版没装成命令，写完整路径
    expect(text).toContain("guide");
    expect(text).not.toContain("SKILL.md"); // 不用下载 skill（所有者 2026-11-04）
    await expect(page.getByText("已复制")).toBeVisible();
  } finally {
    await app.close();
  }
});
