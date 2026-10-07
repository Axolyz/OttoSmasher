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
    env: { ...process.env, OTTO_WORKSPACE: workspace, OTTO_DEV: "1", OTTO_LOCALE: opts.locale ?? "zh-CN" },
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByTestId("nav-library")).toBeVisible();
  // 等 Core 就绪（横幅消失）
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
  await page.waitForFunction(async () => (await window.otto.core.status()).state === "ready");
  return { app, page, workspace };
}
