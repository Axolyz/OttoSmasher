# Practices and experience (not rules)

Practices and pitfalls collected while doing real tasks with `otto`. **They are not rules and may be out of date**; operational facts come from the regular guide,
parameters from `otto describe`, and the owner's playbook (`otto guide playbook`) wins over this page. When unsure, use your own judgement.

## Separation strategy: whole episodes or only what you need

- **Whole episodes**: done once, and the vocal then serves subtitle cleaning, retiming, samples and analysis with little rework; costs ten to several tens of minutes per episode. The owner can also select all and run it in the app.
- **Only the parts you need** (`separation.submit` with `start` / `end`): fast, good for a few lines or a first look; partial stems cannot be the default track, so pass their `assetId` where you use them.
- Measured 2026-10-30 (HyperACE v2, Apple silicon): each separation job takes about 8 s to start, then about 0.35 s per second of audio — 8.5 s for a 5 s part, 29 s for 60 s, about 9 minutes for a 24-minute episode.
  So with one job per line, a few dozen lines take about as long as the whole episode.
  Pass them together with `ranges`: the app joins them into one input and separates once (10 parts × 6 s measured 31 s, about 100 s as separate jobs).
  Results depend on context: a line separated alone, joined with others, or inside the surrounding minute differ by about −9 dB (alone and joined are equally close); for demanding lines use a longer range or the whole episode.
- Cleaning subtitles and retiming need a clear voice, so usually **separate first, then clean**. For whole episodes, submit all of them at once, then wait as in ground rule 5 of the overview — never idle-poll.

## Cleaning subtitles

