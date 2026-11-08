# Timbre selection and flattening

## Decide the output shape

For an instrument source, establish monophonic note/vowel versus a whole spoken phrase, target register, attack/sustain needs and candidate count per track. A flattened sentence still contains consonants and several articulations. Flattening changes pitch; it neither cuts out one vowel nor normalizes loudness. For a single note, locate a suitable vowel, cut the usable range and verify its articulation before flattening. OP/ED audio is eligible through explicit asset selections even when line-sample planning skips those ranges.

Use `samples.metrics {"ids"}` to compare cached metrics (including rmsDb, pitchSpread and voicedDuration); missing/stale is not zero. `metrics.prepare` explicitly queues missing work. Compare representative candidates with audio tools; pitch and spectral numbers alone do not establish timbre suitability. Level-match temporary listening copies when useful, preserving original products. Start with a few end-to-end examples before creating a large set.

## Open, preview and submit

1. `flatten.open {"assetId", "start", "end", "entry": "single", "sampleId"}` freezes asset-local selection and returns token, defaults, alignment and alignmentIssue. Times in alignment, inner and processing intervals are input-local seconds (selection start = 0).
2. `alignmentIssue` explains missing segments, unavailable analysis, incomplete windows, conflicts or a track lacking vocal role. With a sample, inspect `speech.sample`, then `speech.preview` and `speech.submit` if appropriate. Do not replace a requested vowel treatment with whole just to bypass missing evidence.
3. `flatten.preview {"token", "options", "name", "sampleId"}` validates current input and returns cached estimate, outputDuration and maximum new-object counts. No model or job runs. Unknown target remains in-job; insufficient evidence remains insufficient. Preview creates nothing; it cannot guarantee sound quality.
4. `flatten.submit` takes the same parameters and starts a job. `flatten.results {"jobId"}` returns per-item outcomes; `flatten.rerunFailed` only retries failed items with their original options.

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

Read `otto describe flatten.open` and settings.list for entry-specific defaults (detail/single/batch); selecting another range does not change target automatically. `flatten.submitBatch {"ids", "options"}` retains shared auto/edge settings and cannot use manual or inner. `flatten.submitMany {"items": [{"id": "sampleId", "options": {"range": "whole", "target": "manual", "manual": "C4"}}]}` accepts per-item options (maximum 500), one job, with independent failures; rerunFailed retains each failed item's options. No global settings need changing.

A successful product registers a flattened track and one pitched sample, with a pitch tag. Identical audio may be reused, but each explicit save creates a sample. Creation cannot be undone; use createdBySession in samples.ids/list for inventory, then existing deletion previews and user confirmation. Preview small experiments first. Full return schemas are available through otto describe.
