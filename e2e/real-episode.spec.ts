import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import type { PlayerState } from "../app/shared/protocol";
import { launch } from "./helpers";

// 阶段 2 真实素材（只读引用交接包 fixtures，不复制）：OTTO_FIXTURES=<交接包>/fixtures 时运行。
// YY2-07 整集（HEVC 10bit + 两条日语 FLAC）：登记耗时、两条音轨、波形就绪、原素材播放器在真实素材上的范围截停、导出样本数。
const FIX = process.env.OTTO_FIXTURES;
test.skip(!FIX, "需要 OTTO_FIXTURES 指向交接包的 fixtures 目录");

test("真实素材 YY2-07：登记、波形、范围截停、导出", async () => {
  const ep = join(FIX!, "episodes", "YY2-07", "[VCB-Studio] Yuru Yuri 2 [07][Ma10p_1080p][x265_2flac].mkv");
  const { app, page, workspace } = await launch();
  await page.keyboard.press("Meta+2");
  const t0 = Date.now();
  const r = await page.evaluate(async (p) => window.otto.core.request<Array<{ ok: boolean; sourceId: string; work: string; episode: string }>>("sources.add", { paths: [p] }), ep);
  const addMs = Date.now() - t0;
  const res = (r as { r: Array<{ ok: boolean; sourceId: string; work: string; episode: string }> }).r[0]!;
  expect(res.ok).toBe(true);
  expect([res.work, res.episode]).toEqual(["Yuru Yuri 2", "07"]);
  console.log(`REAL add ${addMs} ms`);

  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  // 两条都是日语 → 默认分析音轨是第一条；下拉里有两条
  await expect(page.getByTestId("source-viewer").getByRole("button", { name: /第 1 条音轨 · jpn/ })).toBeVisible();
  await expect(page.getByTestId("source-row").first()).toContainText("2 条音轨");
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 20000 });

  // 原素材播放器：真实 HEVC 上的范围截停（静音输出）
  await page.evaluate(() => {
    (window as unknown as { __st: PlayerState[] }).__st = [];
    window.otto.player.onState((s) => (window as unknown as { __st: PlayerState[] }).__st.push(s));
  });
  for (const [a, b] of [[600.25, 601.0], [83.5, 84.123]] as const) {
    const gen = await page.evaluate(([x, y]) => window.otto.player.playRange(x, y), [a, b] as const);
    await expect
      .poll(() => page.evaluate((g) => (window as unknown as { __st: PlayerState[] }).__st.find((s) => s.player === "source" && s.gen === g && s.ended)?.time ?? null, gen), { timeout: 10000 })
      .toBeCloseTo(b, 3);
    console.log(`REAL range ${a}-${b} ended`);
  }
  await page.screenshot({ path: ".cache/playwright-results/real-episode.png" });

  // 导出：样本数 = 区间 × 48000
  const assets = await page.evaluate(async (s) => window.otto.core.request<Array<{ id: string }>>("assets.listForSource", { sourceId: s }), res.sourceId);
  const aid = (assets as { r: Array<{ id: string }> }).r[1]!.id;
  const out = await page.evaluate(
    async (id) => window.otto.core.request<{ path: string }>("exports.wav", { assetId: id, start: 83.5, end: 84.123, content: "real", track: "原混音" }),
    aid,
  );
  const path = (out as { r: { path: string } }).r.path;
  expect(path.startsWith(join(workspace, "Library"))).toBe(true);
  const buf = readFileSync(path);
  const dataLen = buf.readUInt32LE(buf.indexOf("data") + 4);
  expect(dataLen / (3 * 2)).toBe(Math.round(84.123 * 48000) - Math.round(83.5 * 48000));
  await app.close();
});
