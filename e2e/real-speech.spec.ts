import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// S1.7（规格 16）：YY1-01 + 人声整轨（开发期钩子，S1.2）→ 默认人声轨 → 导入到文本层（含 OP/ED）→
// 原片页「语音分析…」：分析默认人声轨上的台词段，不需要先建采样（所有者 2026-10-09：分析属于“段 + 那条轨”）；不触发分离、确认框 M/N/K；
// 任务完成后再发起一次全部跳过；之后再从台词段批量建采样，采样直接读到这段的分析；截一个音节 = 只读到一部分（◐）；舞台显示音素。
const FIX = process.env.OTTO_FIXTURES;
const MODELS = resolve("dev-workspace/Models");
test.skip(!FIX || !existsSync(join(MODELS, "pydomino", "phoneme_transition_model.onnx")), "需要 OTTO_FIXTURES 与 dev 模型");

type R<T> = { ok: boolean; r: T; e?: unknown };
test("真实素材 YY1-01：原片入口语音分析、再发起跳过、舞台音素", async () => {
  test.setTimeout(900_000);
  const base = mkdtempSync(join(tmpdir(), "otto-real-speech-"));
  const workspace = join(base, "工作区 real");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const { app, page } = await launch({ workspace });
  const req = async <T>(m: string, p: Record<string, unknown>) => {
    const res = (await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>;
    if (!res.ok) throw new Error(`${m}: ${JSON.stringify(res.e)}`);
    return res.r;
  };
  const sid = (await req<Array<{ sourceId: string }>>("sources.add", { paths: [join(FIX!, "episodes", "YY1-01", "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv")] }))[0]!.sourceId;
  const vocals = await req<{ assetId: string }>("dev.registerStem", { sourceId: sid, path: join(FIX!, "stems", "YY1-01", "hyperacev2_vocals.mp3") });
  const tr = await req<{ sourceVersion: number }>("assets.tracks", { sourceId: sid });
  await req("edits.apply", { batch: { ops: [{ entity: "source", id: sid, version: tr.sourceVersion, fields: { default_vocal: vocals.assetId } }] } });
  await req("subtitles.importDefault", { sourceId: sid });
  const first = await req<{ run: number; blocked: number }>("speech.preview", { entry: "source", ids: [sid] });
  console.log("source entry lines", first.run);
  expect(first.run).toBeGreaterThan(250);

  // 原片页 → 准备 ▾ → 语音分析（还没有任何采样）
  await page.keyboard.press("Meta+2");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await page.getByTestId("prep").click();
  await expect(page.getByTestId("prep-sp")).toContainText(`已分析 0 / ${first.run} 段`);
  await page.getByTestId("prep-sp").getByRole("button").click();
  const dlg = page.getByTestId("speech-dialog");
  await expect(dlg.getByTestId("speech-run")).toContainText(String(first.run));
  await expect(dlg.getByTestId("speech-blocked")).toContainText("0");
  await page.waitForTimeout(300);
  await page.screenshot({ path: ".cache/playwright-results/real-speech-dialog.png" });
  await dlg.getByTestId("speech-submit").click();
  // 不触发分离：资产数不变
  const before = (await req<unknown[]>("assets.listForSource", { sourceId: sid })).length;
  await expect
    .poll(async () => (await req<Array<{ kind: string; status: string }>>("jobs.list", {})).find((j) => j.kind === "speech.analyze")?.status, { timeout: 800_000, intervals: [2000] })
    .toBe("succeeded");
  expect((await req<unknown[]>("assets.listForSource", { sourceId: sid })).length).toBe(before);
  const job = (await req<Array<{ id: string; kind: string; items: { ok: number; failed: number } }>>("jobs.list", {})).find((j) => j.kind === "speech.analyze")!;
  console.log("speech job items", JSON.stringify(job.items));
  expect(job.items.ok).toBeGreaterThan(first.run * 0.9);
  const res = await req<Array<{ name: string; status: string; error: { code: string } | null }>>("speech.results", { jobId: job.id });
  for (const r of res.filter((x) => x.status === "failed").slice(0, 10)) console.log("failed", r.name, r.error?.code);

  // 再发起：未改动的全部跳过（失败的那几条照样会重跑）
  const again = await req<{ run: number; fresh: number }>("speech.preview", { entry: "source", ids: [sid] });
  expect(again.fresh).toBe(job.items.ok);
  expect(again.run).toBe(job.items.failed);

  // 之后再从台词段批量建采样（与逐句建是同一个动作）：直接读到这段的分析（不用重跑）
  type Plan = { token: string; items: Array<{ key: string; status: string }> };
  const from = { kind: "segments", sourceId: sid, track: "default" };
  const lp = await req<Plan>("samples.plan", { from });
  const pending = lp.items.filter((l) => l.status === "pending");
  await req("samples.createPlanned", { from, token: lp.token, keys: pending.map((l) => l.key) });
  expect((await req<{ run: number }>("speech.preview", { entry: "source", ids: [sid] })).run).toBe(job.items.failed);

  // 舞台：アッカリ～ン 的音素
  type Row = { id: string; name: string; asset_id: string; start: number; end: number; analysis: string };
  const all = await req<{ rows: Row[] }>("samples.list", { offset: 0, limit: 500, text: "アッカリ" });
  const ak = all.rows.find((r) => r.name === "アッカリ～ン")!;
  // 对齐窗口 = 段 ± 0.65 秒，采样 = 段 ± 0.1 秒：边上的音素伸出采样范围时是 ◐（只读到这段的一部分）
  expect(["ok", "partial"]).toContain(ak.analysis);
  console.log("akkarin analysis", ak.analysis);
  type Phones = { phones: Array<{ label: string; start: number; end: number }> };
  type View = { units: Array<{ unitId: string; state: string; head: { result: Phones } }>; head: { partial?: boolean; result: Phones } };
  const view = await req<View>("speech.sample", { id: ak.id });
  expect(view.units.map((u) => u.state)).toEqual(["ok"]); // 判定区间 = 这段：只读这一段
  // 这段的分析是整段的；采样只读到自己范围里的音素（字幕结束得比拖长音早时，尾巴在采样范围外 → 不读，列表 ◐）
  const whole = view.units[0]!.head.result.phones.filter((p) => p.label !== "pau").map((p) => p.label).join(" ");
  expect(whole).toBe("a cl k a r i i N");
  const inside = view.head.result.phones.filter((p) => p.label !== "pau").map((p) => p.label).join(" ");
  console.log("akkarin reads", inside);
  expect(whole.startsWith(inside) || whole.endsWith(inside) || whole === inside).toBe(true);
  // 截一个音节（ka）：判定区间 = 选区，读到这段的一部分（◐）
  const ka = view.head.result.phones.find((p) => p.label === "k")!;
  const kaEnd = view.head.result.phones[view.head.result.phones.indexOf(ka) + 1]!.end;
  const cut = await req<{ id: string }>("samples.create", { assetId: ak.asset_id, start: ka.start, end: kaEnd, name: "か", nature: "speech" });
  const cv = await req<View>("speech.sample", { id: cut.id });
  expect(cv.units.length).toBe(1);
  expect(cv.head.partial).toBe(true);
  expect(cv.head.result.phones.map((p) => p.label).join(" ")).toBe("k a");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+1");
  await page.getByTestId("refresh-lists").click().catch(() => {});
  await page.getByTestId("library-search").fill("アッカリ");
  await page.getByTestId("sample-row").filter({ hasText: "アッカリ～ン" }).first().click();
  await expect(page.getByTestId("speech-phone")).toHaveCount(view.head.result.phones.length);
  await expect(page.getByTestId("speech-status")).toHaveText("已分析 · pydomino");
  await page.waitForTimeout(800);
  await page.screenshot({ path: ".cache/playwright-results/real-speech-stage.png" });
  await app.close();
});
