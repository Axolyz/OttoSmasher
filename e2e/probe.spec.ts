// 阶段 1 探针：只在设置了 OTTO_PROBE_FILE（指向交接包 fixtures 里的整集）时运行，不复制素材。
import { writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { ProbeStats } from "../app/shared/protocol";
import { launch } from "./helpers";

test.skip(!process.env.OTTO_PROBE_FILE, "OTTO_PROBE_FILE not set");

test("mpv 渲染桥：1080p HEVC 10bit 播放、跳转、逐帧", async () => {
  test.setTimeout(180_000);
  const { app, page } = await launch();
  await page.getByTestId("nav-tools").click();
  await page.getByTestId("probe-open").click();
  const stats = () => page.evaluate(() => window.ottoProbe!.stats()) as Promise<ProbeStats>;
  await expect.poll(async () => (await stats()).timePos ?? 0, { timeout: 20_000 }).toBeGreaterThan(0.5);

  // 播放 30 秒：每秒采样一次
  const samples: Array<{ t: number; shown: number; drops: number | null; cpu: number }> = [];
  await page.evaluate(() => window.ottoProbe!.control("seek", 300));
  await page.waitForTimeout(1500);
  const s0 = await stats();
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(1000);
    const st = await stats();
    const m = await page.evaluate(() => window.ottoProbe!.metrics());
    samples.push({ t: st.timePos ?? 0, shown: st.framesShown, drops: st.frameDrops, cpu: m.reduce((a, x) => a + x.cpu, 0) });
  }
  const s1 = await stats();
  const shownFps = (s1.framesShown - s0.framesShown) / 30;
  const played = (s1.timePos ?? 0) - (s0.timePos ?? 0);

  // 跳转：发出到画面更新的时间
  const seekMs: number[] = [];
  for (const target of [900, 120, 1300, 600]) {
    const before = (await stats()).framesShown;
    const t0 = Date.now();
    await page.evaluate((x) => window.ottoProbe!.control("seek", x), target);
    await expect.poll(async () => {
      const st = await stats();
      return Math.abs((st.timePos ?? 0) - target) < 0.5 && st.framesShown > before;
    }, { timeout: 10_000, intervals: [10] }).toBe(true);
    seekMs.push(Date.now() - t0);
  }

  // 逐帧：暂停后下一帧的显示延迟
  await page.evaluate(() => window.ottoProbe!.control("toggle"));
  await page.waitForTimeout(500);
  const stepMs: number[] = [];
  for (let i = 0; i < 10; i++) {
    const before = (await stats()).framesShown;
    const t0 = Date.now();
    await page.evaluate(() => window.ottoProbe!.control("step"));
    await expect.poll(async () => (await stats()).framesShown > before, { timeout: 5000, intervals: [5] }).toBe(true);
    stepMs.push(Date.now() - t0);
  }
  await page.screenshot({ path: ".cache/playwright-results/probe.png" });
  const report = {
    file: process.env.OTTO_PROBE_FILE!.split("/").pop(),
    hwdec: s1.hwdec,
    canvas: await page.evaluate(() => {
      const c = document.querySelector("canvas[data-mpv-canvas]") as HTMLCanvasElement;
      return `${c.width}x${c.height}`;
    }),
    playedSeconds: played,
    shownFps,
    videoFps: s1.videoFps,
    renderMsAvg: s1.renderMsAvg,
    renderMsMax: s1.renderMsMax,
    renderCpuMsAvg: s1.renderCpuMsAvg,
    renderCpuMsMax: s1.renderCpuMsMax,
    uiMsAvg: s1.uiMsAvg,
    uiMsMax: s1.uiMsMax,
    frameDropsDuringPlay: (s1.frameDrops ?? 0) - (s0.frameDrops ?? 0),
    decoderDropsDuringPlay: (s1.decoderDrops ?? 0) - (s0.decoderDrops ?? 0),
    cpuPercentAvg: samples.reduce((a, x) => a + x.cpu, 0) / samples.length,
    seekMs,
    stepMs,
  };
  writeFileSync(".cache/playwright-results/probe.json", JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  expect(shownFps).toBeGreaterThan(20);
  await app.close();
});
