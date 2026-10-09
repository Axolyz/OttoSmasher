import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 原片文件夹（阶段 3.13，所有者 2026-10-07）：第一层子文件夹 = 作品；扫描登记、自动关联字幕、扫描后一键全长采样；
// 作品设置改名 = 改磁盘上的文件夹名；Finder 里改名后重新扫描认出移动
type R<T> = { r: T };
test("原片文件夹：扫描、作品设置改名、Finder 改名后重新扫描", async () => {
  const base = mkdtempSync(join(tmpdir(), "otto-roots-"));
  const root = join(base, "原片库");
  const kf = join(root, "Kemono Friends");
  mkdirSync(kf, { recursive: true });
  mkdirSync(join(root, "Game", "se"), { recursive: true });
  const ff = (...a: string[]) => execFileSync("ffmpeg", ["-v", "error", "-y", ...a]);
  ff("-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=2", "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-c:a", "flac", "-shortest",
    join(kf, "[G] Kemono Friends [01].mkv"));  // prettier-ignore
  writeFileSync(join(kf, "[G] Kemono Friends [01].ja.srt"), "1\n00:00:00,500 --> 00:00:01,000\nすごーい\n");
  ff("-f", "lavfi", "-i", "sine=f=880:duration=0.3", join(root, "Game", "se", "hit.wav"));

  const { app, page } = await launch();
  const req = async <T>(m: string, p: Record<string, unknown> = {}) =>
    ((await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>).r;
  await app.evaluate(({ dialog }, d) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [d] })) as typeof dialog.showOpenDialog;
  }, root);

  // 设置「原片」组：添加原片文件夹 → 扫描登记
  await page.keyboard.press("Meta+2");
  await expect(page.getByTestId("sources-rescan")).toBeDisabled(); // 还没有原片文件夹
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-source").click();
  await page.getByTestId("roots-add").click();
  await expect(page.getByTestId("root-row")).toContainText("2 个作品 · 2 个原片", { timeout: 30000 });
  await page.keyboard.press("Escape");

  // 原片页：两个作品组；字幕（.ja.srt）已自动关联；扫描提示里「为新原片建立全长采样…」
  await expect(page.getByTestId("source-group").filter({ hasText: "Kemono Friends" })).toBeVisible();
  await expect(page.getByTestId("source-group").filter({ hasText: "Game" })).toBeVisible();
  const list = await req<Array<{ id: string; path: string; work: string; episode: string; subtitle_path: string | null; root_id: string | null }>>("sources.list");
  const ep = list.find((x) => x.path.endsWith(".mkv"))!;
  expect([ep.work, ep.episode, !!ep.root_id]).toEqual(["Kemono Friends", "01", true]);
  expect(ep.subtitle_path).toMatch(/\[01\]\.ja\.srt$/);
  await page.getByRole("button", { name: "为新原片建立全长采样…" }).click();
  await page.getByTestId("new-samples").getByTestId("newsamples-run").click();
  await expect.poll(async () => (await req<{ total: number }>("samples.list", { offset: 0, limit: 1 })).total).toBe(2);

  // 作品设置（组头右键）：改名 = 改磁盘上的文件夹名；来源类型整组一起设
  await page.getByTestId("source-group").filter({ hasText: "Game" }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "作品设置…" }).click();
  const ws = page.getByTestId("work-settings");
  await ws.getByTestId("work-settings-name").fill("ゲーム");
  await expect(ws.getByTestId("work-settings-rename-note")).toContainText("改名为「ゲーム」");
  await ws.getByTestId("work-settings-type").fill("游戏");
  await ws.getByTestId("work-settings-save").click();
  await expect(page.getByTestId("source-group").filter({ hasText: "ゲーム" })).toBeVisible();
  expect(existsSync(join(root, "ゲーム", "se", "hit.wav"))).toBe(true);
  expect(existsSync(join(root, "Game"))).toBe(false);
  const hit = (await req<Array<{ path: string; work: string; source_type: string }>>("sources.list")).find((x) => x.path.endsWith("hit.wav"))!;
  expect([hit.work, hit.source_type, existsSync(hit.path)]).toEqual(["ゲーム", "游戏", true]);

  // 「作品与输入设置」：原片文件夹里的原片，作品只读、跟随文件夹
  await page.getByTestId("source-group").filter({ hasText: "Kemono Friends" }).click().catch(() => {});
  await page.getByTestId("source-row").filter({ hasText: "第 01 集" }).click({ button: "right" });
  await page.getByRole("menuitem", { name: /作品、字幕与音轨|作品与输入设置/ }).click();
  await expect(page.getByTestId("field-work-follows")).toContainText("跟随文件夹「Kemono Friends」");
  await page.keyboard.press("Escape");

  // Finder 里改了文件夹名 →「重新扫描」认出移动（不重复登记，采样还在）
  renameSync(kf, join(root, "けものフレンズ"));
  await page.getByTestId("sources-rescan").click();
  await expect(page.getByTestId("source-group").filter({ hasText: "けものフレンズ" })).toBeVisible({ timeout: 30000 });
  const after = await req<Array<{ id: string; work: string }>>("sources.list");
  expect(after.length).toBe(2);
  expect(after.find((x) => x.id === ep.id)!.work).toBe("けものフレンズ");
  expect((await req<{ total: number }>("samples.list", { offset: 0, limit: 1 })).total).toBe(2);
  await page.screenshot({ path: ".cache/playwright-results/roots.png" });
  await app.close();
});
