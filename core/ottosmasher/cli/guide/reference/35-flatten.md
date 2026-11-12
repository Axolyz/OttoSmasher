# Timbre selection and flattening

## Choose a useful piece of sound

For an instrument sample to play from a keyboard, usually select a single vocal unit or a suitable vowel segment from speech before flattening. Keep the attack and sustain that suit the intended timbre, choosing boundaries from the actual sound. A whole phrase can help locate candidates; select the playable part for the finished sample. Song material in OP/ED can be sampled through an explicit asset selection.

Flattening changes pitch while retaining words and duration: a whole phrase at one pitch still contains changing syllables, consonants and pauses. Flatten the whole phrase when the user wants that phrase effect. For instrument one-shots, first check that the selection contains the intended vocal unit, then consider register and candidate count per track.

`samples.metrics {"ids"}` reads cached measures such as rmsDb, pitchSpread and voicedDuration; `metrics.prepare` computes missing ones. Compare representative candidates with audio tools. Temporary level-matched copies help when loudness differences get in the way. Try a few finished samples before processing a large set.

Both `flatten.submit` and `flatten.submitBatch` accept `localTags` to tag new samples or `useCurrentProject: true` to use the desktop project at submission. Retrying failures keeps the original job’s tags.

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
