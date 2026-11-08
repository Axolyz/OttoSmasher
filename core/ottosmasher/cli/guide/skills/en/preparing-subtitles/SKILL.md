---
name: preparing-subtitles
description: "Prepare subtitles for OttoSmasher: clean text, retime across releases, split speaker turns, identify speakers, or transcribe material without captions. Use for CC, bilingual or messy subtitles and timing/speaker work; reuse parts that already meet the request."
---

# Prepare subtitles

Prepare a same-name UTF-8 SRT for each requested video, with the words actually spoken and times in source seconds. Keep one person's continuous speech in each cue; simultaneous speech may overlap and unknown names stay blank. App parsing and import are described in otto guide prepare.

## Before starting

Read otto guide workflow to choose scope and precision, following existing user requirements. Try the needed audio tools as described in otto guide audio. Use `tracks.separatedVocals` / `tracks.defaultFromSeparation` to find and reuse vocals, separating missing ones as needed. Back up captions before editing.

## Suggested route

1. Take representative audio from the beginning, middle and end to check release offsets and editing differences. See references/retiming.md.
2. Clean alignment text and count and interpret this source's annotation habits. See references/cleaning.md.
3. Split sequential turns before building voiceprint references. A known turn can be split while its name is still pending. See references/speakers.md.
4. Check starts, ends, uncertain turns and overlaps. At fine precision, record an outcome for each suspicious case and sample other scenes. See references/verification.md.
5. Check the final parsing result and import. Create requested missing samples and reuse analysis. Small corrections after import can edit existing objects; finish by checking per-item results and search coverage.

This route describes dependencies; tools and order can be adapted to the material. Experiment parameters are useful starting points, to be reconsidered against the audio of a different work.

## Doing just one part

| Task | References |
|---|---|
| Clean text / interpret CC annotations | cleaning.md |
| Timing / subtitles from another release | retiming.md and cleaning.md |
| Identify speakers | cleaning.md annotation audit, then speakers.md |
| No captions | no-subtitles.md |
| Review suspicious boundaries and finish a batch | verification.md |

## Included scripts

Paths are relative to this skill. scripts/speaker_embed.py computes voiceprints for your grouping and naming; scripts/audio_probe.py calls audio-mcp from hosts without an MCP connection. Choose caption statistics to suit the source; see references/verification.md.
