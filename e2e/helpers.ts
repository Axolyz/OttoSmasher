import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type ElectronApplication, type Page, _electron as electron, expect } from "@playwright/test";

export interface Launched {
  app: ElectronApplication;
  page: Page;
  workspace: string;
}

/** 用一个临时工作区启动真实的 Electron 应用（路径带中文与空格，规格 16 R23.1）。 */
export async function launch(opts: { locale?: string; workspace?: string } = {}): Promise<Launched> {
  const workspace = opts.workspace ?? join(mkdtempSync(join(tmpdir(), "otto-e2e-")), "工作区 test");
  const app = await electron.launch({
    args: ["."],
    // OTTO_MPV_AO=null：测试不出声（仍按实时推进）；OTTO_STRICT_API=1：Core 核对每个命令的返回值与命令目录一致（ROADMAP L2）
    env: { ...process.env, OTTO_WORKSPACE: workspace, OTTO_DEV: "1", OTTO_STRICT_API: "1", OTTO_LOCALE: opts.locale ?? "zh-CN", OTTO_MPV_AO: process.env.OTTO_MPV_AO ?? "null" },
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByTestId("nav-library")).toBeVisible();
  // 等 Core 就绪（横幅消失）
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
  // 注意：waitForFunction 不会等异步函数的结果（Promise 本身为真），要用 poll
  await expect.poll(() => page.evaluate(async () => (await window.otto.core.status()).state), { timeout: 20000 }).toBe("ready");
  return { app, page, workspace };
}

/** 刷新浏览列表：有“资料已更新”就点它；自己窗口的请求引起的变化不提示（P8 / L13），测试里用页面的刷新钩子 */
export async function refreshLists(page: Page): Promise<void> {
  const b = page.getByTestId("refresh-lists");
  if (await b.isVisible().catch(() => false)) return b.click();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("otto:refresh-lists")));
}
