import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type ElectronApplication, type Page, _electron as electron, expect, test } from "@playwright/test";

export interface Launched {
  app: ElectronApplication;
  page: Page;
  workspace: string;
}

// 失败时留一张截图（放在测试的输出目录，云端跑完会带回来）。只有合成数据才进云端（AGENTS §5）
let lastPage: Page | null = null;
test.afterEach(async ({}, info) => {
  if (info.status !== info.expectedStatus && lastPage && !lastPage.isClosed()) {
    await lastPage.screenshot({ path: info.outputPath("failure.png") }).catch(() => {});
  }
  lastPage = null;
});

/** 用一个临时工作区启动真实的 Electron 应用（路径带中文与空格，规格 16 R23.1）。 */
export async function launch(
  opts: {
    /** 界面语言。null = 不固定：按真实流程来（上次用的语言、设置里切换），这时必须同时给 userData */
    locale?: string | null;
    workspace?: string;
    /** 界面缓存文件夹（语言选择存在这里）：不碰开发版自己的 */
    userData?: string;
    /** 这条测试就是要让界面报错 */
    allowPageErrors?: boolean;
  } = {},
): Promise<Launched> {
  const workspace = opts.workspace ?? join(mkdtempSync(join(tmpdir(), "otto-e2e-")), "工作区 test");
  const env: Record<string, string> = { ...(process.env as Record<string, string>), OTTO_WORKSPACE: workspace, OTTO_DEV: "1", OTTO_STRICT_API: "1", OTTO_MPV_AO: process.env.OTTO_MPV_AO ?? "null" };
  if (opts.locale === null) delete env.OTTO_LOCALE;
  else env.OTTO_LOCALE = opts.locale ?? "zh-CN";
  if (opts.userData) env.OTTO_USER_DATA = opts.userData;
  const app = await electron.launch({
    // 窗口被遮挡或屏幕关闭时 Chromium 会暂停后台窗口的动画与计时器，弹层的退出动画走不完、一直留在页面上（L48 / 命令面板偶发失败）
    args: [".", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling"],
    // OTTO_MPV_AO=null：测试不出声（仍按实时推进）；OTTO_STRICT_API=1：Core 核对每个命令的返回值与命令目录一致（ROADMAP L2）
    env,
  });
  // 任何窗口的界面报错都算这条测试失败（所有者 2026-11-04）：没有断言走到的地方也能发现界面崩溃。
  // pageerror 只收未捕获的错误（比如事件回调里的）；渲染错误被全局兜底接住，要看它打的 otto-render-crash。
  // 用软断言：事件回调里抛错到不了测试，软断言直接记在当前测试上，不用每个文件注册钩子
  const watch = (w: Page) => {
    if (opts.allowPageErrors) return;
    const fail = (text: string) => void expect.soft(text, "界面不能报错").toBe("");
    w.on("pageerror", (e) => fail(`${e.message}\n${e.stack ?? ""}`));
    w.on("console", (m) => {
      if (m.type() === "error" && m.text().startsWith("otto-render-crash")) fail(m.text());
    });
  };
  app.on("window", watch);
  const page = await app.firstWindow();
  watch(page);
  lastPage = page;
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
