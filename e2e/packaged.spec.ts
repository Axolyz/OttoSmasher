import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { _electron as electron, expect, test } from "@playwright/test";
import type { PlayerState } from "../app/shared/protocol";

// 发布包冒烟（阶段 10，15 §15.8）：跑打好的 .app（tools/package_mac.py 的产物），清空的环境变量、带中文与空格的空工作区。
// 只在 OTTO_PACKAGED_E2E=1 时运行（平时的 e2e 测的是源码运行）。
const WIN = process.platform === "win32";
const APP = resolve(WIN ? "out/release/OttoSmasher/OttoSmasher.exe" : "out/release/OttoSmasher.app/Contents/MacOS/OttoSmasher");
test.skip(!process.env.OTTO_PACKAGED_E2E || !existsSync(APP), "需要 OTTO_PACKAGED_E2E=1 和打好的发布包（tools/package_mac.py、tools/package_win.py）");
// 不继承开发环境（没有 Homebrew、没有 .venv）
const ENV: Record<string, string> = WIN
  ? Object.fromEntries(["SystemRoot", "windir", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramData", "SystemDrive", "HOMEDRIVE", "HOMEPATH"].flatMap((k) => (process.env[k] ? [[k, process.env[k]!]] : [])).concat([["PATH", `${process.env.SystemRoot}\\System32`]]))
  : { HOME: process.env.HOME!, PATH: "/usr/bin:/bin" };

test("发布包：随包的模型、媒体工具、播放与命令行", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-packaged-"));
  const wav = join(dir, "素材 目录", "试听 片段.wav");
  mkdirSync(join(dir, "素材 目录"), { recursive: true });
  execFileSync(WIN ? "ffmpeg" : "/opt/homebrew/bin/ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=3", wav]);
  const workspace = join(dir, "工作 区");
  const app = await electron.launch({
    executablePath: APP,
    args: ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling"],
    env: { ...ENV, OTTO_WORKSPACE: workspace, OTTO_MPV_AO: "null", OTTO_NO_SELF_INSTALL: "1", OTTO_REGISTRY_DIR: join(dir, "registry") }, // 不改这台电脑上真正的 otto
  });
  try {
    const page = await app.firstWindow();
    await expect.poll(() => page.evaluate(async () => (await window.otto.core.status()).state), { timeout: 30000 }).toBe("ready");
    // 随包的模型全部就绪（不需要下载）
    const models = await page.evaluate(async () => ((await window.otto.core.request("models.status")) as { r: { files: Array<{ model: string; state: string }> } }).r.files);
    expect(models.map((m) => m.state)).toEqual(models.map(() => "ready"));
    // 登记（随包的 ffprobe）、试听播完（mpv 渲染桥与随包的 libmpv）
    const states = await page.evaluate(async (p) => {
      const req = window.otto.core.request;
      const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
      const aid = add.r[0]!.assets[0]!.assetId;
      const seen: PlayerState[] = [];
      window.otto.player.onState((s) => seen.push(s));
      await window.otto.player.audition(aid, 1.0, 1.5);
      await new Promise((r) => setTimeout(r, 2500));
      return seen.filter((s) => s.player === "audition");
    }, wav);
    expect(states.some((s) => s.ended)).toBe(true);
    // 设置里的 otto 指向包里的启动器
    await page.keyboard.press("ControlOrMeta+,");
    await page.getByTestId("settings-group-agent").click();
    await expect(page.getByTestId("agent-otto-path")).toHaveText(WIN ? /resources\\bin\\otto\.cmd$/ : /OttoSmasher\.app\/Contents\/Resources\/bin\/otto$/);
  } finally {
    await app.close();
  }
});
