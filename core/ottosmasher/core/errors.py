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
    # ---- 外部连接（命令行 / agent，阶段 A）
    "app-not-running": (("workspace",), "OttoSmasher is not running on this workspace; run otto open first (the command line only talks to a running app)."),
    "agent-link-failed": (("reason",), "Could not connect to the running app (stale endpoint file, wrong key or the app is shutting down)."),
    "agent-command-forbidden": (("method", "effect"), "This command belongs to the app's own interface and cannot be called from the command line."),
    "agent-confirm-declined": (("method",), "The user declined this command in the app (it cannot be undone, so it needs their confirmation). Do not retry unless they ask."),
    "agent-confirm-timeout": (("method", "seconds"), "Nobody confirmed this command in the app in time; it was not run. Do not retry unless the user asks."),
    "setting-human-only": (("key",), "Only the user can change this setting, in the app's settings; the command line cannot change or undo it."),
    "job-not-succeeded": (("status",), "The job ended without succeeding (cancelled or interrupted); see the job summary."),
    "search-not-done": (("status",), "The search ended without a result (cancelled); see the search status."),
    "agent-confirm-unknown": (("id",), "No pending confirmation with this id (already answered, timed out or its connection closed)."),
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
    "edit-conflict": (("actual", "entity", "expected", "id", "index"), "Object changed since it was read (version mismatch); read it again and rebuild the edit."),
    "edit-invalid": (("entity", "field", "first", "index", "line", "max", "min", "options", "reason", "role"), "Edit value rejected (field and reason in args)."),
    "undo-nothing-safe": ((), "Nothing can be undone safely."),
    "edit-history-unknown": (("id",), "No edit with this id in the edit history."),
    "edit-not-undoable": (("id", "reason"), "This edit cannot be undone on its own (reason: is-undo, already-undone, before-barrier, or changed-later = something it changed was edited again afterwards)."),
    # ---- 任务
    "job-kind-unknown": (("kind",), "No such job kind."),
    "job-not-found": (("id",), "No such job."),
    "job-results-unavailable": (("id", "kind"), "This job's kind has no results of that type; use the results command that matches the job."),
    "job-not-cancellable": (("id", "status"), "Job already finished."),
    "job-not-queued": (("id", "status"), "Only queued jobs can be moved to the front."),
    "job-all-items-failed": (("failed",), "Every item of the job failed; per-item reasons are in its results."),
    "job-not-retryable": (("id", "status"), "Only failed, cancelled or interrupted jobs can be retried."),
    "job-interrupted": ((), "Job was running when the app exited."),
    "job-spawn-failed": (("reason",), "Could not start the job process."),
    "job-worker-exited": (("exit_code",), "Job process exited without a result."),
    "job-exception": (("message", "type"), "Job process raised an unexpected exception."),
    # ---- 媒体与文件
    "file-missing": (("path",), "File not found."),
    "audio-stream-not-found": (("path", "stream"), "The file has no audio stream with this number (count from 0)."),
    "primitive-input-invalid": (("reason", "index"), "Give exactly one of assetId or path, and non-empty text / items (or non-empty lines instead of text)."),
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
    "source-has-independent-samples": (("id", "n"), "Source has independent samples; pass release=true to keep them and release the media."),
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
    "visual-invalid": (("kind", "mode", "path", "reason"), "Picture file or binding mode rejected."),
    "visual-changed": (("path",), "The bound picture file has changed since it was bound."),
    "video-probe-failed": (("detail", "path"), "Cannot read the video stream."),
    "video-export-failed": (("detail",), "Video clip export failed."),
    "independ-invalid": (("id", "reason"), "Samples cannot be made independent as requested."),
    "asset-not-deletable": (("id", "reason"), "This track cannot be deleted: the original stream, a track with samples on it, or a track a running job uses."),
    "storage-busy": (("jobs",), "Cleanup is refused while jobs are queued or running."),
    "media-released": (("end", "id", "start"), "The source media was released; only the independent slices can be read."),
    "reimport-invalid": (("path", "reason"), "The file cannot be reimported."),
    "reimport-out-of-bounds": (("duration", "end", "start"), "From the selection start the reimported file runs past the current asset."),
    "video-export-invalid": (("reason",), "Video export request is invalid."),
    "visual-none": (("id",), "This sample has no picture (bind one first)."),
    "spectrum-invalid": (("max", "reason"), "Spectrum request is invalid (scale, or longer than 30 s)."),
    "tag-expr-invalid": (("position", "reason", "where"), "Tag expression cannot be parsed (1-based character position)."),
    # ---- 字幕、OP/ED
    "subtitle-missing": (("path",), "Subtitle file not found."),
    "subtitle-unreadable": (("detail", "path"), "Subtitle file cannot be read."),
    "subtitle-encoding": (("path",), "Subtitle file is not UTF-8; convert it first."),
    "subtitle-format": (("format",), "Unsupported subtitle format."),
    "subtitle-not-associated": (("id",), "Source has no associated subtitle file."),
    "subtitle-preview-stale": (("id",), "Subtitle preview is out of date; preview again."),
    "subtitle-rule-invalid": (("setting", *_RULE_ARGS), "A subtitle rule is invalid."),
    "subtitle-rule-timeout": (("setting",), "A subtitle rule took too long."),
    "oped-not-found": (("id",), "No such OP/ED range."),
    "oped-invalid": (("duration", "reason"), "OP/ED range rejected."),
    "oped-overlap": (("end", "kind", "start"), "OP/ED range overlaps an existing one."),
    # ---- 模型与推理（14 §14.1、§14.7）
    "model-file-missing": (("model", "path"), "Model file is not where it should be."),
    "model-sha-mismatch": (("expected", "got", "model", "path"), "Model file does not match the pinned SHA-256."),
    "model-download-failed": (("model", "url", "path", "reason", "detail"), "Downloading a model weight failed; nothing was placed."),
    "models-nothing-to-download": ((), "Every model weight is already in place (or waiting to be checked)."),
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
    "align-ambiguous": (("expected", "got"), "Aligner output does not match the input phonemes exactly (attribution uncertain)."),
    "speech-blocked": (("reason",), "This line or sample cannot be analyzed (reason given)."),
    "speech-invalid": (("field", "reason"), "Speech analysis request rejected."),
    "speech-nothing-to-do": (("blocked", "fresh"), "Nothing to analyze: everything is up to date or blocked."),
    "speech-f0-failed": (("failed", "total"), "Job warning, not a failure: pitch (F0) chunks were not measured in a speech analysis; alignments are adopted anyway (cause attached)."),
    "speech-edit-invalid": (("expected", "got", "line", "reason"), "Phoneme time edit rejected (only times may change; line given)."),
    "speech-edit-conflict": (("actual", "expected"), "The analysis changed since it was loaded; reload and edit again."),
    # ---- 拉平（规格 11）
    "flatten-invalid": (("field", "max", "reason"), "Flatten request rejected."),
    "flatten-target-invalid": (("reason",), "Manual target must be a note name (A4, C#5) or a frequency with unit (445Hz)."),
    "flatten-f0-insufficient": (("frames",), "Not enough reliable F0 frames to choose a target."),
    "flatten-edge-insufficient": (("frames", "side"), "Not enough reliable F0 near the chosen edge; the other side is never used automatically."),
    "flatten-needs-alignment": (("reason",), "This range needs an alignment covering the selection (same physical sound)."),
    "flatten-inner-invalid": (("ms", "reason"), "Inner region is out of bounds or its plateau is too short."),
    "flatten-asset-changed": ((), "The frozen sound asset changed since the workbench was opened; reopen it."),
    "flatten-output-invalid": (("expected", "got", "reason"), "Vocoder output has the wrong length or non-finite samples."),
    # ---- 节奏与卡拍（规格 09 §9.2–§9.5）
    # ---- 文本层、音效提示、建采样（所有者 2026-10-09）
    "segment-not-found": (("id",), "No such text segment (or it was deleted)."),
    "segment-overlap": (("n", "canCut"), "The new segment overlaps existing segments; choose replace, cut or cancel."),
    "segment-invalid": (("reason",), "The segment operation is invalid (split point outside the segment, merge needs two segments)."),
    "sample-plan-invalid": (("field",), "The sample plan request is invalid."),
    "sample-plan-stale": ((), "Things changed since the plan was made; plan again."),
    "sample-plan-not-pending": (("key", "status"), "That planned sample cannot be created (OP/ED, outside the track or without a name)."),
    "rhythm-no-blocks": ((), "The analysis has no vowel or N, so there are no rhythm blocks."),
    "rhythm-too-many-blocks": (("count", "max"), "A sentence may have at most 128 rhythm blocks."),
    "rhythm-onsets-not-increasing": (("at",), "Block onsets must be strictly increasing."),
    "rhythm-param-invalid": (("field", "min", "max"), "Rhythm parameter is out of range."),
    "rhythm-cut-invalid": (("k", "count"), "A manual segment cut must be before block 1..n-1."),
    "rhythm-cells-invalid": (("block", "count", "cells", "max"), "Manual cells must be 1-64 on an existing block."),
    "rhythm-map-not-monotonic": (("at",), "The time map is not strictly increasing."),
    "rhythm-output-too-long": (("seconds", "max"), "Stretched output would be longer than 10 minutes."),
    "rhythm-original-speed-impossible": (("error",), "Original speed cannot be kept under onset protection."),
    "rhythm-no-analysis": (("id",), "The sample has no successful speech analysis (needed for rhythm); run speech.submit."),
    "rhythm-units-conflict": (("a", "b", "start", "end"), "Two segments read by this sample overlap in time; shrink the judge interval or fix one segment's phoneme times."),
    "rhythm-segments-missing": (("segments", "n"), "Some segments read by this sample have no usable analysis on this track yet; run speech.submit."),
    "rhythm-segment-stale": (("segments", "n"), "Some segments read by this sample were edited after their analysis; analyze them again with speech.submit."),
    "rhythm-mora-unavailable": (("blocks",), "Pure mora is unavailable: some blocks have no mora."),
    "rhythm-not-for-single-sound": (("nature",), "Single sounds (pitched/unpitched) have no stretch."),
    "rhythm-manual-stale": ((), "Manual rhythm edits belong to an older analysis; reapply or clear them first."),
    "rhythm-render-missing": (("key",), "The rendered audition is no longer in the cache."),
    "bpm-invalid": (("min", "max"), "BPM must be 20-400 (empty = original speed)."),
    "stretch-render-failed": (("tool", "detail"), "Time-stretch rendering failed."),
    # ---- 三大搜索（规格 09 §9.6、10 §10.2）
    "search-invalid": (("field",), "Search request is invalid."),
    "hit-not-found": (("result", "rank", "index"), "No such hit in the fixed result."),
    "hit-stale": (("state",), "The hit is no longer valid (sample deleted, rebound, or analysis changed); search again."),
    "hit-no-stretch": ((), "Pitch hits have no stretched version."),
    "search-not-found": (("id",), "No such search in this session."),
    "result-not-found": (("id",), "The fixed result no longer exists."),
    "search-nothing-to-prepare": ((), "Everything in the current scope is already prepared for this search."),
    "speech-query-invalid": (("field", "block", "reason"), "The speech search query is invalid (unknown field, out of range, overlapping or too-close notes)."),
    "pitch-query-invalid": (("block", "reason"), "The pitch query cannot be searched (empty, block too short, longer than 10 s, inverted range or bad note)."),
    "pitch-param-invalid": (("field", "min", "max"), "Pitch search parameter is out of range."),
    "pitch-param-unknown": (("field",), "Unknown pitch search parameter (the reliability threshold cannot be changed)."),
    # ---- REAPER 交接（规格 12 §12.3）
    "reaper-empty": ((), "Nothing to hand off."),
    "reaper-path-invalid": (("field",), "Path or name contains NUL/CR/LF or every quote character."),
    "reaper-markers-not-monotonic": (("at",), "Stretch markers are not strictly increasing."),
    "reaper-too-large": (("bytes", "max"), "REAPER clipboard content is larger than about 2 MB."),
    "reaper-file-conflict": (("path",), "A different file with the same name already exists in the REAPER folder."),
    "reaper-clipboard-failed": (("reason",), "Writing the REAPER clipboard failed or did not read back identically."),
    # ---- PyMSS Studio
    "studio-not-found": (("path",), "PyMSS Studio is not installed."),
    "studio-no-runtime": (("detail", "path"), "PyMSS Studio has no active inference environment."),
    "studio-models-unknown": ((), "Studio models have not been listed yet; call studio.status again shortly."),
    "studio-model-missing": (("model",), "Model is not available in Studio. Ask the user to download it there; the app neither downloads separation models nor substitutes another."),
    "studio-failed": (("command", "exit_code", "log", "message", "reason", "studio_code"), "Studio worker failed."),
    "sep-model-changed": (("model",), "Model files changed during separation."),
    "sep-stems-invalid": (("model", "stems"), "Requested stems are not produced by this model."),
    "sep-output-invalid": (("expected", "got", "path", "reason", "stem", "stems"), "Separation output is incomplete or wrong."),
}


def table() -> list[dict[str, Any]]:
    """命令目录用的错误码表。"""
    return [{"code": c, "args": list(a), "summary": s} for c, (a, s) in sorted(ERRORS.items())]
