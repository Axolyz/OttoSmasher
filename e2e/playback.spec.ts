import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { PlayerState } from "../app/shared/protocol";
import { launch } from "./helpers";

// 播放闭环（规格 16 R22.2–R22.5、R22.7）：引擎截停、结束只通知一次、过期请求不能改终点、普通跳转恢复无界、
// 全应用一个声音、试听时钟为区间本地秒。声音输出为 null（不出声）。
test("播放：范围截停、代次、一个声音、试听", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-play-"));
  const media = join(dir, "片 [x] ♪.mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6", "-c:v", "libx264", "-c:a", "flac", media]);  // prettier-ignore
  const { app, page } = await launch();

  const added = await page.evaluate(async (p) => (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })), media);
  expect(JSON.stringify(added)).toContain("\"ok\":true");
  const sourceId = (added as { r: Array<{ sourceId: string }> }).r[0]!.sourceId;
  const assets = await page.evaluate(async (id) => (await window.otto.core.request<Array<{ id: string }>>("assets.listForSource", { sourceId: id })), sourceId);
  const assetId = (assets as { r: Array<{ id: string }> }).r[0]!.id;

  await page.evaluate(() => {
    const c = document.createElement("canvas");
    c.dataset.ottoVideo = "";
    c.style.cssText = "position:fixed;left:0;top:0;width:320px;height:180px;z-index:9999";
    document.body.appendChild(c);
    (window as unknown as { __states: PlayerState[] }).__states = [];
    window.otto.player.onState((s) => (window as unknown as { __states: PlayerState[] }).__states.push(s));
  });
  const states = () => page.evaluate(() => (window as unknown as { __states: PlayerState[] }).__states);
  const waitEnded = async (player: string, gen: number) => {
    await expect.poll(async () => (await states()).filter((s) => s.player === player && s.gen === gen && s.ended).length, { timeout: 8000 }).toBe(1);
    return (await states()).find((s) => s.player === player && s.gen === gen && s.ended)!;
  };

  expect(await page.evaluate(() => window.otto.player.attachVideo())).toBe(true);
  const info = await page.evaluate((id) => window.otto.player.openSource(id), sourceId);
  expect(info.hasVideo).toBe(true);
  expect(info.duration).toBeCloseTo(6, 1);

  // 范围截停：在终点停下，结束只通知一次
  let gen = await page.evaluate(() => window.otto.player.playRange(1.0, 1.4));
  let end = await waitEnded("source", gen);
  expect(end.time!).toBeCloseTo(1.4, 2);
  await page.waitForTimeout(300);
  expect((await states()).filter((s) => s.player === "source" && s.gen === gen && s.ended)).toHaveLength(1);

  // 往回的范围：上一次停在 1.4，这次 1.0–1.2，旧位置不能让它立刻“结束”（旧版 mpv 桥的教训：跳转完成前丢弃位置）
  gen = await page.evaluate(() => window.otto.player.playRange(1.0, 1.2));
  end = await waitEnded("source", gen);
  expect(end.time!).toBeCloseTo(1.2, 3);
  const during = (await states()).filter((s) => s.player === "source" && s.gen === gen && s.playing);
  expect(during.length).toBeGreaterThan(0); // 真的播放过，不是一开始就判为结束

  // 过期请求不能改终点：连续两个请求，只按最新的截停
  gen = await page.evaluate(() => {
    window.otto.player.playRange(2.0, 4.0);
    return window.otto.player.playRange(3.0, 3.2);
  });
  end = await waitEnded("source", gen);
  expect(end.time!).toBeCloseTo(3.2, 2);
  expect((await states()).some((s) => s.player === "source" && s.gen === gen - 1 && s.ended)).toBe(false);

  // 普通跳转后恢复无界播放
  await page.evaluate(() => {
    window.otto.player.seek(3.3);
    window.otto.player.play();
  });
  await expect.poll(async () => (await states()).filter((s) => s.player === "source").at(-1)!.time!, { timeout: 5000 }).toBeGreaterThan(3.8);

  // 全应用一个声音：试听开始 → 原素材暂停；试听时钟为区间本地秒
  gen = await page.evaluate((id) => window.otto.player.audition(id, 0.2, 0.5), assetId);
  await expect.poll(async () => (await states()).filter((s) => s.player === "source").at(-1)!.playing).toBe(false);
  end = await waitEnded("audition", gen);
  expect(end.time!).toBeCloseTo(0.3, 2);

  // 错误：Core 的错误码原样传回，不换轨
  const err = await page.evaluate(async () => {
    try {
      await window.otto.player.audition("no-such-asset", 0, 1);
      return null;
    } catch (e) {
      return (e as { code: string }).code;
    }
  });
  expect(err).toBe("asset-not-found");
  await page.screenshot({ path: ".cache/playwright-results/playback.png" });
  await app.close();
});
