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


def _user_dictionary(v: Any) -> dict[str, Any]:
    from ottosmasher.lang.ja import dictionary

    if not isinstance(v, dict) or set(v) != {"text", "compiled"} or not isinstance(v["text"], str):
        raise CoreError("setting-invalid", reason="not-an-option")
    if len(v["text"]) > 1_000_000:
        raise CoreError("setting-invalid", reason="too-long", max=1_000_000)
    name = dictionary.content_name(v["text"])  # 逐行校验（不合格抛 dictionary-invalid，带行号）
    if v["compiled"] != name:
        raise CoreError("setting-invalid", reason="dict-not-compiled")
    return {"text": v["text"], "compiled": name}


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


def _path_text(v: Any) -> str:
    if not isinstance(v, str) or len(v) > 4096:
        raise CoreError("setting-invalid", reason="not-text")
    return v.strip()


def _text100(v: Any) -> str:
    if not isinstance(v, str) or len(v) > 200:
        raise CoreError("setting-invalid", reason="not-text")
    return v.strip()


def _role_aliases(v: Any) -> Any:
    from .assets import validate_role_aliases  # 避免循环导入

    return validate_role_aliases(v)


def _opt_bpm(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (20 <= float(v) <= 400):
        raise CoreError("bpm-invalid", min=20, max=400)
    return float(v)


def _markers(v: Any) -> Any:
    from .oped import validate_markers  # 避免循环导入

    return validate_markers(v)


SPECS: dict[str, SettingSpec] = {
    s.key: s
    for s in [
        # 通用
        SettingSpec("general.ui_language", "auto", _choice("auto", "zh-CN", "en"), "general"),
        # 时间线标签最多显示几行（所有图层同一条避让 + 折行规则，所有者 2026-10-13）
        SettingSpec("general.label_max_lines", 3, _int_range(1, 6), "general"),
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
        # PyMSS Studio（规格 14 §14.6.1；留空 = 自动检测 / 默认 ~/.pymss-studio）
        SettingSpec("studio.app_path", "", _path_text, "studio"),
        SettingSpec("studio.data_dir", "", _path_text, "studio"),
        SettingSpec("studio.vocal_model", "", _text100, "studio"),
        SettingSpec("studio.device", "auto", _choice("auto", "cpu", "cuda", "mps"), "studio"),
        SettingSpec("studio.device_id", 0, _int_range(0, 16), "studio"),
        # 分离声部名 → 角色别名表（规格 05 §5.4、推定 A9；不分大小写）
        SettingSpec("separation.role_aliases", [list(x) for x in rules_defaults()["separation.role_aliases"]], _role_aliases, "studio"),
        # 语音分析：对齐前/后容差（默认各 0.2 秒：窗口要紧贴说话，放宽到 0.5 秒约一半句子偏 0.3 秒以上；所有者 2026-10-30）
        # 文本前端（08 §8.2.4）：用户辞典 = 源文本 + 编译产物名；只能由「保存」任务在编译成功后写入（产物名必须与内容一致）
        SettingSpec("frontend.user_dictionary", {"text": "", "compiled": None}, _user_dictionary, "frontend"),
        SettingSpec("analysis.tolerance_before", 0.2, _float_range(0.0, 5.0), "analysis"),
        SettingSpec("analysis.tolerance_after", 0.2, _float_range(0.0, 5.0), "analysis"),
        # 节奏（09 §9.3–§9.4、03 §3.7）：大数字惩罚度只作用于原节奏路线，改了只重建派生节奏；
        # 停顿灵敏度与语段阈值是**新采样**的默认值（创建时写进采样，之后可逐采样改；改设置不影响已有采样）
        SettingSpec("analysis.penalty", 1.0, _float_range(0.0, 3.0), "analysis"),
        SettingSpec("analysis.pause_sensitivity", 1.0, _float_range(0.5, 2.0), "analysis"),
        SettingSpec("analysis.segment_threshold", 0.28, _float_range(0.16, 2.0), "analysis"),
        # 检索的准备在后台自动做（所有者 2026-10-08）：新采样与默认轨测 F0、语音分析后建语音检索索引
        SettingSpec("analysis.auto_prepare", True, _bool, "analysis"),
        # 改段后自动在后台重跑（所有者 2026-10-09，默认关）：段的文本或边界改了、拆分 / 合并 / 切开之后，在原段已有分析的资产上重新分析
        SettingSpec("analysis.auto_rerun_segments", False, _bool, "analysis"),
        # 全局目标 BPM（03 §3.1：20–400，None = 原速卡拍）：工作参数，不进撤销，由 rhythm.setBpm 写（不在设置页里出现）
        SettingSpec("rhythm.bpm", None, _opt_bpm, "rhythm"),
        # 拉平：各入口的默认处理范围与定音方式（03 §3.7；只是默认值，拉平台上随时可改，改范围不自动改定音，Q6）。
        # 详情 = 首元音起 + 交界左；其他单个入口 = 整段 + 段内自动；批量 = 仅元音 + 段内自动（批量只有自动定音、没有内部拉平，Q10）
        SettingSpec("flatten.detail_range", "first", _choice("whole", "vowels", "first", "inner"), "flatten"),
        SettingSpec("flatten.detail_target", "edge", _choice("auto", "edge", "manual"), "flatten"),
        SettingSpec("flatten.single_range", "whole", _choice("whole", "vowels", "first", "inner"), "flatten"),
        SettingSpec("flatten.single_target", "auto", _choice("auto", "edge", "manual"), "flatten"),
        SettingSpec("flatten.batch_range", "vowels", _choice("whole", "vowels", "first"), "flatten"),
        SettingSpec("flatten.batch_target", "auto", _choice("auto", "edge"), "flatten"),
        # 导出：REAPER 交接的吸附（12 §12.3：首个起音落在编辑光标 / 以条目开头为准）
        SettingSpec("export.reaper_snap", "onset", _choice("onset", "start"), "export"),
        # ⌘C 复制哪种 REAPER 交接（所有者 2026-10-08 选丙）：卡好拍＋起音标记 / 原声＋拉伸标记（可再调）；菜单里两种都有
        SettingSpec("export.reaper_kind", "fitted", _choice("original", "fitted"), "export"),
        # 视频片段的编码（12 §12.5：默认 H.264 MP4 + AAC；可选高质量中间编码 ProRes 422 HQ MOV + PCM）
        SettingSpec("export.video_codec", "h264", _choice("h264", "prores"), "export"),
        # 任务并发（规格 13 §13.1.2、16 R19.3：模型 1、轻量 2；可设 1–4，0 拒绝）
        SettingSpec("jobs.concurrency_model", 1, _int_range(1, 4), "jobs"),
        SettingSpec("jobs.concurrency_light", 2, _int_range(1, 4), "jobs"),
        # 存储：空闲时整理可重建缓存
        SettingSpec("storage.idle_cleanup", True, _bool, "storage"),
        # 命令行 / agent（阶段 A，所有者 2026-10-24）：撤销不了的命令也不弹确认框，直接执行。只有界面能改（HUMAN_ONLY）
        SettingSpec("agent.skip_confirm", False, _bool, "agent"),
    ]
}


# 只有用户（界面）能改的设置：命令行 / agent 改不了，也撤销不了对它们的修改（否则 agent 能自己关掉确认）
HUMAN_ONLY = frozenset({"agent.skip_confirm"})


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
        if key == "export.reaper_kind" and value in ("baked", "unbaked"):  # 2026-11-04 之前存的：两种听上去都是卡好拍的
            value = "fitted"
        out[key] = {"value": value, "default": s.default, "version": version, "group": s.group}
    return out


def values(conn: Any) -> dict[str, Any]:
    return {k: v["value"] for k, v in read_all(conn).items()}
