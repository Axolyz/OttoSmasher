---
name: grouping-speakers
description: "Labels who says each OttoSmasher line by comparing voiceprints from the bundled script, with or without existing speaker labels. Use when segments lack speakers and the user wants lines sorted by character. Experimental."
---

# Grouping lines by speaker (experimental)

The app does not do this. Compute voiceprints with the script in `scripts/`, do the grouping and decisions yourself, and write the result to the segments' `speakers`.
These methods and numbers come from one show, so recalibrate for another. Results are in `references/experiments.md`.
The user usually cares only about named main characters. Minor characters may stay pending, and two voice styles of one character may stay two groups.

## Prepare

1. Audit the labels first (skill `cleaning-subtitles`). A segment's `speakers` hold only what could be read for certain. Segments with `speakersWithheld` true still have labels in `raw`.
2. Read label samples from `raw` or the subtitle file, and interpret them by the audit. A bracket alone on a line may label the next line, reading brackets are not names, and 人, たち, 一同 and the like mean several people.
3. Use separated vocals. Find the track with `assets.tracks` and export it with `exports.wav`; its `mapping` converts file seconds to source seconds.
4. Split two-line cues with `speech.align` and `lines`, using the cue time ± 0.2 s as the window. Diarization models could not tell anime female voices apart in the trial.
5. Compute voiceprints: `uv run scripts/speaker_embed.py vocals ranges.json out-prefix`. It needs uv and ffmpeg, and the first run downloads PyTorch and the model, a few hundred MB. Usage is at the top of the script.

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

## Write back

Set `speakers` with `edits.apply` (entity `segment`, field `speakers`). It is recorded as a speaker edit, and `segments.regenerateSpeakers` skips it.

- Do not overwrite segments the subtitles already label. List predictions that contradict a label for the user.
- For two people in one cue, write both names, or use `segments.split` and write one on each. Follow the playbook; if it says nothing, ask.
- Leave pending lines unwritten. If one line of a cue is pending, write nothing for that cue. Report how many are pending and in which episodes.
- Spot-check similar-sounding main characters first, where mistakes concentrate.
