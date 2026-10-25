import { execFile, execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { promisify } from "node:util";
import { expect, test } from "@playwright/test";
import { launch, unbracketed } from "./helpers";

// 命令行 otto 对着正在运行的应用（阶段 A）：改动在界面上提示、会话标记、撤销不了的命令弹确认框、按会话撤回、任务抽屉的 agent 标记
const run = promisify(execFile);
const PY = resolve(process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");

test("命令行：资料已更新、会话标记与撤回、危险命令等确认、任务标记", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-agent-"));
  const wav = join(dir, "agent line.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:duration=3", wav]);
  const { app, page, workspace } = await launch();
  const env = { ...process.env, OTTO_WORKSPACE: workspace, OTTO_AGENT_SESSION: "e2e-agent" };
  const otto = async (...args: string[]) => JSON.parse((await run(PY, ["-m", "ottosmasher.cli", ...args], { env })).stdout);

  // 界面这边建一个原素材和一个采样
  const sample = await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const s = (await req("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    const sid = s.r[0]!.sourceId;
    const a = (await req("assets.listForSource", { sourceId: sid })) as { r: Array<{ id: string }> };
    const smp = (await req("samples.create", { assetId: a.r[0]!.id, start: 0.5, end: 1.5, name: "agent test" })) as { r: { id: string } };
    return smp.r.id;
  }, wav);

  // 命令行打标签：界面提示“资料已更新”（别处的改动，P8），顶栏出现会话标记
  const plan = await otto("call", "samples.batchEdit", JSON.stringify({ ids: [sample], fields: { addTags: ["topic:game"] } }));
  const applied = await otto("call", "edits.apply", JSON.stringify({ batch: plan.batch }));
  expect(applied.edit_id).toBeTruthy();
  await expect(page.getByTestId("refresh-lists")).toBeVisible();
  await expect(page.getByTestId("agent-badge")).toBeVisible();

  // 会话面板：一处修改 → 撤回
  await page.getByTestId("agent-badge").click();
  const row = page.getByTestId("agent-panel").getByTestId("agent-session");
  await expect(row).toContainText("e2e-agent");
  await expect(row).toContainText("1 处修改");
  await page.screenshot({ path: ".cache/playwright-results/agent-panel.png" });
  await row.getByTestId("agent-undo").click();
  await page.getByTestId("agent-undo-confirm").getByTestId("confirm-ok").click();
  await expect(page.getByText("已撤回 1 处修改")).toBeVisible();
  const tags = await otto("call", "tags.ofSamples", JSON.stringify({ ids: [sample] }));
  expect(JSON.stringify(tags)).not.toContain("topic:game");

  // 撤销不了的命令：先拒绝，再允许
  const declined = run(PY, ["-m", "ottosmasher.cli", "call", "samples.delete", JSON.stringify({ ids: [sample] })], { env }).then(
    () => 0,
    (e: { code: number }) => e.code,
  );
  const dlg = page.getByTestId("agent-confirm");
  await expect(dlg).toContainText("删除采样");
  await expect(dlg).toContainText("agent test");
  await page.screenshot({ path: ".cache/playwright-results/agent-confirm.png" });
  await dlg.getByRole("button", { name: "取消" }).click();
  expect(await declined).toBe(3);
  const approved = otto("call", "samples.delete", JSON.stringify({ ids: [sample] }));
  await expect(dlg).toContainText("会一直等你回答");
  await dlg.getByTestId("confirm-ok").click();
  expect((await approved).deleted).toBe(1);

  // 设置里关掉确认：撤销不了的命令直接执行，不弹框（这里执行结果是“没有这个采样”）
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-agent").click();
  await page.getByTestId("setting-agent.skip_confirm").locator("label").click();
  await expect(page.getByText("已保存")).toBeVisible();
  await page.keyboard.press("Escape");
  const direct = await run(PY, ["-m", "ottosmasher.cli", "call", "samples.delete", JSON.stringify({ ids: [sample] })], { env }).then(
    () => 0,
    (e: { code: number }) => e.code,
  );
  expect(direct).toBe(1);
  await expect(dlg).toHaveCount(0);

  // 命令行提交的任务在任务抽屉里带 agent 标记
  await otto("call", "jobs.submit", JSON.stringify({ kind: "selftest.sleep", params: { seconds: 0.2 } }), "--wait");
  await page.getByTestId("nav-tasks").click();
  await expect(page.getByTestId("job").first().getByTestId("job-agent")).toBeVisible();
  await app.close();
});

test("命令行的会话面板与确认框在伪语言下没有写死的文字", async () => {
  const { app, page, workspace } = await launch({ locale: "pseudo" });
  const env = { ...process.env, OTTO_WORKSPACE: workspace, OTTO_AGENT_SESSION: "pseudo-agent" };
  await run(PY, ["-m", "ottosmasher.cli", "call", "core.hello"], { env });
  await page.getByTestId("agent-badge").click();
  await expect(page.getByTestId("agent-session")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.keyboard.press("Escape");
  const pending = run(PY, ["-m", "ottosmasher.cli", "call", "samples.delete", JSON.stringify({ ids: ["nope"] })], { env }).catch(() => null);
  await expect(page.getByTestId("agent-confirm")).toBeVisible();
  expect(await unbracketed(page)).toEqual([]);
  await page.getByTestId("agent-confirm").getByTestId("confirm-ok").click();
  await pending;
  await app.close();
});
