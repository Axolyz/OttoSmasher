import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 作品/集数推断规则（P10，所有者 2026-10-07）：试算、草稿报错不能保存、保存走编辑通道且可撤销
test("推断规则：试算、校验、保存与撤销", async () => {
  const { app, page } = await launch();
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-source").click();
  const row = page.getByTestId("setting-source.infer_rules");
  const result = row.getByTestId("rules-result");

  // 默认规则试算默认样例
  await expect(result).toHaveText("第 1 条匹配：作品「Yuru Yuri」· 素材标识「01」");
  await row.getByTestId("rules-sample").fill("[DBD-Raws][Kemono Friends][02][1080P].mkv");
  await expect(result).toHaveText("第 2 条匹配：作品「Kemono Friends」· 素材标识「02」");
  await row.getByTestId("rules-sample").fill("no pattern here.mkv");
  await expect(result).toHaveAttribute("data-state", "none");

  // 草稿写错：显示是第几条、什么错，保存按钮不可用
  await row.getByRole("button", { name: "添加规则" }).click();
  const last = row.locator('[data-testid^="rule-"]').last();
  await last.fill("^(?P<work>");
  await expect(result).toHaveAttribute("data-state", "error");
  await expect(result).toContainText("第 8 条正则写法有误");
  await expect(row.getByTestId("rules-save")).toBeDisabled();
  await page.screenshot({ path: ".cache/playwright-results/settings-rules-error.png" });

  // 改对：新规则命中，保存
  await last.fill("^(?P<work>no pattern) (?P<episode>here)$");
  await expect(result).toHaveText("第 8 条匹配：作品「no pattern」· 素材标识「here」");
  await row.getByTestId("rules-save").click();
  await expect.poll(() => page.evaluate(async () => {
    const r = await window.otto.core.request<Record<string, { value: string[] }>>("settings.list");
    return r.ok && r.r["source.infer_rules"]!.value.length === 8;
  })).toBe(true);
  await page.screenshot({ path: ".cache/playwright-results/settings-rules.png" });

  // 撤销回到默认
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  await expect.poll(() => page.evaluate(async () => {
    const r = await window.otto.core.request<Record<string, { value: string[]; version: number }>>("settings.list");
    return r.ok && r.r["source.infer_rules"]!.value.length === 7;
  })).toBe(true);
  await app.close();
});

// 字幕规则（规格 06 §6.2、16 R4.4–R4.6、S11.2）：试算、拆分/清理、无效规则标红不能保存、五条一起保存一次撤销
test("字幕规则：试算、可选规则、校验、保存与撤销", async () => {
  const { app, page } = await launch();
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-subtitle").click();
  const ed = page.getByTestId("subtitle-rules");
  const trial = ed.getByTestId("subtitle-trial");

  // 默认样例：嵌套读音的说话人整体是一个名字，名字里的读音默认去掉（所有者 2026-10-24【基线变更】）
  await expect(ed.getByTestId("trial-kind")).toHaveText("台词");
  await expect(ed.getByTestId("trial-name")).toHaveText("アッカリ～ン");
  await expect(ed.getByTestId("trial-speakers")).toHaveText("京子たち");
  // 多行：音效行
  await trial.fill("（悲鳴）\n（倒れる音）");
  await expect(ed.getByTestId("trial-kind")).toHaveText("音效");
  await expect(ed.getByTestId("trial-name")).toHaveText("悲鳴 / 倒れる音");
  // 逐行读（所有者 2026-10-31【基线变更】）：有一行没标 → 不记、提示“有标注没记”；同一条里的音效行另成音效
  await trial.fill("（京子）あ\nい");
  await expect(ed.getByTestId("trial-speakers")).toContainText("—");
  await expect(ed.getByTestId("trial-withheld")).toBeVisible();
  await trial.fill("（園児たちの笑い声）\n（園児）私も～！");
  await expect(ed.getByTestId("trial-speakers")).toHaveText("園児");
  await expect(ed.getByTestId("trial-sfx")).toHaveText("園児たちの笑い声");

  // 填入拆分与清理示例 → 草稿立即生效
  await trial.fill("（結衣･ちなつ(ちなつ)）わあ…");
  await ed.getByTestId("setting-subtitle.speaker_split").getByRole("button").click();
  await ed.getByTestId("setting-subtitle.speaker_clean").getByRole("button").click();
  await expect(ed.getByTestId("trial-speakers")).toContainText("結衣、ちなつ");

  // 写错：缺命名组 → 那一条标红，保存不可用
  const note = ed.getByTestId("rule-subtitle.note_rule");
  const original = await note.inputValue();
  await note.fill("\\((.*?)\\)");
  await expect(ed.getByTestId("subtitle-trial-result")).toContainText("注释括号");
  await expect(ed.getByTestId("subtitle-trial-result")).toContainText("缺少命名组 content");
  await expect(ed.getByTestId("setting-subtitle.note_rule")).toHaveAttribute("data-invalid", "true");
  await expect(ed.getByTestId("subtitle-rules-save")).toBeDisabled();
  await page.screenshot({ path: ".cache/playwright-results/settings-subtitle-error.png" });
  await note.fill(original);

  // 保存（两条可选规则一起）→ 一次撤销回到默认
  await ed.getByTestId("subtitle-rules-save").click();
  const values = () =>
    page.evaluate(async () => {
      const r = await window.otto.core.request<Record<string, { value: string }>>("settings.list");
      return r.ok ? [r.r["subtitle.speaker_split"]!.value, r.r["subtitle.speaker_clean"]!.value] : null;
    });
  await expect.poll(values).toEqual(["[･・＆&、/／]", "[（(][^（）()]*[）)]"]);
  await page.screenshot({ path: ".cache/playwright-results/settings-subtitle.png" });
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  await expect.poll(values).toEqual(["、", "[（(][^（）()]*[）)]"]);
  await app.close();
});
