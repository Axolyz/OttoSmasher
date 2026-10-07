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

  const { app, page } = await launch();
  // 系统对话框换成固定返回这个文件夹（主进程里）
  await app.evaluate(({ dialog }, d) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [d] })) as typeof dialog.showOpenDialog;
  }, dir);
  await page.getByTestId("library-import").click();
  const dlg = page.getByTestId("import-dialog");
  await expect(dlg.getByTestId("import-preview")).toBeVisible({ timeout: 20000 });
  await expect(dlg.getByTestId("import-work")).toHaveValue("游戏 A"); // 作品默认 = 文件夹名
  await expect(dlg.getByTestId("import-preview")).toContainText("2 个音频");
  await expect(dlg.getByTestId("import-preview")).toContainText("1 个找到同名画面");
  await expect(dlg.getByTestId("import-unreadable")).toContainText("broken.wav");
  await dlg.getByTestId("import-type").fill("游戏");
  await dlg.locator('[data-nature="unpitched"][role="radio"]').click();
  await page.screenshot({ path: ".cache/playwright-results/import-dialog.png" });
  await dlg.getByTestId("import-submit").click();
  await expect(dlg).toHaveCount(0);

  // 采样库：两个整段采样（名 = 文件名去扩展名，性质 = 选的），打开第一个
  await expect(page.getByTestId("library-total")).toHaveText("2 个采样");
  await expect(page.locator('[data-testid="sample-row"][data-nature="unpitched"]')).toHaveCount(2);
  await expect(page.getByTestId("stage-title")).toBeVisible();
  // 绑定了图片的那个有缩略图
  await expect(page.getByTestId("sample-thumb").locator("img")).toHaveCount(1, { timeout: 15000 });

  // 原片页：作品组「游戏 A」，行显示时长秒、子文件夹、同名画面；短音频查看器
  await page.keyboard.press("Meta+2");
  await page.getByTestId("source-group").filter({ hasText: "游戏 A" }).click();
  const coin = page.getByTestId("source-row").filter({ hasText: "coin.wav" });
  await expect(coin).toContainText("se/ui");
  await expect(page.getByTestId("source-row").filter({ hasText: "hit_01.wav" })).toContainText("同名画面");
  await page.getByTestId("source-row").filter({ hasText: "hit_01.wav" }).click();
  await expect(page.getByTestId("short-head")).toBeVisible();
  await expect(page.getByTestId("short-chip")).toHaveText("短音频 · 0.40 秒");
  await expect(page.getByTestId("transcript")).toBeHidden();
  await expect(page.getByTestId("short-poster").locator("img")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("short-sample")).toContainText("整段 0.000–0.400 秒");
  await expect(page.getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });
  await page.screenshot({ path: ".cache/playwright-results/short-viewer.png" });
  await page.getByTestId("short-open").click();
  await expect(page.getByTestId("page-library")).toBeVisible();
  await expect(page.getByTestId("stage-title")).toHaveText("hit_01");

  // 再导入同一文件夹：已登记的跳过，不重复建采样
  await page.getByTestId("library-import").click();
  await expect(dlg.getByTestId("import-preview")).toContainText("2 个已登记过", { timeout: 20000 });
  await expect(dlg.getByTestId("import-submit")).toBeDisabled();
  await page.keyboard.press("Escape");
  await app.close();
});
