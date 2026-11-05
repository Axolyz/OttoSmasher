# Transcribing without subtitles

This method is still being refined, and the tools are not settled. Use the VAD and ASR tools in your environment, and say which ones you used in your report.

## Why this way

These are the author's conclusions after trying several methods, without a quantified comparison, and on only some kinds of material:

- **ASR alone:** misrecognition is now uncommon, but the timing drifts slightly, and later speech analysis depends on that timing.
- **Forced alignment in a time window:** it is accurate when the window holds exactly this line. With 0.5 s extra or missing, results get poor.
- **ASR, then forced alignment:** this fixes some drift, but sentence breaks are poor. A sentence may be split across two cues, and it needs manual polishing.

So VAD secures the timing, sentence breaks go to the agent, and manual review goes to the uncertain parts.

## Steps

1. **Prepare the sound.** Use separated vocals; material that is already dry can be used as is.
2. **Run low-threshold VAD.** Accept many small pieces in exchange for accurate starts and ends.
3. **Run ASR per piece.** Each piece's timing comes from the VAD boundaries.
4. **Merge into sentences.** Join pieces into complete sentences, one person's continuous speech per cue. Merging changes only boundaries and grouping; do not rewrite the recognized words along the way.
5. **Flag low-confidence parts.** For example, words the tool marks as uncertain, very short pieces, places where the meaning does not connect, and places where people may overlap. List them for the user with times and reasons. The user reviews only these.
6. **Write back.** Write a UTF-8 `.srt` with the same name as the video, then continue with `references/cleaning.md` if the text needs more cleaning.

## When not to use this

- **Subtitles exist:** fine-tuning a fansub's rough timing works better than this method. A mismatch usually comes from TV and BD differences; see `references/retiming.md`.
- **Lyric timing:** lyrics are timed fairly accurately, clearly pronounced, and only need word level, which suits forced alignment well. This process is not needed.
