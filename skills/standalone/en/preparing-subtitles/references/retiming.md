# Retiming subtitles

Separated vocals are steadier than the original mix.

## How forced alignment behaves

The aligner fits the whole line into the window it receives. It does not look for where the line is, and it does not report "no match". The window must hug the actual speech, with 0.1–0.2 s of margin on each side.

Tested with 60 Japanese lines using pydomino: widening the window to 0.5 s on each side moved the start or end by more than 0.3 s for about half of them, and shifting the time by 0.5 s or more almost never aligned well.

A successful alignment does not prove its window was right, so check windows independently.

## Retime a line

1. Get boundaries within 0.1–0.2 s from a transcript with word times, or from loudness on/offsets. If a fansub's rough timing exists, start from it; fine-tuning it has worked better than the automatic tools tried so far.
2. Refine with the first and last phoneme times from the aligner.
3. Write the new times back.

A very small gap between the window's ends and the first or last phoneme, or an absurdly long phoneme such as a 0.8 s 「ン」, usually means the window is off or overlaps another line.

If you measure times on an extracted clip, convert them back to the original video's time before writing them.

## Subtitles from another release

Subtitles from a TV or streaming release on a BD video may be off by a fixed amount, drift from where a commercial break used to be, or miss whole passages.

1. Spot-check lines at the start, middle and end against the voice.
2. Apply one shift for an overall offset, or shift from the exact cue where the offset starts.
3. Locate an edit point at a specific line. The nearest subtitle is not precise enough when a release has extra dialogue.
4. Keep a written record of dialogue that exists in only one release. Do not force alignment onto different words.

Boundary screening must inspect both starts and ends, even with no silence gap. Use the actual curve, whole-sentence contents and neighbouring speech together. ASR word times, energy runs and forced alignment are clues, not ground truth. Avoid fixed padding or automatic midpoints.
