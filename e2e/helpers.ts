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
    // 窗口被遮挡或屏幕关闭时 Chromium 会暂停后台窗口的动画与计时器，弹层的退出动画走不完、一直留在页面上（L48 / 命令面板偶发失败）
    args: [".", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling"],
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

/** 伪语言检查（规格 16 R22.13）：页面上可见、没有方括号的文字（用户数据、符号、快捷键除外）。 */
export async function unbracketed(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const bad: string[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n: Node | null = walker.nextNode();
    while (n) {
      const el = n.parentElement;
      const text = (n.textContent ?? "").trim();
      const visible = el && el.offsetParent !== null && getComputedStyle(el).visibility !== "hidden";
      // 允许：纯符号/数字/快捷键、mono 显示的路径与令牌名、用户数据
      // 文件大小（Q21：数字与单位是统一格式，不翻译）
      const exempt = !text || /^[\s\d.,:;·/\\()\-–—+×♩?⌘⌫⇧⌥↶{}#%→]*$/.test(text) || /^[\d.]+ (B|KB|MB|GB|TB)$/.test(text) || el?.closest(".mono, kbd, [data-user-data], [aria-hidden=\"true\"], [data-live-announcer]");
      if (visible && !exempt && !/[[\]]/.test(text) && !/^(Esc|Space|B|OttoSmasher)$/.test(text)) bad.push(text);
      n = walker.nextNode();
    }
    return bad;
  });
}
