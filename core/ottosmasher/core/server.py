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
from . import text_layer as text_layer_mod
from . import assets as assets_mod
from . import playback as playback_mod
from . import sample_filter, saved_filters, text_search
from .exports import ExportService, export_range
from .samples import SampleService
from .oped import OpedService
from .subtitle_import import SubtitleImporter
from .flatten import FlattenService
from .separation import SeparationService
from .probes import record_probes
from .rhythm import RhythmService
from .search import SearchService
from .handoff import HandoffService
from .speech import SpeechService
from .sample_plan import SamplePlanner
from .text_layer import TextLayer
from .sources import SourceService
from .imports import ImportService
from .roots import RootService
from .thumbnails import ThumbnailService
from .waveforms import WaveformService

log = logging.getLogger(__name__)

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
        r("app.prepareQuit", "app", T.NoParams, T.PrepareQuit,
          "Number of user jobs that quitting would cancel (automatic background jobs are not counted; they resume on next start).",
          lambda p: {"active": self.jobs.active_count(include_background=False)})
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
        r("sources.prep", "read", T.IdParams, T.Prep, "Preparation checklist state of one source.", self._sources_prep)
        r("sources.relocate", "write", T.RelocateParams, T.SourceRelocated, "Point a source at a moved file (reports changed streams, does not refuse).",
          lambda p: self.sources.relocate(p["id"], p["path"]))
        r("sources.deletePreview", "read", T.IdParams, T.DeletePreview, "What deleting a source would remove.", lambda p: self.sources.delete_preview(p["id"]))
        r("sources.delete", "write", T.IdParams, T.DeletePreview, "Delete a source with its assets, samples, text layer and tags (not undoable).",
          lambda p: self.sources.delete(p["id"]))
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
        r("samples.create", "write", T.SampleCreateParams, T.SampleRow,
          "Create one sample on an asset range with the same defaults as the unified new-sample action (name/nature optional overrides).",
          lambda p: self.samples.get(self.sample_plan.create_selection(
              p["assetId"], float(p["start"]), float(p["end"]), name=p.get("name"), nature=p.get("nature"),
              parent_sample_id=p.get("parentSampleId"), via=p.get("via") or "manual")))
        r("samples.plan", "read", T.SamplePlanParams, T.SamplePlan,
          "Plan new samples from one source kind (selection, segments, sfx hints, stem, whole source): same defaults for single and batch.",
          lambda p: self.sample_plan.plan(dict(p["from"])))
        r("samples.createPlanned", "write", T.SampleCreatePlannedParams, T.SamplesCreated, "Create the chosen planned samples atomically (always new samples).",
          lambda p: self.sample_plan.create(dict(p["from"]), p["token"], list(p["keys"]), p.get("overrides"), p.get("nature")))
        r("samples.list", "read", T.SamplesListParams, T.SamplePage,
          "One page of samples matching the filter (nature, star, text incl. read segments and readings, tag facets, tag expressions), with the total.",
          lambda p: self.samples.list(
              offset=int(p.get("offset", 0)), limit=int(p.get("limit", 100)), sort=p.get("sort", "created"),
              **{k: v for k, v in p.items() if k not in ("offset", "limit", "sort")},
          ))
        r("samples.ids", "read", T.SampleFilter, list[str], "IDs of all samples matching the filter (select all across pages).",
          lambda p: self.samples.ids(**p))
        r("tags.facets", "read", T.NoParams, T.FacetValues, "Existing values of each tag facet with sample counts (scope row).",
          lambda p: sample_filter.facet_values(self.conn))
        r("tags.checkExpr", "read", T.ExprParams, T.ExprCheck, "Parse a tag expression; on error give the reason and the 1-based character position.",
          lambda p: sample_filter.check_expr(str(p["expr"])))
        r("filters.list", "read", T.NoParams, list[T.SavedFilter],
          "Saved filters (named scope-row presets: tag conditions only) in user order; create/rename/update/delete/reorder via edits.apply.",
          lambda p: saved_filters.list_filters(self.conn))
        r("samples.get", "read", T.IdParams, T.SampleRow, "One sample with its effective tags.", lambda p: self.samples.get(p["id"]))
        r("samples.delete", "write", T.IdsParams, T.Deleted, "Delete samples (assets, measurements and exports stay).", lambda p: self.samples.delete(list(p["ids"])))
        r("exports.samples", "write", T.ExportSamplesParams, list[str],
          "Export samples as WAV files for drag-out (original, or stretched per sample); returns file paths.",
          lambda p: self.handoff.export_samples(list(p["ids"]), dict(p.get("words", {})), dict(p.get("versions") or {})))
        r("exports.stretched", "write", T.StretchedExportParams, T.ExportedWav,
          "Export a whole sample as a stretched WAV at the global BPM (scheme computed on demand; manifest with the composed mapping).",
          lambda p: self.handoff.export_stretched(p["id"], dict(p.get("words", {})), p.get("plan") or "near_fast", bool(p.get("mora")), bool(p.get("longVowel"))))
        r("reaper.handoff", "write", T.ReaperParams, T.ReaperHandoff,
          "Copy WAVs to the REAPER folder and build the REAPERMedia clipboard text: unbaked original + stretch markers, or (baked) stretched audio + onset markers.",
          lambda p: self.handoff.reaper_handoff(list(p["ids"]), dict(p.get("words", {})), p.get("plan") or "near_fast", bool(p.get("mora")), bool(p.get("longVowel")),
                                                p.get("baked"), hits=p.get("hits")))
        r("reaper.template", "write", T.ReaperParams, T.ReaperTemplate, "Write the same items as an .RTrackTemplate file (experimental).",
          lambda p: self.handoff.reaper_template(list(p["ids"]), dict(p.get("words", {})), p.get("plan") or "near_fast", bool(p.get("mora")), bool(p.get("longVowel")),
                                                 bool(p.get("baked")), hits=p.get("hits")))
        r("exports.wav", "write", T.ExportWavParams, T.ExportedWav, "Export an asset range as a WAV file (reuses an identical export).",
          lambda p: self.exports.export_wav(
              p["assetId"], float(p["start"]), float(p["end"]), content=p["content"], track=p["track"],
              local_prefix=p.get("localPrefix"), processing=p.get("processing", ""), directory=p.get("directory"),
          ))
        r("exports.range", "write", T.ExportRangeParams, T.ExportedWav, "Export an asset range as WAV named by the naming rule (+ fragment word).",
          lambda p: export_range(self.exports, self.samples.suggest, p["assetId"], float(p["start"]), float(p["end"]), dict(p.get("words", {}))))
        r("tags.promoteBatch", "read", T.PromoteParams, T.PromoteInfo, "Edit batch that promotes local tags to a segment tag (apply with edits.apply).",
          lambda p: text_layer_mod.promote_batch(self.conn, p["sampleId"], list(p["tags"]), role=p.get("role"), start=p.get("start"), end=p.get("end")))
        # ---- 字幕导入、文本层、音效提示、区段标签、OP/ED（所有者 2026-10-09）
        r("subtitles.preview", "read", T.SubtitlePreviewParams, T.SubtitlePreview,
          "Preview importing a subtitle file into the text layer, sfx hints, speakers and OP/ED (new / unchanged / replace / skip per line).",
          lambda p: self.subtitles.preview(p["sourceId"], p.get("path"), p.get("options")))
        r("subtitles.import", "write", T.SubtitleImportParams, T.SubtitleImportResult, "Import a subtitle file as previewed (one atomic, undoable edit).",
          lambda p: self.subtitles.import_(p["sourceId"], p["token"], p.get("options"), p.get("path")))
        r("subtitles.importDefault", "write", T.SourceIdParams, T.SubtitleImportResult, "One-click import of the associated subtitle with default options.",
          lambda p: self.subtitles.import_default(p["sourceId"]))
        r("subtitles.previewMany", "read", T.SourceIdsParams, list[T.SubtitleBatchRow], "Batch preview of subtitle import (sources without subtitles are skipped).",
          lambda p: self.subtitles.preview_many(list(p["sourceIds"])))
        r("subtitles.importMany", "write", T.SubtitleImportManyParams, list[T.SubtitleImportManyRow], "Batch subtitle import with default options, each source atomic.",
          lambda p: self.subtitles.import_many(list(p["items"])))
        r("textLayer.list", "read", T.TextLayerParams, T.TextLayerList, "Text segments, sfx hints, range tags, OP/ED and derived samples of a source.",
          lambda p: text_layer_mod.list_for_source(self.conn, p["sourceId"], p.get("assetId")))
        r("segments.get", "read", T.IdParams, T.TextSegment, "One text segment (with usage count and protection flags).",
          lambda p: text_layer_mod.get_segment(self.conn, p["id"]))
        r("segments.checkAdd", "read", T.SegmentRangeParams, T.SegmentAddCheck, "Which segments a new typed segment would overlap, and whether cut is possible.",
          lambda p: self.text.check_add(p["sourceId"], float(p["start"]), float(p["end"])))
        r("segments.add", "write", T.SegmentAddParams, T.SegmentAdded, "Add a typed segment to the text layer (replace or cut overlapping ones when asked).",
          lambda p: self.text.add_segment(p["sourceId"], float(p["start"]), float(p["end"]), str(p["text"]), p.get("resolve")))
        r("segments.split", "write", T.SegmentSplitParams, T.SegmentsSplit, "Split a segment (old one deleted, two new protected segments).",
          lambda p: self.text.split(p["id"], int(p["version"]), float(p["at"]), str(p["left"]), str(p["right"])))
        r("segments.merge", "write", T.SegmentMergeParams, T.SegmentAdded, "Merge segments into one new protected segment.",
          lambda p: self.text.merge(list(p["ids"]), p.get("text")))
        r("segments.regenerateSpeakers", "write", T.SourceIdParams, T.SpeakersRegenerated,
          "Re-extract speakers from the original subtitle lines with the current rules (unprotected, not hand-edited segments only).",
          lambda p: self.text.regenerate_speakers(p["sourceId"]))
        r("hints.add", "write", T.HintAddParams, T.SegmentAdded, "Add an sfx hint by hand (protected).",
          lambda p: self.text.add_hint(p["sourceId"], float(p["start"]), float(p["end"]), str(p["text"])))
        r("oped.list", "read", T.SourceIdParams, list[T.Oped], "OP/ED ranges of a source.", lambda p: self.oped.list(p["sourceId"]))
        r("oped.identify", "write", T.SourceIdParams, T.IdentifyResult, "Identify OP/ED from subtitle rules; applies non-overlapping pairs when there are no errors.",
          lambda p: self.oped.identify(p["sourceId"]))
        r("oped.identifyMany", "write", T.SourceIdsParams, list[T.IdentifyManyRow], "Batch OP/ED identification.", lambda p: self.oped.identify_many(list(p["sourceIds"])))
        r("oped.add", "write", T.OpedAddParams, T.OpedAdded, "Mark or confirm an OP/ED range (undoable).",
          lambda p: self.oped.add(p["sourceId"], p["kind"], float(p["start"]), float(p["end"]), p.get("via", "mark"), p.get("refs")))
        r("oped.delete", "write", T.IdParams, T.EditRef, "Delete an OP/ED range (undoable).", lambda p: self.oped.delete(p["id"]))
        # ---- 分离（PyMSS Studio）
        # ---- 语音分析（08 §8.4）
        r("speech.preview", "read", T.SpeechPlanParams, T.SpeechPreview,
          "What a speech analysis would do: M segment+track units to analyze, N up to date (skipped), K blocked with reasons.",
          lambda p: self.speech.preview(p["entry"], list(p["ids"]), bool(p.get("rerunFresh", False)), p.get("assetId")))
        r("speech.submit", "job", T.SpeechPlanParams, T.JobSummary, "Queue a speech analysis job (inputs frozen now; one process for all items).",
          lambda p: self.speech.submit(p["entry"], list(p["ids"]), bool(p.get("rerunFresh", False)), p.get("assetId")))
        r("speech.saveManual", "write", T.SpeechManualParams, T.SpeechHeadRef,
          "Save edited phoneme times of a segment on a track as a new manual version (times only; labels/order fixed; rejected if the version changed).",
          lambda p: self.speech.save_manual(p["unitId"], int(p["version"]), p.get("phones"), p.get("text")))
        r("speech.switchHead", "write", T.SpeechSwitchParams, T.SpeechHeadRef, "Make another successful version of a segment on a track the current one.",
          lambda p: self.speech.switch_head(p["unitId"], p["runId"], int(p["version"])))
        r("speech.sample", "read", T.IdParams, T.SpeechSampleView, "Speech analysis a sample reads: the segments overlapping its judge interval on its track, each with versions, plus the merged result.",
          lambda p: self.speech.sample_view(p["id"]))
        r("speech.forAsset", "read", T.AssetRangeParams, list[T.AssetAlignment], "Usable alignments of all segments on an asset range (same physical audio only).",
          lambda p: self.speech.for_asset(p["assetId"], float(p["start"]), float(p["end"])))
        r("measure.f0", "read", T.AssetRangeParams, T.F0Frames, "FCPE pitch/confidence/energy frames of an asset range (unmeasured frames are NaN).",
          lambda p: self.speech.f0(p["assetId"], float(p["start"]), float(p["end"])))
        r("speech.results", "read", T.JobIdParams, list[T.SpeechResultRow], "Per-item results of a speech analysis job.", lambda p: self.speech.results(p["jobId"]))
        r("studio.status", "read", T.NoParams, T.StudioStatus, "PyMSS Studio installation and model list (submits a listing job when unknown).",
          lambda p: self.separation.status())
        r("separation.submit", "job", T.SeparationSubmitParams, T.SeparationSubmitted, "Separate an asset (range) with a Studio model; reuses identical results.",
          lambda p: self.separation.submit(p["assetId"], p.get("start"), p.get("end"), p["model"], p.get("stems")))
        r("flatten.open", "read", T.FlattenOpenParams, T.FlattenOpened,
          "Open the flatten workbench: freeze asset + outer selection, entry defaults, alignment availability, suggested name.",
          lambda p: self.flatten.open(p["assetId"], float(p["start"]), float(p["end"]), p["entry"], p.get("sampleId")))
        r("flatten.estimate", "read", T.FlattenEstimateParams, T.FlattenEstimate, "Estimate the target from cached measurements only (no model run).",
          lambda p: self.flatten.estimate(dict(p["token"]), dict(p["options"]), p.get("sampleId")))
        r("flatten.submit", "job", T.FlattenSubmitParams, T.JobSummary, "Queue one flatten (checks the frozen asset is unchanged).",
          lambda p: self.flatten.submit(dict(p["token"]), dict(p["options"]), str(p["name"]), p.get("sampleId")))
        r("flatten.submitBatch", "job", T.FlattenBatchParams, T.JobSummary, "Queue a batch flatten: one job, each sample targets independently (auto only).",
          lambda p: self.flatten.submit_batch(list(p["ids"]), dict(p["options"])))
        r("flatten.rerunFailed", "job", T.JobIdParams, T.JobSummary, "Re-queue only the failed items of a flatten job with the same options.",
          lambda p: self.flatten.rerun_failed(p["jobId"]))
        r("flatten.results", "read", T.JobIdParams, list[T.FlattenResultRow], "Per-item results of a flatten job (product sample and target).",
          lambda p: self.flatten.results(p["jobId"]))
        # ---- 节奏与卡拍（阶段 6）
        # ---- 三大搜索（规格 09 §9.6、10 §10.2）
        r("search.coverage", "read", T.SearchCoverageParams, T.SearchCoverage,
          "How much of the current browse scope is ready to search (speech index built / F0 measured).",
          lambda p: self.search.coverage(p["mode"], p.get("scope")))
        r("search.prepare", "job", T.SearchCoverageParams, T.JobSummary,
          "Queue a job that prepares the search index for the current scope (speech: rhythm index; pitch: F0). Does not search.",
          lambda p: self.search.prepare(p["mode"], p.get("scope")))
        r("metrics.status", "read", T.MetricsStatusParams, T.MetricsStatus,
          "Single-sound metrics in the current scope: prepared count and, per chosen metric, how many samples lack it (they never match).",
          lambda p: self.acoustic.status(p.get("scope"), list(p.get("metrics") or [])))
        r("metrics.prepare", "job", T.MetricsPrepareParams, T.JobSummary,
          "Queue a job that measures missing F0 and computes the single-sound metrics for the current scope.",
          lambda p: self.acoustic.prepare(p.get("scope")))
        r("search.speech", "write", T.SearchSpeechParams, T.SearchStarted,
          "Start a speech/rhythm search on the current scope; finishes with event search.finished and a fixed result (all hits kept).",
          lambda p: self.search.run_speech(p["query"], p.get("scope")))
        r("search.pitch", "write", T.SearchPitchParams, T.SearchStarted,
          "Start a complete pitch search (saved samples or analysed source tracks); finishes with event search.finished and a fixed result.",
          lambda p: self.search.run_pitch(p["blocks"], p.get("params"), p["mode"], p.get("scope")))
        r("search.pitchCheck", "read", T.PitchCheckParams, T.PitchChecked,
          "Validate a pitch query (blocks or the text helper format) and return on-the-spot problems; no search.",
          lambda p: self.search.pitch_check(p.get("blocks"), p.get("text")))
        r("search.cancel", "ui", T.SearchIdParams, T.SearchCancelled, "Cancel a running search (a cancelled search writes no fixed result).",
          lambda p: self.search.cancel(p["searchId"]))
        r("search.status", "read", T.SearchIdParams, T.SearchFinished, "State of a search started in this session.",
          lambda p: self.search.status(p["searchId"]))
        r("hits.resolve", "read", T.HitRefParams, T.HitInfo, "Check that a hit is still valid and return its range and evidence scheme (09 §9.7).",
          lambda p: self.hits.wire(p["resultId"], int(p["rank"]), int(p["index"])))
        r("hits.render", "write", T.HitRenderParams, T.RhythmRendered,
          "Render a hit for audition: stretched with the scheme its evidence chose (whole scope rendered, hit range cut out), or original with clicks.",
          lambda p: self.hits.render(p["resultId"], int(p["rank"]), int(p["index"]), p["version"], p["sound"]))
        r("hits.export", "write", T.HitExportParams, T.ExportedWav, "Export a hit as WAV (original, or stretched with its evidence scheme).",
          lambda p: self.hits.export(p["resultId"], int(p["rank"]), int(p["index"]), p["version"], dict(p.get("words", {}))))
        r("results.list", "read", T.NoParams, list[T.ResultHeader], "Open fixed results (restored without searching again).",
          lambda p: self.search.results())
        r("results.page", "read", T.ResultPageParams, T.ResultPage,
          "One page (at most 100) of a fixed result; only checks members for invalidation, never recomputes or reorders.",
          lambda p: self.search.page(p["id"], int(p.get("offset", 0)), int(p.get("limit", 100))))
        r("results.close", "write", T.IdParams, T.IdParams, "Close a fixed result (deletes the result set only, never samples).",
          lambda p: self.search.close(p["id"]))
        r("results.setUi", "ui", T.ResultUiParams, None, "Remember a fixed result's UI state (active, page, selection, scroll).",
          lambda p: self.search.set_ui(p["id"], p.get("uiState")))
        r("rhythm.bpm", "read", T.NoParams, T.Bpm, "Global target BPM (null = original-speed stretch).", lambda p: {"bpm": self.rhythm.bpm()})
        r("rhythm.setBpm", "ui", T.BpmParams, T.Bpm, "Set the global target BPM (20-400 or null); a working parameter, not undoable; broadcast as rhythm.bpm.",
          lambda p: self.rhythm.set_bpm(p.get("bpm")))
        r("rhythm.view", "read", T.RhythmViewParams, T.RhythmView,
          "Rhythm analysis of one sample: blocks, pauses, segments, cells and the three schemes at the global BPM (computed on demand, no model run).",
          lambda p: self.rhythm.view(p["id"], bool(p.get("mora")), bool(p.get("longVowel"))))
        r("rhythm.setParams", "write", T.RhythmSetParams, T.RhythmEdited,
          "Edit per-sample rhythm parameters (pause sensitivity, segment threshold, splits, manual cells/cuts/merges); undoable.",
          lambda p: self.rhythm.set_params(p["id"], int(p["version"]), {k: v for k, v in p.items() if k not in ("id", "version")}))
        r("rhythm.render", "write", T.RhythmRenderParams, T.RhythmRendered,
          "Render an audition (original or stretched; voice, voice+click or click only) into the rebuildable cache.",
          lambda p: self.rhythm.render(p["id"], p["version"], p["sound"], p.get("plan") or "near_fast", bool(p.get("mora")), bool(p.get("longVowel"))))
        r("playback.resolveRender", "read", T.RenderKeyParams, T.AssetHandle, "Playback handle of a rendered audition (by key, never by path).",
          lambda p: self.rhythm.resolve_render(p["key"]))
        r("separation.results", "read", T.JobIdParams, list[T.AssetRecord], "Assets registered by a separation job.", lambda p: self.separation.results(p["jobId"]))

    # ---------- 打开与关闭

    def open(self) -> None:
        self.ws.ensure()
        self._lock.acquire()
        self.conn = connect(self.ws.db_path)
        report = migrate(self.conn, self.ws.backups)
        actor_mod.install(self.conn)
        self._upgrade_steps()
        if report.backup:
            log.info("schema migrated %s -> %s, backup %s", report.from_version, report.to_version, report.backup)
        self.edits = EditService(self.conn, on_change=self._on_change)
        self.sources = SourceService(self.conn, on_change=self._on_change, workspace_root=self.ws.root)
        self.exports = ExportService(self.conn, self.ws)
        self.reader = text_search.Reader(self.ws.dictionary)
        self.samples = SampleService(self.conn, on_change=self._on_change, reader=self.reader)
        self.subtitles = SubtitleImporter(self.conn, self.edits, on_change=self._on_change)
        self.oped = OpedService(self.conn, self.edits, on_change=self._on_change)
        self.text = TextLayer(self.conn, self.edits, on_change=self._on_change)
        self.sample_plan = SamplePlanner(self.conn, self.samples, on_change=self._on_change)
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
        self.speech = SpeechService(self.conn, self.ws, self.jobs, self.support_dir, on_change=self._on_change)
        self.flatten = FlattenService(self.conn, self.ws, self.jobs, self.support_dir, self.speech, self.samples, on_change=self._on_change)
        self.rhythm = RhythmService(self.conn, self.ws, self.speech, self.edits, emit=self.emit)
        self.handoff = HandoffService(self.conn, self.ws, self.exports, self.rhythm)
        from .acoustic import AcousticService

        self.search = SearchService(self.conn, self.ws, self.jobs, self.samples, self.speech, self.support_dir, emit=self.emit, rhythm=self.rhythm, post=self.post)
        from .hits import HitService

        self.hits = HitService(self.conn, self.search, self.rhythm, self.handoff, self.exports)
        self.handoff.hits = self.hits
        from .search_auto import AutoPrepare

        self.auto = AutoPrepare(self.conn, self.search, self.jobs, self.post, speech=self.speech)
        self.acoustic = AcousticService(self.conn, self.ws, self.jobs, self.search, self.speech, self.support_dir, emit=self.emit)
        self.roots = RootService(self.conn, self.ws, self.jobs, self.sources, on_change=self._on_change, emit=self.emit)
        self.interrupted_on_start = self.jobs.recover()
        self.roots.rescan()  # 启动时扫一次原片文件夹（阶段 3.13；不实时监视）
        self.auto.kick_all()  # 启动时把检索的准备补齐一次（后台，所有者 2026-10-08）
        self._readings_soon(1.0)

    def _upgrade_steps(self) -> None:
        """迁移后在 Python 里补做的步骤（``upgrade_pending``；做完就删，失败下次打开再做）。"""
        try:
            pending = [r[0] for r in self.conn.execute("SELECT name FROM upgrade_pending")]
        except Exception:  # noqa: BLE001 — 旧库没有这张表
            return
        for name in pending:
            if name == "effective-tags":
                from . import effective_tags

                with transaction(self.conn):
                    effective_tags.rebuild_all(self.conn)
                    self.conn.execute("DELETE FROM upgrade_pending WHERE name=?", (name,))

    def close(self) -> None:
        try:
            self.waveforms.shutdown()
            self.thumbs.shutdown()
            self.jobs.kill_all()
            if getattr(self, "search", None) is not None:
                self.search.shutdown()
            if getattr(self, "auto", None) is not None:
                self.auto.shutdown()
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
        if getattr(self, "auto", None) is not None:
            self.auto.on_change(cs.entities)
        if "segment" in cs.entities or "setting" in cs.entities:
            self._readings_soon()

    # ---------- 文字搜索的读音（07 §7.1）：资料变化后合并 2 秒在主循环里补；检索前也会补齐，这里只是让检索不用等

    def _readings_soon(self, delay: float = 2.0) -> None:
        t = getattr(self, "_readings_timer", None)
        if t is not None:
            t.cancel()
        self._readings_timer = threading.Timer(delay, lambda: self.post(self._fill_readings))
        self._readings_timer.daemon = True
        self._readings_timer.start()

    def _fill_readings(self) -> None:
        try:
            if text_search.ensure(self.conn, self.reader, limit=500) == 500:
                self.post(self._fill_readings)
        except Exception:  # noqa: BLE001 — 补不上就等检索时再补（那时出错会报给用户）
            log.exception("filling segment readings failed")

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
        """原片列表 + 每个原片的统计（05 §5.8：句数、OP/ED、派生采样数；阶段 4：语音采样数与已分析数）。"""
        c = text_layer_mod.counts(self.conn)
        sp = self.speech.analyzed_counts()
        zero = {"speech": 0, "analyzed": 0}
        return [r | {"counts": None if r["id"] not in c else c[r["id"]] | sp.get(r["id"], zero)} for r in self.sources.list()]

    def _sources_prep(self, p: dict[str, Any]) -> dict[str, Any]:
        sp = self.speech.source_counts(p["id"])  # 句（文本单元）：原片入口范围内的台词行与语音采样自己的那一句
        return text_layer_mod.prep(self.conn, p["id"]) | {"speech": {"ok": sp["speech"] > 0 and sp["analyzed"] == sp["speech"], **sp}}

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
