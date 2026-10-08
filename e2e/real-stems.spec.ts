import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 真实素材（只读引用交接包 fixtures，OTTO_FIXTURES）：YY1-01 + 现成分离声部（开发期钩子登记为整轨，S1.2）
// S1.3 默认人声轨、S1.4 导入标记、S1.6 台词采样、S6.1–S6.2 音效采样、S6.3 切换音源不清空选区且截取性质按角色预填
const FIX = process.env.OTTO_FIXTURES;
test.skip(!FIX, "需要 OTTO_FIXTURES 指向交接包的 fixtures 目录");

type R<T> = { ok: boolean; r: T; e?: unknown };
test("真实素材 YY1-01 + 分离声部：默认轨、字幕采样、切换音源", async () => {
  test.setTimeout(180_000);
  const dir = join(FIX!, "episodes", "YY1-01");
  const stems = join(FIX!, "stems", "YY1-01");
  const { app, page } = await launch();
  const req = async <T>(m: string, p: Record<string, unknown>) => {
    const res = (await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>;
    if (!res.ok) throw new Error(`${m}: ${JSON.stringify(res.e)}`);
    return res.r;
  };
  const sid = (await req<Array<{ sourceId: string }>>("sources.add", { paths: [join(dir, "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv")] }))[0]!.sourceId;
  // S1.2：登记现成的声部为整轨
  const vocals = await req<{ assetId: string; stem: string }>("dev.registerStem", { sourceId: sid, path: join(stems, "hyperacev2_vocals.mp3") });
  const effect = await req<{ assetId: string }>("dev.registerStem", { sourceId: sid, path: join(stems, "bandit_v2_effect.mp3") });
  expect(vocals.stem).toBe("vocals");
  // S1.3：「人声／音效与默认轨」只列原混音和整轨；vocals 按别名表已是人声、effect 是音效
  type Tr = { sourceVersion: number; tracks: Array<{ id: string; roles: string[]; origin: string; stemName: string | null }> };
  const tr = await req<Tr>("assets.tracks", { sourceId: sid });
  expect(tr.tracks.map((x) => [x.origin, x.stemName, x.roles])).toEqual([["stream", null, []], ["separation", "vocals", ["vocal"]], ["separation", "effect", ["sfx"]]]);
  await req("edits.apply", { batch: { ops: [{ entity: "source", id: sid, version: tr.sourceVersion, fields: { default_vocal: vocals.assetId, default_sfx: effect.assetId } }] } });
  // S1.4：导入标记后采样数仍为 0
  const pv = await req<{ token: string }>("subtitles.preview", { sourceId: sid });
  await req("subtitles.import", { sourceId: sid, token: pv.token });
  expect((await req<{ total: number }>("samples.list", { offset: 0, limit: 1 })).total).toBe(0);
  // S1.6：台词采样——L3「（京子(きょうこ)たち）アッカリ～ン」→ 名称「アッカリ～ン」，±0.1 秒，语音，绑定 vocals
  type Pv = { token: string; lines: Array<{ annotationId: string; name: string; status: string; start: number; end: number; sampleStart: number; sampleEnd: number; speakers: string[] }> };
  const lp = await req<Pv>("subtitleSamples.preview", { sourceId: sid, kind: "line" });
  const akkarin = lp.lines.find((l) => l.name === "アッカリ～ン")!;
  expect([akkarin.status, akkarin.speakers]).toEqual(["pending", ["京子(きょうこ)たち"]]);
  expect(akkarin.sampleStart).toBeCloseTo(akkarin.start - 0.1, 6);
  const made = await req<{ ids: string[] }>("subtitleSamples.create", { sourceId: sid, kind: "line", token: lp.token, annotationIds: [akkarin.annotationId] });
  const smp = await req<{ name: string; nature: string; asset_id: string; people: string[] }>("samples.get", { id: made.ids[0] });
  expect([smp.name, smp.nature, smp.asset_id, smp.people]).toEqual(["アッカリ～ン", "speech", vocals.assetId, ["京子(きょうこ)たち"]]);
  // S6.2：音效采样——「（殴る音）」→ 殴る音、非调谐单音；「（悲鳴）」×3
  const sp = await req<Pv>("subtitleSamples.preview", { sourceId: sid, kind: "sfx" });
  expect(sp.lines.filter((l) => l.name === "悲鳴").length).toBe(3);
  const hit = sp.lines.find((l) => l.name === "殴る音")!;
  const made2 = await req<{ ids: string[] }>("subtitleSamples.create", { sourceId: sid, kind: "sfx", token: sp.token, annotationIds: [hit.annotationId] });
  const s2 = await req<{ name: string; nature: string; asset_id: string }>("samples.get", { id: made2.ids[0] });
  expect([s2.name, s2.nature, s2.asset_id]).toEqual(["殴る音", "unpitched", effect.assetId]);

  // S6.3：界面上切到音效声部，选区不清空；截取性质预填“非调谐单音”
  await page.keyboard.press("Meta+2");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 60000 });
  const tl = page.getByTestId("source-viewer").getByTestId("timeline");
  const box = (await tl.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.33, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.34, box.y + box.height / 2, { steps: 4 });
  await page.mouse.up();
  const ro = page.getByTestId("readout");
  const a0 = await ro.getAttribute("data-a");
  await page.getByTestId("source-viewer").getByRole("button", { name: /第 1 条音轨/ }).click();
  await page.getByRole("option", { name: "bandit_v2 · effect" }).click();
  await expect(ro).toHaveAttribute("data-a", a0!);
  await page.getByTestId("source-viewer").getByTestId("clip").click();
  await expect(page.getByTestId("clip-panel").locator('[role="radio"][aria-checked="true"]')).toHaveAttribute("data-nature", "unpitched");
  await page.screenshot({ path: ".cache/playwright-results/real-stems.png" });
  await page.keyboard.press("Escape");
  // 外挂声部播放：引擎在选区终点截停
  await page.getByTestId("play-selection").click();
  await expect.poll(() => page.evaluate(() => window.otto.player.position("source")), { timeout: 10000 }).toBeGreaterThan(Number(a0));
  await app.close();
});
