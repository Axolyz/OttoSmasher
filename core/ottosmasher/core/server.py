"""Core 进程（ARCHITECTURE §2）：唯一写库者；命令 = 公开业务接口。

主线程串行处理请求与内部回调（数据库只在这里访问）；读 stdin 的线程把帧放进队列；
任务监视线程把回调投递进同一个队列。stdin 结束（主进程退出或崩溃）→ 结束所有任务进程树 → 退出，
未完成的任务在下次启动时显示为“已中断”。
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from .. import __version__
from ..api import types as T
from ..api.registry import CommandSet
from ..domain import naming, subtitle_rules
from ..models import registry
from ..store.db import connect, current_version, migrate, transaction
from ..store.workspace import Workspace, WorkspaceLock
from . import settings as settings_mod
from .clock import now_iso
from .edits import ChangeSet, EditService, dumps, loads
from .errors import CoreError
from .rpc import FrameWriter, read_frame
from .scheduler import Scheduler
from . import actor as actor_mod
from . import annotations as annotations_mod
from . import assets as assets_mod
from . import playback as playback_mod
from .exports import ExportService, export_samples
from .samples import SampleService
from .oped import OpedService
from .subtitle_import import SubtitleImporter
from .separation import SeparationService
from .subtitle_samples import SubtitleSamples
from .sources import SourceService
from .imports import ImportService
from .roots import RootService
from .thumbnails import ThumbnailService
from .waveforms import WaveformService

log = logging.getLogger(__name__)

def record_probes(conn: sqlite3.Connection, probes: list[dict[str, Any]]) -> None:
    ts = now_iso()
    with transaction(conn):
        for pr in probes:
            conn.execute(
                "INSERT INTO model_probe(model, device_setting, file_sha, status, ep_node_counts, error, tested_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(model, device_setting) DO UPDATE SET file_sha=excluded.file_sha, status=excluded.status,"
                " ep_node_counts=excluded.ep_node_counts, error=excluded.error, tested_at=excluded.tested_at",
                (pr["model"], dumps(pr["device"]), pr.get("file_sha"), pr["status"], dumps(pr["nodes"]) if pr.get("nodes") is not None else None,
                 pr.get("error"), ts),
            )


class Core:
    def __init__(self, workspace: Path, *, support_dir: Path | None = None, dev: bool = False) -> None:
        self.ws = Workspace(workspace)
        self.support_dir = support_dir or registry.default_support_dir()
        self.dev = dev
        # 严格模式：核对每个命令的返回值与命令目录一致（开发模式的 e2e 与测试打开，ROADMAP L2）
        self.strict_api = os.environ.get("OTTO_STRICT_API") == "1"
        self.writer: FrameWriter | None = None
        self._q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._lock = WorkspaceLock(self.ws)
        self.conn: sqlite3.Connection
        self.edits: EditService
        self.jobs: Scheduler
        self.sources: SourceService
        self.exports: ExportService
        self.waveforms: WaveformService
        self.thumbs: ThumbnailService
        self.samples: SampleService
        self.interrupted_on_start = 0
        self._stop = False
        self.api = CommandSet()
        self._register(self.api)

    def _register(self, api: CommandSet) -> None:
        """全部公开命令（ROADMAP L2）：名称、作用类别、参数与返回类型、一句说明（英文，进命令目录）、处理函数。"""
        r = api.add
        # ---- 应用、设置、界面状态
        r("core.hello", "read", T.NoParams, T.Hello, "Core version, workspace and schema version.", self._hello)
        r("settings.list", "read", T.NoParams, dict[str, T.SettingEntry], "All settings with value, default and version (edit via edits.apply, entity 'setting').",
          lambda p: settings_mod.read_all(self.conn))
        r("sources.inferTest", "read", T.InferTestParams, T.InferTest, "Try the work/episode inference rules (draft or current) on a file name.", self._infer_test)
        r("subtitles.ruleTest", "read", T.RuleTestParams, T.Classified, "Try the subtitle rules (draft or current) on one subtitle text.", self._subtitle_rule_test)
        r("models.status", "read", T.NoParams, T.ModelsStatus, "Model files, ONNX Runtime and inference probe status.", self._models_status)
        r("models.verify", "job", T.NoParams, T.JobSummary, "Submit a job that hashes the model files.", self._models_verify)
        r("dictionary.check", "read", T.DictionaryTextParams, T.DictionaryCheck, "Validate user dictionary text line by line (no compiling).", self._dictionary_check)
        r("dictionary.save", "job", T.DictionarySaveParams, T.JobSummary,
          "Compile the user dictionary in a job; on success it becomes active atomically (undoable, rejected if changed meanwhile).", self._dictionary_save)
        r("dictionary.preview", "job", T.DictionaryPreviewParams, T.JobSummary, "Phonemes and readings of one sentence with a draft (or the current) dictionary.",
          self._dictionary_preview)
        r("models.probe", "job", T.NoParams, T.JobSummary, "Submit a job that runs one minimal inference per model under the current device setting.",
          self._models_probe)
        r("ui.get", "ui", T.UiGetParams, dict[str, Any], "Restore UI state of one page.", self._ui_get)
        r("ui.set", "ui", T.UiSetParams, None, "Save one UI state value (not user data, no undo).", self._ui_set)
        r("app.prepareQuit", "app", T.NoParams, T.PrepareQuit, "Number of active jobs that quitting would cancel.", lambda p: {"active": self.jobs.active_count()})
        r("app.quit", "app", T.QuitParams, T.Quit, "Cancel jobs and stop Core.", self._quit)
        # ---- 编辑通道、任务
        r("edits.preview", "read", T.EditBatchParams, T.EditPreview, "Validate an edit batch and show its changes without writing.", lambda p: self.edits.preview(p["batch"]))
        r("edits.apply", "write", T.EditBatchParams, T.EditApplied, "Apply an edit batch atomically (undoable).", lambda p: self.edits.apply(p["batch"]))
        r("edits.undo", "write", T.NoParams, T.EditUndone, "Undo the latest edit that can be undone safely.", lambda p: self.edits.undo())
        r("edits.peekUndo", "read", T.NoParams, T.UndoPeek | None, "What undo would revert next.", lambda p: self.edits.peek_undo())
        r("jobs.list", "read", T.JobsListParams, list[T.JobSummary], "Recent jobs, newest first.", lambda p: self.jobs.list(int(p.get("limit", 200))))
        r("jobs.submit", "job", T.JobSubmitParams, T.JobSummary, "Submit a job of a registered kind (low-level; prefer the specific commands).",
          lambda p: self.jobs.submit(p["kind"], p.get("params", {}), p.get("affects")))
        r("jobs.cancel", "job", T.IdParams, T.JobSummary, "Cancel a queued or running job (kills its whole process tree).", lambda p: self.jobs.cancel(p["id"]))
        r("jobs.retry", "job", T.IdParams, T.JobSummary, "Retry a failed, cancelled or interrupted job as a new job.", lambda p: self.jobs.retry(p["id"]))
        # ---- 原片
        r("sources.add", "write", T.SourcesAddParams, list[T.AddResult], "Register source files (each succeeds or fails on its own).",
          lambda p: self.sources.add(p["paths"], import_root=p.get("importRoot")))
        r("sources.list", "read", T.NoParams, list[T.SourceRow], "All sources with per-source counts.", self._sources_list)
        r("sources.get", "read", T.IdParams, T.SourceDetail, "One source with its streams.", lambda p: self.sources.get(p["id"]))
        r("sources.prep", "read", T.IdParams, T.Prep, "Preparation checklist state of one source.", lambda p: annotations_mod.prep(self.conn, p["id"]))
        r("sources.relocate", "write", T.RelocateParams, T.SourceRelocated, "Point a source at a moved file (reports changed streams, does not refuse).",
          lambda p: self.sources.relocate(p["id"], p["path"]))
        r("sources.deletePreview", "read", T.IdParams, T.DeletePreview, "What deleting a source would remove.", lambda p: self.sources.delete_preview(p["id"]))
        r("sources.delete", "write", T.IdParams, T.DeletePreview, "Delete a source with its assets, samples and annotations (not undoable).",
          lambda p: self.sources.delete(p["id"]))
        r("sources.wholeSamples", "write", T.WholeSamplesParams, T.SampleIds, "Create one full-length sample per source on its default track.",
          lambda p: self.imports.whole_samples(list(p["ids"]), p.get("nature")))
        r("sources.rescan", "job", T.NoParams, T.JobRef | None, "Scan all source folders for new, moved or missing files.", lambda p: self.roots.rescan())
        r("roots.list", "read", T.NoParams, list[T.SourceRoot], "Source folders.", lambda p: self.roots.list())
        r("roots.add", "write", T.PathParams, T.RootAdded, "Add a source folder (adopts sources already inside, then scans).", lambda p: self.roots.add(str(p["path"])))
        r("roots.remove", "write", T.IdParams, T.RootRemoved, "Stop treating a folder as a source folder (sources stay).", lambda p: self.roots.remove(str(p["id"])))
        r("roots.relocate", "write", T.RelocateParams, T.RootRelocated, "A whole source folder moved: re-point its sources by relative path, then scan.",
          lambda p: self.roots.relocate(str(p["id"]), str(p["path"])))
        r("works.list", "read", T.NoParams, list[T.WorkFolder], "Work folders (first-level subfolders of source folders).", lambda p: self.roots.works())
        r("works.rename", "write", T.WorkRenameParams, T.WorkRenamed, "Rename a work: renames the folder on disk (not undoable).",
          lambda p: self.roots.rename(str(p["id"]), str(p["name"])))
        r("works.settingsBatch", "read", T.WorkSettingsParams, T.EditBatch, "Edit batch for a work's settings (apply with edits.apply).",
          lambda p: self.roots.settings_batch(str(p["id"]), str(p.get("sourceType", "")), bool(p.get("bindPictures", True))))
        r("imports.scan", "job", T.PathsParams, T.JobSummary, "Scan files/folders to import (background job).", lambda p: self.imports.scan(list(p["paths"])))
        r("imports.preview", "read", T.JobIdParams, T.ImportPreview, "Preview of a finished import scan.", lambda p: self.imports.preview(p["jobId"]))
        r("imports.commit", "write", T.ImportCommitParams, T.ImportResult, "Register the scanned files (optionally with full-length samples).",
          lambda p: self.imports.commit(
              p["jobId"], work=None if p.get("workMode", "unified") == "infer" else str(p.get("work") or ""), source_type=str(p.get("sourceType") or ""),
              whole_sample=bool(p.get("wholeSample", False)), nature=str(p.get("nature", "unclassified")),
              bind_pictures=bool(p.get("bindPictures", True)),
          ))
        # ---- 资产、播放、波形、缩略图
        r("assets.listForSource", "read", T.SourceIdParams, list[T.AssetInfo], "All sound assets of a source, full tracks first.",
          lambda p: assets_mod.list_for_source(self.conn, p["sourceId"]))
        r("assets.get", "read", T.IdParams, T.AssetRecord, "One sound asset.", lambda p: assets_mod.get(self.conn, p["id"]))
        r("assets.tracks", "read", T.SourceIdParams, T.Tracks, "Tracks that can be default tracks, with roles and current defaults.",
          lambda p: assets_mod.tracks(self.conn, p["sourceId"]))
        r("playback.resolveSource", "read", T.ResolveSourceParams, T.SourceHandle, "Playback handle for the source player (file, audio track, external stem).",
          lambda p: playback_mod.resolve_source(self.conn, p["sourceId"], p.get("ordinal"), asset_id=p.get("assetId"), workspace_root=self.ws.root))
        r("playback.resolveAsset", "read", T.AssetRangeParams, T.AssetHandle, "Playback handle for auditioning an asset range (file seconds).",
          lambda p: playback_mod.resolve_asset(self.conn, self.ws.root, p["assetId"], float(p["start"]), float(p["end"])))
        r("peaks.get", "read", T.PeaksParams, T.Peaks, "Waveform peaks for an asset range (pending while the cache is built).",
          lambda p: self.waveforms.get(p["assetId"], float(p["start"]), float(p["end"]), int(p.get("points", 2000))))
        r("thumbs.get", "read", T.ThumbsParams, list[T.ThumbResult], "List thumbnails (pending while generated).", lambda p: self.thumbs.get(list(p["items"])))
        r("dev.registerStem", "dev", T.RegisterStemParams, T.StemRegistered, "Dev hook: register an existing stem file as a full-track asset (S1.2).",
          self._dev_register_stem)
        # ---- 采样、导出、标签
        r("samples.suggest", "read", T.SuggestParams, T.SampleSuggestion, "Suggested name and nature for a new sample on an asset range.",
          lambda p: self.samples.suggest(p["assetId"], float(p["start"]), float(p["end"]), local_marker=p.get("localMarker", "")))
        r("samples.create", "write", T.SampleCreateParams, T.SampleRow, "Create a sample on an asset range (always a new sample).",
          lambda p: self.samples.create(
              p["assetId"], float(p["start"]), float(p["end"]), name=p["name"], nature=p.get("nature"),
              created_via=p.get("createdVia", "manual"), parent_sample_id=p.get("parentSampleId"),
          ))
        r("samples.list", "read", T.SamplesListParams, T.SamplePage, "One page of samples matching the filter, with the total.",
          lambda p: self.samples.list(
              offset=int(p.get("offset", 0)), limit=int(p.get("limit", 100)), natures=p.get("natures"),
              starred=bool(p.get("starred", False)), text=p.get("text", ""), source_id=p.get("sourceId"), sort=p.get("sort", "created"),
          ))
        r("samples.ids", "read", T.SampleFilter, list[str], "IDs of all samples matching the filter (select all across pages).",
          lambda p: self.samples.ids(natures=p.get("natures"), starred=bool(p.get("starred", False)), text=p.get("text", ""), source_id=p.get("sourceId")))
        r("samples.get", "read", T.IdParams, T.SampleRow, "One sample with its effective tags.", lambda p: self.samples.get(p["id"]))
        r("samples.delete", "write", T.IdsParams, T.Deleted, "Delete samples (assets, measurements and exports stay).", lambda p: self.samples.delete(list(p["ids"])))
        r("exports.samples", "write", T.ExportSamplesParams, list[str], "Export samples as WAV files for drag-out; returns file paths.",
          lambda p: export_samples(self.exports, list(p["ids"]), dict(p.get("words", {}))))
        r("exports.wav", "write", T.ExportWavParams, T.ExportedWav, "Export an asset range as a WAV file (reuses an identical export).",
          lambda p: self.exports.export_wav(
              p["assetId"], float(p["start"]), float(p["end"]), content=p["content"], track=p["track"],
              local_prefix=p.get("localPrefix"), processing=p.get("processing", ""), directory=p.get("directory"),
          ))
        r("tags.promoteBatch", "read", T.PromoteParams, T.PromoteInfo, "Edit batch that promotes local tags to a segment tag (apply with edits.apply).",
          lambda p: annotations_mod.promote_batch(self.conn, p["sampleId"], list(p["tags"]), role=p.get("role"), start=p.get("start"), end=p.get("end")))
        # ---- 字幕标记、标注、OP/ED
        r("subtitles.preview", "read", T.SubtitlePreviewParams, T.SubtitlePreview, "Preview importing subtitle markers of one source.",
          lambda p: self.subtitles.preview(p["sourceId"], p.get("path")))
        r("subtitles.import", "write", T.SubtitleImportParams, T.SubtitleImportResult, "Import subtitle markers from a preview (insert only, atomic, undoable).",
          lambda p: self.subtitles.import_(p["sourceId"], p["token"], p.get("lines"), p.get("path")))
        r("subtitles.previewMany", "read", T.SourceIdsParams, list[T.SubtitleBatchRow], "Batch preview of subtitle import (sources without subtitles are skipped).",
          lambda p: self.subtitles.preview_many(list(p["sourceIds"])))
        r("subtitles.importMany", "write", T.SubtitleImportManyParams, list[T.SubtitleImportManyRow], "Batch subtitle import, each source atomic on its own.",
          lambda p: self.subtitles.import_many(list(p["items"])))
        r("annotations.list", "read", T.SourceIdParams, T.AnnotationList, "Subtitle/segment annotations, OP/ED and derived samples of a source.",
          lambda p: annotations_mod.list_for_source(self.conn, p["sourceId"]))
        r("subtitleSamples.preview", "read", T.SubtitleSamplesPreviewParams, T.SubtitleSamplePreview, "Preview creating samples from subtitle lines or sound effects.",
          lambda p: self.subtitle_samples.preview(p["sourceId"], p["kind"], p.get("start"), p.get("end")))
        r("subtitleSamples.create", "write", T.SubtitleSamplesCreateParams, T.SubtitleSamplesCreated, "Create samples from chosen subtitle lines (atomic).",
          lambda p: self.subtitle_samples.create(p["sourceId"], p["kind"], p["token"], list(p["annotationIds"]), p.get("start"), p.get("end")))
        r("oped.list", "read", T.SourceIdParams, list[T.Oped], "OP/ED ranges of a source.", lambda p: self.oped.list(p["sourceId"]))
        r("oped.identify", "write", T.SourceIdParams, T.IdentifyResult, "Identify OP/ED from subtitle rules; applies non-overlapping pairs when there are no errors.",
          lambda p: self.oped.identify(p["sourceId"]))
        r("oped.identifyMany", "write", T.SourceIdsParams, list[T.IdentifyManyRow], "Batch OP/ED identification.", lambda p: self.oped.identify_many(list(p["sourceIds"])))
        r("oped.add", "write", T.OpedAddParams, T.OpedAdded, "Mark or confirm an OP/ED range (undoable).",
          lambda p: self.oped.add(p["sourceId"], p["kind"], float(p["start"]), float(p["end"]), p.get("via", "mark"), p.get("refs")))
        r("oped.delete", "write", T.IdParams, T.EditRef, "Delete an OP/ED range (undoable).", lambda p: self.oped.delete(p["id"]))
        # ---- 分离（PyMSS Studio）
        r("studio.status", "read", T.NoParams, T.StudioStatus, "PyMSS Studio installation and model list (submits a listing job when unknown).",
          lambda p: self.separation.status())
        r("separation.submit", "job", T.SeparationSubmitParams, T.SeparationSubmitted, "Separate an asset (range) with a Studio model; reuses identical results.",
          lambda p: self.separation.submit(p["assetId"], p.get("start"), p.get("end"), p["model"], p.get("stems")))
        r("separation.results", "read", T.JobIdParams, list[T.AssetRecord], "Assets registered by a separation job.", lambda p: self.separation.results(p["jobId"]))

    # ---------- 打开与关闭

    def open(self) -> None:
        self.ws.ensure()
        self._lock.acquire()
        self.conn = connect(self.ws.db_path)
        report = migrate(self.conn, self.ws.backups)
        actor_mod.install(self.conn)
        if report.backup:
            log.info("schema migrated %s -> %s, backup %s", report.from_version, report.to_version, report.backup)
        self.edits = EditService(self.conn, on_change=self._on_change)
        self.sources = SourceService(self.conn, on_change=self._on_change, workspace_root=self.ws.root)
        self.exports = ExportService(self.conn, self.ws)
        self.samples = SampleService(self.conn, on_change=self._on_change)
        self.subtitles = SubtitleImporter(self.conn, self.edits, on_change=self._on_change)
        self.oped = OpedService(self.conn, self.edits, on_change=self._on_change)
        self.subtitle_samples = SubtitleSamples(self.conn, on_change=self._on_change)
        self.waveforms = WaveformService(self.conn, self.ws, post=self.post, emit=self.emit)
        self.thumbs = ThumbnailService(self.conn, self.ws, post=self.post, emit=self.emit)
        self.jobs = Scheduler(
            self.conn,
            self.ws.jobs,
            get_setting=lambda k: settings_mod.values(self.conn)[k],
            device_snapshot=lambda: settings_mod.device_snapshot(settings_mod.values(self.conn)),
            post=self.post,
            emit=self.emit,
            dev=self.dev,
        )
        self.jobs.adopters["models.verify"] = self._adopt_hashes
        self.jobs.adopters["models.probe"] = self._adopt_probes
        self.jobs.adopters["dictionary.compile"] = self._adopt_dictionary
        self.jobs.adopters["dictionary.preview"] = self._adopt_probes
        self.separation = SeparationService(self.conn, self.ws, self.jobs, on_change=self._on_change)
        self.imports = ImportService(self.conn, self.ws, self.jobs, self.sources, on_change=self._on_change)
        self.roots = RootService(self.conn, self.ws, self.jobs, self.sources, on_change=self._on_change, emit=self.emit)
        self.interrupted_on_start = self.jobs.recover()
        self.roots.rescan()  # 启动时扫一次原片文件夹（阶段 3.13；不实时监视）

    def close(self) -> None:
        try:
            self.waveforms.shutdown()
            self.thumbs.shutdown()
            self.jobs.kill_all()
        finally:
            self.conn.close()
            self._lock.release()

    # ---------- 事件与回调

    def emit(self, name: str, data: Any) -> None:
        if self.writer is not None:
            self.writer.event(name, data)

    def post(self, fn: Callable[[], None]) -> None:
        self._q.put(("call", fn))

    def _on_change(self, cs: ChangeSet) -> None:
        self.emit("data.changed", cs.to_wire())

    # ---------- 主循环

    def serve(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        self.writer = FrameWriter(stdout)
        threading.Thread(target=self._reader, args=(stdin,), name="stdin-reader", daemon=True).start()
        self.emit("core.ready", self._hello({}))
        while not self._stop:
            kind, item = self._q.get()
            if kind == "eof":
                log.info("stdin closed; shutting down")
                break
            if kind == "call":
                try:
                    item()
                except Exception:  # noqa: BLE001
                    log.exception("internal callback failed")
                continue
            self.writer.send(self.dispatch(item))

    def _reader(self, stdin: BinaryIO) -> None:
        try:
            while True:
                msg = read_frame(stdin)
                if msg is None:
                    break
                self._q.put(("req", msg))
        except Exception:  # noqa: BLE001
            log.exception("stdin reader failed")
        self._q.put(("eof", None))

    def dispatch(self, msg: dict[str, Any]) -> dict[str, Any]:
        rid = msg.get("id")
        method = msg.get("m")
        cmd = self.api.get(method)
        try:
            if cmd is None:
                raise CoreError("unknown-method", method=method)
            params = cmd.parse(msg.get("p"))
            kind, session = actor_mod.parse(msg.get("actor"))
            with actor_mod.acting(self.conn, kind, session):
                result = cmd.handler(params)
            if self.strict_api:
                cmd.check_result(result)
            return {"t": "res", "id": rid, "ok": True, "r": result}
        except CoreError as exc:
            if exc.code == "result-mismatch":
                log.error("%s", exc)
            return {"t": "res", "id": rid, "ok": False, "e": exc.to_wire()}
        except (KeyError, TypeError, ValueError) as exc:
            log.exception("bad request %s", method)
            return {"t": "res", "id": rid, "ok": False, "e": {"code": "bad-request", "args": {"method": method, "reason": repr(exc)}}}
        except Exception as exc:  # noqa: BLE001
            log.exception("command %s failed", method)
            return {"t": "res", "id": rid, "ok": False, "e": {"code": "internal-error", "args": {"method": method, "reason": repr(exc)}}}

    # ---------- 命令

    def _hello(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": __version__,
            "pid": os.getpid(),
            "workspace": str(self.ws.root),
            "schema_version": current_version(self.conn),
            "interrupted_on_start": self.interrupted_on_start,
            "dev": self.dev,
        }

    def _cached_hashes(self) -> dict[str, tuple[int, int, str]]:
        return {r[0]: (r[1], r[2], r[3]) for r in self.conn.execute("SELECT path, size, mtime_ns, sha256 FROM file_hash_cache")}

    def _models_status(self, p: dict[str, Any]) -> dict[str, Any]:
        """文件、运行库、实测三者分开（R19.7）；实测只列当前设备设置下的记录。"""
        device = settings_mod.device_snapshot(settings_mod.values(self.conn))
        probes = [
            {"model": r["model"], "device": loads(r["device_setting"]), "status": r["status"], "nodes": loads(r["ep_node_counts"]) if r["ep_node_counts"] else None,
             "error": r["error"], "tested_at": r["tested_at"]}
            for r in self.conn.execute("SELECT * FROM model_probe WHERE device_setting=? ORDER BY model", (dumps(device),))
        ]
        return {
            "models_dir": str(self.ws.models),
            "support_dir": str(self.support_dir),
            "files": registry.file_status(self.ws.models, self.support_dir, self._cached_hashes()),
            "runtime": registry.runtime_status(),
            "device": device,
            "probes": probes,
        }

    def _models_verify(self, p: dict[str, Any]) -> dict[str, Any]:
        paths = [str(x) for x in registry.all_files(self.ws.models, self.support_dir) if x.exists()]
        return self.jobs.submit("models.verify", {"paths": paths})

    # ---------- 用户辞典（08 §8.2.4）

    def _dictionary_check(self, p: dict[str, Any]) -> dict[str, Any]:
        from ..lang.ja import dictionary

        entries, errors = dictionary.parse(str(p["text"]))
        return {"entries": len(entries), "errors": errors}

    def _dictionary_save(self, p: dict[str, Any]) -> dict[str, Any]:
        from ..lang.ja import dictionary

        dictionary.check(str(p["text"]))
        return self.jobs.submit("dictionary.compile", {"text": str(p["text"]), "base_version": int(p["version"])})

    def _dictionary_preview(self, p: dict[str, Any]) -> dict[str, Any]:
        from ..lang.ja import dictionary

        text = p.get("text")
        if text is not None:
            dictionary.check(str(text))
        cur = settings_mod.values(self.conn)["frontend.user_dictionary"]["compiled"]
        return self.jobs.submit("dictionary.preview", {
            "sentence": str(p["sentence"]), "text": text, "current": str(self.ws.dictionary / cur) if cur else None,
            "models_dir": str(self.ws.models), "support_dir": str(self.support_dir),
        })

    def _adopt_dictionary(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """编译成功：产物按内容名放进 Data/Dictionary（已有同名就是同一份内容），再经编辑通道启用；期间辞典被改过 → edit-conflict，任务失败。"""
        params = loads(job["params"])
        name = result.get("name")
        if name:
            dst = self.ws.dictionary / name
            if not dst.exists():
                self.ws.dictionary.mkdir(parents=True, exist_ok=True)
                tmp = self.ws.staging / f"{name}.{job['id'][:8]}.tmp"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(result["path"], tmp)
                os.replace(tmp, dst)
        self.edits.apply(
            {
                "label": {"code": "dictionary-save", "args": {"n": int(result.get("entries", 0))}},
                "ops": [{"entity": "setting", "id": "frontend.user_dictionary", "version": params["base_version"], "fields": {"value": {"text": params["text"], "compiled": name}}}],
            }
        )

    def _models_probe(self, p: dict[str, Any]) -> dict[str, Any]:
        return self.jobs.submit("models.probe", {"models_dir": str(self.ws.models), "support_dir": str(self.support_dir)})

    def _adopt_probes(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """实测记录按（模型、设备设置）保存（14 §14.7）；任何带模型推理的任务都可以交回 probes。"""
        record_probes(self.conn, result.get("probes") or [])
        self.emit("models.changed", {})

    def _adopt_hashes(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        ts = now_iso()
        with transaction(self.conn):
            for path, h in result.get("hashes", {}).items():
                self.conn.execute(
                    "INSERT INTO file_hash_cache(path, size, mtime_ns, sha256, computed_at) VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns,"
                    " sha256=excluded.sha256, computed_at=excluded.computed_at",
                    (path, h["size"], h["mtime_ns"], h["sha256"], ts),
                )
        self.emit("models.changed", {})

    def _infer_test(self, p: dict[str, Any]) -> dict[str, Any]:
        """设置里的试算框：用草稿规则（未保存，先做保存时的同样校验）或当前设置推断一个文件名。"""
        rules = p.get("rules")
        if rules is None:
            rules = settings_mod.values(self.conn)["source.infer_rules"]
        else:
            rules = naming.validate_rules(rules)
        r = naming.infer_work_episode(str(p["filename"]), rules)
        return {"work": r.work, "episode": r.episode, "rule": r.rule, "timedOut": list(r.timed_out)}

    def _sources_list(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        """原片列表 + 每个原片的统计（05 §5.8：句数、OP/ED、派生采样数）。"""
        c = annotations_mod.counts(self.conn)
        return [r | {"counts": c.get(r["id"])} for r in self.sources.list()]

    def _dev_register_stem(self, p: dict[str, Any]) -> dict[str, Any]:
        """开发期测试钩子（S1.2；只在开发模式）：把现成的分离声部文件登记为原片的整轨声部（原地引用，不复制）。
        声部名与模型名取自文件名 ``<模型>_<声部>.<扩展名>``；角色按别名表预填；时长必须与原片一致（容差 20 ms）。"""
        if not self.dev:
            raise CoreError("dev-only")
        from ..core import assets as a_mod
        from ..media import probe as pmod

        sid, path = p["sourceId"], str(p["path"])
        src = self.conn.execute("SELECT duration FROM source WHERE id=?", (sid,)).fetchone()
        if src is None:
            raise CoreError("source-not-found", id=sid)
        pr = pmod.probe(path)
        if not pr.audio or pr.audio[0].duration is None:
            raise CoreError("source-no-audio", path=path)
        dur = float(pr.audio[0].duration)
        if abs(dur - float(src[0])) > 0.02:
            raise CoreError("default-track-invalid", reason="not-full-track", asset=path)
        stem_file = Path(path).stem
        model, _, stem = stem_file.rpartition("_")
        from .clock import new_id as nid

        mid, aid, ts = nid(), nid(), now_iso()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, created_at) VALUES (?, ?, 'external', ?, ?, ?, ?)",
                (mid, path, dumps(pmod.snapshot(path, pr)), pr.format_name, pr.audio[0].sample_rate, ts),
            )
            self.conn.execute(
                "INSERT INTO sound_asset(id, source_id, origin, media_file_id, duration, mapping, stem_name, production, created_at)"
                " VALUES (?, ?, 'separation', ?, ?, ?, ?, ?, ?)",
                (aid, sid, mid, float(src[0]), dumps([[0.0, 0.0], [float(src[0]), float(src[0])]]), stem or stem_file, dumps({"op": "dev-register", "model": model or None}), ts),
            )
            self.conn.execute("INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, ?, ?, 'primary')", (aid, float(src[0]), mid))
            a_mod.prefill_roles(self.conn, aid, a_mod.roles_for_stem(stem or stem_file, settings_mod.values(self.conn)["separation.role_aliases"]))
        cs = ChangeSet()
        cs.add("asset", aid)
        cs.add("source", sid)
        self._on_change(cs)
        return {"assetId": aid, "stem": stem, "model": model}

    def _subtitle_rule_test(self, p: dict[str, Any]) -> dict[str, Any]:
        """设置里的字幕规则试算框（规格 06 §6.2.2）：草稿规则先做保存时的同样校验（逐条 + 整套在样例上跑一遍），再分类一行。"""
        current = settings_mod.values(self.conn)
        draft = p.get("rules")
        if draft is None:
            rs = subtitle_rules.SubtitleRules.build(current)
        else:
            rs = subtitle_rules.SubtitleRules.build({k: draft.get(k, current[k]) for k in subtitle_rules.KEYS}, check=True)
        return subtitle_rules.classify(str(p["text"]), rs).wire()

    def _ui_get(self, p: dict[str, Any]) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT key, value FROM ui_state WHERE window=? AND page=?", (p.get("window", "main"), p["page"])
        )
        return {r[0]: loads(r[1]) for r in rows}

    def _ui_set(self, p: dict[str, Any]) -> None:
        """界面状态（重启恢复）。不是用户资料，不走编辑通道。"""
        self.conn.execute(
            "INSERT INTO ui_state(window, page, key, value, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(window, page, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (p.get("window", "main"), p["page"], p["key"], dumps(p["value"]), now_iso()),
        )

    def _quit(self, p: dict[str, Any]) -> dict[str, Any]:
        cancelled = self.jobs.cancel_all() if p.get("cancel_jobs", True) else 0
        self._stop = True
        return {"cancelled": cancelled}
