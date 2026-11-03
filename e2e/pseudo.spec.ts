// 规格 16 R22.13：用伪语言运行，界面上不应残留写死的文字。
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists, unbracketed } from "./helpers";


test("伪语言下没有写死的界面文字", async () => {
  const { app, page } = await launch({ locale: "pseudo" });
  for (const nav of ["nav-library", "nav-sources", "nav-tools"]) {
    await page.getByTestId(nav).click();
    expect(await unbracketed(page)).toEqual([]);
  }
  await page.getByTestId("specimen-toggle").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("ControlOrMeta+,");
  for (const g of ["general", "inference", "source", "frontend", "analysis", "flatten", "export", "jobs", "agent", "models"]) {
    await page.getByTestId(`settings-group-${g}`).click();
    await page.waitForTimeout(150);
    expect(await unbracketed(page)).toEqual([]);
  }
  await page.keyboard.press("Escape");

  // 有资料时的原素材页（查看器、截取面板、设置框）与采样库（列表、舞台）
  const wav = join(mkdtempSync(join(tmpdir(), "otto-pseudo-")), "a.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=duration=3", wav]);
  const sid = await page.evaluate(async (p) => {
    const r = (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    const a = (await window.otto.core.request<Array<{ id: string }>>("assets.listForSource", { sourceId: r.r[0]!.sourceId })) as { r: Array<{ id: string }> };
    await window.otto.core.request("samples.create", { assetId: a.r[0]!.id, start: 0.5, end: 1.5, name: "x" });
    return r.r[0]!.sourceId;
  }, wav);
  await page.getByTestId("nav-sources").click();
  await page.getByTestId("source-group").first().click();
  await page.locator(`[data-testid="source-row"][data-id="${sid}"]`).click();
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });
  // 命令面板：作用于当前原素材的命令、本页与全局；有输入时每条右边写分组；没有匹配
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByTestId("palette")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("palette-input").fill("a");
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("palette-input").fill("zzzzqqq");
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByTestId("palette")).toHaveCount(0);
  const tl = (await page.getByTestId("source-viewer").getByTestId("timeline").boundingBox())!;
  await page.mouse.move(tl.x + tl.width * 0.2, tl.y + tl.height / 2);
  await page.mouse.down();
  await page.mouse.move(tl.x + tl.width * 0.4, tl.y + tl.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("source-viewer").getByTestId("clip").click();
  await expect(page.getByTestId("clip-panel")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await page.getByTestId("viewer-menu").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  // 「建立全长采样…」（批量整页）与「从台词段批量建采样…」（空状态）
  await page.getByTestId("viewer-menu").click();
  await page.getByTestId("menu-whole").click();
  await expect(page.getByTestId("new-samples")).toBeVisible();
  await expect(page.getByTestId("newsamples-run")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("new-samples")).toHaveCount(0);
  await page.getByTestId("viewer-menu").click();
  await page.getByTestId("menu-newsamples-segments").click();
  await expect(page.getByTestId("new-samples")).toBeVisible();
  await page.waitForTimeout(300);
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("new-samples")).toHaveCount(0);
  // 批量「语音分析…」确认框与「作品与类型…」框
  await page.locator(`[data-testid="source-row"][data-id="${sid}"]`).locator("label").first().click();
  await page.getByTestId("page-sources").getByTestId("batch-actions").click();
  await page.getByTestId("menu-speech").click();
  await expect(page.getByTestId("speech-dialog")).toBeVisible();
  await expect(page.getByTestId("speech-run")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("speech-dialog")).toHaveCount(0);
  await page.getByTestId("page-sources").getByTestId("batch-actions").click();
  await page.getByTestId("menu-work-type").click();
  await expect(page.getByTestId("work-type-dialog")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("work-type-dialog")).toHaveCount(0);
  await page.getByTestId("page-sources").getByTestId("batch-clear").click();
  // 时间线右键菜单与「新增区段标签」「添加台词」「新增音效提示」框
  for (const item of ["menu-tag", "menu-add-seg", "menu-add-hint"]) {
    await page.mouse.click(tl.x + tl.width * 0.3, tl.y + 50, { button: "right" });
    await expect(page.getByTestId("timeline-menu")).toBeVisible();
    expect(await unbracketed(page)).toEqual([]);
    await page.getByTestId("timeline-menu").getByTestId(item).click();
    await expect(page.getByTestId("annotation-dialog")).toBeVisible();
    expect(await unbracketed(page)).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("annotation-dialog")).toHaveCount(0);
  }
  await page.getByTestId("nav-library").click();
  await page.getByTestId("sample-row").first().click();
  expect(await unbracketed(page)).toEqual([]);
  // 加本地标签 → 「提升为区段标签」框
  await page.getByTestId("add-tag").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("add-tag-input").fill("t1");
  await page.getByTestId("add-tag-input").press("Enter");
  await page.getByTestId("promote").click();
  await expect(page.getByTestId("promote-preview")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  // 舞台动作条 → 拉平台（内部拉平 + 手动目标都展开）；批量拉平台
  await page.getByTestId("stage-flatten").click();
  await expect(page.getByTestId("flatten-sheet")).toBeVisible();
  await page.getByTestId("flatten-range-inner").click();
  await page.getByTestId("flatten-target-manual").click();
  await page.getByTestId("flatten-manual").fill("440");
  await expect(page.getByTestId("flatten-estimate")).not.toBeEmpty();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("flatten-sheet")).toHaveCount(0);
  await page.getByTestId("sample-row").first().locator("label").first().click();
  await page.getByTestId("page-library").getByTestId("batch-actions").click();
  await page.getByTestId("menu-flatten").click();
  await expect(page.getByTestId("flatten-batch-sheet")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await page.getByTestId("page-library").getByTestId("batch-clear").click();

  // 导入独立采样框（预览出来以后）
  await app.evaluate(({ dialog }, d) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [d] })) as typeof dialog.showOpenDialog;
  }, wav);
  await page.getByTestId("library-import").click();
  await expect(page.getByTestId("import-preview")).toBeVisible({ timeout: 15000 });
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");

  await page.keyboard.press("ControlOrMeta+j");
  await page.waitForTimeout(200);
  expect(await unbracketed(page)).toEqual([]);
  await page.screenshot({ path: ".cache/playwright-results/pseudo.png" });
  await app.close();
});

