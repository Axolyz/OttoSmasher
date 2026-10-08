// 规格 16 R22.13：用伪语言运行，界面上不应残留写死的文字。
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
      const exempt = !text || /^[\s\d.,:;·/\\()\-–—+×♩?⌘⌫⇧⌥↶{}#%→]*$/.test(text) || el?.closest(".mono, kbd, [data-user-data], [aria-hidden=\"true\"]");
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
  for (const g of ["general", "inference", "source", "jobs", "models"]) {
    await page.getByTestId(`settings-group-${g}`).click();
    await page.waitForTimeout(150);
    expect(await unbracketed(page)).toEqual([]);
  }
  await page.keyboard.press("Escape");

  // 有资料时的原片页（查看器、截取面板、设置框）与采样库（列表、舞台）
  const wav = join(mkdtempSync(join(tmpdir(), "otto-pseudo-")), "a.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=duration=3", wav]);
  const sid = await page.evaluate(async (p) => {
    const r = (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    const a = (await window.otto.core.request<Array<{ id: string }>>("assets.listForSource", { sourceId: r.r[0]!.sourceId })) as { r: Array<{ id: string }> };
    await window.otto.core.request("samples.create", { assetId: a.r[0]!.id, start: 0.5, end: 1.5, name: "x" });
    return r.r[0]!.sourceId;
  }, wav);
  await page.getByTestId("nav-sources").click();
  await page.getByTestId("source-group").first().click();
  await page.locator(`[data-testid="source-row"][data-id="${sid}"]`).click();
  await expect(page.getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });
  const tl = (await page.getByTestId("timeline").boundingBox())!;
  await page.mouse.move(tl.x + tl.width * 0.2, tl.y + tl.height / 2);
  await page.mouse.down();
  await page.mouse.move(tl.x + tl.width * 0.4, tl.y + tl.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("clip").click();
  await expect(page.getByTestId("clip-panel")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await page.getByTestId("viewer-menu").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  // 「建立全长采样…」框（单个原片菜单第 8 项）
  await page.getByTestId("viewer-menu").click();
  await page.getByRole("menuitem").nth(7).click();
  await expect(page.getByTestId("whole-dialog")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("whole-dialog")).toHaveCount(0);
  // 批量「作品与类型…」框（批量菜单第 4 项）
  await page.locator(`[data-testid="source-row"][data-id="${sid}"]`).locator("label").first().click();
  await page.getByTestId("page-sources").getByTestId("batch-actions").click();
  await page.getByRole("menuitem").nth(3).click();
  await expect(page.getByTestId("work-type-dialog")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("work-type-dialog")).toHaveCount(0);
  await page.getByTestId("page-sources").getByTestId("batch-clear").click();
  // 时间线右键菜单与「新增区段标签」框
  await page.mouse.click(tl.x + tl.width * 0.3, tl.y + 50, { button: "right" });
  await expect(page.getByTestId("timeline-menu")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("timeline-menu").getByRole("menuitem").nth(4).click();
  await expect(page.getByTestId("annotation-dialog")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await page.getByTestId("nav-library").click();
  await page.getByTestId("sample-row").first().click();
  expect(await unbracketed(page)).toEqual([]);
  // 加本地标签 → 「提升为区段标签」框
  await page.getByTestId("add-tag").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("add-tag-input").fill("t1");
  await page.getByTestId("add-tag-input").press("Enter");
  await page.getByTestId("promote").click();
  await expect(page.getByTestId("promote-preview")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");

  // 导入独立采样框（预览出来以后）
  await app.evaluate(({ dialog }, d) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [d] })) as typeof dialog.showOpenDialog;
  }, wav);
  await page.getByTestId("library-import").click();
  await expect(page.getByTestId("import-preview")).toBeVisible({ timeout: 15000 });
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");

  await page.keyboard.press("Meta+j");
  await page.waitForTimeout(200);
  expect(await unbracketed(page)).toEqual([]);
  await page.screenshot({ path: ".cache/playwright-results/pseudo.png" });
  await app.close();
});
