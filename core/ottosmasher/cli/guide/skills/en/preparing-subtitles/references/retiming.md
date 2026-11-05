# Retiming lines

The aligner fits the whole line into the window it receives and does not look for where the line is. Numbers are in `otto guide primitives`. If a fansub's rough timing exists, start from it; fine-tuning it has worked better than the automatic tools tried so far.

## Retime a line

1. Get boundaries within 0.1–0.2 s from a transcript with word times (such as audio-mcp's `audio_transcribe`) or from loudness on/offsets. Times from an exported file map back through its `mapping` (`otto guide export`).
2. Refine with the first and last phoneme times from `speech.align`, which stores nothing. Leave 0.1–0.2 s of margin on each side and use separated vocals, which are steadier than the original mix.
3. Write the segments back with `edits.apply` (see `otto describe edits.apply`). Put many updates in one batch, so they make one undo.

## Signs the window is wrong

In the alignment result, `edges` near 0 or an absurdly long phoneme, such as a 0.8 s 「ン」, usually mean the window is off or overlaps another line.
