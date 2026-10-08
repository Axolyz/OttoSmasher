"""公开命令目录（ROADMAP L2 / QUESTIONS Q24，ARCHITECTURE §15）。

每条 Core 命令在这里登记：名称、作用类别、参数类型、返回类型、一句说明。参数与返回都是 ``TypedDict``（``types.py``），
同一份定义导出两样东西：

- ``docs/api/commands.json``：机器可读的命令目录（参数与返回的 JSON Schema、错误码表），给阶段 11 的接口文档与将来的 agent 工具定义用；
- ``app/renderer/api/generated.ts``：前端类型，``call()`` 按命令名推断参数与返回。

生成：``.venv/bin/python -m ottosmasher.api.catalog``；测试检查生成物是否最新（``test_api_catalog``）。
"""
