import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 采样库导入与短音频原片（规格 06 §6.6、ARCHITECTURE §4.10、UI_PLAN §4/§8）
test("导入文件夹：预览（同名画面、读不了的）→ 导入 → 采样库与短音频查看器", async () => {
  const dir = join(mkdtempSync(join(tmpdir(), "otto-import-")), "游戏 A");
  mkdirSync(join(dir, "se", "ui"), { recursive: true });
  const ff = (...a: string[]) => execFileSync("ffmpeg", ["-v", "error", "-y", ...a]);
  ff("-f", "lavfi", "-i", "sine=f=660:duration=0.4", join(dir, "hit_01.wav"));
  ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=1:duration=1", "-frames:v", "1", join(dir, "hit_01.png"));
  ff("-f", "lavfi", "-i", "sine=f=880:duration=0.65", join(dir, "se", "ui", "coin.wav"));
  writeFileSync(join(dir, "broken.wav"), "RIFF");
  // 没有同名音频的视频：也作为采样导入（所有者 2026-10-07）
  ff("-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2", "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-shortest", join(dir, "clip.mp4"));

  const { app, page } = await launch();
  // 系统对话框换成固定返回这个文件夹（主进程里）
  await app.evaluate(({ dialog }, d) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [d] })) as typeof dialog.showOpenDialog;
  }, dir);
  await page.getByTestId("library-import").click();
  const dlg = page.getByTestId("import-dialog");
  await expect(dlg.getByTestId("import-preview")).toBeVisible({ timeout: 20000 });
  await expect(dlg.getByTestId("import-work")).toHaveValue("游戏 A"); // 统一设为：文件名推断不出同一作品 → 文件夹名
  await expect(dlg.getByTestId("import-groups")).toContainText("全部归入「游戏 A」");
  await expect(dlg.getByTestId("import-preview")).toContainText("3 个文件（其中 1 个视频）");
  await expect(dlg.getByTestId("import-preview")).toContainText("1 个找到同名画面");
  await expect(dlg.getByTestId("import-unreadable")).toContainText("broken.wav");
  await dlg.getByTestId("import-type").fill("游戏");
  await dlg.locator('[data-nature="unpitched"][role="radio"]').click();
  await page.screenshot({ path: ".cache/playwright-results/import-dialog.png" });
  await dlg.getByTestId("import-submit").click();
  await expect(dlg).toHaveCount(0);

  // 采样库：两个整段采样（名 = 文件名去扩展名，性质 = 选的），打开第一个
  await expect(page.getByTestId("library-total")).toHaveText("3 个采样");
  await expect(page.locator('[data-testid="sample-row"][data-nature="unpitched"]')).toHaveCount(3);
  await expect(page.getByTestId("stage-title")).toBeVisible();
  // 绑定了图片的那个有缩略图
  await expect(page.getByTestId("sample-thumb").locator("img")).toHaveCount(2, { timeout: 15000 }); // 绑定图片的那个 + 视频

  // 原片页：作品组「游戏 A」，行显示时长秒、子文件夹、同名画面；查看器只有一种，只按内容调整（所有者 2026-10-07）
  await page.keyboard.press("Meta+2");
  await page.getByTestId("source-group").filter({ hasText: "游戏 A" }).click();
  const coin = page.getByTestId("source-row").filter({ hasText: "coin.wav" });
  await expect(coin).toContainText("se/ui");
  await expect(page.getByTestId("source-row").filter({ hasText: "hit_01.wav" })).toContainText("同名画面");
  await page.getByTestId("source-row").filter({ hasText: "hit_01.wav" }).click();
  // 没有视频、没有字幕：上面一行缩矮，画面区显示绑定的图片；台本、准备清单照常
  await expect(page.getByTestId("source-viewer")).toHaveAttribute("data-compact", "true");
  await expect(page.getByTestId("bound-picture")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("transcript")).toBeVisible();
  await expect(page.getByTestId("prep")).toBeVisible();
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });
  await page.screenshot({ path: ".cache/playwright-results/import-audio-viewer.png" });
  // 导入的视频：照常播放画面
  await page.getByTestId("source-row").filter({ hasText: "clip.mp4" }).click();
  await expect(page.locator("canvas[data-otto-video]")).toBeVisible();
  await expect(page.getByTestId("source-viewer")).not.toHaveAttribute("data-compact", "true");
  // 它的采样：时间线头「派生采样 n」点开
  await page.getByTestId("source-row").filter({ hasText: "hit_01.wav" }).click();
  await page.getByTestId("derived-button").click();
  await page.getByTestId("derived-menu").getByRole("menuitem", { name: /hit_01/ }).click();
  await expect(page.getByTestId("page-library")).toBeVisible();
  await expect(page.getByTestId("stage-title")).toHaveText("hit_01");

  // 再导入同一文件夹（所有者 2026-10-07 允许）：原片不重复登记，勾着全长采样就再建一个
  await page.getByTestId("library-import").click();
  await expect(dlg.getByTestId("import-preview")).toContainText("3 个已登记过", { timeout: 20000 });
  await dlg.getByTestId("import-submit").click();
  await expect(page.getByTestId("library-total")).toHaveText("6 个采样");

  // 原片页「＋」：同一个导入框，「直接建立全长采样」默认不勾 → 只登记原片；之后「建立全长采样…」补建
  const more = join(dir, "..", "原片B");
  mkdirSync(more);
  ff("-f", "lavfi", "-i", "sine=f=440:duration=1.5", join(more, "[Group] Show B [01].wav"));
  await app.evaluate(({ dialog }, d) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [d] })) as typeof dialog.showOpenDialog;
  }, more);
  await page.keyboard.press("Meta+2");
  await page.getByTestId("sources-add").click();
  await expect(dlg.getByTestId("import-preview")).toContainText("1 个文件", { timeout: 20000 });
  await expect(dlg.getByTestId("import-whole")).not.toBeChecked();
  await expect(dlg.getByTestId("import-nature")).toHaveCount(0);
  await expect(dlg.getByTestId("import-work")).toHaveValue("Show B"); // 统一设为：文件名推断出同一个作品就预填它
  await dlg.getByTestId("import-work-mode").getByRole("radio", { name: "按文件名推断" }).click();
  await expect(dlg.getByTestId("import-groups")).toContainText("Show B 1 个");
  await dlg.getByTestId("import-submit").click();
  await expect(page.getByTestId("source-settings")).toBeVisible(); // 只为第一个新原片弹「作品与输入设置」
  await expect(page.getByTestId("field-work")).toHaveValue("Show B");
  await page.keyboard.press("Escape");
  const total = async () =>
    ((await page.evaluate(async () => window.otto.core.request("samples.list", { offset: 0, limit: 1 }))) as { r: { total: number } }).r.total;
  expect(await total()).toBe(6);
  await page.getByTestId("viewer-menu").click();
  await page.getByTestId("menu-whole").click();
  // 建采样是一个动作（所有者 2026-10-09）：整段原片走批量整页，默认全勾
  await page.getByTestId("new-samples").getByTestId("newsamples-run").click();
  await expect.poll(total).toBe(7);

  // 批量「作品与类型…」：勾选两个原片 → 统一改作品（重新归组）→ 撤销
  await page.getByTestId("sources-search").fill("游戏 A"); // 搜索时组都展开
  for (const name of ["coin.wav", "clip.mp4"]) await page.getByTestId("source-row").filter({ hasText: name }).locator("label").first().click();
  await page.getByTestId("page-sources").getByTestId("batch-actions").click();
  await page.getByRole("menuitem", { name: /设作品与类型/ }).click();
  const wt = page.getByTestId("work-type-dialog");
  await wt.getByTestId("work-type-work").fill("游戏 C");
  await wt.getByTestId("work-type-ok").click();
  await page.getByTestId("sources-search").fill("");
  await expect(page.getByTestId("source-group").filter({ hasText: "游戏 C" })).toContainText("2");
  await page.keyboard.press("Meta+z");
  await expect(page.getByTestId("source-group").filter({ hasText: "游戏 C" })).toHaveCount(0);
  await app.close();
});
