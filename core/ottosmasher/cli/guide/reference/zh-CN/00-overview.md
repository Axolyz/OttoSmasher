# OttoSmasher agent 说明书

OttoSmasher 是音 MAD 素材工作台，登记原片、导入字幕、分离人声、分析日语音素与音高、保存采样和标签、按节奏或音高检索，再导出 WAV、视频或 REAPER item。

通过命令行 otto 操作正在运行的应用，命令与界面共用。修改会显示在应用中。数据编辑可以撤销；新建采样、原素材和音轨不能撤销。

## 应用与 agent 的分工

应用负责存储、分析、检索和导出。你负责理解材料、选择方法、判断内容，再把结果写回。相关原始计算可以直接给文件，不必先登记，见 `otto guide primitives`。

## 指令放在哪里

| 来源 | 内容 | 谁维护 |
|---|---|---|
| otto guide | 应用事实、接口和数据安全要求，中英各一份 | 应用开发者 |
| 工作区 Agent/skills/ | 可以编辑的方法和任务流程，按任务选择读取 | 用户 |
| 工作区 Agent/playbook.md | 用户的长期偏好，优先于一般方法 | 用户 |

用户明确要求决定当前任务目标，方法不能覆盖它。playbook 和 skills 不放宽数据安全要求。仅在用户要求记住或更新时修改其工作区指令。相关任务先读匹配技能及适用引用，不要把整套参考文档都读进上下文。

## 开始任务

1. 运行 otto status，确认应用、版本及工作区；没开则运行 otto open。
2. 运行 otto guide playbook。涉及内容判断时再读 `otto guide workflow`，确定范围、精度与可核验的完成条件。
3. 每个任务用一个 session。macOS / bash 为 export OTTO_AGENT_SESSION=my-task；PowerShell 为 $env:OTTO_AGENT_SESSION='my-task'。也可把 --session my-task 放在子命令之前或之后。
4. 对需要声音判断的任务，真实验证音频工具。对齐模型就绪不能证明 audio-mcp 可用。接入方法、失败处理及短片段示例见 `otto guide audio`。

## 可以接触的文件

- 不直接读写应用数据库。
- Library/ 只读或复制命令返回的明确路径，不写、不改名、不删除。
- 修改用户字幕前在旁边保留 backup_ 原件。用户原始媒体只读。
- 临时脚本和中间音频放自己的临时目录。需要长期使用的结果放到用户指定的项目位置，汇报留下什么。

## 调用与返回

stdout 为 UTF-8 JSON，进度和提示在 stderr。退出码 0 成功、1 业务或任务失败、2 用法或连接错误、3 用户拒绝或没有确认。stderr 有内容不等于失败，脚本检查退出码和 JSON。

先用 otto commands --grep 关键词 找命令，再用 otto describe 命令 看完整参数和结果。未声明的参数会被拒绝，不猜字段和返回包裹。JSON 中二进制是 base64，otto run 中为原生 bytes。

```sh
otto call samples.list @params.json
otto call samples.list -
otto run my_script.py
```

Windows PowerShell 通过 .cmd 传 JSON 时引号可能丢失，推荐 UTF-8 文件或 stdin。命令解析报错会提示这个问题，不要反复试转义。各平台例子见 `otto guide scripts`。

## 长任务

otto call 后加 --wait，或在后台运行 otto wait job ID。默认不刷进度，--progress 把进度写到 stderr；最终 stdout 仍是完整任务 JSON。用 `jobs.summaries` 看精简状态和 queuedAhead，`jobs.get` 查单个完整结果。排队数量不含运行任务，不是剩余秒数。

批量 succeeded 不表示每项成功，检查 speech.results、flatten.results 或原始计算的逐项结果。speech.align 等默认每页 100 条；--wait 取全，脚本可用 LinkClient.iter_results。

能后台等待时持续负责到约定完成条件。无法等待或缺少前置能力时说明阻碍和已保存的进度，不把中间状态宣称完成。会话恢复用 otto session。

## 危险操作确认

otto commands 标有 danger 的命令会等待用户在应用里确认，最多两分钟。退出码 3 表示未执行，不自动重试；继续独立工作并说明阻碍，收到用户继续指令再重发。命令行不能关闭这个确认。

工具权限限制和任务澄清是两回事。无法提权时不能绕过限制；缺少素材范围、处理精度或必要工具时，仍须把问题说明给用户。

## 更多

otto guide 主题 查看对应说明，--lang zh-CN/en 选择语言，--all 打印全部应用参考。otto guide skills 列出可编辑技能，notes 是其旧别名。otto setup skills 检查更新与失效命令；用户改过的文件不会被自动覆盖。
