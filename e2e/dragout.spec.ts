import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 拖出（规格 12 §12.2、16 R21.8）：⌥ + 拖动越过 4 px 才生成，生成后交给系统拖拽。
// 系统拖拽本身（拖到 Finder / REAPER）要人工验收；这里在主进程截下 startDrag 的参数，核对文件。
test("拖出：时间线选区、勾选集、未越过阈值不生成", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-drag-"));
  const wav = join(dir, "拖出 ♪.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=duration=4", wav]);
  const { app, page, workspace } = await launch();
  await app.evaluate(({ BrowserWindow }) => {
    const g = globalThis as unknown as { __drags: string[][] };
    g.__drags = [];
    for (const w of BrowserWindow.getAllWindows())
      w.webContents.startDrag = (item: { files?: string[]; file: string }) => {
        g.__drags.push(item.files ?? [item.file]);
      };
  });
  const drags = () => app.evaluate(() => (globalThis as unknown as { __drags: string[][] }).__drags);

  await page.keyboard.press("Meta+2");
  const sid = await page.evaluate(async (p) => {
    const r = (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    return r.r[0]!.sourceId;
  }, wav);
  await page.getByTestId("source-group").first().click();
  await page.locator(`[data-testid="source-row"][data-id="${sid}"]`).click();
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });
  const tl = (await page.getByTestId("source-viewer").getByTestId("timeline").boundingBox())!;
  const y = tl.y + tl.height / 2;
  await page.mouse.move(tl.x + tl.width * 0.25, y);
  await page.mouse.down();
  await page.mouse.move(tl.x + tl.width * 0.5, y, { steps: 5 });
  await page.mouse.up();

  // ⌥ 在选区内按下但只动 3 px：不生成
  await page.keyboard.down("Alt");
  await page.mouse.move(tl.x + tl.width * 0.35, y);
  await page.mouse.down();
  await page.mouse.move(tl.x + tl.width * 0.35 + 3, y);
  await page.mouse.up();
  await page.waitForTimeout(300);
  expect(await drags()).toEqual([]);

  // 越过 4 px：生成选区 WAV 并发起系统拖拽
  await page.mouse.down();
  await page.mouse.move(tl.x + tl.width * 0.35 + 30, y, { steps: 4 });
  await expect.poll(async () => (await drags()).length).toBe(1);
  await page.mouse.up();
  await page.keyboard.up("Alt");
  const [first] = await drags();
  expect(first).toHaveLength(1);
  expect(existsSync(first![0]!)).toBe(true);
  expect(first![0]!.startsWith(join(workspace, "Library", "Exports"))).toBe(true);
  // 选区没被这次拖动改掉（⌥ 拖动不是普通选区拖动）
  await expect(page.getByTestId("readout")).toHaveAttribute("data-a", /\d/);

  // 采样库：两个采样都勾选，在其中一行上 ⌥ 拖 → 整个勾选集
  await page.evaluate(async (s) => {
    const a = (await window.otto.core.request<Array<{ id: string }>>("assets.listForSource", { sourceId: s })) as { r: Array<{ id: string }> };
    await window.otto.core.request("samples.create", { assetId: a.r[0]!.id, start: 0.5, end: 1.0, name: "一" });
    await window.otto.core.request("samples.create", { assetId: a.r[0]!.id, start: 1.5, end: 2.0, name: "二" });
  }, sid);
  await page.keyboard.press("Meta+1");
  const rows = page.getByTestId("sample-row");
  await expect(rows).toHaveCount(2);
  for (const i of [0, 1]) await rows.nth(i).locator("label").first().click();
  const rb = (await rows.nth(1).boundingBox())!;
  await page.keyboard.down("Alt");
  await page.mouse.move(rb.x + rb.width * 0.5, rb.y + rb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.5 + 40, rb.y + rb.height / 2, { steps: 4 });
  await expect.poll(async () => (await drags()).length).toBe(2);
  await page.mouse.up();
  await page.keyboard.up("Alt");
  const second = (await drags())[1]!;
  expect(second).toHaveLength(2);
  expect(second.map((p) => p.split("/").pop()!.split("__")[0]).sort()).toEqual(["一", "二"]);
  await app.close();
});