// 节奏与卡拍（阶段 6）：有分析时的面板、分组与停顿、人工占格、逐音属性、交接 ▾、全局播放条的版本说明
test("伪语言：节奏与卡拍", async () => {
  const MODELS = resolve("dev-workspace/Models");
  test.skip(!existsSync(join(MODELS, "pydomino", "phoneme_transition_model.onnx")), "dev models missing");
  test.setTimeout(120_000);
  const base = mkdtempSync(join(tmpdir(), "otto-pseudo-rhythm-"));
  const workspace = join(base, "ws");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const wav = join(base, "v.wav");
  const gate = [1.0, 1.25, 1.5, 2.2].map((o) => `between(t\\,${o}\\,${(o + 0.2).toFixed(2)})`).join("+");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `aevalsrc=0.3*sin(2*PI*220*t)*(${gate}):s=44100:d=3`, wav]);
  const { app, page } = await launch({ locale: "pseudo", workspace });
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }> };
    const c = (await req("samples.create", { assetId: add.r[0]!.assets[0]!.assetId, start: 0.9, end: 2.6, name: "x", nature: "speech" })) as { r: { id: string; version: number } };
    await req("segments.add", { sourceId: add.r[0]!.sourceId, start: 0.9, end: 2.6, text: "かかかか" }); // 台词 = 文本层的段（采样读判定区间里的段）
    await req("speech.submit", { entry: "samples", ids: [c.r.id], rerunFresh: false });
  }, wav);
  await expect
    .poll(async () => page.evaluate(async () => ((await window.otto.core.request("jobs.list", {})) as { r: Array<{ status: string }> }).r[0]?.status), { timeout: 60000 })
    .toBe("succeeded");
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("sample-row").first().click();
  await expect(page.getByTestId("rhythm-map")).toBeVisible();
  await page.getByTestId("bpm").fill("150");
  await page.getByTestId("bpm").press("Enter");
  await page.getByTestId("rhythm-mora").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("rhythm-play-stretched").click();
  await expect(page.getByTestId("dock-version")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("dock-stop").click();
  for (const id of ["rhythm-grouping", "rhythm-cells", "rhythm-attrs", "stage-handoff"]) {
    await page.getByTestId(id).click();
    await page.waitForTimeout(150);
    expect(await unbracketed(page)).toEqual([]);
    await page.keyboard.press("Escape");
  }
  await app.close();
});

