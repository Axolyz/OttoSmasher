from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .backends import AnalysisKind


class Cell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["any", "required", "forbidden"] = "any"
    phone: Literal["a", "i", "u", "e", "o"] | None = None
    speaker: str | None = Field(None, max_length=120)
    pitch_trend: Literal["up", "down"] | None = None
    pitch_trend_min: float = Field(1, ge=0, le=24)
    pitch_register: Literal["high", "low"] | None = None
    pitch_register_min: float = Field(2, ge=0, le=24)
    energy_relative_min_db: float | None = Field(None, ge=-40, le=40)
    sustain_to_end: bool = False
    strength_min: float | None = Field(None, ge=0, le=1)
    duration_min_beats: float | None = Field(None, ge=0)
    duration_max_beats: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def valid_range(self):
        if (
            self.duration_min_beats is not None
            and self.duration_max_beats is not None
            and self.duration_max_beats < self.duration_min_beats
        ):
            raise ValueError("Duration maximum must be >= minimum")
        if self.state != "required" and any(
            x is not None
            for x in (
                self.phone,
                self.strength_min,
                self.duration_min_beats,
                self.duration_max_beats,
                self.speaker,
                self.pitch_trend,
                self.pitch_register,
                self.energy_relative_min_db,
                True if self.sustain_to_end else None,
            )
        ):
            raise ValueError("Attributes require a required cell")
        return self


class Note(Cell):
    state: Literal["required"] = "required"
    start_beats: float = Field(ge=0, le=1024)
    end_beats: float = Field(gt=0, le=1024)

    @model_validator(mode="after")
    def positive_width(self):
        if self.end_beats <= self.start_beats:
            raise ValueError("Note block must have positive width")
        return self


class RhythmQuery(BaseModel):
    material_ids: list[str] | None = None
    collection_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")
    bpm: float = Field(120, ge=20, le=400)
    step_beats: float = Field(0.5, ge=0.125, le=4)
    cells: list[Cell] = Field(default_factory=list, max_length=32)
    notes: list[Note] = Field(default_factory=list, max_length=64)
    span_beats: float = Field(8, gt=0, le=1024)
    boundary: Literal["anywhere", "start", "end", "both"] = "anywhere"
    engine: Literal["quantized"] = "quantized"
    strategy: Literal["mora", "mora_guided", "acoustic"] = "acoustic"
    scope: Literal["both", "whole", "segments"] = "both"
    densities: list[float] = Field(default_factory=lambda: [1, 2, 4, 8], min_length=1, max_length=4)
    speed_filter: bool = False
    adjust_pauses: bool = False
    factor_min: float = Field(0.85, ge=0.5, le=2)
    factor_max: float = Field(1.18, ge=0.5, le=2)
    tolerance_beats: float = Field(0.15, gt=0, le=0.45)
    mode: AnalysisKind = "narabas"
    text: str = ""
    source_id: str | None = None
    limit: int = Field(20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_query(self):
        import math

        if any(
            not math.isfinite(d) or d <= 0 or abs(math.log2(d) - round(math.log2(d))) > 1e-9
            for d in self.densities
        ):
            raise ValueError("Grid density must be a positive power of two")
        if self.factor_min > self.factor_max:
            raise ValueError("Duration multiplier maximum must be >= minimum")
        if self.notes:
            if self.cells:
                raise ValueError("Use note blocks or legacy cells, not both")
            ordered = sorted(self.notes, key=lambda n: n.start_beats)
            if ordered[-1].end_beats > self.span_beats:
                raise ValueError("Note blocks must fit the query span")
            if any(a.end_beats > b.start_beats for a, b in pairwise(ordered)):
                raise ValueError("Note blocks cannot overlap")
            if any(b.start_beats - a.start_beats <= 2 * self.tolerance_beats for a, b in pairwise(ordered)):
                raise ValueError("Onset tolerance must be less than half the closest onset interval")
        if not self.notes and not any(c.state == "required" for c in self.cells):
            raise ValueError("At least one required onset is needed")
        if not self.notes and self.tolerance_beats >= self.step_beats / 2:
            raise ValueError("Tolerance must be less than half the grid interval")
        if self.mode in {"acoustic", "vocals_energy"} and any(
            c.phone or c.duration_min_beats is not None or c.duration_max_beats is not None
            for c in (self.notes or self.cells)
        ):
            raise ValueError("Acoustic candidates have no phoneme or phone-duration measurements")
        return self


def search_rhythm(db, query: RhythmQuery):
    from .rhythm_index import search_index

    return search_index(db, query)
