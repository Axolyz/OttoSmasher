## Audit the labels

Read the original text and relevant style/track information, then compare examples with audio. Establish how this source marks speaker changes: a new line often marks a turn, but can also continue one person's speech. Choose counting scripts from what you observe, updating them as you find new forms.

Examples to inspect per source:

- both lines of a cue labelled (a possible turn change to verify)
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
2. Establish turns and boundaries from the audio, full sentence and curve. A real silent gap gives room for a cut; keep overlaps where the speakers actually overlap.
3. Review short or failed alignments with more context. Once a turn is clear, split it and leave any unknown name pending.

To fill in unlabelled cues from voices, see `references/speakers.md`.

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
| No subtitles | See `references/no-subtitles.md`. |

## Check timing against this release

Subtitles from another release (TV or streaming on a BD video) may be off by a fixed amount, drift from where a commercial break used to be, or miss whole passages.

1. Spot-check lines at the start, middle and end against the voice, using word times and loudness on/offsets.
2. Apply one shift for an overall offset, or shift from the exact cue where the offset starts.
3. Locate an edit point at a specific line. The nearest subtitle is not precise enough when a release has extra dialogue.
4. Keep a written record of dialogue that exists in only one release. Do not force alignment onto different words.

A successful alignment does not prove its window was right, so check windows independently.

## Use transcripts to check, not to replace

A transcript can miss words or invent them (see `otto guide combine`). When it disagrees with the subtitle, use the waveform and the original subtitle to decide.

## Music marks

`♪～` / `～♪` also mark insert songs and karaoke scenes, so a correct subtitle file can report OP/ED errors, such as three pairs or an unpaired end mark.
Keep the real OP and ED pairs. Rewrite other music as a sound line such as `（音楽）`. A sound hint is limited to 120 s, so split a longer one into consecutive cues.

## Bring it into the app

1. Check the file with `subtitles.parse {"path", "duration"}`. Look at `speakers` (pieces of speech, readings or odd names mean brackets are left), cues with `withheld` true (labels present but not recorded), `problems`, and `oped`.
2. For registered sources, run `sources.rescan --wait`, then confirm `subtitle_path` in `sources.list`. A source whose subtitle was chosen by hand keeps that choice; change it with `edits.apply` (entity `source`, field `subtitle_path`).
3. Import as `otto guide prepare` describes. An existing segment with unchanged time and text keeps its old speakers; run `subtitles.clear` first to start over.
