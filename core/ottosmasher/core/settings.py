"""设置项登记表（规格 13 §13.2、03 §3.7）。

设置存在工作区数据库的 ``setting`` 表里；没有存过的项取默认值（版本 0）。
修改一律走统一编辑通道（可撤销），只作用于之后的操作。
阶段 1 先登记任务、推理、语言、存储几项；其余随各阶段补上。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ottosmasher.domain import naming, subtitle_rules
from ottosmasher.domain.rules import defaults as rules_defaults

from .errors import CoreError


@dataclass(frozen=True)
class SettingSpec:
    key: str
    default: Any
    validate: Callable[[Any], Any]
    group: str


def _int_range(lo: int, hi: int | None) -> Callable[[Any], Any]:
    def check(v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise CoreError("setting-invalid", reason="not-integer")
        if v < lo or (hi is not None and v > hi):
            raise CoreError("setting-invalid", reason="out-of-range", min=lo, max=hi)
        return v

    return check


def _float_range(lo: float, hi: float | None) -> Callable[[Any], Any]:
    def check(v: Any) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CoreError("setting-invalid", reason="not-number")
        v = float(v)
        if v < lo or (hi is not None and v > hi):
            raise CoreError("setting-invalid", reason="out-of-range", min=lo, max=hi)
        return v

    return check


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise CoreError("setting-invalid", reason="not-boolean")
    return v


def _choice(*options: str) -> Callable[[Any], Any]:
    def check(v: Any) -> str:
        if v not in options:
            raise CoreError("setting-invalid", reason="not-an-option", options=list(options))
        return v

    return check


def _role_aliases(v: Any) -> Any:
    from .assets import validate_role_aliases  # 避免循环导入

    return validate_role_aliases(v)


def _markers(v: Any) -> Any:
    from .oped import validate_markers  # 避免循环导入

    return validate_markers(v)


SPECS: dict[str, SettingSpec] = {
    s.key: s
    for s in [
        # 通用
        SettingSpec("general.ui_language", "zh-CN", _choice("zh-CN"), "general"),
        # 推理（规格 14 §14.7：默认 CPU；开启加速但没拿到 EP 时报错不回退）
        SettingSpec("inference.accelerate", False, _bool, "inference"),
        SettingSpec("inference.directml_device", 0, _int_range(0, None), "inference"),
        # 原片
        SettingSpec("source.sample_language", "ja", _choice("ja"), "source"),
        # 作品/集数推断规则：有序正则列表，第一条匹配生效（P10；所有者 2026-10-07）
        SettingSpec("source.infer_rules", naming.default_rules(), naming.validate_rules, "source"),
        # 字幕采样前后扩展（所有者 2026-10-05：0.1 / 0.1 秒）
        SettingSpec("subtitle.pad_before", 0.1, _float_range(0.0, 5.0), "subtitle"),
        SettingSpec("subtitle.pad_after", 0.1, _float_range(0.0, 5.0), "subtitle"),
        # 字幕规则（规格 06 §6.2：音效整行、注释括号、说话人提取、可选的拆分与清理；P10 可编辑，只作用于之后导入的标记）
        *[SettingSpec(k, subtitle_rules.default_value(k), subtitle_rules.validate_setting(k), "subtitle") for k in subtitle_rules.KEYS],
        # OP/ED 开始/结束标记（规格 05 §5.6.1：可各填多个；换一种字幕写法时改这里，程序里不加特判）
        SettingSpec("subtitle.oped_start", list(rules_defaults()["subtitle.oped_start"]), _markers, "subtitle"),
        SettingSpec("subtitle.oped_end", list(rules_defaults()["subtitle.oped_end"]), _markers, "subtitle"),
        # 分离声部名 → 角色别名表（规格 05 §5.4、推定 A9；不分大小写）
        SettingSpec("separation.role_aliases", [list(x) for x in rules_defaults()["separation.role_aliases"]], _role_aliases, "studio"),
        # 语音分析：对齐前/后容差
        SettingSpec("analysis.tolerance_before", 0.65, _float_range(0.0, 5.0), "analysis"),
        SettingSpec("analysis.tolerance_after", 0.65, _float_range(0.0, 5.0), "analysis"),
        # 任务并发（规格 13 §13.1.2、16 R19.3：模型 1、轻量 2；可设 1–4，0 拒绝）
        SettingSpec("jobs.concurrency_model", 1, _int_range(1, 4), "jobs"),
        SettingSpec("jobs.concurrency_light", 2, _int_range(1, 4), "jobs"),
        # 存储：空闲时整理可重建缓存
        SettingSpec("storage.idle_cleanup", True, _bool, "storage"),
    ]
}


def spec(key: str) -> SettingSpec:
    s = SPECS.get(key)
    if s is None:
        raise CoreError("setting-unknown", key=key)
    return s


def device_snapshot(values: dict[str, Any]) -> dict[str, Any]:
    """提交任务时冻结的设备设置（规格 13 §13.1.2、16 R19.6）。"""
    return {
        "accelerate": values["inference.accelerate"],
        "directml_device": values["inference.directml_device"],
    }


def read_all(conn: Any) -> dict[str, dict[str, Any]]:
    """所有设置项：当前值、默认值、版本（没存过的版本为 0）。"""
    import msgspec

    stored = {r[0]: (msgspec.json.decode(r[1]), r[2]) for r in conn.execute("SELECT key, value, version FROM setting")}
    out: dict[str, dict[str, Any]] = {}
    for key, s in SPECS.items():
        value, version = stored.get(key, (s.default, 0))
        out[key] = {"value": value, "default": s.default, "version": version, "group": s.group}
    return out


def values(conn: Any) -> dict[str, Any]:
    return {k: v["value"] for k, v in read_all(conn).items()}