Goal: one UTF-8 `.srt` per episode with **exactly the same name** as the video, each cue holding only the words actually spoken; put the speaker in a leading bracket when you can tell, otherwise leave it out (fansub subtitles usually have no speakers; that is normal).
The original `.ass` can stay (with the same name the app prefers `.srt`). (Keep a `backup_` copy before changing the owner's files — see the ground rules in the overview.)

Common problems and fixes:
- **Fansub bilingual Chinese–Japanese ASS** (most common): keep only the Japanese, by style name (`JP` / `CN` and the like) or by the text; when one event stacks two languages with `\N`, keep the Japanese line;
  remove override tags and effect-only lines (titles, notes, translations of on-screen text); delete OP/ED and insert-song lyric lines and write `♪～` / `～♪` markers at their timings, or `oped.add` after importing.
- Readings in the spoken text `歳納(としのう)京子` → remove the brackets.
- A cue with a sound on the first line and speech on the second → split it into two cues with the same timing.
- Humming written as `♪（ハミング）` → make it a sound line `（ハミング）`, or write out the lyrics.
- Subtitle name differs from the video (extra prefix, language suffix) → write a same-name copy. With both a machine transcript (`.ja.srt`) and proper subtitles, prefer the proper ones (they have speakers).
- Embedded subtitles: extract with `ffmpeg -i ep01.mkv -map 0:s:0 ep01.ass`; image subtitles need text recognition first.
- **Timing does not match** (TV subtitles on a BD video and the like): off by a few seconds overall, or drifting after where a commercial break used to be. Spot-check lines at the start, middle and end
  against the voice (word times from a transcript, loudness on/offsets); shift everything for an overall offset, or from the point where it starts.
- No subtitles: you may run speech recognition locally and write a same-name `.srt`.

Checking the result: `subtitles.parse {"path", "duration"}`, or (for registered sources) `sources.rescan --wait` → `subtitles.preview {"sourceId"}`;
look at `speakers` (pieces of speech, readings or odd names = brackets left over), `problems`, the `text` to be aligned, and `oped`.

## Retiming: rough first, then refine with alignment

Tried on 2026-10-29 / 30 with 60 analysed lines: the aligner fits the whole line into the window it is given and does not look for where the line is; windows that are too wide or off do not align (numbers in topic `primitives`).
Approach: get boundaries roughly right (within 0.1–0.2 s) from a transcript with word timestamps (e.g. audio-mcp's `audio_transcribe`, Whisper) or loudness on/offsets,
then refine with the first and last phoneme times from `speech.align` (not stored; 0.1–0.2 s of margin on each side), and write the segments back. Separated vocals are steadier than the original mix.
In the result, `edges` near 0 or an absurdly long phoneme (e.g. a 0.8 s 「ン」) usually mean the window is off or overlaps someone else's line.

## Mapping external times back to the source

WAV export results carry `mapping` (file seconds → source seconds, a polyline): interpolate a time t from an external tool over it to get the source time.
Scripts run with `otto run` can also use the app's implementation: `from ottosmasher.domain.mapping import Mapping; Mapping.of(m).to_source(t)`.
Writing segment boundaries back: `segments.get` for the version → `edits.apply` (entity `segment`, fields `start` / `end`).

## Editing many lines

Put the `start` / `end` updates of many `segment`s into the `ops` of one `edits.apply`: one commit, one undo. To remove unwanted segments: fields `{"deleted": true}`.
Segments whose text or boundaries changed lose their old analysis; with the setting `analysis.auto_rerun_segments` (off by default) the app re-analyses them in the background, otherwise submit it yourself.

## Picking lines

Do not read thousands of lines into context: prefilter candidates locally by keywords or rules, then judge each candidate with its context.
Keywords mis-hit (in Kemono Friends 「ボス」 is a character, 「プレーリー」 an animal). List the doubtful ones for the owner.

## Finding the OP / ED without subtitles

Every episode of a work uses the same OP / ED song: cut the first and last minutes of several episodes and compare them; the longest nearly identical stretch is the OP (or ED); then `oped.add`.
Report episodes that do not match (different version, no OP) instead of forcing a mark. Tried on Yuru Yuri on 2026-10-24: start within 0.1 s, end about 6 s late.

## When analysis results look wrong

Find the cause first: typos in the subtitles, the wrong vocal track (music in the original mix), segment boundaries off; fix it and analyse again. When unsure, export the audio and listen or look at its spectrogram.

## When you cannot hear

audio-mcp (connected by the owner with `otto setup audio`): `audio_view` (spectrogram / waveform images), `audio_analyze` (loudness, peaks, onsets, pitch etc.),
`audio_transcribe` (Whisper turbo with word times and uncertain words; only via MCP). CPU only, so split long audio with `start` / `end`.
It is fine for a rough look at pitch; use `f0.track` when results must match the app's pitch search.

## Grouping lines by speaker (experimental)

Labelling who says each line. The app does not do this: you compute voiceprints with the bundled script in your own environment, do the grouping and
decisions yourself, and write the result back to the segments' `speakers`.
The practice and numbers below come from one show only (2026-10-30, Bocchi the Rock! full season of 12 episodes, Netflix Japanese CC subtitles,
vocals separated with HyperACE v2); recalibrate for another show.
The owner usually cares only about the named main characters: minor characters may all stay pending, and two voice styles of one character may stay two groups.

**Check up the subtitles first** (text only, seconds). Only one thing is certain: a speaker change always starts a new line (one text line = one person). Other labelling habits depend on the source:
- Both lines of a cue labelled = a change; only the first labelled = most likely the same person; only the second labelled, or two consecutive cues with the same name,
  vary a lot between sources (in the subtitles tried, consecutive labelled cues named the same person 3% to 47% of the time; cues labelled only on the second line ranged from none to over a thousand).
  Count these first, then decide how far to trust the labels.
- Fansub subtitles usually have no labels; CC subtitles label only when the speaker is not obvious, so labelled lines tend to be the harder ones.
- The app merges the lines of one cue into one segment; `subtitles.parse` gives the original text in `raw` — take the labels from it yourself
  (a parenthesis alone on a line labels the next line; reading parentheses are not names; 人, たち, 一同 and the like are several people).

**Material**
- Use separated vocals, not the original mix. The vocal track: `assets.tracks`; export: `exports.wav` (its `mapping` maps file seconds to source seconds).
- Split two-line cues first: `speech.align` with `lines` instead of `text` aligns both lines at once and returns each line's span; window = cue time ± 0.2 s.
  In the trial, for real two-speaker cues both halves were split correctly 63% of the time with alignment versus 11–12% with diarization segmenters
  such as pyannote and Nemotron — they cannot tell anime female voices apart.
- Voiceprints: save the script with `otto guide speaker_embed.py > <your temp dir>/speaker_embed.py`, then `uv run speaker_embed.py vocals ranges.json out-prefix`
  (needs uv and ffmpeg; the first run downloads PyTorch and the model, a few hundred MB; usage and easy-to-miss details are at the top of the script). About 9000 ranges for 12 episodes take two to three minutes on CPU.
  Model anime_speaker_embedding (char): 87% cross-episode identification in the trial, versus 80% for ReDimNet2+ and 72% for WeSpeaker ResNet293.
- Low similarities are normal (same person around 0.3–0.4 on average, different people around 0.2): compare relatively, do not apply a fixed threshold like 0.7.

**With labels**: use the labels directly as voice samples.
- Main characters = the few people with the most labelled lines over the season (≥ 40 lines in the trial, 8 people); other named single speakers together form "other"; multi-person labels and singing are not samples.
- For each line (the two halves of a split cue count as two lines): per class, average the similarity of the 5 most similar samples; assign the top main character only if it beats the runner-up by a margin, otherwise leave it pending.
- Do not borrow the margin from another show: split the samples into a few folds, predict each fold from the rest, and pick the lowest margin that reaches the target precision — that is the show's own calibration.
- Trial (hide one fifth of the labels and predict them, 5 rounds): precision 95%, recall 73%; lines under 1 s 49%, 1–2 s 77%, 2 s and longer 85%. At 97% precision, recall 66%.
  Logistic regression and one average voiceprint per character did worse; a bonus for "this character is labelled nearby" did not help.
- With few labels: with only about 240 labelled lines recall was 53%; adding very confident results (calibrated to 98%) as samples and running again raised it to 61%. With enough samples this round adds almost nothing.

**Without labels**
1. Split a two-line cue when its halves' voiceprints differ (the middle of the bimodal similarity distribution, 0.36 in the trial) and forbid the halves from going to the same person; also forbid lines that overlap in time.
2. Lines of 1.5 s and longer take part in grouping: first chain neighbours (gap ≤ 1 s) that are very similar (≥ 0.45), then cluster the whole season with constrained average-linkage hierarchical clustering.
3. Take the top 20 groups by total duration, export a few representative lines of each for the owner to listen to and name; a character may have several voice groups, keep them separate; unnamed ones count as "other". In the trial 20 groups were enough; more did not raise recall.
4. Per line: assign to the most similar main-character voice group only if the similarity is high enough and beats other characters and "other" groups by a margin; relax the margin by 0.05 for characters already confirmed within 60 s;
   recompute the groups from the long lines assigned to them and decide once more. Use as "other" only groups the owner confirmed and groups clearly unlike every main character — unnamed small groups often hold fragments of main characters, and using them as negatives halved recall.
5. Trial (thresholds picked on episodes 1–6, scored on 7–12): precision 94%, recall 65%, lines under 1 s 36%. Even the ideal ceiling, using all labels as voice samples, is only about 63%: the limit is the voiceprint itself (short lines, similar voices), not the grouping.

**Writing back**: set the segments' `speakers` with `edits.apply` (entity `segment`, field `speakers`; it is recorded as a speaker edit automatically and `segments.regenerateSpeakers` skips it).
- Do not overwrite segments the subtitles already label; list predictions that contradict a label for the owner.
- Two people in one cue: either write both names on the segment, or `segments.split` between the two lines and write one name on each (the new segments are protected and the old analysis is retired). Follow the owner's playbook; if it says nothing, ask.
- Leave pending lines unwritten (if one line of a cue is pending, write nothing for that cue, so half a cue is not taken for the whole) and report how many there are and in which episodes. Mistakes concentrate between similar-sounding main characters (in the trial Nijika ↔ Ryo, Hitori ↔ Nijika / Kita); spot-check those first.

## A complete example (outline)

"Make every line about games in these episodes a speech sample tagged `topic:game`, search them for a rhythm, export the hits":
read the playbook → register → separate (whole episodes, wait in the background) → clean and import subtitles → script prefilter + judge each line → `samples.plan` / `samples.createPlanned` → `speech.submit`
→ `samples.batchEdit` to tag → `search.speech` → `hits.export` → report what you created, what you were unsure about, where the files are; to undo, `edits.undoSession`.

## External tools used before (production task of 2026-10-26, removed afterwards)

Multilingual sentence embeddings (MiniLM, ONNX) for matching Chinese and Japanese subtitle lines; mlx-whisper (small, large-v3-turbo) for local transcription of doubtful passages; Matplotlib for waveform / pitch / spectrum plots; Mido for MIDI;
RAR / UnRAR for subtitle archives. Clean up tools and models when done, and list what you removed.

## Pitfalls met

- Keeping one connection open through long external computations can let events pile up; short connections (one `otto call` each) are steadier.
- Separating 65 whole episodes once filled the disk with intermediate files (fixed: deleted after success); check free space before big batches and submit in batches.
- Do not pile working files in the workspace root; use your own temporary folder and list what you left behind.
