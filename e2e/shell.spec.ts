import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

test("三页常驻、设置走编辑通道且可撤销、任务可取消与重试", async () => {
  const { app, page } = await launch();
  // 三页常驻：切页只隐藏
  await page.getByTestId("nav-sources").click();
  await expect(page.getByTestId("page-sources")).toBeVisible();
  await expect(page.getByTestId("page-library")).toBeHidden();
  expect(await page.getByTestId("page-library").count()).toBe(1);
  await page.keyboard.press("ControlOrMeta+3");
  await expect(page.getByTestId("page-tools")).toBeVisible();

  // 设置：改轻量并发 2 → 3，再撤销
  await page.keyboard.press("ControlOrMeta+,");
  await page.getByTestId("settings-group-jobs").click();
  const row = page.getByTestId("setting-jobs.concurrency_light");
  await row.getByRole("button", { name: /increase|增加|Increase/i }).click().catch(async () => {
    await row.locator("input").fill("3");
    await row.locator("input").press("Enter");
  });
  await expect(row.locator("input")).toHaveValue("3");
  await expect.poll(() => page.evaluate(async () => {
    const r = await window.otto.core.request<Record<string, { value: number }>>("settings.list");
    return r.ok && r.r["jobs.concurrency_light"]!.value === 3;
  })).toBe(true);
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  await expect.poll(() => page.evaluate(async () => {
    const r = await window.otto.core.request<Record<string, { value: number }>>("settings.list");
    return r.ok && r.r["jobs.concurrency_light"]!.value === 2;
  })).toBe(true);

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

  // 提到最前（L50）：模型通道一次一个；第三个提前后，第一个结束时先跑它
  const ids: string[] = [];
  for (let i = 0; i < 3; i++) {
    ids.push(await page.evaluate(async () => {
      const r = await window.otto.core.request<{ id: string }>("jobs.submit", { kind: "selftest.sleep_model", params: { seconds: 60 } });
      if (!r.ok) throw new Error("submit failed");
      return r.r.id;
    }));
  }
  const rowOf = (id: string) => page.locator(`[data-testid="job"][data-job-id="${id}"]`);
  await expect(rowOf(ids[0]!)).toHaveAttribute("data-status", "running");
  await expect(rowOf(ids[1]!).getByTestId("job-promote")).toBeVisible();
  await rowOf(ids[2]!).getByTestId("job-promote").click();
  await expect(rowOf(ids[2]!)).toContainText("已提前");
  await rowOf(ids[0]!).getByRole("button", { name: "取消" }).click();
  await expect(rowOf(ids[2]!)).toHaveAttribute("data-status", "running");
  await expect(rowOf(ids[1]!)).toHaveAttribute("data-status", "queued");
  for (const id of [ids[2]!, ids[1]!]) await rowOf(id).getByRole("button", { name: "取消" }).click();
  await expect(rowOf(ids[2]!)).toHaveAttribute("data-status", "cancelled");
  await app.close();
});

test("模型检测：文件、运行库、实测分开显示", async () => {
  const { app, page } = await launch();
  await page.keyboard.press("ControlOrMeta+,");
  await page.getByTestId("settings-group-models").click();
  await expect(page.getByTestId("model-fcpe")).toHaveAttribute("data-state", "missing");
  await expect(page.getByText(process.platform === "win32" ? /ONNX Runtime 1\.24\.4/ : /ONNX Runtime 1\.30\.0/)).toBeVisible();
  await expect(page.getByTestId("probe-fcpe")).toContainText("未实测");
  // 实测：模型文件不在的不实测，任务照样完成（L6）
  await page.getByTestId("models-probe").click();
  await expect(page.getByTestId("models-probe")).toBeEnabled({ timeout: 20000 });
  await expect.poll(() => page.evaluate(async () => {
    const r = await window.otto.core.request<Array<{ kind: string; status: string }>>("jobs.list");
    return r.ok ? r.r.find((j) => j.kind === "models.probe")?.status : null;
  })).toBe("succeeded");
  await expect(page.getByTestId("probe-fcpe")).toContainText("未实测");
  // 模型权重不随应用分发（所有者 2026-10-10）：显式下载（不在测试里真的下载）、单个下载、从文件导入、打开目录；
  // 缺的模型写明许可（声码器是非商业许可）、直链与放置路径
  await expect(page.getByTestId("models-download")).toHaveText("下载缺少的模型（4 个，约 186.9 MB）");
  await expect(page.getByTestId("model-download-fcpe")).toBeVisible();
  await expect(page.getByTestId("models-import")).toBeEnabled();
  await expect(page.getByTestId("model-pc_nsf_hifigan")).toContainText("CC BY-NC-SA 4.0");
  await expect(page.getByTestId("model-fcpe")).toContainText("https://raw.githubusercontent.com/ARounder-183/HiFiShifter/6432687");
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

// 开发版与发布版并存（所有者 2026-10-31）：源码运行叫 OttoSmasher Dev；顶栏显示当前工作区（悬停看完整路径与版本）
test("顶栏显示当前工作区；源码运行标 Dev", async () => {
  const { app, page, workspace } = await launch();
  const tag = page.getByTestId("workspace-tag");
  await expect(tag).toContainText("Dev");
  await expect(tag).toContainText(workspace.split(/[\\/]/).pop()!);
  await expect(page).toHaveTitle("OttoSmasher Dev");
  await expect(tag).toHaveAttribute("title", new RegExp(workspace.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  await app.close();
});
