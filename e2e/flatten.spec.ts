import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 拉平（规格 11、16 R17）：舞台动作条 → 拉平台（默认值随入口、改范围不改定音、手动目标即时解析、内区）→ 任务 → 「打开结果」跳到成品
// （调谐单音、pitch: 标签、名称不带音名）；列表右键是“其他单个入口”的默认值；批量拉平没有对齐的项逐条失败、可只重跑失败项。
const MODELS = resolve("dev-workspace/Models");

test("拉平：拉平台、任务、成品、批量", async () => {
  test.skip(!existsSync(join(MODELS, "flatten", "pc_nsf_hifigan.onnx")), "dev models missing");
  test.setTimeout(240_000);
  const base = mkdtempSync(join(tmpdir(), "otto-flatten-"));
  const workspace = join(base, "工作区 flatten");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const wav = join(base, "tone.wav");
  // 约 233 Hz（A♯3）带 5 Hz 颤音的谐波音
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "aevalsrc=0.2*sin(2*PI*233*t+3*sin(2*PI*5*t))+0.1*sin(4*PI*233*t+6*sin(2*PI*5*t)):s=44100:d=3", wav]);
  const { app, page } = await launch({ workspace });
  const aid = await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req<Array<{ assets: Array<{ assetId: string }> }>>("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    await req("samples.create", { assetId: aid, start: 0.5, end: 2.5, name: "ふぁー", nature: "speech" });
    await req("samples.create", { assetId: aid, start: 1.0, end: 1.6, name: "みー", nature: "speech" });
    return aid;
  }, wav);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  const rows = page.getByTestId("sample-row");
  await expect(rows).toHaveCount(2);
  await rows.filter({ hasText: "ふぁー" }).click();

  // ---- 舞台动作条（L19）→ 拉平台：详情入口默认 首元音起 + 交界左；没有对齐 → 说明
  const actions = page.getByTestId("stage-actions");
  await expect(actions).toBeVisible();
  await expect(actions.getByTestId("stage-readout")).toHaveAttribute("data-a", "0.5");
  await actions.getByTestId("stage-flatten").click();
  const sheet = page.getByTestId("flatten-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByTestId("flatten-range-first")).toHaveAttribute("data-selected", "true");
  await expect(sheet.getByTestId("flatten-target-edge")).toHaveAttribute("data-selected", "true");
  await expect(sheet.getByTestId("flatten-estimate")).toContainText("语音分析结果");
  await expect(page.getByRole("button", { name: "开始拉平" })).toBeDisabled();
  // 改范围不自动改定音（Q6）
  await sheet.getByTestId("flatten-range-whole").click();
  await expect(sheet.getByTestId("flatten-target-edge")).toHaveAttribute("data-selected", "true");
  await expect(sheet.getByTestId("flatten-estimate")).toContainText("任务中分析确定");
  // 手动目标：纯数字拒绝；带单位的频率精确换算、不吸附
  await sheet.getByTestId("flatten-target-manual").click();
  await sheet.getByTestId("flatten-manual").fill("440");
  await expect(sheet.getByTestId("flatten-estimate")).toContainText("纯数字含义不明");
  await sheet.getByTestId("flatten-manual").fill("445Hz");
  await expect(sheet.getByTestId("flatten-estimate")).toContainText("A4+20c");
  // 内部拉平：金色内区（初始 [0.1, d − 0.1]）
  await sheet.getByTestId("flatten-range-inner").click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: ".cache/playwright-results/flatten-sheet.png" });
  // 整段 + 段内自动 → 开始
  await sheet.getByTestId("flatten-range-whole").click();
  await sheet.getByTestId("flatten-target-auto").click();
  await expect(sheet.getByTestId("flatten-name")).toHaveValue("ふぁー");
  await sheet.getByTestId("flatten-go").click();
  await expect(sheet).toHaveCount(0);
  await expect(page.getByText("已排队拉平")).toBeVisible();
  // 当前采样不变
  await expect(page.getByTestId("stage-title")).toHaveText("ふぁー");

  await page.getByTestId("nav-tasks").click();
  const job = page.getByTestId("job").filter({ hasText: "拉平" }).first(); // 抽屉里还有自动准备检索的后台任务
  await expect(job).toHaveAttribute("data-status", "succeeded", { timeout: 120000 });
  await job.getByTestId("job-results").click();
  // 「打开结果」= 选中成品并回到采样库
  await expect(page.getByTestId("stage-title")).toHaveText("ふぁー");
  const stage = page.getByTestId("stage");
  await expect(stage).toContainText("调谐单音");
  await expect(stage).toContainText("A♯3");
  await page.waitForTimeout(500);
  await page.screenshot({ path: ".cache/playwright-results/flatten-product.png" });
  // 「返回原素材」（所有者 2026-10-12）：换到它拉平前的整轨（不是只覆盖 2 秒的拉平成品），选区 = 原素材 0.5–2.5 秒，“采样”车道突出它
  const product = await page.getByTestId("sample-row").filter({ hasText: "ふぁー" }).first().getAttribute("data-id");
  await page.getByTestId("back-to-source").click();
  const viewer = page.getByTestId("source-viewer");
  await expect(viewer).toHaveAttribute("data-asset", aid);
  await expect(viewer).toHaveAttribute("data-highlight", /.+/);
  await expect(page.getByTestId("readout")).toHaveAttribute("data-a", "0.5");
  // 音源下拉（所有者 2026-10-13）：整轨都列；拉平成品这种局部音轨只在播放头落在它上面时出现在“这里的局部音轨”小节里
  await page.getByTestId("audio-source").getByRole("button").click();
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await page.evaluate(() => window.otto.player.seek(1.0));
  await page.waitForTimeout(400);
  await page.getByTestId("audio-source").getByRole("button").click();
  await expect(page.getByRole("option")).toHaveCount(2);
  await expect(page.getByText("这里的局部音轨（盖住播放头的）")).toBeVisible();
  await page.keyboard.press("Escape");
  expect(product).toBeTruthy();
  // 加工链与相关采样：成品 ← 原混音；与原采样、みー 交叠
  await page.keyboard.press("Meta+1");
  await expect(page.getByTestId("stage-chain").getByTestId("stage-chain-step")).toHaveCount(2);
  await expect(page.getByTestId("stage-related")).toContainText("みー");

  // ---- 列表右键「拉平…」= 其他单个入口：整段 + 段内自动
  await refreshLists(page);
  await rows.filter({ hasText: "みー" }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "拉平…" }).click();
  await expect(sheet.getByTestId("flatten-range-whole")).toHaveAttribute("data-selected", "true");
  await expect(sheet.getByTestId("flatten-target-auto")).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);

  // ---- 批量：仅元音 + 段内自动（默认）；没有对齐 → 逐条失败、可只重跑失败项
  await expect(rows).toHaveCount(3);
  await rows.filter({ hasText: "みー" }).locator("label").first().click();
  await page.getByTestId("page-library").getByTestId("batch-actions").click();
  await page.getByRole("menuitem", { name: "拉平 1 项…" }).click();
  const bsheet = page.getByTestId("flatten-batch-sheet");
  await expect(bsheet.getByTestId("flatten-range-vowels")).toHaveAttribute("data-selected", "true");
  await expect(bsheet.getByTestId("flatten-target-manual")).toHaveCount(0); // 批量没有手动（Q10）
  await expect(bsheet.getByTestId("flatten-range-inner")).toHaveCount(0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: ".cache/playwright-results/flatten-batch.png" });
  await bsheet.getByTestId("flatten-batch-go").click();
  await page.getByTestId("nav-tasks").click();
  const bjob = page.getByTestId("job").filter({ hasText: "拉平" }).first();
  await expect(bjob).toHaveAttribute("data-status", "succeeded", { timeout: 60000 });
  await expect(bjob.getByTestId("speech-summary")).toHaveText("0 条成功 · 1 条失败");
  await bjob.getByTestId("job-results").click();
  const res = bjob.getByTestId("flatten-results");
  await expect(res).toContainText("语音分析结果");
  await expect(res.getByTestId("flatten-rerun-failed")).toBeVisible();
  await app.close();
});
