# 给 agent 的 OttoSmasher 说明：总览

OttoSmasher 是做音MAD 素材的桌面应用：登记视频与音频（“原素材”），导入字幕，分离人声，分析日语语音（音素、音高、节奏），
维护一个带标签的**采样**库，按节奏或音高找采样，导出 WAV、视频片段和 REAPER 条目。

你用命令行 `otto` 操作它。`otto` 连接**正在运行的应用**（所有者开着它），调用的就是应用界面自己用的那组命令，
所以你做的一切都会出现在应用里，也能在应用里撤销。

## 基本规则

1. **应用必须开着。** 用 `otto status` 看。显示 `"running": false`（退出码 2）就请所有者打开应用。
   不要自己打开数据库或 `Library/` 文件夹，只用命令。
2. **每个任务设一次会话 ID**：`export OTTO_AGENT_SESSION=<简短任务名>`。你的每个修改都记在它名下，
   之后所有者（或你）可以整批撤回这个会话（主题 `undo`）。
3. **stdout 只输出 JSON**，进度写在 stderr。退出码：`0` 成功，`1` 业务错误（JSON 里的 `error.code`），
   `2` 用法 / 连接 / 参数错误，`3` 所有者拒绝或没人确认。
4. **先查再猜**：`otto commands [--effect read|write|job] [--grep 词]`、`otto describe <命令>`（完整的参数与返回结构）、
   `otto describe <事件>`、`otto errors [错误码]`。
5. **耗时的工作是任务。** 加 `--wait` 就会一直跟到返回的任务、检索或视频导出结束：
   `otto call speech.submit '{...}' --wait`。
6. **撤销不了的命令**（`otto commands` 里带 `"danger"`：删除原素材或采样、给作品文件夹改名、清理存储、独立化后删原素材）
   会在应用里弹出确认框，你的调用**一直等到所有者回答**（所有者可能不在电脑前，可能要等几个小时）。等待时 stderr 有一行
   `"note": "waiting for the owner…"`。所以这类调用要放在后台跑或不设超时，最好把它们留到任务最后再做；
   你的进程被结束，请求就撤回了。退出码 3 表示所有者拒绝。被拒绝的命令不要重试，改为询问所有者。
   所有者可以在应用的「设置 › 命令行与 agent」里关掉这个确认，那时这些命令直接执行；这一项只有所有者能改，命令行改不了。

## 调用命令

```sh
otto call samples.list '{"limit": 5}'
otto call samples.list @query.json        # 参数来自文件
echo '{"text": "ゲーム"}' | otto call samples.list -
```

命令没声明的参数会被拒绝（`bad-request`，带出错位置）。所有 ID 都是字符串。

## 应用不做的事

命令列表以外的事都由你用自己的工具做：清理字幕文件、语音识别、判断一句台词说的是什么、抠图之类的图像处理、剪视频、搭 REAPER 工程。
组合方式：从应用导出 → 用你的工具处理 → 把结果带回来（新的字幕文件、画面绑定、标签）。主题 `combine` 讲怎么做。

## 主题

`otto guide <主题>`（加 `--lang en` 或 `--lang zh-CN`；`--all` 打印全部；`--skill` 打印成 Claude Code skill）：
`concepts`、`prepare`、`samples`、`search`、`export`、`combine`、`undo`、`example`。
