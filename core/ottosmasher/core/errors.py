"""Core 的错误：只返回“错误码 + 参数”，界面按当前语言生成提示（规格 15 §15.7）。

``ERRORS`` 是错误码表（命令目录导出它，ROADMAP L2）：每个码可能带的参数名 + 一句英文说明。
新加错误码必须登记在这里；``test_api_catalog`` 扫描源码检查登记齐全、参数名一致，并检查文案资源里有 ``error.<码>``。
"""

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


# 规则校验的定位与原因参数（domain/rules.py：rule-invalid 与调用方指定的码共用）
_RULE_ARGS = ("reason", "max", "detail", "group", "sample")

ERRORS: dict[str, tuple[tuple[str, ...], str]] = {
    # ---- 协议与分发
    "unknown-method": (("method",), "No such command."),
    "bad-request": (("method", "reason"), "Parameters do not match the command's schema."),
    "internal-error": (("method", "reason"), "Unexpected failure inside Core (a bug)."),
    "result-mismatch": (("method", "reason"), "Strict mode: a command returned data that does not match its declared result type."),
    "dev-only": ((), "Command is only available in development mode."),
    # ---- 工作区与数据库
    "workspace-locked": (("path",), "The workspace is open in another OttoSmasher."),
    "schema-too-new": (("found", "supported"), "The database was written by a newer version."),
    "schema-migration-failed": (("backup", "migration", "reason"), "A schema migration failed; the pre-migration backup is kept."),
    "setting-unknown": (("key",), "No such setting."),
    "setting-invalid": (("max", "min", "options", "reason"), "Setting value rejected."),
    "rule-invalid": (("rule", *_RULE_ARGS), "A regular-expression rule is invalid (syntax, missing group, too long, or too slow)."),
    "selftest-failed": (("reason",), "Development self-test job failed."),
    # ---- 编辑通道
    "edit-empty": ((), "Edit batch has no operations."),
    "edit-unknown-entity": (("entity", "index"), "Edit targets an unknown kind of object."),
    "edit-unknown-field": (("entity", "field", "index"), "Edit touches a field that cannot be edited."),
    "edit-not-found": (("entity", "id", "index"), "Edited object does not exist."),
    "edit-duplicate-object": (("entity", "id", "index"), "The same object appears twice in one batch."),
    "edit-conflict": (("actual", "entity", "expected", "id", "index"), "Object changed since it was read (version mismatch)."),
    "edit-invalid": (("entity", "field", "first", "index", "line", "max", "min", "options", "reason", "role"), "Edit value rejected."),
    "undo-nothing-safe": ((), "Nothing can be undone safely."),
    # ---- 任务
    "job-kind-unknown": (("kind",), "No such job kind."),
    "job-not-found": (("id",), "No such job."),
    "job-not-cancellable": (("id", "status"), "Job already finished."),
    "job-not-retryable": (("id", "status"), "Only failed, cancelled or interrupted jobs can be retried."),
    "job-interrupted": ((), "Job was running when the app exited."),
    "job-spawn-failed": (("reason",), "Could not start the job process."),
    "job-worker-exited": (("exit_code",), "Job process exited without a result."),
    "job-exception": (("message", "type"), "Job process raised an unexpected exception."),
    # ---- 媒体与文件
    "file-missing": (("path",), "File not found."),
    "tool-missing": (("path", "tool"), "External tool (ffmpeg, ffprobe, …) not found."),
    "media-probe-failed": (("detail", "path"), "Could not read media information."),
    "decode-failed": (("detail", "path"), "Could not decode audio."),
    "decode-misaligned": (("pts",), "Decoded audio does not start where expected."),
    "mp3-encode-failed": (("channels", "detail", "expected", "got", "reason"), "MP3 encoding or its gapless check failed."),
    "filename-too-long": (("name",), "Export file name is too long even after shortening."),
    "export-exists": (("path",), "Export target already exists."),
    "export-modified": (("path",), "A previously exported file was modified."),
    "export-key-invalid": (("key",), "Export key is invalid."),
    # ---- 原片、资产、映射
    "source-not-found": (("id",), "No such source."),
    "source-no-audio": (("path",), "Source has no audio stream."),
    "source-path-taken": (("other", "path"), "Another source is registered at this path."),
    "source-changed": (("path", "what"), "Source file was replaced or changed since registration."),
    "source-has-active-jobs": (("id", "jobs"), "Source cannot be deleted while jobs use it."),
    "source-has-independent-samples": (("id", "n"), "Source has independent samples (handled in stage 9)."),
    "stream-not-found": (("ordinal", "source"), "No such audio stream."),
    "asset-not-found": (("id",), "No such sound asset."),
    "asset-file-missing": (("id", "path"), "Sound asset file not found."),
    "asset-not-hangable": (("id",), "Asset is time-stretched and cannot be played against the source."),
    "mapping-invalid": (("reason",), "Time mapping is invalid."),
    "range-invalid": (("duration", "end", "reason", "start"), "Time range is invalid or out of bounds."),
    "time-out-of-range": (("clock", "end", "start", "t"), "Time is outside the mapped range."),
    "default-track-missing": (("role",), "No default track for this role."),
    "default-track-invalid": (("asset", "reason", "role"), "Asset cannot be the default track for this role."),
    # ---- 原片文件夹、作品、导入
    "root-invalid": (("other", "path", "reason"), "Folder cannot be a source folder."),
    "root-offline": (("path",), "Source folder is not reachable."),
    "work-folder-missing": (("name",), "Work folder not found."),
    "work-folder-exists": (("name",), "A work folder with this name already exists."),
    "work-name-invalid": (("name",), "Work name is not a valid folder name."),
    "work-rename-failed": (("detail", "name"), "Renaming the folder on disk failed (rolled back)."),
    "import-empty": ((), "Nothing to import."),
    "import-expired": (("job",), "Import preview expired; scan again."),
    # ---- 采样与标签
    "sample-not-found": (("id",), "No such sample."),
    "sample-invalid": (("field", "max", "reason"), "Sample value rejected."),
    "sample-has-active-jobs": (("jobs",), "Sample cannot be deleted while jobs use it."),
    "promote-invalid": (("reason", "role", "roles"), "Local tags cannot be promoted as requested."),
    # ---- 字幕、OP/ED
    "subtitle-missing": (("path",), "Subtitle file not found."),
    "subtitle-unreadable": (("detail", "path"), "Subtitle file cannot be read."),
    "subtitle-encoding": (("path",), "Subtitle file is not UTF-8."),
    "subtitle-format": (("format",), "Unsupported subtitle format."),
    "subtitle-not-associated": (("id",), "Source has no associated subtitle file."),
    "subtitle-preview-stale": (("id",), "Subtitle preview is out of date; preview again."),
    "subtitle-line-not-importable": (("line", "status"), "Subtitle line cannot be imported."),
    "subtitle-rule-invalid": (("setting", *_RULE_ARGS), "A subtitle rule is invalid."),
    "subtitle-rule-timeout": (("setting",), "A subtitle rule took too long."),
    "subtitle-sample-invalid": (("field", "reason"), "Subtitle sample request rejected."),
    "subtitle-sample-not-pending": (("annotation", "status"), "Subtitle line is not ready to become a sample."),
    "subtitle-sample-stale": (("id",), "Subtitle sample preview is out of date; preview again."),
    "oped-not-found": (("id",), "No such OP/ED range."),
    "oped-invalid": (("duration", "reason"), "OP/ED range rejected."),
    "oped-overlap": (("end", "kind", "start"), "OP/ED range overlaps an existing one."),
    # ---- 模型与推理（14 §14.1、§14.7）
    "model-file-missing": (("model", "path"), "Model file is not where it should be."),
    "model-sha-mismatch": (("expected", "got", "model", "path"), "Model file does not match the pinned SHA-256."),
    "onnx-runtime-missing": (("detail",), "ONNX Runtime cannot be loaded."),
    "onnx-ep-missing": (("active", "model", "provider"), "The requested acceleration provider did not enter the session (no silent CPU fallback)."),
    "onnx-session-failed": (("detail", "model", "provider"), "Creating the ONNX session failed."),
    "native-missing": (("name", "path"), "A native extension has not been built."),
    # ---- 文本前端与对齐（规格 08）
    "frontend-failed": (("detail", "reason"), "Text frontend failed."),
    "language-unsupported": (("language",), "No text frontend is registered for this language."),
    "dictionary-invalid": (("first", "line", "max", "reason"), "A user dictionary line is invalid (line number given)."),
    "dictionary-compile-failed": (("detail",), "Compiling the user dictionary failed; the active dictionary is unchanged."),
    "align-empty": ((), "Nothing to align (no phonemes)."),
    "align-unsupported": (("detail",), "The aligner does not support a phoneme transition in this text."),
    "align-audio-too-short": (("frames",), "Audio window is too short to align."),
    # ---- PyMSS Studio
    "studio-not-found": (("path",), "PyMSS Studio is not installed."),
    "studio-no-runtime": (("detail", "path"), "PyMSS Studio has no active inference environment."),
    "studio-models-unknown": ((), "Studio models have not been listed yet."),
    "studio-model-missing": (("model",), "Model is not available in Studio."),
    "studio-failed": (("command", "exit_code", "log", "message", "reason", "studio_code"), "Studio worker failed."),
    "sep-model-changed": (("model",), "Model files changed during separation."),
    "sep-stems-invalid": (("model", "stems"), "Requested stems are not produced by this model."),
    "sep-output-invalid": (("expected", "got", "path", "reason", "stem", "stems"), "Separation output is incomplete or wrong."),
}


def table() -> list[dict[str, Any]]:
    """命令目录用的错误码表。"""
    return [{"code": c, "args": list(a), "summary": s} for c, (a, s) in sorted(ERRORS.items())]
