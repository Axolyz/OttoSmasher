import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 设置 › 命令行与 agent（所有者 2026-10-30）：otto 的位置、复制给 agent 的开场白（不在测试里点“安装 otto 命令”：那会写用户主目录）
test("命令行与 agent：otto 的位置与开场白", async () => {
  const { app, page } = await launch();
  try {
    await app.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.keyboard.press("Meta+,");
    await page.getByTestId("settings-group-agent").click();
    const path = await page.getByTestId("agent-otto-path").textContent();
    expect(path).toMatch(/tools\/otto$/);
    await page.getByTestId("agent-copy-prompt").click();
    const text = await page.evaluate(() => navigator.clipboard.readText());
    expect(text).toContain("otto");
    expect(text).toContain("skills/ottosmasher/SKILL.md");
    await expect(page.getByText("已复制")).toBeVisible();
  } finally {
    await app.close();
  }
});
