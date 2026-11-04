// 原片页的批量操作（所有者 2026-11-03）：整片分离、把分离出的人声设为默认人声轨、从台词段建采样、重新生成说话人。
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

const PY = resolve(process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");

test("批量：整片分离、设默认人声轨、从台词段建采样、重新生成说话人", async () => {
  test.setTimeout(240_000);
  const dir = mkdtempSync(join(tmpdir(), "otto-batch-"));
  const files = ["01", "02"].map((ep) => {
    const wav = join(dir, `[Group] Batch Show [${ep}].wav`);
    execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6", "-ac", "2", "-c:a", "pcm_s16le", wav]);
    writeFileSync(wav.replace(/\.wav$/, ".srt"), `1\n00:00:01,000 --> 00:00:02,000\n（京子）第${ep}話のせりふ\n\n2\n00:00:03,000 --> 00:00:04,000\n（結衣）もう一つ\n`);
    return wav;
  });
  const code = `import sys, json; sys.path.insert(0, 'core/tests'); from fake_studio import make_fake_studio; from pathlib import Path; a, d = make_fake_studio(Path(sys.argv[1])); print(json.dumps([str(a), str(d)]))`;
  const [appPath, dataDir] = JSON.parse(execFileSync(PY, ["-c", code, join(dir, "studio")], { encoding: "utf8" })) as [string, string];
  const { app, page } = await launch();
  await page.evaluate(
    async ([a, d, paths]) => {
      const req = window.otto.core.request;
      await req("edits.apply", { batch: { ops: [
        { entity: "setting", id: "studio.app_path", version: 0, fields: { value: a } },
        { entity: "setting", id: "studio.data_dir", version: 0, fields: { value: d } },
      ] } });  // prettier-ignore
      const added = (await req("sources.add", { paths })) as { r: Array<{ sourceId: string }> };
      for (const x of added.r) await req("subtitles.importDefault", { sourceId: x.sourceId });
    },
    [appPath, dataDir, files] as const,
  );
  await page.keyboard.press("ControlOrMeta+2");
  await page.keyboard.press("Escape");
  const group = page.getByTestId("source-group").first();
  await group.click({ button: "right" });
  await page.getByTestId("menu-check").click();
  const batch = async (item: string) => {
    await page.getByTestId("batch-actions").click();
    await page.getByTestId(`menu-${item}`).click();
  };

  // 还没分离：设默认人声轨的框说清楚要先分离
  await batch("separated-vocal");
  const pick = page.getByTestId("separated-vocal");
  await expect(pick).toContainText("还没有分离出的人声声部");
  await expect(pick.getByTestId("separated-vocal-run")).toBeDisabled();
  await page.keyboard.press("Escape");

  // 整片分离：只选一次模型，每个原素材一个任务
  await batch("separate");
  const dlg = page.getByTestId("sep-dialog");
  await expect(dlg).toContainText("2 个原素材");
  const models = dlg.getByTestId("sep-models");
  await expect(models).toContainText("fake_vocals", { timeout: 20000 });
  await models.getByText("fake_vocals").click();
  await dlg.getByTestId("sep-submit").click();
  await expect(page.getByText(/已排队 2 个分离任务/)).toBeVisible();
  const separated = async () =>
    page.evaluate(async () => {
      const jobs = (await window.otto.core.request("jobs.list")) as { r: Array<{ kind: string; status: string }> };
      return jobs.r.filter((j) => j.kind === "separate" && j.status === "succeeded").length;
    });
  await expect.poll(separated, { timeout: 90000 }).toBe(2);

  // 再分离一次：不做自动复用，真的再跑一遍（DECISIONS §9）
  await batch("separate");
  await expect(models).toContainText("fake_vocals", { timeout: 20000 });
  await models.getByText("fake_vocals").click();
  await dlg.getByTestId("sep-submit").click();
  await expect.poll(separated, { timeout: 90000 }).toBe(4);

  // 批量设默认人声轨：一次可撤销
  await batch("separated-vocal");
  await expect(pick).toContainText("fake_vocals · Vocals");
  await expect(pick).toContainText("2 / 2 个原素材有");
  await pick.getByTestId("separated-vocal-run").click();
  await expect(page.getByText(/已为 2 个原素材设好默认人声轨/)).toBeVisible();

  // 从台词段建采样：合并显示两集，各建在自己的默认人声轨上
  await batch("newsamples-segments");
  const sheet = page.getByTestId("new-samples");
  await expect(sheet.getByTestId("stat-pending")).toContainText("4");
  await expect(sheet).toContainText("第01話のせりふ");
  await expect(sheet).toContainText("第02話のせりふ");
  await expect(sheet.getByTestId("newsamples-run")).toBeDisabled(); // 默认一项都不勾（规格 06 §6.4）
  await sheet.getByTestId("table-check-all").click();
  await expect(sheet.getByTestId("newsamples-run")).toHaveText("创建 4 项");
  await sheet.getByTestId("newsamples-run").click();
  await expect(page.getByText(/已建立 4 个采样/)).toBeVisible();
  const made = await page.evaluate(async () => {
    const res = (await window.otto.core.request("samples.list", { offset: 0, limit: 50 })) as { r: { rows: Array<{ asset_id: string }> } };
    return new Set(res.r.rows.map((x) => x.asset_id)).size + res.r.rows.length * 100;
  });
  expect(made).toBe(402); // 4 个采样，分属两集的人声轨

  // 重新生成说话人：规则没变，什么都不改，也不报错
  await batch("speakers");
  await expect(page.getByText(/2 个原素材里，已重新生成 0 段/)).toBeVisible();
  await page.screenshot({ path: ".cache/playwright-results/sources-batch.png" });

  // 音轨弹窗：默认轨上有采样 → 不让删；没人用的那条可以删
  await page.getByRole("button", { name: "清空勾选" }).click(); // 还勾选着时右键是批量菜单
  if (!(await page.getByTestId("source-row").first().isVisible())) await group.click(); // 展开作品分组
  await page.getByTestId("source-row").first().click({ button: "right" });
  await page.getByTestId("menu-tracks").click();
  const tracks = page.getByTestId("tracks-dialog");
  const trackRows = tracks.getByTestId("track-row");
  await expect(trackRows).toHaveCount(5); // 原混音 + 两次分离各 Vocals、Instrumental
  await expect(trackRows.first().getByTestId("track-delete")).toHaveCount(0); // 原混音没有删除按钮
  const defaultRow = trackRows.filter({ hasText: "默认" });
  await defaultRow.getByTestId("track-delete").click();
  await expect(tracks.getByTestId("track-delete-confirm")).toContainText("个采样建在这条音轨上");
  await expect(tracks.getByTestId("track-delete-run")).toHaveCount(0);
  await tracks.getByRole("button", { name: "取消" }).click();
  const spare = trackRows.filter({ hasText: "Instrumental" }).first();
  await spare.getByTestId("track-delete").click();
  await expect(tracks.getByTestId("track-delete-confirm")).toContainText("不能撤销");
  await tracks.getByTestId("track-delete-run").click();
  await expect(trackRows).toHaveCount(4);
  await expect(page.getByText(/已删除，释放/)).toBeVisible();
  await tracks.getByRole("button", { name: "关闭" }).click();

  // 设置 › 存储：其余没人用的音轨一次清掉，默认轨不在里面
  await page.keyboard.press("ControlOrMeta+,");
  await page.getByTestId("settings-group-storage").click();
  const unused = page.getByTestId("storage-unused");
  await expect(unused).toContainText("Instrumental");
  await unused.getByTestId("table-check-all").click();
  await page.getByTestId("storage-unused-delete").click();
  await page.getByTestId("storage-unused-confirm").getByTestId("confirm-ok").click();
  await expect(page.getByTestId("storage-unused-empty")).toBeVisible();
  await expect(page.getByText(/已删除 \d+ 条音轨/)).toBeVisible();
  const left = await page.evaluate(async () => {
    const res = (await window.otto.core.request("samples.list", { offset: 0, limit: 50 })) as { r: { rows: unknown[] } };
    return res.r.rows.length;
  });
  expect(left).toBe(4); // 采样和它们的音轨都还在
  await app.close();
});

test("批量导入字幕：取消和导入之后界面都还在", async () => {
  test.setTimeout(120_000);
  const dir = mkdtempSync(join(tmpdir(), "otto-batch-sub-"));
  const files = ["01", "02"].map((ep) => {
    const wav = join(dir, `[Group] Batch Show [${ep}].wav`);
    execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=3", "-ac", "2", "-c:a", "pcm_s16le", wav]);
    writeFileSync(wav.replace(/\.wav$/, ".srt"), `1\n00:00:01,000 --> 00:00:02,000\n第${ep}話のせりふ\n`);
    return wav;
  });
  const { app, page } = await launch();
  await page.evaluate(async (paths) => void (await window.otto.core.request("sources.add", { paths })), files);
  await page.keyboard.press("ControlOrMeta+2");
  await page.keyboard.press("Escape");
  const group = page.getByTestId("source-group").first();
  await group.click({ button: "right" });
  await page.getByTestId("menu-check").click();
  const open = async () => {
    await page.getByTestId("batch-actions").click();
    await page.getByTestId("menu-subimport").click();
    await expect(page.getByTestId("subtitle-import-batch").getByTestId("table-row")).toHaveCount(2);
  };
  const alive = async () => {
    await expect(page.getByTestId("subtitle-import-batch")).toHaveCount(0);
    await expect(group).toBeVisible();
  };

  await open();
  await page.getByTestId("subtitle-import-batch").getByRole("button", { name: "取消" }).click();
  await alive();

  await open();
  await page.keyboard.press("Escape");
  await alive();

  await open();
  await page.getByTestId("subimport-batch-run").click();
  await alive();
  await app.close();
});
