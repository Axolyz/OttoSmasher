from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .backends import AnalysisKind, PhoneKind
from .rhythm import RhythmQuery


class IndexRequest(BaseModel):
    analysis_kind: PhoneKind = "narabas"


class SegmentSettings(BaseModel):
    analysis_kind: PhoneKind = "narabas"
    analysis_version: str
    pause_threshold_seconds: float = Field(0.28, ge=0.16, le=2, allow_inf_nan=False)
    split_before: list[int] = Field(default_factory=list, max_length=128)
    suppressed_split_before: list[int] = Field(default_factory=list, max_length=128)


class ExportRequest(BaseModel):
    factor: float = Field(1, gt=0, allow_inf_nan=False)
    offset: float = Field(0, allow_inf_nan=False)
    context: dict = Field(default_factory=dict)
    analysis_kind: AnalysisKind = "phonetic"
    variant: Literal["raw", "vocals"] = "raw"
    query: RhythmQuery | None = None
    analysis_version: str | None = None
    rhythm_id: str | None = None
    plan_id: str | None = None
    scope_id: str | None = None


class Feedback(BaseModel):
    value: str = Field(pattern="^(keep|reject|timing_issue)$")
    context: dict = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    mode: Literal["rhythm", "overlay", "aligned", "strict", "strict_overlay", "strict_rhythm"]
    variant: Literal["raw", "vocals"] = "vocals"
    analysis_kind: PhoneKind = "phonetic"
    query: RhythmQuery | None = None
    analysis_version: str | None = None
    rhythm_id: str | None = None
    plan_id: str | None = None
    scope_id: str | None = None


class RhythmEdit(BaseModel):
    kind: PhoneKind
    analysis_version: str
    split_before: list[int] = Field(default_factory=list, max_length=256)


class PlanRequest(BaseModel):
    query: RhythmQuery | None = None
    analysis_kind: PhoneKind = "narabas"
    bpm: float = Field(120, ge=20, le=400, allow_inf_nan=False)
    strategy: Literal["mora", "mora_guided", "acoustic"] = "acoustic"
    auto_long_vowels: bool = False
    density: Literal[1, 2, 4, 8] | None = None
    lock_query: Literal[False] = False
    analysis_version: str | None = None
    rhythm_id: str | None = None
    scope_id: str | None = None
    matched_plan_id: str | None = None
    composition: bool = False
    rest_overrides: dict[str, int] = Field(default_factory=dict)


class CueSettings(BaseModel):
    analysis_kind: PhoneKind
    analysis_version: str
    pause_sensitivity: float = Field(1, ge=0.5, le=2, allow_inf_nan=False)
    slots: dict[str, int] = Field(default_factory=dict)


class CropEdit(BaseModel):
    analysis_kind: PhoneKind
    analysis_version: str
    start: float = Field(allow_inf_nan=False)
    end: float = Field(allow_inf_nan=False)


class ReaperRequest(BaseModel):
    plan_id: str
    analysis_kind: PhoneKind = "narabas"
    variant: Literal["raw", "vocals"] = "vocals"
    directory: str | None = None
    origin: Literal["first_onset", "item_start"] = "first_onset"
    scope_id: str | None = None


class SpeakerRange(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    speaker: str = Field(min_length=1, max_length=120)


class SpeakerAction(BaseModel):
    operation: Literal["label", "regroup", "exclude", "split", "undo"]
    sample_ids: list[str] = Field(default_factory=list, max_length=6000)
    speaker: str | None = Field(None, max_length=120)
    ranges: list[SpeakerRange] | None = None


class SpeakerTask(BaseModel):
    action: Literal["pause", "resume", "retry"]
