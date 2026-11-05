---
name: preparing-subtitles
description: "Prepares subtitles for OttoSmasher: cleans the text, fixes timing, splits two-person cues, labels speakers by voiceprint, or makes timed subtitles when there are none. Use for messy, bilingual or closed-caption subtitles, mistimed segments, speaker labeling, or material with no subtitles. Not needed when the subtitles are already clean."
---

# Preparing subtitles

Goal: one UTF-8 `.srt` per video with exactly the same name, where each cue holds one person's spoken words with accurate timing. Reading rules are in `otto guide prepare`. Paths below are relative to this skill's folder.

## Recommended order

For a full job, do these in one pass and produce one final subtitle file, because later steps depend on earlier ones:

1. Separate the vocals.
2. Check the timing against this release and fix any overall offset, because alignment needs windows that are close. Read `references/retiming.md`.
3. Clean the text down to spoken words, because it becomes the alignment text. Read `references/cleaning.md`.
4. Audit the speaker labels. Read `references/cleaning.md`.
5. Split two-person cues, because voiceprints need one person per range. Read `references/cleaning.md`.
6. Compute voiceprints on the split lines and label speakers. Read `references/speakers.md`.
7. Write one final subtitle file, check it, and import it once. A later re-import does not update the speakers of unchanged segments.

## If you only need part of it

Read only what the task needs:

| Task | Read |
|---|---|
| Clean messy or bilingual subtitles | `references/cleaning.md` |
| Fix the timing of segments or subtitles | `references/retiming.md` |
| Use subtitles from another release | `references/cleaning.md` ("Check timing against this release") |
| Label who says each line | `references/cleaning.md` (label audit), then `references/speakers.md` |
| Make subtitles for material with none | `references/no-subtitles.md` |

## Before you start

1. List finished vocals with `tracks.separatedVocals {"sourceIds"}` and reuse them. Set a default with `tracks.defaultFromSeparation` if one is missing. Separate first if there are none, because splitting cues needs a clear voice.
2. Check your audio tool as the overview describes.
3. Keep a `backup_` copy of every subtitle file you change. A same-name `.ass` can stay.
