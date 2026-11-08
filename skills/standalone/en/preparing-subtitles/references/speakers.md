# Labeling lines by speaker (experimental)

Compute voiceprints with the script in `scripts/`, then do the grouping and decisions yourself. These methods and numbers come from one show, so recalibrate for another. Results are in `references/experiments.md`. Paths are relative to the skill folder.
Users usually care only about named main characters. Minor characters may stay pending, and two voice styles of one character may stay two groups.

## Prepare

Audit the labels first (`references/cleaning.md`). Reading brackets are not names, and 人, たち, 一同 and the like mean several people.

1. Use separated vocals, not the original mix.
2. Split two-line cues by aligning the lines one after another with a forced aligner, using the cue time ± 0.2 s as the window. A gap midpoint is usable only after confirming a real silence. Missing/short alignment needs contextual review; split known sequential turns independently of uncertain identity. Diarization models could not tell anime female voices apart in the trial.
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
3. Take the top 20 groups by total duration and export a few representative lines of each for the user to name. A character may have several groups. Keep unnamed groups pending; a background "other" class is not an output identity.
4. For each line, assign the most similar main-character group only if the similarity is high enough and beats other characters and "other" by a margin. Relax the margin by 0.05 for characters already confirmed within 60 s.
5. Recompute the groups from the long lines assigned to them, then decide once more.

Two rules matter here:

- Compare against each group's **average voiceprint**, because grouped samples contain other people's lines and the most similar few often land on those. Labelled samples are clean, which is why the other method works there.
- Use as "other" only groups the user confirmed and groups clearly unlike every main character. Unnamed small groups often hold fragments of main characters.

## Write the result

Write speakers in the form the user wants, for example a leading `（name）` on each line. Keep a backup of the subtitle file.

- Do not overwrite lines the subtitles already label. List predictions that contradict a label for the user.
- Leave unknown identities unlabelled. Split a known sequential turn and preserve the known identity on its own turn. Report how many are pending and in which episodes.
- Spot-check similar-sounding main characters first, where mistakes concentrate.

Known sequential turns must be split even when a name is unknown. Keep known names on their turns; multiple names are for simultaneous speech. Background other is not an output identity. Calibrate on independent scenes, keep near-duplicates in one fold and report coverage/uncertainty; experiment numbers are not universal thresholds.
