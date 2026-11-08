# Cleaning subtitles

## Audit the labels

Sources label speakers differently, so measure this for each source before you trust it. Speaker changes usually start new lines, but line breaks need not be turns; audit each source.

Count these per source:

- both lines of a cue labelled (a possible turn change to verify)
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
2. Confirm sequential speech and locate the actual turn. Use a midpoint only inside a verified silent gap; inspect overlap or contradictory alignment separately.
3. A missing or implausibly short alignment is a suspicious case, not permission to keep known sequential turns merged. Inspect contextual audio to locate the change; keep unresolved boundaries/identities explicit.

To fill in unlabelled cues from voices, see `references/speakers.md`.

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
| Subtitles from another release | See `references/retiming.md`. |
| No subtitles | See `references/no-subtitles.md`. |

## Music marks

`♪～` / `～♪` can mark OP/ED, but also insert songs and karaoke scenes. If a tool pairs them as OP/ED, a correct subtitle file can produce errors, such as three pairs or an unpaired end mark. Keep the real OP and ED marks, and rewrite other music as a sound line such as `（音楽）`.

## Check the result

Look for pieces of speech, readings or odd names among the speakers, which mean brackets are left; cues with labels on only some lines; and text that is not what was actually said.
