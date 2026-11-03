import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 分离（规格 05 §5.5、14 §14.6、R18）：伪 Studio（core/tests/fake_studio.py）——确认框、任务、结果
test("分离：确认框选模型、排队、任务结果里的声部", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-sep-"));
  const wav = join(dir, "[Group] Sep Show [01].wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=3", "-ac", "2", "-c:a", "pcm_s16le", wav]);
  const out = execFileSync(resolve(process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"), ["-c", `import sys, json; sys.path.insert(0, 'core/tests'); from fake_studio import make_fake_studio; print(json.dumps(make_fake_studio(__import__('pathlib').Path(${JSON.stringify(join(dir, "studio"))}))))`]).toString();
  const [appPath, dataDir] = JSON.parse(out) as [string, string];
  const { app, page } = await launch();
  await page.evaluate(
    async ([a, d]) => {
      await window.otto.core.request("edits.apply", { batch: { ops: [
        { entity: "setting", id: "studio.app_path", version: 0, fields: { value: a } },
        { entity: "setting", id: "studio.data_dir", version: 0, fields: { value: d } },
      ] } });  // prettier-ignore
    },
    [appPath, dataDir] as const,
  );
  await page.keyboard.press("ControlOrMeta+2");
  await page.evaluate(async (p) => window.otto.core.request("sources.add", { paths: [p] }), wav);
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await page.getByTestId("separate").click();
  const dlg = page.getByTestId("sep-dialog");
  await expect(dlg).toContainText("整片连续音轨 0–3.000 s");
  const models = dlg.getByTestId("sep-models");
  await expect(models).toContainText("fake_vocals · Vocals | Instrumental", { timeout: 20000 });
  await expect(models).toContainText("fake_3track");
  await expect(models).not.toContainText("half_downloaded");
  await models.getByText("fake_vocals").click();
  await expect(dlg).toContainText("Vocals → 人声");
  await page.screenshot({ path: ".cache/playwright-results/separation.png" });
  await dlg.getByTestId("sep-submit").click();
  await expect(page.getByText(/已排队分离/)).toBeVisible();
  await expect
    .poll(async () => page.evaluate(async () => ((await window.otto.core.request<Array<{ kind: string; status: string }>>("jobs.list")) as { r: Array<{ kind: string; status: string }> }).r.find((j) => j.kind === "separate")?.status), { timeout: 30000 })
    .toBe("succeeded");
  await page.keyboard.press("ControlOrMeta+j");
  const job = page.getByTestId("job").filter({ hasText: "分离" }).first();
  await job.getByTestId("job-results").click();
  const results = job.getByTestId("sep-results");
  await expect(results).toContainText("Vocals");
  await expect(results).toContainText("Instrumental");
  await expect(results).toContainText("人声");
  await page.screenshot({ path: ".cache/playwright-results/separation-results.png" });
  // 再提交同一模型 → 再跑一次
  await page.keyboard.press("Escape");
  await page.getByTestId("separate").click();
  await expect(models).toContainText("fake_vocals");
  await models.getByText("fake_vocals").click();
  await dlg.getByTestId("sep-submit").click();
  // 不做自动复用（DECISIONS §9）：再点一次就再排一个任务
  await expect.poll(async () => page.evaluate(async () => ((await window.otto.core.request("jobs.list")) as { r: Array<{ kind: string; status: string }> }).r.filter((j) => j.kind === "separate" && j.status === "succeeded").length), { timeout: 60000 }).toBe(2);
  await app.close();
});
