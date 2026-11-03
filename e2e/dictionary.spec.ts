import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 用户辞典（规格 08 §8.2.4、16 R10.2）：Tab 插入制表符、逐行报错（行号）、保存 = 编译 + 原子启用、撤销；没有模型时预览明确报错
test("用户辞典：逐行校验、保存启用、撤销、预览", async () => {
  const { app, page } = await launch();
  await page.keyboard.press("ControlOrMeta+,");
  await page.getByTestId("settings-group-frontend").click();
  const box = page.getByTestId("dict-text");
  const status = page.getByTestId("dict-status");
  await expect(status).toHaveText("0 条");

  // Tab 在编辑框里插入制表符（不移走焦点）
  await box.click();
  await page.keyboard.type("歳納");
  await page.keyboard.press("Tab");
  await page.keyboard.type("トシノウ");
  await page.keyboard.press("Enter");
  await page.keyboard.type("歳納");
  await page.keyboard.press("Tab");
  await page.keyboard.type("としのう");
  await expect(box).toHaveValue("歳納\tトシノウ\n歳納\tとしのう");
  await expect(status).toHaveText("1 处错误");
  await expect(page.getByTestId("dict-errors")).toContainText("第 2 行：表记与第 1 行重复");
  await expect(page.getByTestId("dict-save")).toBeDisabled();
  await page.screenshot({ path: ".cache/playwright-results/dictionary-error.png" });

  // 改对 → 保存并启用
  await box.fill("歳納\tトシノウ\n京子\tキョーコ");
  await expect(status).toHaveText("2 条");
  await page.getByTestId("dict-save").click();
  await expect(page.getByText("用户辞典已保存并启用（2 条）")).toBeVisible({ timeout: 20000 });
  await expect.poll(() => page.evaluate(async () => {
    const r = await window.otto.core.request<Record<string, { value: { compiled: string | null } }>>("settings.list");
    return r.ok ? r.r["frontend.user_dictionary"]!.value.compiled : null;
  })).toMatch(/^user-[0-9a-f]{16}\.dic$/);
  await expect(page.getByTestId("dict-save")).toBeDisabled();

  // 预览：工作区里没有 tsqyomi 权重 → 明确报错（不跳过前端）
  await page.getByTestId("dict-preview").click();
  await expect(page.getByText(/模型文件不在应放的位置（tsqyomi）/)).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: ".cache/playwright-results/dictionary.png" });

  // 撤销 → 回到空辞典，编辑框跟着更新
  await page.getByTestId("dict-status").click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("dict-text")).toBeHidden();
  await page.getByTestId("undo").click();
  await page.keyboard.press("ControlOrMeta+,");
  await page.getByTestId("settings-group-frontend").click();
  await expect(page.getByTestId("dict-text")).toHaveValue("");
  await app.close();
});
