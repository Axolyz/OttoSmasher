import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { PlayerState } from "../app/shared/protocol";
import { launch } from "./helpers";

// 原素材页（UI_PLAN §4、§6.1、§6.2）：分组折叠、打开、时间线选区与缩放、播放选区（引擎截停）、导出 WAV、作品与输入设置、删除。
test("原素材页：列表、时间线、导出、设置、删除", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-src-"));
  const mkv = join(dir, "[Group] Test Show [01].mkv");
  const wav = join(dir, "效果音 ♪.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-f", "lavfi", "-i", "sine=f=660:sample_rate=48000:duration=8",
    "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-c:a", "flac", "-metadata:s:a:1", "language=jpn", mkv]);  // prettier-ignore
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=440:duration=2", wav]);
  const { app, page, workspace } = await launch();
  await page.keyboard.press("ControlOrMeta+2");
  await expect(page.getByTestId("page-sources")).toBeVisible();
  await expect(page.getByTestId("sources-add-empty")).toBeVisible();

  await page.evaluate(async (paths) => window.otto.core.request("sources.add", { paths }), [mkv, wav]);
  const groups = page.getByTestId("source-group");
  await expect(groups).toHaveCount(2);
  await expect(groups.nth(0)).toContainText("Test Show");
  await expect(groups.nth(1)).toContainText("未指定作品");
  await expect(page.getByTestId("source-row")).toHaveCount(0); // 默认折叠
  await groups.nth(0).click();
  await page.getByTestId("source-row").first().click();
  const viewer = page.getByTestId("source-viewer");
  await expect(page.getByTestId("top-sources")).toContainText("Test Show · 01");
  await expect(viewer).toContainText("第 2 条音轨 · jpn"); // 默认分析音轨 = 日语那条

  // 波形生成后状态提示消失
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });

  // 分隔条（所有者 2026-11-05）：原素材列表、视频与台词栏都能拖宽窄并记住；收起列表时查看器不重建（播放器留在原处）
  const list = page.getByTestId("source-list");
  const w0 = (await list.boundingBox())!.width;
  const sp = (await page.getByTestId("list-splitter").boundingBox())!;
  await page.mouse.move(sp.x + sp.width / 2, sp.y + 100);
  await page.mouse.down();
  await page.mouse.move(sp.x + sp.width / 2 + 120, sp.y + 100, { steps: 4 });
  await page.mouse.up();
  expect((await list.boundingBox())!.width).toBeGreaterThan(w0 + 80);
  const stageSp = page.getByTestId("stage-splitter");
  const v0 = Number(await stageSp.getAttribute("aria-valuenow"));
  await stageSp.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(stageSp).toHaveAttribute("aria-valuenow", String(v0 - 2));
  await expect
    .poll(async () => page.evaluate(async () => (await window.otto.core.request("ui.get", { page: "sources" })) as { ok: boolean; r: Record<string, unknown> }).then((x) => [typeof x.r.listSplit, Math.round(Number(x.r.stageSplit) * 100)]))
    .toEqual(["number", v0 - 2]);
  await viewer.evaluate((el) => ((el as unknown as { __mark: number }).__mark = 1));
  await page.getByTestId("list-toggle").click();
  await expect(list).toHaveCount(0);
  expect(await viewer.evaluate((el) => (el as unknown as { __mark?: number }).__mark)).toBe(1);
  await page.getByTestId("list-toggle").click();
  await expect(list).toBeVisible();
  await page.screenshot({ path: ".cache/playwright-results/sources-split.png" });

  // 拖出选区（20% → 40% ≈ 1.6–3.2 秒）
  const tl = page.getByTestId("source-viewer").getByTestId("timeline");
  const box = (await tl.boundingBox())!;
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width * 0.2, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.3, y, { steps: 4 });
  await page.mouse.move(box.x + box.width * 0.4, y, { steps: 4 });
  await page.mouse.up();
  const readout = page.getByTestId("readout");
  await expect(readout).toHaveAttribute("data-a", /\d/);
  const [a, b] = [Number(await readout.getAttribute("data-a")), Number(await readout.getAttribute("data-b"))];
  // 选区起止输入框显示同一区间
  await expect(page.getByTestId("sel-start")).toHaveValue(/^0:0\d\.\d{3}$/);
  expect(a).toBeGreaterThan(1.4);
  expect(b).toBeLessThan(3.4);

  // 播放选区：引擎在终点截停（静音输出）
  await page.evaluate(() => {
    (window as unknown as { __st: PlayerState[] }).__st = [];
    window.otto.player.onState((s) => (window as unknown as { __st: PlayerState[] }).__st.push(s));
  });
  await page.getByTestId("play-selection").click();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __st: PlayerState[] }).__st.some((s) => s.player === "source" && s.ended)), { timeout: 8000 })
    .toBe(true);

  // 缩放：Z 放大选区、F 适合窗口
  await viewer.focus();
  await page.keyboard.press("z");
  const zoomed = (await tl.getAttribute("data-view"))!.split(",").map(Number);
  expect(zoomed[1]! - zoomed[0]!).toBeLessThan(3);
  await page.keyboard.press("f");
  await expect(tl).toHaveAttribute("data-view", /^0\.000,8\.0/);
  await page.screenshot({ path: ".cache/playwright-results/sources-page.png" });

  // 导出 WAV：在素材库导出目录
  await page.getByTestId("export-menu").click();
  await page.getByRole("menuitem", { name: "导出 WAV" }).click();
  await expect(page.getByText(/已导出：/)).toBeVisible();
  const exports = join(workspace, "Library", "Exports");
  const day = readdirSync(exports)[0]!;
  const files = readdirSync(join(exports, day));
  expect(files).toHaveLength(1);
  expect(files[0]).toMatch(/^Test Show 01 0_0\d\.\d{3}–0_0\d\.\d{3} · 片段__原混音__\[Group\] Test Show \[01\]__[0-9a-f]{8}_00-00-0\d\.\d{3}-00-00-0\d\.\d{3}__[0-9a-f]{12}\.wav$/);

  // 作品与输入设置：改作品名 → 分组跟着变；可撤销
  await page.getByTestId("viewer-menu").click();
  await page.getByRole("menuitem", { name: "作品与输入设置…" }).click();
  const dlg = page.getByTestId("source-settings");
  await expect(dlg.getByTestId("field-work").locator("input").or(dlg.getByTestId("field-work"))).toHaveValue("Test Show");
  await dlg.getByTestId("field-work").fill("Renamed Show");
  await dlg.getByTestId("confirm-ok").click();
  await expect(groups.nth(0)).toContainText("Renamed Show");
  await expect(page.getByTestId("top-sources")).toContainText("Renamed Show · 01");

  // 删除纯音频原素材：确认框写清删什么、不删什么；文件保留
  await groups.nth(1).click();
  const wavRow = page.getByTestId("source-row").filter({ hasText: "效果音" });
  await wavRow.click({ button: "right" });
  await page.getByRole("menuitem", { name: "删除原素材…" }).click();
  const del = page.getByTestId("source-delete");
  await expect(del).toContainText("不会删除：磁盘上的原素材文件");
  await del.getByTestId("confirm-ok").click();
  await expect(page.getByTestId("source-row").filter({ hasText: "效果音" })).toHaveCount(0);
  expect(existsSync(wav)).toBe(true);
  await app.close();
});

test("短窗口的原素材长菜单可滚动到末项", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-menu-"));
  const wav = join(dir, "Menu Show 01.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:duration=2", wav]);
  const { app, page } = await launch();
  try {
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setSize(900, 600));
    await page.evaluate(async (path) => {
      const r = await window.otto.core.request("sources.add", { paths: [path] });
      if (!r.ok) throw new Error("source setup failed");
    }, wav);
    await page.getByTestId("nav-sources").click();
    await page.getByTestId("source-group").first().click();
    await page.getByTestId("source-row").first().click({ button: "right" });
    const menu = page.getByRole("menu").first();
    await expect(menu).toBeVisible();
    const bounds = await menu.boundingBox();
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(await page.evaluate(() => innerHeight));
    const last = menu.getByRole("menuitem").last();
    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeInViewport();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
  } finally {
    await app.close();
  }
});
