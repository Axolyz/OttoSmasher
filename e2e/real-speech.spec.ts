import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// S1.7（规格 16）：YY1-01 + 人声整轨（开发期钩子，S1.2）→ 默认人声轨 → 导入标记 → OP/ED → 全部台词采样 →
// 原片页「语音分析…」：默认范围、不触发分离、确认框 M/N/K；任务完成后再发起一次全部跳过；舞台与原片时间线显示音素。
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
  const pv = await req<{ token: string }>("subtitles.preview", { sourceId: sid });
  await req("subtitles.import", { sourceId: sid, token: pv.token });
  await req("oped.identify", { sourceId: sid });
  type Pv = { token: string; lines: Array<{ annotationId: string; name: string; status: string }> };
  const lp = await req<Pv>("subtitleSamples.preview", { sourceId: sid, kind: "line" });
  const pending = lp.lines.filter((l) => l.status === "pending");
  await req("subtitleSamples.create", { sourceId: sid, kind: "line", token: lp.token, annotationIds: pending.map((l) => l.annotationId) });

  // 原片页 → 准备 ▾ → 语音分析
  await page.keyboard.press("Meta+2");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await page.getByTestId("prep").click();
  await expect(page.getByTestId("prep-sp")).toContainText(`已分析 0 / ${pending.length} 条语音`);
  await page.getByTestId("prep-sp").getByRole("button").click();
  const dlg = page.getByTestId("speech-dialog");
  await expect(dlg.getByTestId("speech-run")).toContainText(String(pending.length));
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
  expect(job.items.ok).toBeGreaterThan(pending.length * 0.9);
  const res = await req<Array<{ name: string; status: string; error: { code: string } | null }>>("speech.results", { jobId: job.id });
  for (const r of res.filter((x) => x.status === "failed").slice(0, 10)) console.log("failed", r.name, r.error?.code);

  // 再发起：未改动的全部跳过（失败的那几条照样会重跑）
  const again = await req<{ run: number; fresh: number }>("speech.preview", { entry: "source", ids: [sid] });
  expect(again.fresh).toBe(job.items.ok);
  expect(again.run).toBe(job.items.failed);

  // 舞台：アッカリ～ン 的音素
  const all = await req<{ rows: Array<{ id: string; name: string }> }>("samples.list", { offset: 0, limit: 500, text: "アッカリ" });
  const ak = all.rows.find((r) => r.name === "アッカリ～ン")!;
  const view = await req<{ head: { result: { phones: Array<{ label: string }> } } }>("speech.sample", { id: ak.id });
  expect(view.head.result.phones.map((p) => p.label).join(" ")).toBe("a cl k a r i i N");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+1");
  await page.getByTestId("refresh-lists").click().catch(() => {});
  await page.getByTestId("library-search").fill("アッカリ");
  await page.getByTestId("sample-row").filter({ hasText: "アッカリ～ン" }).first().click();
  await expect(page.getByTestId("speech-phone")).toHaveCount(8);
  await expect(page.getByTestId("speech-status")).toHaveText("已分析 · pydomino");
  await page.waitForTimeout(800);
  await page.screenshot({ path: ".cache/playwright-results/real-speech-stage.png" });
  await app.close();
});
