---
name: labeling-speakers
description: "Labels who says each subtitle line in anime by comparing voiceprints, with or without existing speaker labels in the subtitles. Use when lines need speaker or character labels across many lines. Experimental, tuned on one anime."
---

# Labeling lines by speaker (experimental)

Compute voiceprints with the script in `scripts/`, then do the grouping and decisions yourself. These methods and numbers come from one show, so recalibrate for another. Results are in `references/experiments.md`.
Users usually care only about named main characters. Minor characters may stay pending, and two voice styles of one character may stay two groups.

## Audit the labels first

Closed captions label speakers in different ways, so measure this for each source before you trust it. The only certainty is that a speaker change starts a new text line.

Count these per source:

- both lines of a cue labelled (a change of speaker)
- first line only (often the same person)
- second line only
- a label alone on its own line
- two consecutive cues with the same label

Then listen to a sample from each pattern in each source. In the subtitles tried so far, consecutive labelled cues named the same person 3% to 47% of the time, and cues labelled only on the second line ranged from none to over a thousand.

Fansub subtitles usually have no labels. Closed captions label a line only when the speaker is not obvious, so labelled lines tend to be the harder ones. Reading brackets are not names, and 人, たち, 一同 and the like mean several people.

## Prepare

1. Use separated vocals, not the original mix.
2. Split two-line cues by aligning the lines one after another with a forced aligner, using the cue time ± 0.2 s as the window. Cut at the middle of the gap. If one line aligns to under 0.1 s, it was probably not found; leave that cue unsplit. Diarization models could not tell anime female voices apart in the trial.
3. Compute voiceprints: `uv run scripts/speaker_embed.py vocals ranges.json out-prefix`. It needs uv and ffmpeg, and the first run downloads PyTorch and the model, a few hundred MB. Usage is at the top of the script.

Low similarities are normal: same person about 0.3–0.4, different people about 0.2. Compare relatively, and do not apply a fixed threshold such as 0.7.

## With labels

Use labels directly as voice samples.

1. Main characters are the few people with the most labelled lines over the season (at least 40 in the trial). Other named single speakers form "other". Multi-person labels and singing are not samples.
2. For each line, average per class the similarity of the 5 most similar samples. The two halves of a split cue count as two lines.
3. Assign the top main character only if it beats the runner-up by a margin. Otherwise leave the line pending.
4. Calibrate the margin on this show: split the samples into folds, predict each fold from the rest, and pick the lowest margin that reaches the target precision.
5. With few labels, add very confident results (calibrated to 98%) as samples and run once more.

## Without labels

1. Split a two-line cue when its halves' voiceprints differ (0.36 in the trial, the middle of the two-peaked distribution), and forbid the halves from going to the same person. Also forbid lines that overlap in time.
2. Group lines of at least 1.5 s. First chain neighbours with a gap of at most 1 s and similarity of at least 0.45, then cluster the whole season with constrained average-linkage hierarchical clustering.
3. Take the top 20 groups by total duration and export a few representative lines of each for the user to name. A character may have several groups. Unnamed groups count as "other".
4. For each line, assign the most similar main-character group only if the similarity is high enough and beats other characters and "other" by a margin. Relax the margin by 0.05 for characters already confirmed within 60 s.
5. Recompute the groups from the long lines assigned to them, then decide once more.

Two rules matter here:

- Compare against each group's **average voiceprint**, because grouped samples contain other people's lines and the most similar few often land on those. Labelled samples are clean, which is why the other method works there.
- Use as "other" only groups the user confirmed and groups clearly unlike every main character. Unnamed small groups often hold fragments of main characters.

## Write the result

Write speakers in the form the user wants, for example a leading `（name）` on each line. Keep a backup of the subtitle file.

- Do not overwrite lines the subtitles already label. List predictions that contradict a label for the user.
- Leave pending lines unlabelled. If one line of a cue is pending, write nothing for that cue. Report how many are pending and in which episodes.
- Spot-check similar-sounding main characters first, where mistakes concentrate.