// 三大搜索（阶段 7）：检索浮层四种方式（含设置、更多条件、音高高级、就地提示）、准备索引、固定结果标签与状态行、命中小卡与命中右键
test("伪语言：三大搜索", async () => {
  const MODELS = resolve("dev-workspace/Models");
  test.skip(!existsSync(join(MODELS, "pydomino", "phoneme_transition_model.onnx")), "dev models missing");
  test.setTimeout(120_000);
  const base = mkdtempSync(join(tmpdir(), "otto-pseudo-search-"));
  const workspace = join(base, "ws");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const wav = join(base, "v.wav");
  const gate = [1.0, 1.25, 1.5, 2.2].map((o) => `between(t\\,${o}\\,${(o + 0.2).toFixed(2)})`).join("+");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `aevalsrc=0.3*sin(2*PI*220*t)*(${gate}):s=44100:d=3`, wav]);
  const { app, page } = await launch({ locale: "pseudo", workspace });
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }> };
    const c = (await req("samples.create", { assetId: add.r[0]!.assets[0]!.assetId, start: 0.9, end: 2.6, name: "x", nature: "speech" })) as { r: { id: string; version: number } };
    await req("segments.add", { sourceId: add.r[0]!.sourceId, start: 0.9, end: 2.6, text: "かかかか" }); // 台词 = 文本层的段（采样读判定区间里的段）
    await req("speech.submit", { entry: "samples", ids: [c.r.id], rerunFresh: false });
  }, wav);
  await expect
    .poll(async () => page.evaluate(async () => ((await window.otto.core.request("jobs.list", {})) as { r: Array<{ status: string }> }).r[0]?.status), { timeout: 60000 })
    .toBe("succeeded");
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("hunt-open").click();
  const composer = page.getByTestId("composer");
  await expect(composer.getByTestId("search-coverage")).toBeVisible();
  await composer.getByTestId("speech-block").first().click();
  await composer.getByTestId("speech-more-conds").getByRole("button").first().click();
  expect(await unbracketed(page)).toEqual([]);
  await composer.getByTestId("speech-more").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await composer.getByTestId("strategy-strict").click();
  expect(await unbracketed(page)).toEqual([]);
  const prep = composer.getByTestId("search-prepare"); // 语音分析后会自动在后台准备；没好时手动点
  if (await prep.isVisible()) await prep.click().catch(() => {});
  await expect(prep).toHaveCount(0, { timeout: 60000 });
  await composer.getByTestId("strategy-free").click();
  await composer.getByTestId("search-find").click();
  await expect(page.getByTestId("result-tab")).toHaveCount(1, { timeout: 30000 });
  await page.getByTestId("sample-row").first().click();
  await expect(page.getByTestId("hit-chips")).toBeVisible();
  await page.getByTestId("hit-chip").first().click();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("hit").last().click({ button: "right" });
  await expect(page.getByTestId("hit-menu")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await page.getByTestId("hunt-open").click();
  await composer.getByTestId("composer-pitch").click();
  await composer.getByTestId("pitch-block").first().click();
  await composer.getByTestId("pitch-seconds").fill("0.05");
  await expect(composer.getByTestId("pitch-problem").first()).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await composer.getByTestId("pitch-more").click();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  for (const m of ["composer-timbre", "composer-transient"]) {
    await composer.getByTestId(m).click();
    await expect(composer.getByTestId("metrics-table")).toBeVisible();
    expect(await unbracketed(page)).toEqual([]);
  }
  await app.close();
});

test("伪语言：阶段 8 / 9 的界面（范围行、批量、管理标签、画面绑定、视频、独立化、回导、存储、删除原素材）", async () => {
  test.setTimeout(120_000);
  const { app, page } = await launch({ locale: "pseudo" });
  const dir = mkdtempSync(join(tmpdir(), "otto-pseudo89-"));
  const mkv = join(dir, "v.mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=4", "-f", "lavfi", "-i", "sine=duration=4", "-c:v", "libx264", "-c:a", "flac", mkv]);
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const r = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    const c = (await req("samples.create", { assetId: r.r[0]!.assets[0]!.assetId, start: 0.5, end: 1.5, name: "x" })) as { r: { id: string; version: number } };
    await req("edits.apply", { batch: { ops: [{ entity: "sample", id: c.r.id, version: c.r.version, fields: { local_tags: ["character:k", "ok"] } }] } });
  }, mkv);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("sample-row").first().click();
  const check = async () => expect(await unbracketed(page)).toEqual([]);
  await check();
  await page.getByTestId("scope-add").click();
  await check();
  await page.keyboard.press("Escape");
  const dialogs: Array<[string, string]> = [
    ["menu-edit", "batch-dialog"],
    ["menu-tags-remove", "batch-dialog"],
    ["menu-visual", "visual-dialog"],
    ["menu-independ", "independ-dialog"],
  ];
  for (const [item, dlg] of dialogs) {
    await page.getByTestId("sample-row").first().click({ button: "right" });
    await page.getByTestId(item).click();
    await expect(page.getByTestId(dlg)).toBeVisible();
    await page.waitForTimeout(300);
    await check();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId(dlg)).toHaveCount(0);
  }
  await page.getByTestId("stage-handoff").click();
  await page.getByTestId("menu-video").click();
  await page.waitForTimeout(300);
  await check();
  await page.keyboard.press("Escape");
  await page.getByTestId("stage-reimport").click();
  await check();
  await page.keyboard.press("Escape");
  await page.getByTestId("top-more").click();
  await page.getByTestId("menu-manage-tags").click();
  await page.waitForTimeout(300);
  await check();
  await page.keyboard.press("Escape");
  await page.keyboard.press("ControlOrMeta+,");
  await page.getByTestId("settings-group-storage").click();
  await page.waitForTimeout(300);
  await check();
  await page.keyboard.press("Escape");
  await page.getByTestId("nav-sources").click();
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click({ button: "right" });
  await page.getByTestId("menu-delete").click();
  await expect(page.getByTestId("delete-independ")).toBeVisible();
  await check();
  await app.close();
});
