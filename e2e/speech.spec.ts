import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 语音分析（规格 08 §8.4、16 S1.7）：采样库批量入口 → 确认框 M/N/K → 排队 → 任务里看逐条结果 → 勾失败项再分析；再发起时已是最新的跳过
const MODELS = resolve("dev-workspace/Models");

test("语音分析：确认框、任务、结果表、再发起", async () => {
  test.skip(!existsSync(join(MODELS, "pydomino", "phoneme_transition_model.onnx")), "dev models missing");
  const base = mkdtempSync(join(tmpdir(), "otto-speech-"));
  const workspace = join(base, "工作区 speech");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const wav = join(base, "v.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-ar", "44100", wav]);
  const { app, page } = await launch({ workspace });
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req<Array<{ sourceId: string; assets: Array<{ assetId: string }> }>>("sources.add", { paths: [p] })) as {
      r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }>;
    };
    const aid = add.r[0]!.assets[0]!.assetId;
    // 台词 = 文本层的段（所有者 2026-10-09）：采样读判定区间里的段；「なし」那里没有段
    for (const [s, e, n, text] of [[1, 2, "ああ", "あー"], [3, 4, "おと", "♪"], [4.5, 5.5, "なし", ""]] as const) {
      await req("samples.create", { assetId: aid, start: s, end: e, name: n, nature: "speech" });
      if (text) await req("segments.add", { sourceId: add.r[0]!.sourceId, start: s, end: e, text });
    }
  }, wav);
  await page.getByTestId("nav-library").click();
  await page.getByTestId("refresh-lists").click();
  const rows = page.getByTestId("sample-row");
  await expect(rows).toHaveCount(3);
  await rows.first().click();
  await page.keyboard.press("Meta+a"); // 集合里 ⌘A = 勾选全部（UI_PLAN §6.1）
  await page.getByTestId("batch-actions").click();
  await page.getByRole("menuitem", { name: "语音分析所选 3 项…" }).click();

  const dlg = page.getByTestId("speech-dialog");
  await expect(dlg.getByTestId("speech-run")).toContainText("2");
  await expect(dlg.getByTestId("speech-fresh")).toContainText("0");
  await expect(dlg.getByTestId("speech-blocked")).toContainText("1");
  await expect(dlg.getByTestId("speech-blocked-list")).toContainText("判定区间里没有台词段");
  await page.waitForTimeout(300);
  await page.screenshot({ path: ".cache/playwright-results/speech-dialog.png" });
  await dlg.getByTestId("speech-submit").click();
  await expect(page.getByText("已排队分析 2 段")).toBeVisible();

  await page.getByTestId("nav-tasks").click();
  const job = page.getByTestId("job").filter({ hasText: "语音分析" }).first(); // 抽屉里还有自动准备检索的后台任务
  await expect(job).toHaveAttribute("data-status", "succeeded", { timeout: 60000 });
  await expect(job.getByTestId("speech-summary")).toHaveText("1 段成功 · 1 段失败");
  await job.getByTestId("job-results").click();
  const res = job.getByTestId("speech-results");
  await expect(res).toContainText("成功");
  await expect(res).toContainText("文本前端失败");
  await page.waitForTimeout(300);
  await page.screenshot({ path: ".cache/playwright-results/speech-results.png" });
  // 勾失败项再分析（按段）→ 确认框只有这一段
  await res.getByTestId("table-check-all").click(); // 只有失败项可勾
  await res.getByTestId("speech-rerun-failed").click();
  await expect(dlg.getByTestId("speech-run")).toContainText("1");
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();

  // 再从全部三条发起：成功的那条已是最新，跳过
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("speech-results")).toBeHidden();
  // 列表里的分析状态（刷新后）
  await page.getByTestId("refresh-lists").click();
  // 分析属于“段 + 轨”：对齐出来的音素可能伸出采样范围一点 → 已分析 ◐（只读到这段的一部分）
  await expect(rows.filter({ hasText: "ああ" }).getByTestId("row-analysis")).toHaveText(/^手动截取 · 已分析( ◐)?$/);
  await expect(rows.filter({ hasText: "おと" }).getByTestId("row-analysis")).toHaveText("手动截取 · 分析失败");

  await page.getByTestId("batch-actions").click();
  await page.getByRole("menuitem", { name: "语音分析所选 3 项…" }).click();
  await expect(dlg.getByTestId("speech-fresh")).toContainText("1");
  await expect(dlg.getByTestId("speech-rerun")).toContainText("也重新分析已是最新的 1 段");
  await dlg.getByTestId("speech-rerun").click();
  await expect(dlg.getByTestId("speech-run")).toContainText("2");
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();

  // 人工修正（08 §8.7、S5.3）：舞台 → 编辑音素时间（编辑条、Esc 放弃）→ 精确时间保存为人工版本 → 再分析（勾“也重新分析”）不覆盖
  await page.getByTestId("batch-clear").click();
  await rows.filter({ hasText: "ああ" }).click();
  await expect(page.getByTestId("speech-status")).toHaveText("已分析 · pydomino");
  await page.getByTestId("speech-edit").click();
  await expect(page.getByTestId("phone-edit-bar")).toBeVisible();
  await page.getByTestId("stage-wave").getByTestId("timeline").click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("phone-edit-bar")).toBeHidden();
  await page.getByTestId("speech-times").click();
  const times = page.getByTestId("speech-times-text");
  const lines = (await times.inputValue()).split("\n");
  const [a0, b0, l0] = lines[0]!.split("\t");
  const nb = (Number(b0) - 0.02).toFixed(3);
  lines[0] = [a0, nb, l0].join("\t");
  const [, b1, l1] = lines[1]!.split("\t");
  lines[1] = [nb, b1, l1].join("\t");
  await times.fill(lines.join("\n"));
  await page.getByTestId("speech-times-save").click();
  await expect(page.getByTestId("speech-status")).toHaveText("人工版本");
  await page.waitForTimeout(300);
  await page.screenshot({ path: ".cache/playwright-results/speech-manual.png" });
  await page.getByTestId("speech-analyze").click();
  await dlg.getByTestId("speech-rerun").click();
  await dlg.getByTestId("speech-submit").click();
  await expect.poll(async () => page.evaluate(async () => {
    const r = await window.otto.core.request<Array<{ kind: string; status: string }>>("jobs.list");
    return r.ok ? r.r.filter((j) => j.kind === "speech.analyze" && j.status === "succeeded").length : 0;
  }), { timeout: 60000 }).toBe(2);
  await expect(page.getByTestId("speech-status")).toHaveText("人工版本");
  await app.close();
});
