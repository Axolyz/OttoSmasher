# Practices and experience (not rules)

Practices and pitfalls collected while doing real tasks with `otto`. **They are not rules and may be out of date**; operational facts come from the regular guide,
parameters from `otto describe`, and the owner's playbook (`otto guide playbook`) wins over this page. When unsure, use your own judgement.

## Separation strategy: whole episodes or only what you need

- **Whole episodes**: done once, and the vocal then serves subtitle cleaning, retiming, samples and analysis with little rework; costs ten to several tens of minutes per episode. The owner can also select all and run it in the app.
- **Only the parts you need** (`separation.submit` with `start` / `end`): fast, good for a few lines or a first look; partial stems cannot be the default track, so pass their `assetId` where you use them.
- Measured 2026-10-30 (HyperACE v2, Apple silicon): each separation job takes about 8 s to start, then about 0.35 s per second of audio — 8.5 s for a 5 s part, 29 s for 60 s, about 9 minutes for a 24-minute episode.
  So with one job per line, a few dozen lines take about as long as the whole episode.
- Cleaning subtitles and retiming need a clear voice, so usually **separate first, then clean**. For whole episodes, submit all of them at once, then wait as in ground rule 5 of the overview — never idle-poll.

## Cleaning subtitles

Goal: one UTF-8 `.srt` per episode with **exactly the same name** as the video, each cue holding only the words actually spoken; put the speaker in a leading bracket when you can tell, otherwise leave it out (fansub subtitles usually have no speakers; that is normal).
The original `.ass` can stay (with the same name the app prefers `.srt`). Before changing the owner's files, keep a copy with a `backup_` prefix.

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

Checking the result: `subtitles.parse {"path"}`, or (for registered sources) `sources.rescan --wait` → `subtitles.preview {"sourceId"}`;
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

## A complete example (outline)

"Make every line about games in these episodes a speech sample tagged `topic:game`, search them for a rhythm, export the hits":
read the playbook → register → separate (whole episodes, wait in the background) → clean and import subtitles → script prefilter + judge each line → `samples.plan` / `samples.createPlanned` → `speech.submit`
→ `samples.batchEdit` to tag → `search.speech` → `hits.export` → report what you created, what you were unsure about, where the files are; to undo, `edits.undoSession`.

## External tools used before (production task of 2026-10-26, removed afterwards)

Multilingual sentence embeddings (MiniLM, ONNX) for matching Chinese and Japanese subtitle lines; mlx-whisper (small, large-v3-turbo) for local transcription of doubtful passages; Matplotlib for waveform / pitch / spectrum plots; Mido for MIDI;
RAR / UnRAR for subtitle archives. Clean up tools and models when done, and list what you removed.

## Pitfalls met

- A pitch measurement job can be `succeeded` with an empty result and the errors in `f0Errors`; check the result, not only the status.
- Keeping one connection open through long external computations can let events pile up; short connections (one `otto call` each) are steadier.
- Separating 65 whole episodes once filled the disk with intermediate files (fixed: deleted after success); check free space before big batches and submit in batches.
- Do not pile working files in the workspace root; use your own temporary folder and list what you left behind.
