import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, symlinkSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 节奏与卡拍（规格 09 §9.3–§9.5、12 §12.1、§12.3、UI_PLAN §1、§3）：顶栏 BPM → 舞台「节奏与卡拍」面板（方案、映射图、试听：不卡拍/卡拍 ×
// 原声/原声＋咔哒/纯咔哒）→ 全局播放条显示版本 → 分组与停顿（切分/合并，可撤销）→ 人工占格 → 临时纯 mora 与「写进人工占格」→ 交接 ▾
// （导出卡拍 WAV、复制 REAPER 交接：剪贴板 REAPERMedia）→ 列表播放按钮右键 = 卡拍；单音没有卡拍。
const MODELS = resolve("dev-workspace/Models");
const ONSETS = [1.0, 1.25, 1.5, 1.75, 2.5, 2.75];

test("节奏与卡拍：BPM、面板、试听、分组与停顿、人工占格、交接", async () => {
  test.skip(!existsSync(join(MODELS, "pydomino", "phoneme_transition_model.onnx")), "dev models missing");
  test.setTimeout(180_000);
  const base = mkdtempSync(join(tmpdir(), "otto-rhythm-"));
  const workspace = join(base, "工作区 rhythm");
  mkdirSync(workspace);
  symlinkSync(MODELS, join(workspace, "Models"));
  const wav = join(base, "v.wav");
  const gate = ONSETS.map((o) => `between(t\\,${o}\\,${(o + 0.2).toFixed(2)})`).join("+"); // 表达式里的逗号要转义
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `aevalsrc=0.3*sin(2*PI*220*t)*(${gate})+0.002*sin(2*PI*90*t):s=44100:d=4`, wav]);
  const { app, page } = await launch({ workspace });
  // 资料：一句「かかかかかか」（语音分析用真实模型，再存一个人工时间版本让音块确定），一个调谐单音
  const sid = await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req<Array<{ sourceId: string; assets: Array<{ assetId: string }> }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    const c = (await req("samples.create", { assetId: aid, start: 0.9, end: 3.1, name: "かかかかかか", nature: "speech" })) as { r: { id: string; version: number } };
    await req("segments.add", { sourceId: add.r[0]!.sourceId, start: 0.9, end: 3.1, text: "かかかかかか" }); // 台词 = 文本层的段（采样读判定区间里的段）
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
      // 人工时间改的是这段在这条轨上的分析（整段的音素，不是采样范围里合成的那份）
      const v = (await req("speech.sample", { id })) as { r: { units: Array<{ unitId: string; headVersion: number; head: { result: { phones: Array<{ label: string }> } } }> } };
      const u = v.r.units[0]!;
      let i = 0;
      const lines = u.head.result.phones.map((p) => {
        const o = onsets[Math.floor(i / 2)]!;
        const line = p.label === "k" ? `${(o - 0.04).toFixed(3)}\t${o.toFixed(3)}\tk` : `${o.toFixed(3)}\t${(o + 0.2).toFixed(3)}\t${p.label}`;
        i += 1;
        return line;
      });
      const r = await req("speech.saveManual", { unitId: u.unitId, version: u.headVersion, text: lines.join("\n") });
      if (!r.ok) throw new Error(JSON.stringify(r.e));
    },
    { id: sid, onsets: ONSETS },
  );

  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  const rows = page.getByTestId("sample-row");
  await expect(rows).toHaveCount(2);
  await rows.filter({ hasText: "かかかかかか" }).click();

  // ---- 面板：没填 BPM = 原速卡拍；三个方案；映射图
  const panel = page.getByTestId("rhythm-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("rhythm-bpm")).toContainText("原速卡拍");
  await expect(panel.getByTestId("rhythm-plan-near_fast")).toContainText("1.00×");
  await expect(panel.getByTestId("rhythm-map")).toBeVisible();
  await expect(panel.getByTestId("rhythm-map-text")).toContainText("同比例秒数轴");

  // ---- 顶栏 BPM：越界拒绝；180 → 面板与方案跟着变
  const bpm = page.getByTestId("bpm");
  await bpm.fill("500");
  await bpm.press("Enter");
  await expect(page.getByText("BPM 范围 20–400")).toBeVisible();
  await expect(bpm).toHaveValue("");
  await bpm.fill("180");
  await bpm.press("Enter");
  await expect(panel.getByTestId("rhythm-bpm")).toHaveText("BPM 180");
  await expect(panel.getByTestId("rhythm-plan-near_fast")).toContainText("格/拍");
  await page.waitForTimeout(300);
  await page.screenshot({ path: ".cache/playwright-results/rhythm-panel.png" });
  await panel.scrollIntoViewIfNeeded();
  await panel.screenshot({ path: ".cache/playwright-results/rhythm-panel-card.png" });

  // ---- 试听：舞台「♩ 卡拍」→ 播放条显示卡拍与方案；面板：不卡拍 + 原声＋咔哒
  await page.getByTestId("stage-stretched").click();
  await expect(page.getByTestId("dock-version")).toHaveText("卡拍 · 180 BPM · 近快");
  await panel.getByTestId("rhythm-sound-voice+click").click();
  await panel.getByTestId("rhythm-play-original").click();
  await expect(page.getByTestId("dock-version")).toHaveText("原声 · 原声＋咔哒");
  await panel.getByTestId("rhythm-plan-near_slow").click();
  await panel.getByTestId("rhythm-sound-click").click();
  await panel.getByTestId("rhythm-play-stretched").click();
  await expect(page.getByTestId("dock-version")).toHaveText("卡拍 · 180 BPM · 近慢 · 纯咔哒");
  await page.getByTestId("dock-stop").click();
  await expect(page.getByTestId("dock-now")).toContainText("没有在播放");

  // ---- 分组与停顿：一处停顿切出两个语段；单击自动切口 = 合并（可撤销）
  await page.getByTestId("rhythm-grouping").click();
  const grouping = page.getByTestId("rhythm-grouping-panel");
  await expect(grouping).toContainText("1 处停顿");
  await expect(grouping).toContainText("2 个语段");
  await grouping.screenshot({ path: ".cache/playwright-results/rhythm-grouping.png" });
  await grouping.getByTestId("rhythm-cut-block").nth(4).click();
  await expect(grouping).toContainText("1 个语段");
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  await page.getByTestId("rhythm-grouping").click();
  await expect(page.getByTestId("rhythm-grouping-panel")).toContainText("2 个语段");
  await page.keyboard.press("Escape");

  // ---- 人工占格：改即保存；面板里看得到
  await panel.getByTestId("rhythm-cells").click();
  const cells = page.getByTestId("rhythm-cells-panel");
  const first = cells.getByRole("textbox").first();
  await first.fill("3");
  await first.press("Enter");
  await expect(cells.getByRole("button", { name: "自动" })).toHaveCount(1);
  await cells.screenshot({ path: ".cache/playwright-results/rhythm-cells.png" });
  await page.keyboard.press("Escape");

  // ---- 临时纯 mora → 写进人工占格
  await panel.getByTestId("rhythm-mora").click();
  await panel.getByTestId("rhythm-mora-save").click();
  await expect(page.getByText("已把 mora 占格写进人工占格")).toBeVisible();

  // ---- 交接 ▾：导出卡拍 WAV（文件名带“卡拍-180BPM”）；复制 REAPER 交接 → 剪贴板 REAPERMedia
  const before = await app.evaluate(async ({ clipboard }) => clipboard.readText());
  await page.getByTestId("stage-handoff").click();
  await page.getByRole("menuitem", { name: "导出卡拍 WAV" }).click();
  await expect(page.getByText(/卡拍-180BPM/).first()).toBeVisible();
  await page.getByTestId("stage-handoff").click();
  await page.getByRole("menuitem", { name: "复制 REAPER 交接（原始音频，靠拉伸标记卡拍）" }).click();
  await expect(page.getByText("已复制 · 在 REAPER 选择轨道和光标位置后粘贴")).toBeVisible();
  const clip = await app.evaluate(async ({ clipboard }) => {
    const fmt = 'electron application/osclipboard;format="REAPERMedia"';
    for (const item of await clipboard.read()) {
      if (item.types.includes(fmt)) return Buffer.from(await ((await item.getType(fmt)) as Blob).arrayBuffer()).toString("utf8");
    }
    return null;
  });
  // ⌘C（所有者选丙）：采样库里复制 REAPER 交接，默认“已卡拍的音频”。真实的 ⌘C 走应用菜单的「拷贝」= webContents.copy（Playwright 的合成按键不经过原生菜单）
  const readClip = () =>
    app.evaluate(async ({ clipboard }) => {
      const fmt = 'electron application/osclipboard;format="REAPERMedia"';
      for (const item of await clipboard.read()) {
        if (item.types.includes(fmt)) return Buffer.from(await ((await item.getType(fmt)) as Blob).arrayBuffer()).toString("utf8");
      }
      return "";
    });
  await page.getByTestId("stage-title").click();
  await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.webContents.copy());
  await expect.poll(readClip, { timeout: 15000 }).toContain("卡拍-180BPM");
  expect(clip).not.toBeNull();
  expect(clip!.startsWith("<ITEM\0")).toBe(true);
  expect(clip!.endsWith("\0\0")).toBe(true);
  expect(clip).toContain("PLAYRATE 1 1 0 -1 0 0.0025");
  // 只写秒：写了按采样 BPM 算的节拍位置，REAPER 粘贴时会整体缩放条目、改 Playback rate（所有者 2026-11-04）
  // 两个菜单项各生成什么：原始音频的文件名没有“卡拍”，标记会拉伸（目标 ≠ 源）；已卡拍的音频文件名有“卡拍”，标记处目标 = 源
  const markersOf = (text: string) =>
    /\0SM ([^\0]+)\0/.exec(text)![1]!.split(" + ").map((m) => m.split(" ").map(Number) as [number, number]);
  expect(/\0FILE [^\0]+/.exec(clip!)![0]).not.toContain("卡拍-");
  expect(markersOf(clip!).some(([t, src]) => Math.abs(t - src) > 1e-6)).toBe(true);
  await app.evaluate(({ clipboard }) => clipboard.clear()); // 上面 ⌘C 留下的也是这一种，先清掉才算测到菜单项
  await page.getByTestId("stage-handoff").click();
  await page.getByRole("menuitem", { name: "复制 REAPER 交接（已卡拍的音频，标记只用于微调）" }).click();
  await expect.poll(readClip, { timeout: 15000 }).toContain("卡拍-180BPM");
  const bakedClip = await readClip();
  expect(markersOf(bakedClip).every(([t, src]) => Math.abs(t - src) < 1e-6)).toBe(true);
  expect(clip).toMatch(/\0LENGTH [\d.]+\0/);
  expect(clip).toMatch(/\0SM [\d.]+ [\d.]+( \+ [\d.]+ [\d.]+)*\0/);
  await app.evaluate(async ({ clipboard }, text) => clipboard.writeText(text), before); // 还原所有者的剪贴板（文字）

  // ---- ⌥⌘ 拖出 = REAPER 条目文件（只有 ITEM，能拖进已有的轨道，带拉伸标记）；系统拖拽本身人工验收
  await app.evaluate(({ BrowserWindow }) => {
    const g = globalThis as unknown as { __drags: string[][] };
    g.__drags = [];
    for (const w of BrowserWindow.getAllWindows())
      w.webContents.startDrag = (item: { files?: string[]; file: string }) => {
        g.__drags.push(item.files ?? [item.file]);
      };
  });
  const dragged = () => app.evaluate(() => (globalThis as unknown as { __drags: string[][] }).__drags);
  const rb = (await rows.filter({ hasText: "かかかかかか" }).boundingBox())!;
  await page.keyboard.down("Alt");
  await page.keyboard.down("ControlOrMeta");
  await page.mouse.move(rb.x + rb.width * 0.5, rb.y + rb.height / 2);
  await page.mouse.down();
  await page.mouse.move(rb.x + rb.width * 0.5 + 40, rb.y + rb.height / 2, { steps: 4 });
  await expect.poll(async () => (await dragged()).length, { timeout: 15000 }).toBe(1);
  await page.mouse.up();
  await page.keyboard.up("ControlOrMeta");
  await page.keyboard.up("Alt");
  const [rtt] = (await dragged())[0]!;
  expect(rtt).toMatch(/\.RTrackTemplate$/);
  const rttText = readFileSync(rtt!, "utf8");
  expect(rttText.startsWith("<ITEM\n")).toBe(true);
  expect(rttText).not.toContain("<TRACK");
  expect(rttText).toContain("\nSM ");

  // ---- 列表播放按钮：右键 = 卡拍（近快）；单音没有节奏面板、没有 ♩ 卡拍
  await rows.filter({ hasText: "かかかかかか" }).getByTestId("sample-play").click({ button: "right" });
  await expect(page.getByTestId("dock-version")).toHaveText("卡拍 · 180 BPM · 近快");
  await page.getByTestId("dock-stop").click();
  await rows.filter({ hasText: "単音" }).click();
  await expect(page.getByTestId("stage-title")).toHaveText("単音");
  await expect(page.getByTestId("rhythm-panel")).toHaveCount(0);
  await expect(page.getByTestId("stage-stretched")).toHaveCount(0);
  await app.close();
});
