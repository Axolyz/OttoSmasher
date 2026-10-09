import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 三大搜索（规格 09 §9.6–§9.7、10 §10.2–§10.3、UI_PLAN §2.1、§2.4、§6.3）：检索浮层（覆盖预检 →「准备当前范围索引」）→ 语音检索 → 固定结果标签与状态行 →
// 行下命中时间线 → 当前行命中小卡（▶ 左键原声 / 右键卡拍）→ 定位（舞台命中导航）→ 按相似度排序（证据）→ 音高检索（采样模式）→ 单音指标 → 关闭结果。
const MODELS = resolve("dev-workspace/Models");
const ONSETS = [1.0, 1.25, 1.5, 1.75, 2.5, 2.75];
const SHOTS = ".cache/compare/shots/stage7";

test("三大搜索：浮层、准备索引、固定结果、命中、音高、单音指标", async () => {
  test.skip(!existsSync(join(MODELS, "pydomino", "phoneme_transition_model.onnx")), "dev models missing");
  test.setTimeout(240_000);
  const base = mkdtempSync(join(tmpdir(), "otto-search-"));
  const workspace = join(base, "工作区 search");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const wav = join(base, "v.wav");
  const gate = ONSETS.map((o) => `between(t\\,${o}\\,${(o + 0.2).toFixed(2)})`).join("+");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `aevalsrc=0.3*sin(2*PI*220*t)*(${gate})+0.002*sin(2*PI*90*t):s=44100:d=4`, wav]);
  const { page } = await launch({ workspace });
  await page.setViewportSize({ width: 1536, height: 864 });
  const sid = await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    const c = (await req("samples.create", { assetId: aid, start: 0.9, end: 3.1, name: "かかかかかか", nature: "speech" })) as { r: { id: string; version: number } };
    await req("edits.apply", { batch: { ops: [{ entity: "sample", id: c.r.id, version: c.r.version, fields: { align_text_manual: "かかかかかか" } }] } });
    await req("samples.create", { assetId: aid, start: 1.0, end: 1.2, name: "単音", nature: "pitched" });
    await req("speech.submit", { entry: "samples", ids: [c.r.id], rerunFresh: false });
    return c.r.id;
  }, wav);
  await expect
    .poll(async () => page.evaluate(async () => ((await window.otto.core.request("jobs.list", {})) as { r: Array<{ status: string }> }).r[0]?.status), { timeout: 60000 })
    .toBe("succeeded");
  await page.evaluate(
    async ({ id, onsets }) => {
      const req = window.otto.core.request;
      const v = (await req("speech.sample", { id })) as { r: { head: { version: number; result: { phones: Array<{ label: string }> } } } };
      let i = 0;
      const lines = v.r.head.result.phones.map((p) => {
        const o = onsets[Math.floor(i / 2)]!;
        const line = p.label === "k" ? `${(o - 0.04).toFixed(3)}\t${o.toFixed(3)}\tk` : `${o.toFixed(3)}\t${(o + 0.2).toFixed(3)}\t${p.label}`;
        i += 1;
        return line;
      });
      const r = await req("speech.saveManual", { sampleId: id, version: v.r.head.version, text: lines.join("\n") });
      if (!r.ok) throw new Error(JSON.stringify(r.e));
    },
    { id: sid, onsets: ONSETS },
  );
  await page.getByTestId("nav-library").click();
  await page.getByTestId("refresh-lists").click();
  await expect(page.getByTestId("sample-row")).toHaveCount(2);

  // ---- 浮层：覆盖预检 0 就绪 → 查找禁用；准备当前范围索引 → 只刷新覆盖数
  await page.getByTestId("hunt-open").click();
  const composer = page.getByTestId("composer");
  await expect(composer).toBeVisible();
  await expect(composer.getByTestId("search-coverage")).toContainText("已就绪 0/2");
  await expect(composer.getByTestId("search-find")).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/01-speech-composer.png` });
  await composer.getByTestId("search-prepare").click();
  // 単音在句子范围里，用的是投影的分析（08 §8.8），所以两条都就绪
  await expect(composer.getByTestId("search-coverage")).toContainText("已就绪 2/2", { timeout: 60000 });
  await expect(page.getByTestId("result-tab")).toHaveCount(0); // 准备完成不自动检索

  // ---- 不限节奏：两块（第一块前导辅音 k、元音 a）→ 查找 → 固定结果标签，浮层收起
  await composer.getByTestId("speech-block").first().click();
  const insp = composer.getByTestId("speech-inspector");
  await expect(insp).toContainText("块 1");
  await composer.getByTestId("search-find").click();
  await expect(page.getByTestId("result-tab")).toHaveCount(1, { timeout: 30000 });
  await expect(composer).toHaveCount(0);
  await expect(page.getByTestId("result-status")).toContainText(/固定结果 · \d+ 个采样 · \d+ 处命中/);
  const row = page.getByTestId("sample-row").filter({ hasText: "かかかかかか" });
  await expect(row.getByTestId("hit")).toHaveCount(4);
  await row.click();
  await expect(row.getByTestId("hit-chips")).toBeVisible();
  await row.getByTestId("hit-chip").nth(1).click();
  await expect(page.getByTestId("hit-nav")).toContainText("命中 2/4");
  await page.screenshot({ path: `${SHOTS}/02-results-hit.png` });
  await row.getByTestId("hit-play").first().click();
  await expect(page.getByTestId("dock-version")).toContainText("原声");
  await row.getByTestId("hit-play").first().click({ button: "right" });
  await expect(page.getByTestId("dock-version")).toContainText("卡拍");
  await row.getByTestId("hit").first().click({ button: "right" });
  await expect(page.getByTestId("hit-menu")).toContainText("导出卡拍 WAV");
  await page.keyboard.press("Escape");

  // ---- 按相似度排序 + BPM 180：证据（严格/近似 · 倍速 · 方案）
  const bpm = page.getByTestId("bpm");
  await bpm.fill("180");
  await bpm.press("Enter");
  await page.getByTestId("hunt-open").click();
  await composer.getByTestId("strategy-rank").click();
  await expect(composer.getByTestId("search-bpm-note")).toHaveText("按 BPM 180");
  await expect(composer.getByTestId("speech-roll")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/03-speech-roll.png` });
  await composer.getByTestId("search-find").click();
  await expect(page.getByTestId("result-tab")).toHaveCount(2, { timeout: 30000 });
  const r2 = page.getByTestId("sample-row").filter({ hasText: "かかかかかか" });
  await r2.click();
  await expect(r2.getByTestId("hit-chip").first()).toContainText(/(严格|近似) · \d\.\d\d× · (近快|近慢)/);

  // ---- 音高检索（采样模式）：0.15 秒 A3（220 Hz）→ 命中；画布与就地提示
  await page.getByTestId("hunt-open").click();
  await composer.getByTestId("composer-pitch").click();
  await expect(composer.getByTestId("pitch-canvas")).toBeVisible();
  await composer.getByTestId("pitch-block").first().click();
  await composer.getByTestId("pitch-seconds").fill("0.05");
  await expect(composer.getByTestId("pitch-problem").first()).toContainText("块最短 0.1 秒");
  await expect(composer.getByTestId("search-find")).toBeDisabled();
  await composer.getByTestId("pitch-seconds").fill("0.15");
  await composer.getByTestId("pitch-note").fill("A3");
  await composer.getByTestId("pitch-block").nth(1).click();
  await page.keyboard.press("Delete");
  await expect(composer.getByTestId("pitch-block")).toHaveCount(1);
  await page.screenshot({ path: `${SHOTS}/04-pitch-composer.png` });
  await expect(composer.getByTestId("search-find")).toBeEnabled();
  await composer.getByTestId("search-find").click();
  await expect(page.getByTestId("result-tab")).toHaveCount(3, { timeout: 30000 });
  await expect(page.getByTestId("result-status")).toContainText(/固定结果 · 2 个采样/);

  // ---- 单音 · 瞬态：后台准备当前范围指标 → 勾指标填范围 → 浏览列表即时筛选
  await page.getByTestId("tab-browse").click();
  await page.getByTestId("hunt-open").click();
  await composer.getByTestId("composer-transient").click();
  await expect(composer.getByTestId("metrics-status")).toContainText("已准备 0/2");
  await composer.getByTestId("metrics-prepare").click();
  await expect(composer.getByTestId("metrics-status")).toContainText("已准备 2/2", { timeout: 60000 });
  await page.screenshot({ path: `${SHOTS}/05-transient.png` });
  await composer.getByTestId("metric-min-effectiveDuration").fill("1");
  await composer.getByTestId("table-row").first().locator("label").first().click();
  await expect(page.getByTestId("metrics-active")).toBeVisible();
  await expect(page.getByTestId("sample-row")).toHaveCount(1);
  await composer.getByTestId("composer-close").click();

  // ---- 关闭结果：只删结果集合
  await page.getByTestId("result-tab").first().getByTestId("tab-close").click();
  await expect(page.getByTestId("result-tab")).toHaveCount(2);
});
