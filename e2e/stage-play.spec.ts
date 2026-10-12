import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { PlayerState } from "../app/shared/protocol";
import { launch, refreshLists } from "./helpers";

// 详情区播放（所有者 2026-10-12）：单击放光标；▶ 播放从光标播到采样末尾；选区 / 循环；播完光标停在播到的位置；
// 波形区快捷键（Space、Shift+Space、I/O、←→）；判定区间车道默认隐藏，勾选才显示。
test("详情区：光标、选区播放、快捷键、判定区间开关", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-stageplay-"));
  const wav = join(dir, "stageplay.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=12", wav]);
  const { app, page } = await launch();
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    await req("samples.create", { assetId: add.r[0]!.assets[0]!.assetId, start: 5.0, end: 6.0, name: "ひかり", nature: "speech" });
    (window as unknown as { __states: PlayerState[] }).__states = [];
    window.otto.player.onState((s) => (window as unknown as { __states: PlayerState[] }).__states.push(s));
  }, wav);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("sample-row").filter({ hasText: "ひかり" }).click();
  const card = page.getByTestId("stage-wave");
  const tl = card.getByTestId("timeline");
  await expect(tl).toBeVisible();
  // 头部不再有「试听原声」：动作条是 播放 · 选区 · 循环
  await expect(page.getByTestId("stage-actions").getByTestId("stage-play")).toHaveText("播放");
  await expect(page.getByTestId("stage-play-range")).toBeDisabled();
  await expect(card).toHaveAttribute("data-cursor", "5.000");

  // 判定区间车道：默认没有，勾上才出现（时间线高一条车道）
  const h0 = (await tl.boundingBox())!.height;
  await page.getByTestId("stage-judge-lane").click();
  await expect.poll(async () => (await tl.boundingBox())!.height).toBeGreaterThan(h0 + 10);
  await page.getByTestId("stage-judge-lane").click();
  await expect.poll(async () => (await tl.boundingBox())!.height).toBeLessThan(h0 + 1);

  // 单击放光标（在采样中间附近）
  const box = (await tl.boundingBox())!;
  const view = (await tl.getAttribute("data-view"))!.split(",").map(Number);
  const xAt = (t: number) => box.x + ((t - view[0]!) / (view[1]! - view[0]!)) * box.width;
  await page.mouse.click(xAt(5.6), box.y + 60);
  await expect.poll(async () => Number(await card.getAttribute("data-cursor"))).toBeCloseTo(5.6, 1);

  // Space（波形有焦点）= 从光标播到采样末尾；播完光标停在采样末尾
  await page.keyboard.press(" ");
  await expect(card).toHaveAttribute("data-mode", "play");
  await expect.poll(async () => card.getAttribute("data-mode"), { timeout: 8000 }).toBeNull();
  await expect.poll(async () => Number(await card.getAttribute("data-cursor"))).toBeCloseTo(6.0, 2);
  // 播完以后引擎位置不越过区间终点
  expect(await page.evaluate(() => window.otto.player.position("audition"))).toBeLessThanOrEqual(0.4 + 1e-6);

  // I / O：光标处设选区；Shift+Space 只播选区，播完光标停在选区终点
  await page.mouse.click(xAt(5.1), box.y + 60);
  await page.keyboard.press("i");
  await page.mouse.click(xAt(5.9), box.y + 60);
  await page.keyboard.press("o");
  const readout = page.getByTestId("stage-readout");
  await expect.poll(async () => Number(await readout.getAttribute("data-a"))).toBeCloseTo(5.1, 1);
  await expect.poll(async () => Number(await readout.getAttribute("data-b"))).toBeCloseTo(5.9, 1);
  const b = Number(await readout.getAttribute("data-b"));
  await card.focus();
  await page.keyboard.press("Shift+Space");
  await expect(card).toHaveAttribute("data-mode", "sel");
  await expect.poll(async () => card.getAttribute("data-mode"), { timeout: 8000 }).toBeNull();
  await expect.poll(async () => Number(await card.getAttribute("data-cursor"))).toBeCloseTo(b, 2);

  // 循环：按钮再按一次停止
  await page.getByTestId("stage-loop").click();
  await expect(card).toHaveAttribute("data-mode", "loop");
  await page.waitForTimeout(800);
  await expect(card).toHaveAttribute("data-mode", "loop"); // 循环不会自己结束
  await page.getByTestId("stage-loop").click();
  await expect.poll(async () => card.getAttribute("data-mode")).toBeNull();

  // ← → 移动光标（停在窗口内）；Esc 清除选区
  await card.focus();
  const c0 = Number(await card.getAttribute("data-cursor"));
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(async () => Number(await card.getAttribute("data-cursor"))).toBeCloseTo(c0 + 0.001, 3);
  for (let i = 0; i < 3; i++) await page.keyboard.press("Alt+ArrowRight");
  await expect(card).toHaveAttribute("data-cursor", "7.000");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("stage-play-range")).toBeDisabled();
  await page.screenshot({ path: ".cache/playwright-results/stage-play.png" });
  await app.close();
});
