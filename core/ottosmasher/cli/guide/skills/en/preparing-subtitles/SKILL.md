---
name: preparing-subtitles
description: "Prepare subtitles for OttoSmasher: clean text, retime across versions, split speaker turns, identify speakers, or transcribe material without captions. Use for CC/bilingual/messy subtitles, timing or speaker work; skip when captions already satisfy the task."
---

# Prepare subtitles

Deliver one same-name UTF-8 SRT per requested video, with spoken text, correct source-time ranges and one continuous speaker turn per cue. Simultaneous speech may overlap. Unknown identity remains unknown even when a turn must be split. App parsing and import behaviour live in `otto guide prepare`.

## Start with the task contract

Follow `otto guide workflow`: agree on scope, precision and completion once, reusing explicit requests. Discover and actually verify the audio capabilities required (`otto guide audio`). Reuse existing stems via `tracks.separatedVocals` / `tracks.defaultFromSeparation`; separate missing ones as needed. Back up input captions before changes. Read the matching references before planning; examples are not an exhaustive catalog of CC conventions.

## Default route and dependencies

1. Check version offsets and editing differences with representative audio from beginning, middle and end. Read `references/retiming.md`.
2. Clean the alignment text and inventory this source's actual CC annotation patterns. Read `references/cleaning.md`; keep the counts and interpretation.
3. Resolve sequential speaker turns before building voiceprint references. Identify names independently of deciding where the turns are. Read `references/speakers.md` when names must be inferred.
4. Screen both starts and ends, turn ambiguity and overlaps; review the agreed coverage using complete-context evidence. Read `references/verification.md`. In fine mode, every suspicious item needs a recorded outcome, including kept or uncertain.
5. Parse and inspect the final file, then import and create missing samples if requested. Reuse existing samples/analysis. Reconcile per-item results and search readiness rather than just job success. Corrections after import use edits where possible; do not delete and rebuild everything as a routine repair.

This route captures dependencies, not a mandated sequence of tool calls. Choose better methods when the material warrants them and retain evidence that they meet the contract. Confirmation about names can be deferred without merging known turns. Do not convert experimental thresholds into fixed rules or adjust boundaries automatically from screening flags.

## Partial tasks

| Task | References |
|---|---|
| Clean text / interpret CC annotations | cleaning.md |
| Timing / subtitles from another version | retiming.md and cleaning.md |
| Identify speakers | cleaning.md annotation audit, then speakers.md |
| No captions | no-subtitles.md |
| Inspect suspicious boundaries and finish a batch | verification.md |

## Useful helpers

Paths are relative to this skill. `scripts/speaker_embed.py` computes voiceprints; classification and naming remain your judgement. `scripts/audio_probe.py` is a portable audio-mcp client when the host has no MCP integration. No bundled script interprets caption conventions or certifies review completeness. Choose task-specific statistics and evidence after understanding the source; see references/verification.md.
