import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 作品/集数推断规则（P10，所有者 2026-10-07）：试算、草稿报错不能保存、保存走编辑通道且可撤销
test("推断规则：试算、校验、保存与撤销", async () => {
  const { app, page } = await launch();
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-source").click();
  const row = page.getByTestId("setting-source.infer_rules");
  const result = row.getByTestId("rules-result");

  // 默认规则试算默认样例
  await expect(result).toHaveText("第 1 条匹配：作品「Yuru Yuri」· 集数「01」");
  await row.getByTestId("rules-sample").fill("[DBD-Raws][Kemono Friends][02][1080P].mkv");
  await expect(result).toHaveText("第 2 条匹配：作品「Kemono Friends」· 集数「02」");
  await row.getByTestId("rules-sample").fill("no pattern here.mkv");
  await expect(result).toHaveAttribute("data-state", "none");

  // 草稿写错：显示是第几条、什么错，保存按钮不可用
  await row.getByRole("button", { name: "添加规则" }).click();
  const last = row.locator('[data-testid^="rule-"]').last();
  await last.fill("^(?P<work>");
  await expect(result).toHaveAttribute("data-state", "error");
  await expect(result).toContainText("第 8 条正则写法有误");
  await expect(row.getByTestId("rules-save")).toBeDisabled();
  await page.screenshot({ path: ".cache/playwright-results/settings-rules-error.png" });

  // 改对：新规则命中，保存
  await last.fill("^(?P<work>no pattern) (?P<episode>here)$");
  await expect(result).toHaveText("第 8 条匹配：作品「no pattern」· 集数「here」");
  await row.getByTestId("rules-save").click();
  await page.waitForFunction(async () => {
    const r = await window.otto.core.request<Record<string, { value: string[] }>>("settings.list");
    return r.ok && r.r["source.infer_rules"]!.value.length === 8;
  });
  await page.screenshot({ path: ".cache/playwright-results/settings-rules.png" });

  // 撤销回到默认
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  await page.waitForFunction(async () => {
    const r = await window.otto.core.request<Record<string, { value: string[]; version: number }>>("settings.list");
    return r.ok && r.r["source.infer_rules"]!.value.length === 7;
  });
  await app.close();
});
