# Retiming

Check release differences before refining individual boundaries. Use dialogue to locate overall offsets and edit points. OP/ED lyric marks can help find the area; check the full music start and end against the sound.

## Refine a line

1. Take the full sentence and neighbouring dialogue. View the waveform/energy curve and check contents against captions and, where useful, a transcript. ASR word times help with rough location.
2. Establish whether edge sounds belong to this line or the next, including continuous speech with no silent gap. Once the window closely holds the utterance, speech.align and lines can refine it, with voiceprints helping identify turns where useful.
3. Record the reason for confirmed changes. For existing segments, write small batches with edits.apply, then check coverage, order and overlaps together.

## Finding cases to review

Sound on both sides of an edge, an abruptly cut tail, unclear neighbouring content, edges near zero and unusually long phones are useful signals. At fine precision, review all such cases and sample other scenes; see verification.md.

## Judging results

A/B transcripts with more or less context can help check complete words. ASR sometimes misses or adds words, so compare the text with the actual curve. Alignment is good at refining a given window, which makes locating the utterance first essential. Adjust to the real speech: use a gap when one exists, and keep overlaps where people actually speak together.
