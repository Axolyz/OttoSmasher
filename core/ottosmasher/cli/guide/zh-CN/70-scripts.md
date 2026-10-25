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
* 撤销不了的命令在脚本里同样会等所有者确认（总览第 6 条）。
