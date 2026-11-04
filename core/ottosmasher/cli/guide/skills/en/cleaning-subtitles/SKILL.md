---
name: cleaning-subtitles
description: "Cleans subtitle files into the form OttoSmasher reads: one same-name UTF-8 SRT per video, spoken words only, one person per cue. Use for messy, bilingual or closed-caption subtitles, adding speaker labels, or subtitles timed for a different release. Not needed when the subtitles are already clean."
---

# Cleaning subtitles

Goal: one UTF-8 `.srt` per video with exactly the same name, where each cue holds one person's spoken words. Reading rules are in `otto guide prepare`; this skill covers how to get there.

## Before you start

Do these before any batch work, and report each one as verified, unavailable or not yet tested:

1. Run `otto status`.
2. List finished vocals with `tracks.separatedVocals {"sourceIds"}` and reuse them. Set a default with `tracks.defaultFromSeparation` if one is missing. Separate first if there are none (skill `separating-audio`), because splitting cues needs a clear voice.
3. Check your audio tool as the overview describes.
4. Audit the labels (next section) before you trust any label or turn boundary.

Keep a `backup_` copy of every subtitle file you change. A same-name `.ass` can stay.

## Audit the labels

Sources label speakers differently, so measure this for each source before you trust it. The only certainty is that a speaker change starts a new text line.

Count these per source:

- both lines of a cue labelled (a change of speaker)
- first line only (often the same person)
- second line only
- a label alone on its own line
- two consecutive cues with the same label

Then listen to a sample from each pattern in each source. Counting names and two-line cues is not enough. In the subtitles tried so far, consecutive labelled cues named the same person 3% to 47% of the time, and cues labelled only on the second line ranged from none to over a thousand.

Fansub subtitles usually have no labels. Closed captions label a line only when the speaker is not obvious, so labelled lines tend to be the harder ones.

## Write speakers in the one form the app reads

- One cue holds one person's continuous speech.
- Start every speech line with `（name）`. Leave it out when unknown.
- Write several people speaking together as `（A、B）`.
- Use one name per character across the whole season.
- Put sounds in their own cue as a whole-line bracket, with the same timing as the original.
- Leave no other brackets inside speech. Delete readings; for words actually spoken, delete only the brackets.

To split a two-person cue:

1. Align both lines with `speech.align` and `lines`, using the cue time ± 0.2 s as the window.
2. Cut at the middle of the gap between the two lines. The two cues may extend to the speech the alignment found.
3. If one line aligns to under 0.1 s, it was probably not found in the vocals. Leave that cue unsplit and unlabelled.

To fill in unlabelled cues from voices, use skill `grouping-speakers`.

## Common fixes

| Problem | Fix |
|---|---|
| Chinese–Japanese ASS | Keep the Japanese by style name or by the text. When one event stacks languages with `\N`, keep the Japanese line. Remove override tags and effect-only lines. |
| OP/ED or insert-song lyrics | Delete the lyric lines. See "Music marks" below. |
| Readings in speech, `歳納(としのう)京子` | Remove the brackets. |
| Sound on the first line, speech on the second | Split into two cues with the same timing. |
| Humming written `♪（ハミング）` | Write the sound line `（ハミング）`, or the lyrics. |
| Subtitle name differs from the video | Write a same-name copy. Prefer proper subtitles over a machine transcript, because they have speakers. |
| Embedded subtitles | Extract with `ffmpeg -i ep01.mkv -map 0:s:0 ep01.ass`. Image subtitles need text recognition first. |
| No subtitles | Run speech recognition and write a same-name `.srt`. Treat the text as a draft. |

## Check timing against this release

Subtitles from another release (TV or streaming on a BD video) may be off by a fixed amount, drift from where a commercial break used to be, or miss whole passages.

1. Spot-check lines at the start, middle and end against the voice, using word times and loudness on/offsets.
2. Apply one shift for an overall offset, or shift from the exact cue where the offset starts.
3. Locate an edit point at a specific line. The nearest subtitle is not precise enough when a release has extra dialogue.
4. Keep a written record of dialogue that exists in only one release. Do not force alignment onto different words.

A successful alignment does not prove its window was right, so check windows independently.

## Use transcripts to check, not to replace

Whisper misses high-pitched exclamations and crowd chanting, and a prompt with character names can produce text nobody said. A wider window helps sometimes. Otherwise use the waveform and the original subtitle.

## Music marks

`♪～` / `～♪` also mark insert songs and karaoke scenes, so a correct subtitle file can report OP/ED errors, such as three pairs or an unpaired end mark.
Keep the real OP and ED pairs. Rewrite other music as a sound line such as `（音楽）`. A sound hint is limited to 120 s, so split a longer one into consecutive cues.

## Bring it into the app

1. Check the file with `subtitles.parse {"path", "duration"}`. Look at `speakers` (pieces of speech, readings or odd names mean brackets are left), cues with `withheld` true (labels present but not recorded), `problems`, and `oped`.
2. For registered sources, run `sources.rescan --wait`, then confirm `subtitle_path` in `sources.list`. A source whose subtitle was chosen by hand keeps that choice; change it with `edits.apply` (entity `source`, field `subtitle_path`).
3. Run `subtitles.previewMany {"sourceIds"}`, then `subtitles.importMany`. An existing segment with unchanged time and text keeps its old speakers; run `subtitles.clear` first to start over.
