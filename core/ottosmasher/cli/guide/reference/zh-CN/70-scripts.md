# 写脚本：一次调很多命令

逐条 `otto call` 适合探索；批量处理（几十集、几千条台词）写成 Python 脚本，用一个连接调用：

```sh
otto run my_script.py 参数1 参数2
```

`otto run` 用应用自带的 Python 运行你的脚本（能 `import ottosmasher`，也带 numpy），并把工作区与会话传给它；
整个脚本的修改记在同一个会话下（`--session` 或 `OTTO_AGENT_SESSION`）。

```python
from ottosmasher.cli.client import LinkClient
from ottosmasher.core.errors import CoreError

with LinkClient.from_env() as c:
    for s in c.call("sources.list"):
        tl = c.call("textLayer.list", {"sourceId": s["id"]})
        print(s["episode"], len(tl["segments"]))
    job = c.call("speech.submit", {"entry": "samples", "ids": ["..."]})
```

* `c.call(命令, 参数)` 返回结果；业务错误抛 `CoreError`（`.code`、`.args_`）。
* `c.request(...)` 返回原始响应 `{"ok", "r" | "e"}`，不抛错。
* `c.next_event(timeout)` 取下一个事件（`{"e": 名称, "d": 数据}`）；等任务时看 `job.updated` 里同一个 `id` 的 `status`，
  或者干脆在脚本外用 `otto wait job <id>`。
* 撤销不了的命令在脚本里同样会等用户确认（总览“危险操作确认”）。

## 分页和二进制

通过 `otto run script.py` 跑脚本能沿用应用 Python、工作区和 session。`LinkClient.from_env()` 也会寻找同种运行应用，但显式 OTTO_WORKSPACE 优先。Python 返回 bytes，可直接用 numpy.frombuffer 读取。

```python
from ottosmasher.cli.client import LinkClient
with LinkClient.from_env() as c:
    rows = list(c.iter_results("speech.alignResults", "<jobId>"))
```

原始计算结果默认每页 100 条，iter_results 会逐页读取并保留失败条目。外部时间换回原片用 `Mapping.of(mapping).to_source(t)`，mapping 来自相应音频导出。

## PowerShell 与任务摘要

Otto 输出 UTF-8。宿主若按其他编码读取原生命令，可先设置 `$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)`。保存 JSON 用 `otto call sources.list | Set-Content -Encoding utf8 sources.json`；Windows PowerShell 5.1 的 `>` 默认写 UTF-16LE，PowerShell 7.4 起原生命令的 stdout 重定向会保留原始字节，不应把两者混为一谈。

复杂 JSON 优先写 UTF-8 文件，CLI 支持 BOM：

```powershell
@{ ids = @('sample-id'); } | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 params.json
& 'C:\path with spaces\otto.cmd' call samples.metrics '@params.json'
```

`-` 从 stdin 读 JSON。注意 PowerShell 单元素数组展开；批量多次调用优先用 otto run，避免手拼命令行 JSON。

`jobs.summaries` 支持 offset/limit/session，返回小摘要；`jobs.get` 才取单个完整结果。queuedAhead 是同通道排在前面的待执行数。otto call ... --wait 和 otto wait 默认不刷进度，--progress 开启 stderr 进度；最终返回完整结果。

otto session --session ID 显示摘要任务和本会话新建采样／资产的数量及最近 ID，--details 才取完整任务。这里的编辑历史最多显示 200 条；需要整理创建物时，使用现有删除流程。
