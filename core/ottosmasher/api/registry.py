"""命令登记表：名称 → (作用类别, 参数类型, 返回类型, 说明, 处理函数)。

- 参数在分发时按类型校验（``msgspec.convert``），不合格返回 ``bad-request``（带出错位置）；未声明的参数键被丢掉，所以参数类型必须写全。
- 返回值只在严格模式下核对（开发模式的 e2e 与测试打开 ``OTTO_STRICT_API=1``）：类型不符或多出未声明的键都算错，
  这样命令目录不会和实际返回慢慢走样。正式运行不核对（不花时间）。
"""

from __future__ import annotations

import types as pytypes
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import msgspec

from ..core.errors import CoreError

# 作用类别：给接口文档与将来的权限分级用（ARCHITECTURE §15.2 第 2 条）。
#   read  只读；write 改用户资料（编辑通道或原子写入）；job 提交任务；ui 界面状态；app 应用生命周期；dev 只在开发模式
Effect = Literal["read", "write", "job", "ui", "app", "dev"]
EFFECTS: tuple[str, ...] = typing.get_args(Effect)
# 层（所有者 2026-10-30）：library 业务命令（资料库里的对象、编辑、任务登记）；primitive 原始能力（只做计算、不改资料库，
# 输入可以是库里的音轨也可以是任意文件——像 git 的 plumbing，业务命令建在同样的引擎上）
Layer = Literal["library", "primitive"]
LAYERS: tuple[str, ...] = typing.get_args(Layer)


@dataclass(frozen=True)
class Command:
    name: str
    effect: str
    params: Any
    result: Any
    summary: str
    handler: Callable[[Any], Any]
    # 危险（撤销不了）：True = 总是；函数 = 按参数判断。外部连接（agent / 脚本）调用时要所有者在应用里确认（阶段 A）
    danger: bool | Callable[[Any], bool] = False
    layer: str = "library"

    def dangerous(self, params: Any) -> bool:
        return bool(self.danger(params)) if callable(self.danger) else bool(self.danger)

    def parse(self, raw: Any) -> Any:
        try:
            return msgspec.convert(raw if raw is not None else {}, self.params)
        except msgspec.ValidationError as exc:
            raise CoreError("bad-request", method=self.name, reason=str(exc)) from None

    def check_result(self, value: Any) -> None:
        """严格模式：返回值必须符合声明的类型，且不含未声明的键。"""
        try:
            msgspec.convert(value, self.result)
        except msgspec.ValidationError as exc:
            raise CoreError("result-mismatch", method=self.name, reason=str(exc)) from None
        extra = extra_keys(value, self.result)
        if extra:
            raise CoreError("result-mismatch", method=self.name, reason="undeclared keys: " + ", ".join(extra[:8]))


class CommandSet:
    def __init__(self) -> None:
        self._by: dict[str, Command] = {}

    def add(self, name: str, effect: str, params: Any, result: Any, summary: str, handler: Callable[[Any], Any], *,
            danger: bool | Callable[[Any], bool] = False, layer: str = "library") -> None:
        if name in self._by:
            raise ValueError(f"duplicate command {name}")
        if effect not in EFFECTS:
            raise ValueError(f"bad effect {effect!r} for {name}")
        if not typing.is_typeddict(params):
            raise TypeError(f"params of {name} must be a TypedDict")
        if layer not in LAYERS:
            raise ValueError(f"bad layer {layer!r} for {name}")
        self._by[name] = Command(name, effect, params, result, summary, handler, danger, layer)

    def get(self, name: Any) -> Command | None:
        return self._by.get(name) if isinstance(name, str) else None

    def __iter__(self):  # noqa: ANN204
        return iter(self._by.values())

    def __len__(self) -> int:
        return len(self._by)

    def __contains__(self, name: object) -> bool:
        return name in self._by


def extra_keys(value: Any, tp: Any, path: str = "$") -> list[str]:
    """``value`` 里没在类型 ``tp`` 中声明的字典键（递归；只看 TypedDict）。"""
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        return extra_keys(value, typing.get_args(tp)[0], path)
    if typing.is_typeddict(tp):
        if not isinstance(value, dict):
            return []
        hints = typing.get_type_hints(tp)
        out = [f"{path}.{k}" for k in value if k not in hints]
        for k, v in value.items():
            if k in hints:
                out += extra_keys(v, hints[k], f"{path}.{k}")
        return out
    if origin in (list, tuple, set, frozenset) and isinstance(value, (list, tuple, set, frozenset)):
        args = typing.get_args(tp)
        if not args:
            return []
        out = []
        for i, v in enumerate(value):
            sub = args[i] if origin is tuple and len(args) > 1 and args[-1] is not Ellipsis and i < len(args) else args[0]
            out += extra_keys(v, sub, f"{path}[{i}]")
        return out
    if origin is dict and isinstance(value, dict):
        args = typing.get_args(tp)
        if len(args) != 2:
            return []
        out = []
        for k, v in value.items():
            out += extra_keys(v, args[1], f"{path}.{k}")
        return out
    if origin in (typing.Union, pytypes.UnionType):
        if value is None:
            return []
        for arg in typing.get_args(tp):
            if arg is type(None):
                continue
            a_origin = typing.get_origin(arg)
            if isinstance(value, dict) and (typing.is_typeddict(arg) or a_origin is dict):
                return extra_keys(value, arg, path)
            if isinstance(value, (list, tuple)) and a_origin in (list, tuple):
                return extra_keys(value, arg, path)
        return []
    return []
