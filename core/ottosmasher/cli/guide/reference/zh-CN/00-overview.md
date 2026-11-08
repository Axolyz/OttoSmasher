# OttoSmasher agent 说明书

OttoSmasher 是音 MAD 素材工作台：登记原片、导入字幕、分离人声、分析日语音素与音高、保存采样和标签，按节奏或音高检索，再导出 WAV、视频或 REAPER item。

通过命令行 otto 操作正在运行的应用，调用的是界面同一组功能。资料编辑可以撤销；新建的采样、原素材和音轨用删除处理。

## 应用与你的分工

应用负责存储、分析、检索和导出。你负责理解材料、选择方法、判断内容，再把结论写回。原始计算也能直接接收文件，见 `otto guide primitives`。

## 指令放在哪里

| 来源 | 内容 | 谁维护 |
|---|---|---|
| otto guide | 应用对象、接口和操作要求，中英各一份 | 应用开发者 |
| 工作区 Agent/skills/ | 按任务选读、可以编辑的方法 | 用户 |
| 工作区 Agent/playbook.md | 用户的长期偏好，优先于一般方法 | 用户 |

以用户的任务要求为准，选读相关技能和引用。用户要你记住偏好时写进 playbook，要改做法时更新相应 skill；其余时候沿用现有文件。应用的文件管理和确认规则见下文。

## 开始任务

1. 运行 otto status，确认应用、版本及工作区；没开则运行 otto open。
2. 读 otto guide playbook。涉及内容判断时，再看 `otto guide workflow` 选定范围和精度。
3. 每个任务用一个 session。macOS / bash：export OTTO_AGENT_SESSION=my-task；PowerShell：$env:OTTO_AGENT_SESSION='my-task'。也可把 --session my-task 放在子命令前或后。
4. 需要声音判断时，先在短片段上试好音频工具。接法和用法见 `otto guide audio`。

## 可以接触的文件

- 资料通过应用命令读写，数据库不直接读写。
- Library/ 中可以读取或复制命令返回的明确路径；文件的写入、改名和删除由应用处理。
- 修改字幕前，在旁边保留 backup_ 原件。用户原始媒体只读。
- 临时脚本和中间音频放自己的临时目录，长期结果放用户指定的项目位置；结束时说明留下的文件。

## 调用与返回

stdout 是 UTF-8 JSON，进度和提示在 stderr。退出码 0 成功、1 业务或任务失败、2 用法或连接错误、3 用户拒绝或没有确认。脚本结合退出码和 JSON 判断结果。

用 otto commands --grep 关键词 找命令，再用 otto describe 命令 看参数和返回结构。参数按 schema 传入。JSON 中的二进制为 base64，otto run 中为原生 bytes。

```sh
otto call samples.list @params.json
otto call samples.list -
otto run my_script.py
```

PowerShell 经 .cmd 传 JSON 时可能丢引号，推荐 UTF-8 文件或 stdin。各平台例子见 `otto guide scripts`。

## 长任务

otto call 后加 --wait，或运行 otto wait job ID 等结束。默认安静等待，--progress 把进度写到 stderr，最终 stdout 返回完整结果。`jobs.summaries` 给出精简状态及同通道排在前面的待执行数 queuedAhead，`jobs.get` 查询单个完整任务。

批量任务结束后查看 speech.results、flatten.results 或原始计算的逐项结果，其中会保留失败项。speech.align 等默认每页 100 条，--wait 自动取全，脚本可用 LinkClient.iter_results。

环境支持后台等待时，等到任务结束再继续。受环境限制需要稍后恢复时，保存进度并说明下一步；otto session 可查看本会话的任务和创建物。

## 危险操作确认

otto commands 中标有 danger 的命令会等用户在应用里确认，最多两分钟。退出码 3 表示没有执行：先继续其他工作，告诉用户待确认的操作；收到继续指令后再发。确认开关由用户在设置里管理。

宿主权限、素材范围和处理精度各自处理。缺少权限或必要信息时，说明需要用户协助的部分，并继续其他准备。

## 更多

otto guide 主题 查看对应说明，--lang zh-CN/en 选择语言，--all 打印全部应用参考。otto guide skills 列出可编辑技能，notes 是旧别名。otto setup skills 检查更新与失效命令；用户改过的文件会保留，更新放在旁边的 .new 文件里。
