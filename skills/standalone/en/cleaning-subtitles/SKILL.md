---
name: cleaning-subtitles
description: "Cleans anime subtitle files for speech work: spoken words only, one person per cue, consistent speaker labels. Use for messy, bilingual or closed-caption subtitles, or before phoneme alignment and speaker labeling."
---

# Cleaning subtitles

Goal: one UTF-8 `.srt` per video with the same name, where each cue holds one person's spoken words. Keep a backup of every subtitle file you change.

## Recommended order

Clean the text, split cues and label speakers in one pass, and produce one final subtitle file. Later steps depend on earlier ones:

1. Separate the vocals.
2. Check the timing against this release and fix any overall offset. Alignment needs windows that are close.
3. Clean the text down to spoken words. It becomes the alignment text.
4. Audit the labels.
5. Split two-person cues. Voiceprints need one person per range.
6. Compute voiceprints on the split lines and label speakers.
7. Write one final subtitle file, check it, and import it once.

## Before you start

Use separated vocals where you can, because splitting cues needs a clear voice. Check your audio tool with a real call on a short clip: a listed tool is not a working tool.

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

## Write speakers consistently

- One cue holds one person's continuous speech.
- Start every speech line with a label such as `（name）`. Leave it out when unknown.
- Write several people speaking together as `（A、B）`.
- Use one name per character across the whole season.
- Put sounds in their own cue, with the same timing as the original.
- Leave no other brackets inside speech. Delete readings; for words actually spoken, delete only the brackets.

To split a two-person cue:

1. Align both lines one after another with a forced aligner, using the cue time ± 0.2 s as the window.
2. Cut at the middle of the gap between the two lines. The two cues may extend to the speech the alignment found.
3. If one line aligns to under 0.1 s, it was probably not found in the vocals. Leave that cue unsplit and unlabelled.

To fill in unlabelled cues from voices, use skill `labeling-speakers`.

## Common fixes

| Problem | Fix |
|---|---|
| Chinese–Japanese ASS | Keep the Japanese by style name or by the text. When one event stacks languages with `\N`, keep the Japanese line. Remove override tags and effect-only lines. |
| Lyrics | Delete the lyric lines of OP/ED and insert songs, or keep them apart from speech. |
| Readings in speech, `歳納(としのう)京子` | Remove the brackets. |
| Sound on the first line, speech on the second | Split into two cues with the same timing. |
| Humming written `♪（ハミング）` | Write the sound line `（ハミング）`, or the lyrics. |
| Subtitle name differs from the video | Write a same-name copy. Prefer proper subtitles over a machine transcript, because they have speakers. |
| Embedded subtitles | Extract with `ffmpeg -i ep01.mkv -map 0:s:0 ep01.ass`. Image subtitles need text recognition first. |
| Subtitles from another release | Use skill `retiming-subtitles`. |
| No subtitles | Use skill `transcribing-without-subtitles`. |

## Music marks

`♪～` / `～♪` can mark OP/ED, but also insert songs and karaoke scenes. If a tool pairs them as OP/ED, a correct subtitle file can produce errors, such as three pairs or an unpaired end mark. Keep the real OP and ED marks, and rewrite other music as a sound line such as `（音楽）`.

## Check the result

Look for pieces of speech, readings or odd names among the speakers, which mean brackets are left; cues with labels on only some lines; and text that is not what was actually said.
