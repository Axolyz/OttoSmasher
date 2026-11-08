# Timbre selection and flattening

## Choose a useful piece of sound

For instrument material, first establish whether the user wants one note or vowel, or a whole phrase. Consider register, attack, sustain and candidate count per track. Flattening changes pitch and retains the words and duration. For one note, locate a suitable vowel and select its usable range first. Song material in OP/ED can be sampled through an explicit asset selection.

`samples.metrics {"ids"}` reads cached measures such as rmsDb, pitchSpread and voicedDuration; `metrics.prepare` computes missing ones. Compare representative candidates with audio tools. Temporary level-matched copies help when loudness differences get in the way. Try a few finished samples before processing a large set.

## Open, estimate and submit

1. `flatten.open {"assetId", "start", "end", "entry": "single", "sampleId"}` freezes an asset-local selection and returns token, defaults, alignment and alignmentIssue. Times in alignment, inner and processing intervals are input-local seconds, with the selection start at zero.
2. If alignment is unavailable, alignmentIssue gives the reason. With a sample, check speech.sample, then use speech.preview and speech.submit as needed to prepare phonemes for first or vowels processing.
3. `flatten.estimate {"token", "options", "sampleId"}` reads cached measurements and returns processing intervals and a target. in-job means the target will be determined during processing; insufficient carries the reason more evidence is needed.
4. `flatten.submit {"token", "options", "name", "sampleId"}` checks the frozen input and starts a job. Read per-item outcomes with `flatten.results {"jobId"}`; use `flatten.rerunFailed` for failed items.

## Options

| Option | Meaning |
|---|---|
| range whole | Change pitch over the full selection, retain duration |
| range vowels | Change vowel/N intervals; requires usable phonemes |
| range first | Change from the first vowel/N through the selection end; requires usable phonemes |
| range inner | Inner plateau and transition, input-local seconds |
| target auto | Determine each target from the processing range |
| target edge | Determine from the chosen left/right edge; insufficient evidence does not switch sides |
| target manual | Explicit A4, C#5, B♭3 or 445Hz; bare numbers are ambiguous and rejected |


Entry defaults for detail/single/batch come from flatten.open and settings.list. Range and target are separate choices. `flatten.submitBatch {"ids", "options"}` uses shared auto/edge options. For different manual targets or inner ranges, use `otto run` and call open / estimate / submit per selected item, keeping the job IDs for checking results.

Each save creates a pitched sample with a pitch tag and registers its flattened track; identical audio may be reused. Creation is outside edit undo. samples.ids/list with createdBySession helps inventory products for the existing deletion flow. Flattening preserves the input level; level normalization is a separate operation.
