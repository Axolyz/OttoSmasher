"""Core 发出的事件（阶段 A：进命令目录的 ``events`` 一节，让命令行 / agent 知道该等什么）。

名称 → (负载类型, 一句英文说明)。新加事件必须登记在这里；``test_api_catalog`` 扫描源码里的 ``emit("…")`` 检查登记齐全。
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from . import types as T


class PeaksEvent(TypedDict):
    assetIds: list[str]
    error: NotRequired[T.ErrorWire]


class ThumbsReady(TypedDict):
    items: list[dict[str, Any]]


class SearchStartedEvent(TypedDict):
    searchId: str
    kind: Literal["speech", "pitch"]


class SearchCoverageEvent(TypedDict):
    mode: Literal["speech", "pitch", "metrics"]
    adopted: int


class VideoDone(TypedDict):
    jobId: str
    path: str
    # 超出视频流、补了几帧黑帧
    black: int
    fps: float
    content: str


class BpmEvent(TypedDict):
    bpm: float | None


class ConfirmClosed(TypedDict):
    id: str


class ScanFailed(TypedDict):
    path: str
    error: T.ErrorWire


class SourcesScanned(TypedDict):
    new: int
    moved: int
    # 已登记的原素材这次新关联上字幕的个数（只关联不导入）
    subtitlesLinked: int
    missing: int
    failed: list[ScanFailed]
    newIds: list[str]
    # [作品, 新原素材数]
    byWork: list[tuple[str, int]]
    offline: list[str]


class NoPayload(TypedDict):
    pass


EVENTS: dict[str, tuple[Any, str]] = {
    "core.ready": (T.Hello, "Core opened the workspace and accepts requests."),
    "core.fatal": (T.ErrorWire, "Core could not open the workspace and is exiting."),
    "data.changed": (dict[str, list[str]], "User data changed: entity -> ids. Re-read what you show; nothing refreshes by itself."),
    "job.updated": (T.JobSummary, "A job was queued, progressed or finished (status succeeded / failed / cancelled / interrupted)."),
    "search.started": (SearchStartedEvent, "A speech or pitch search started."),
    "search.finished": (T.SearchFinished, "A search ended; when status is done, read hits with results.page(resultId)."),
    "search.coverage": (SearchCoverageEvent, "Background preparation added search index / pitch / metrics for some items."),
    "exports.videoDone": (VideoDone, "A queued video clip export finished; path is the file."),
    "sources.scanned": (SourcesScanned, "A scan of the source folders finished: counts, new source ids, failures (first 50), offline folders."),
    "rhythm.bpm": (BpmEvent, "The global target BPM changed."),
    "peaks.ready": (PeaksEvent, "Waveform peaks became available for these assets."),
    "peaks.failed": (PeaksEvent, "Building waveform peaks failed for these assets."),
    "thumbs.ready": (ThumbsReady, "List thumbnails became available."),
    "models.changed": (NoPayload, "Model files or their status changed."),
    "agent.sessions": (list[T.AgentSession], "Command-line connections attached or detached."),
    "agent.confirm": (T.AgentConfirm, "A command-line connection asks to run a command that cannot be undone; the owner answers in the app."),
    "agent.confirmClosed": (ConfirmClosed, "A pending confirmation was answered, timed out or dropped."),
    "agent.missed": (list[T.AgentMissed], "The list of missed confirmation requests changed (timed out, connection closed, or dismissed)."),
}
