# 过程记录（存档）

开发期间（2026-10-05 起，到 0.1.x 发布）的原始记录，**原样保留、只追加不改**。平时不用读；代码注释、提交说明里的旧编号要查出处时来这里。
现在有效的规矩看 [`../DECISIONS.md`](../DECISIONS.md)，未结事项看 [`../ROADMAP.md`](../ROADMAP.md)。

| 文件 | 是什么 |
|---|---|
| [`QUESTIONS.md`](QUESTIONS.md) | 规格疑问、所有者的逐轮答复、基线变更提议与决定（原 `docs/QUESTIONS.md`，按时间追加）。DECISIONS 从这里整理出现行决定；已被取代的段落旁标了“已被 DECISIONS §x 取代” |
| [`ROADMAP-stages.md`](ROADMAP-stages.md) | 原 `docs/ROADMAP.md` 全文：阶段 3–11 / A 的完成定义、会话交接协议、各阶段“开工前要知道的”、遗留事项登记表 L1–L54 |
| [`UI_PLAN.md`](UI_PLAN.md) | 原 `docs/UI_PLAN.md`：阶段 0 照原型写的界面方案 §0–§10，加 §11 命令行与 agent（原 §23）。正文没随实现更新，现在以应用为准，仍有效的统一规则在 DECISIONS「界面」 |
| [`UI_PLAN-rounds.md`](UI_PLAN-rounds.md) | 原 `docs/UI_PLAN.md` §11–§22：定稿前各轮修改、阶段 4–9 实现时的界面取舍 |
| [`retiming-and-speakers-research.md`](retiming-and-speakers-research.md) | 字幕对轴与说话人识别试过哪些模型、流程架构怎么定下来、实测数字与局限；**要接着做或换模型时先读它** |
| [`prototype.html`](prototype.html)、[`prototype-v1.html`](prototype-v1.html) | 阶段 0 与所有者敲定的可点原型（v3.3）和被否决的 v1。现在的应用已远比原型完善，**不再作为参照** |

## 编号去哪查

| 编号 | 出处 |
|---|---|
| Q1–Q24、D1–D3（例：Q3、Q23、Q D3） | `QUESTIONS.md` 第一到第四节 |
| “QUESTIONS「某一节」” | `QUESTIONS.md` 里同名的小节 |
| L1–L54（遗留事项） | 还没结的在 [`../ROADMAP.md`](../ROADMAP.md)；全部原文在 `ROADMAP-stages.md` §3 |
| 阶段 0–11、阶段 A | `ROADMAP-stages.md` §4 |
| UI_PLAN §0–§10、§11 | `UI_PLAN.md`（§11 = 原 §23“命令行与 agent”） |
| UI_PLAN §11–§22（2026-10-31 以前的旧编号） | `UI_PLAN-rounds.md` |
| 规格 NN、P、R、S、A 编号 | 不在这里，见 [`../spec/`](../spec/README.md) |
