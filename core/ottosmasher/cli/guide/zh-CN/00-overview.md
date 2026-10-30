# 给 agent 的 OttoSmasher 说明：总览

OttoSmasher 是做音MAD 素材的桌面应用：登记视频与音频（“原素材”），导入字幕，分离人声，分析日语语音（音素、音高、节奏），
维护一个带标签的**采样**库，按节奏或音高找采样，导出 WAV、视频片段和 REAPER 条目。

你用命令行 `otto` 操作它。`otto` 连接**正在运行的应用**（所有者开着它），调用的就是应用界面自己用的那组命令，
所以你做的一切都会出现在应用里，也能在应用里撤销。

## 分工

应用做**确定的事**：存资料、分离、对齐分析、检索、卡拍、导出，结果可靠、可撤销。
**需要判断的事归你**：字幕写法乱了怎么清理、哪些台词“在说游戏”、没有字幕时 OP 在哪、一段声音是谁在说……
应用给你原子能力——读资料、拿到音频和画面、把结论写回去（标签、台词段、OP/ED、默认轨……）——你用自己的推理和工具把它们串起来。
命令分两层：**业务命令**改资料库里的对象，**原始能力**只做计算（对齐、读音、测音高、读字幕文件……），声音可以是任意文件（主题 `primitives`）。
应用里的规则或自动识别不灵时，不要等应用改：读资料、自己判断、把结果写回去（主题 `combine`）。
说明书里的做法和顺序都是例子，用来说明应用怎么工作；必须遵守的只有下面的基本规则。

## 基本规则

1. **应用必须开着。** 用 `otto status` 看。显示 `"running": false`（退出码 2）就请所有者打开应用。
   不要自己打开数据库或 `Library/` 文件夹，只用命令。原素材的媒体文件和字幕可以直接读。
2. **每个任务设一次会话 ID**：`export OTTO_AGENT_SESSION=<简短任务名>`。你的每个修改都记在它名下，
   之后所有者（或你）可以整批撤回这个会话（主题 `undo`）。
3. **stdout 只输出 JSON**，进度写在 stderr。退出码：`0` 成功，`1` 业务错误（JSON 里的 `error.code`），
   `2` 用法 / 连接 / 参数错误，`3` 所有者拒绝或没人确认。
   音高帧、频谱等二进制字段按命令结构中的 `contentEncoding: base64` 输出为字符串；`otto run` 的 Python 客户端直接返回 `bytes`。
4. **先查再猜**：`otto commands [--effect read|write|job] [--grep 词]`、`otto describe <命令>`（完整的参数与返回结构）、
   `otto describe <事件>`、`otto errors [错误码]`。
5. **耗时的工作是任务。** 加 `--wait` 就会一直跟到返回的任务、检索或视频导出结束：
   `otto call speech.submit '{...}' --wait`。分离、语音分析、测音高共用“模型”通道（排队方式见主题 `prepare`）。
   任务 `succeeded` 只表示跑完了：批量任务里逐项的失败写在结果里，要看（主题 `concepts`）。
6. **撤销不了的命令**（`otto commands` 里带 `"danger"`：删除原素材或采样、给作品文件夹改名、清理存储、独立化后删原素材）
   会在应用里弹出确认框，你的调用最多等 2 分钟（等待时 stderr 有一行 `"note": "waiting for the owner…"`）。
   退出码 3 表示没有执行：所有者拒绝了（`agent-confirm-declined`），或 2 分钟没人回答（`agent-confirm-timeout`，所有者可能不在电脑前；
   这个请求会留在应用的操作历史里给所有者看）。这时**不要重试**：停下依赖这一步的工作，把想做什么、为什么告诉所有者，
   其他不受影响的工作照做，最后汇报；所有者回来让你继续时再发一次。
   放行时应用会核对资料和提问时是否一样，变了就带新的影响重新问。
   所有者可以在应用的「设置 › 命令行与 agent」里关掉这个确认，那时这些命令直接执行；这一项只有所有者能改，命令行改不了。

## 调用命令

```sh
otto call samples.list '{"limit": 5}'
otto call samples.list @query.json        # 参数来自文件
echo '{"text": "ゲーム"}' | otto call samples.list -
otto run my_script.py                     # 一次要调很多命令时写成 Python 脚本（主题 scripts）
```

命令没声明的参数会被拒绝（`bad-request`，带出错位置）。所有 ID 都是字符串。

## 主题

`otto guide <主题>`（加 `--lang en` 或 `--lang zh-CN`；`--all` 打印全部正式主题）：
`concepts`、`prepare`、`samples`、`search`、`primitives`、`export`、`combine`、`scripts`、`undo`、`example`。
另有 `notes`：实测攒下的经验和坑，**不是规定**，卡住或想找做法时再看。
`otto guide --skill-dir <目录>` 把这些写成一个 skill 文件夹（Claude Code、Codex 都认），按需读取。
