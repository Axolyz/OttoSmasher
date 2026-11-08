# Retiming lines

The aligner fits the whole line into the window it receives and does not look for where the line is. Numbers are in `otto guide primitives`. If a fansub's rough timing exists, start from it; fine-tuning it has worked better than the automatic tools tried so far.

## Retime a line

1. Roughly locate the speech with a transcript with word times (such as audio-mcp's `audio_transcribe`) or loudness on/offsets, then check boundaries against the full sentence and neighbouring dialogue. Times from an exported file map back through its `mapping` (`otto guide export`).
2. Use the first and last phoneme times from `speech.align` to help refine the window; it stores nothing. Start with 0.1–0.2 s of margin on each side and use separated vocals, which are steadier than the original mix, then compare the final boundaries with the actual speech.
3. Write the segments back with `edits.apply` (see `otto describe edits.apply`). Put many updates in one batch, so they make one undo.

## Signs the window is wrong

In the alignment result, `edges` near 0 or an absurdly long phoneme, such as a 0.8 s 「ン」, usually mean the window is off or overlaps another line.

## Check both ends

Check starts and ends, including adjacent speech with no silent gap. Use the sound to distinguish sequential turns from simultaneous overlap. At fine precision, review every suspicious case and sample other scenes; see `references/verification.md`.
