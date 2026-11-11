import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { PlayerState } from "../app/shared/protocol";
import { launch, refreshLists } from "./helpers";

test("窄窗采样库：一屏一页时，试听和缩放保留浏览位置", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-lib-paging-"));
  const wav = join(dir, "paging.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=sample_rate=48000:duration=5", wav]);
  const { app, page } = await launch();
  try {
    const resize = (height: number) => app.evaluate(({ BrowserWindow }, h) => {
      BrowserWindow.getAllWindows()[0]!.setContentSize(900, h);
    }, height);
    await resize(860);
    await page.evaluate(async (path) => {
      const req = window.otto.core.request;
      const add = (await req("sources.add", { paths: [path] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
      const assetId = add.r[0]!.assets[0]!.assetId;
      for (let i = 0; i < 40; i++) {
        await req("samples.create", { assetId, start: i / 20, end: i / 20 + 2, name: `Paging ${i}`, nature: "speech" });
      }
    }, wav);
    await refreshLists(page);
    await expect(page.getByTestId("library-total")).toHaveText("40 个采样");
    const rows = page.getByTestId("sample-row");
    const next = page.getByRole("button", { name: "下一页" });
    const first = await rows.first().getAttribute("data-id");
    await next.click();
    await expect(rows.first()).not.toHaveAttribute("data-id", first!);
    const second = await rows.first().getAttribute("data-id");
    await next.click();
    await expect(rows.first()).not.toHaveAttribute("data-id", second!);
    const anchor = (await rows.first().getAttribute("data-id"))!;
    const anchored = page.locator(`[data-testid="sample-row"][data-id="${anchor}"]`);
    const rowCount = await rows.count();

    await anchored.getByTestId("sample-play").click();
    await expect(page.getByTestId("dock-stop")).toBeVisible();
    await expect(rows.first()).toHaveAttribute("data-id", anchor);
    await expect(page.getByTestId("dock-stop")).toBeHidden({ timeout: 6000 });
    await expect(rows.first()).toHaveAttribute("data-id", anchor);

    await resize(610);
    await expect.poll(() => rows.count()).toBeLessThan(rowCount);
    await expect(anchored).toBeAttached();
    const smallCount = await rows.count();
    await resize(860);
    await expect.poll(() => rows.count()).toBeGreaterThan(smallCount);
    await expect(anchored).toBeAttached();
  } finally {
    await app.close();
  }
});

// 截取与采样库（规格 16 R7.1、R7.2、R2.6；UI_PLAN §2、§5、§6.1、§8）
test("截取：建议名与性质 → 保存 → 采样库；试听、1/2/3/0、全选、返回原素材、删除", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-lib-"));
  const mkv = join(dir, "[Group] Test Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  const { app, page } = await launch();
  await page.keyboard.press("ControlOrMeta+2");
  await page.evaluate(async (p) => window.otto.core.request("sources.add", { paths: [p] }), mkv);
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });

  const tl = page.getByTestId("source-viewer").getByTestId("timeline");
  const box = (await tl.boundingBox())!;
  const drag = async (fa: number, fb: number) => {
    await page.mouse.move(box.x + box.width * fa, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * fb, box.y + box.height / 2, { steps: 6 });
    await page.mouse.up();
  };
  await drag(0.25, 0.5);

  // 截取面板：建议名 = 原素材名 起–止；原混音没有角色 → 未分类
  await page.getByTestId("source-viewer").getByTestId("clip").click();
  const panel = page.getByTestId("clip-panel");
  await expect(panel.getByTestId("clip-name")).toHaveValue(/^Test Show 01 0:0\d\.\d{3}–0:0\d\.\d{3}$/);
  await expect(panel.locator('[role="radio"][aria-checked="true"]')).toHaveAttribute("data-nature", "unclassified");
  await panel.getByTestId("clip-name").fill("やったー");
  await panel.locator('[data-nature="speech"][role="radio"]').click();
  await panel.getByTestId("clip-save").click();

  // 跳到采样库并打开新采样
  await expect(page.getByTestId("page-library")).toBeVisible();
  await expect(page.getByTestId("stage-title")).toHaveText("やったー");
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  const row = page.getByTestId("sample-row").first();
  await expect(row).toHaveAttribute("data-nature", "speech");

  // Space 试听焦点：试听播放器在终点截停
  await page.evaluate(() => {
    (window as unknown as { __st: PlayerState[] }).__st = [];
    window.otto.player.onState((s) => (window as unknown as { __st: PlayerState[] }).__st.push(s));
  });
  await page.getByTestId("sample-row").first().focus();
  await page.keyboard.press("Space");
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __st: PlayerState[] }).__st.some((s) => s.player === "audition" && s.ended)), { timeout: 8000 })
    .toBe(true);

  // 数字键 3 → 非调谐单音（编辑通道，可撤销）
  await page.keyboard.press("3");
  await expect(row).toHaveAttribute("data-nature", "unpitched");
  const id = await row.getAttribute("data-id");
  const nat = await page.evaluate(async (i) => ((await window.otto.core.request<{ nature: string }>("samples.get", { id: i })) as { r: { nature: string } }).r.nature, id);
  expect(nat).toBe("unpitched");

  // R7.1 同一范围再保存一次 → 两个采样
  await page.keyboard.press("ControlOrMeta+2");
  await page.getByTestId("source-viewer").getByTestId("clip").click();
  await page.getByTestId("clip-save").click();
  await expect(page.getByTestId("library-total")).toHaveText("2 个采样");

  // ⌘A 勾选全部匹配
  await page.getByTestId("sample-row").first().focus();
  await page.keyboard.press("ControlOrMeta+a");
  await expect(page.getByTestId("library-checked")).toContainText("2 项已勾选");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("library-checked")).toHaveCount(0);

  // 返回原素材：带着区间作为选区
  const before = await page.getByTestId("stage-title").textContent();
  await page.getByTestId("back-to-source").click();
  await expect(page.getByTestId("page-sources")).toBeVisible();
  await expect(page.getByTestId("readout")).toHaveAttribute("data-a", /\d/);
  // 时间线放大到该区间（不是整段）
  await expect.poll(async () => {
    const v = (await page.getByTestId("source-viewer").getByTestId("timeline").getAttribute("data-view"))!.split(",").map(Number);
    return v[1]! - v[0]!;
  }).toBeLessThan(4);
  // 画面不是黑的：原素材页隐藏时加载，切回来后应重画当前帧
  await page.waitForTimeout(400);
  // WebGL 画布读不回像素（preserveDrawingBuffer: false），用真实截图量亮度
  const shot = await page.locator("canvas[data-otto-video]").screenshot();
  const lit = await page.evaluate(async (b64) => {
    const img = new Image(); // 页面的 CSP 不许 fetch(data:)，但 img-src 允许 data:
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const g = new OffscreenCanvas(32, 18);
    const ctx = g.getContext("2d")!;
    ctx.drawImage(img, 0, 0, 32, 18);
    const d = ctx.getImageData(0, 0, 32, 18).data;
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) sum += d[i]! + d[i + 1]! + d[i + 2]!;
    return sum / (d.length / 4);
  }, shot.toString("base64"));
  expect(lit).toBeGreaterThan(30);
  await page.screenshot({ path: ".cache/playwright-results/back-to-source.png" });

  // 删除焦点采样（确认框）
  await page.keyboard.press("ControlOrMeta+1");
  await expect(page.getByTestId("stage-title")).toHaveText(before!);
  await page.getByTestId("sample-row").first().focus();
  await page.keyboard.press("Delete");
  await page.getByTestId("sample-delete").getByTestId("confirm-ok").click();
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.screenshot({ path: ".cache/playwright-results/library.png" });

  // 列表缩略图（R22.11）：采样行取中点帧、原素材行取整片中点帧（Core 后台生成后补上）
  await expect(page.getByTestId("sample-thumb").first().locator("img")).toBeVisible({ timeout: 15000 });
  const remaining = await page.getByTestId("sample-row").first().getAttribute("data-id");
  // 采样车道（R7.6；所有者 2026-10-12 改名）：原素材页时间线头「采样 n」→ 单击打开（跳到采样库）
  await page.keyboard.press("ControlOrMeta+2");
  await expect(page.getByTestId("source-thumb").first().locator("img")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("derived-button")).toHaveText("采样 1");
  await page.getByTestId("derived-button").click();
  await page.getByTestId(`menu-${remaining}`).click();
  await expect(page.getByTestId("page-library")).toBeVisible();
  await expect(page.locator(`[data-testid="sample-row"][data-id="${remaining}"]`)).toHaveAttribute("data-focus", /.*/);
  // 「在采样库里列出全部」：查找栏出现临时“原素材：…”块，移除后回到全部（L16）
  await page.keyboard.press("ControlOrMeta+2");
  await page.getByTestId("derived-button").click();
  await page.getByTestId("menu-in-library").click();
  await expect(page.getByTestId("find-source")).toContainText("Test Show 01");
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.getByTestId("find-source").getByRole("button", { name: "移除原素材条件" }).click();
  await expect(page.getByTestId("find-source")).toHaveCount(0);
  await expect(page.getByTestId("stage-title")).toBeVisible();
  await page.screenshot({ path: ".cache/playwright-results/library-thumbs.png" });
  await app.close();
});
