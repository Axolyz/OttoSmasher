---
name: preparing-subtitles
description: "Prepares anime subtitles for speech work: cleans the text, fixes timing, splits two-person cues, labels speakers by voiceprint, or makes timed subtitles when there are none. Use for messy, bilingual or closed-caption subtitles, mistimed subtitles, speaker labeling, or before phoneme alignment."
---

# Preparing subtitles

Goal: one UTF-8 `.srt` per video with the same name, where each cue holds one person's spoken words with accurate timing. These methods come from the author's own exploration on a few anime series. Treat the numbers as a reference.

## Recommended order

Do these in one pass and produce one final subtitle file, because later steps depend on earlier ones:

1. Separate the vocals.
2. Check the timing against this release and fix any overall offset, because alignment needs windows that are close. Read `references/retiming.md`.
3. Clean the text down to spoken words, because it becomes the alignment text. Read `references/cleaning.md`.
4. Audit the speaker labels. Read `references/cleaning.md`.
5. Split two-person cues, because voiceprints need one person per range. Read `references/cleaning.md`.
6. Compute voiceprints on the split lines and label speakers. Read `references/speakers.md`.
7. Write one final subtitle file, check it, and import it once.

## If you only need part of it

| Task | Read |
|---|---|
| Clean messy or bilingual subtitles | `references/cleaning.md` |
| Fix timing, or use subtitles from another release | `references/retiming.md` |
| Label who says each line | `references/cleaning.md` (label audit), then `references/speakers.md` |
| Make subtitles for material with none | `references/no-subtitles.md` |

## Before you start

- Use separated vocals where you can, because splitting and alignment need a clear voice.
- You need an audio tool (spectrograms, loudness, timed transcripts), such as audio-mcp. Check it with a real call on a short clip: a listed tool is not a working tool.
- You need a forced aligner for the language. The numbers here were measured with pydomino on Japanese.
- Keep a backup of every subtitle file you change.

## Use transcripts to check, not to replace

Whisper misses high-pitched exclamations and crowd chanting, and a prompt with character names can produce text nobody said. When a transcript disagrees with the subtitle, use the waveform and the original subtitle to decide.

## Precision and completion

When not specified, ask once for quick / standard / fine, explaining this task's actual tradeoff. Reuse explicit requirements. Fine means screen the whole scope and review every suspicious boundary/turn, sampling normal scenes. Every-line verification can be requested. Screening proposes cases, not automatic edits; preserve evidence and pending counts. Mechanical helpers can prepare data while the agent chooses suitable judgement methods.
