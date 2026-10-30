import { mkdirSync, mkdtempSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

test("task drawer uses frozen PyMSS settings independently of ONNX", async () => {
  mkdirSync(resolve(".cache/e2e-device"), { recursive: true });
  const { app, page } = await launch({ workspace: mkdtempSync(resolve(".cache/e2e-device/ws-")) });
  try {
    await page.evaluate(async () => {
      const request = async (name: string, params: Record<string, unknown>) => {
        const r = await window.otto.core.request(name, params);
        if (!r.ok) throw new Error(JSON.stringify(r.e));
        return r.r;
      };
      // Hold the model lane; these synthetic separation requests never run a model.
      await request("jobs.submit", { kind: "selftest.sleep_model", params: { seconds: 60 } });
      for (const device of ["auto", "cpu", "cuda", "mps"]) {
        await request("jobs.submit", { kind: "separate", params: { device, deviceId: 2 } });
      }
      await request("jobs.submit", { kind: "separate", params: {} });
    });
    await page.getByTestId("nav-tasks").click();
    await expect(page.getByText("分离设备设置：自动（由 PyMSS Studio 选择）", { exact: true })).toBeVisible();
    await expect(page.getByText("分离设备设置：CPU", { exact: true })).toBeVisible();
    await expect(page.getByText("分离设备设置：CUDA（设备 2）", { exact: true })).toBeVisible();
    await expect(page.getByText("分离设备设置：MPS（Apple）", { exact: true })).toBeVisible();
    await expect(page.getByText("分离设备设置：未知", { exact: true })).toBeVisible();
  } finally {
    // 取消占着模型通道的睡眠任务和排队的分离，否则关应用要等它睡完
    await page.evaluate(async () => {
      const r = await window.otto.core.request("jobs.list", { limit: 50 });
      for (const j of r.ok ? r.r : []) {
        if (j.status === "queued" || j.status === "running") await window.otto.core.request("jobs.cancel", { id: j.id });
      }
    });
    await app.close();
  }
});
