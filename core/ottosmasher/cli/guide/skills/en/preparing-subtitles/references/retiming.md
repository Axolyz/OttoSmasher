# Retiming

The aligner fits text into its supplied window without checking whether that sentence is there. Start from existing rough captions, verify version differences in real audio, and establish global or piecewise offsets. Lyric markers do not establish the musical start of OP/ED.

## Refine one boundary

1. Prepare the full sentence and adjacent speech, inspect the actual waveform/energy curve, and use original captions plus contextual transcription when needed to check contents. ASR word times are only location clues.
2. Establish whether edge audio belongs to this sentence or its neighbour, including continuous speech without a gap. Use speech.align, lines or voiceprints when helpful. Phonemes can refine an already suitable window, but their edges are not automatic ground truth.
3. Write only confirmed changes and retain evidence/reasons. For existing segments use edits.apply, preferring small versioned batches, then reconcile coverage, order and actual overlap.

## Suspicious signals

Energy before/after an edge, abrupt cuts, unclear neighbouring contents, near-zero edges or absurd phoneme lengths flag cases. Screening must not modify boundaries or select only cases with silence gaps. Fine reviews every suspicious item, sampling normal scenes; see verification.md.

## Choosing methods

A/B windows with more/less context can help establish content completeness. ASR omission, hallucination and changed context alter recognition, so output differences alone are not conclusions. Do not pad every sentence or midpoint away every overlap, and do not assume professional CC is exact. Simultaneous speech may overlap; sequential speech should not absorb the neighbouring sentence.
