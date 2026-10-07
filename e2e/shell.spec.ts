import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

test("三页常驻、设置走编辑通道且可撤销、任务可取消与重试", async () => {
  const { app, page } = await launch();
  // 三页常驻：切页只隐藏
  await page.getByTestId("nav-sources").click();
  await expect(page.getByTestId("page-sources")).toBeVisible();
  await expect(page.getByTestId("page-library")).toBeHidden();
  expect(await page.getByTestId("page-library").count()).toBe(1);
  await page.keyboard.press("Meta+3");
  await expect(page.getByTestId("page-tools")).toBeVisible();

  // 设置：改轻量并发 2 → 3，再撤销
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-jobs").click();
  const row = page.getByTestId("setting-jobs.concurrency_light");
  await row.getByRole("button", { name: /increase|增加|Increase/i }).click().catch(async () => {
    await row.locator("input").fill("3");
    await row.locator("input").press("Enter");
  });
  await expect(row.locator("input")).toHaveValue("3");
  await page.waitForFunction(async () => {
    const r = await window.otto.core.request<Record<string, { value: number }>>("settings.list");
    return r.ok && r.r["jobs.concurrency_light"]!.value === 3;
  });
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  await page.waitForFunction(async () => {
    const r = await window.otto.core.request<Record<string, { value: number }>>("settings.list");
    return r.ok && r.r["jobs.concurrency_light"]!.value === 2;
  });

  // 任务：起一个带子进程的长任务，取消；再重试，再取消
  await page.getByTestId("specimen-toggle").click();
  await expect(page.getByTestId("specimen")).toBeVisible();
  await page.getByRole("button", { name: /60/ }).click();
  const job = page.getByTestId("job").first();
  await expect(job).toHaveAttribute("data-status", "running");
  await job.getByRole("button", { name: "取消" }).click();
  await expect(job).toHaveAttribute("data-status", "cancelled");
  await job.getByRole("button", { name: "重试" }).click();
  await expect(page.getByTestId("job").first()).toHaveAttribute("data-status", "running");
  await page.screenshot({ path: ".cache/playwright-results/shell-tasks.png" });
  await page.getByTestId("job").first().getByRole("button", { name: "取消" }).click();
  await expect(page.getByTestId("job").first()).toHaveAttribute("data-status", "cancelled");
  await app.close();
});

test("模型检测：文件、运行库、实测分开显示", async () => {
  const { app, page } = await launch();
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-models").click();
  await expect(page.getByTestId("model-fcpe")).toHaveAttribute("data-state", "missing");
  await expect(page.getByText(/ONNX Runtime 1\.30\.0/)).toBeVisible();
  await page.screenshot({ path: ".cache/playwright-results/settings-models.png" });
  await app.close();
});

test("外壳布局：播放条在窗口底部，页面占满中间", async () => {
  const { app, page } = await launch();
  const vh = await page.evaluate(() => window.innerHeight);
  const dock = await page.locator("footer").boundingBox();
  expect(dock).not.toBeNull();
  expect(Math.round(dock!.y + dock!.height)).toBe(vh);
  const lib = await page.getByTestId("page-library").locator("..").boundingBox();
  expect(lib!.height).toBeGreaterThan(vh * 0.6);
  await app.close();
});
