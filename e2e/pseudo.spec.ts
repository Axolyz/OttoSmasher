// 规格 16 R22.13：用伪语言运行，界面上不应残留写死的文字。
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

async function unbracketed(page: import("@playwright/test").Page): Promise<string[]> {
  return page.evaluate(() => {
    const bad: string[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n: Node | null = walker.nextNode();
    while (n) {
      const el = n.parentElement;
      const text = (n.textContent ?? "").trim();
      const visible = el && el.offsetParent !== null && getComputedStyle(el).visibility !== "hidden";
      // 允许：纯符号/数字/快捷键、mono 显示的路径与令牌名、用户数据
      const exempt = !text || /^[\s\d.,:;·/\\()\-–—+×♩?⌘⌫⇧⌥↶{}#%]*$/.test(text) || el?.closest(".mono, kbd, [data-user-data], [aria-hidden=\"true\"]");
      if (visible && !exempt && !/[[\]]/.test(text) && !/^(Esc|Space|B|OttoSmasher)$/.test(text)) bad.push(text);
      n = walker.nextNode();
    }
    return bad;
  });
}

test("伪语言下没有写死的界面文字", async () => {
  const { app, page } = await launch({ locale: "pseudo" });
  for (const nav of ["nav-library", "nav-sources", "nav-tools"]) {
    await page.getByTestId(nav).click();
    expect(await unbracketed(page)).toEqual([]);
  }
  await page.getByTestId("specimen-toggle").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Meta+,");
  for (const g of ["general", "inference", "jobs", "models"]) {
    await page.getByTestId(`settings-group-${g}`).click();
    await page.waitForTimeout(150);
    expect(await unbracketed(page)).toEqual([]);
  }
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+j");
  await page.waitForTimeout(200);
  expect(await unbracketed(page)).toEqual([]);
  await page.screenshot({ path: ".cache/playwright-results/pseudo.png" });
  await app.close();
});
