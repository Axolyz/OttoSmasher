"""Core 的错误：只返回“错误码 + 参数”，界面按当前语言生成提示（规格 15 §15.7）。"""

from __future__ import annotations

from typing import Any


class CoreError(Exception):
    """业务错误。``code`` 是稳定的错误码（kebab-case），``args`` 是给文案用的参数。"""

    def __init__(self, code: str, **args: Any) -> None:
        super().__init__(code)
        self.code = code
        self.args_ = args

    def to_wire(self) -> dict[str, Any]:
        return {"code": self.code, "args": self.args_}

    def __repr__(self) -> str:
        return f"CoreError({self.code!r}, {self.args_!r})"
