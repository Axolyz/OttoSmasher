# Naming and audition delivery

## Keep source relationships

Give each candidate a stable ID and retain its original cut, eligible parts, source asset and interval, source-time mapping, root and tuning correction, measures and recommendation reason. Choose useful fields for the task; JSON or a table works, without packing everything into filenames.

Follow existing naming conventions. Otherwise, a library name can retain the original sound and line, such as `aa (original line)`, with role tags linking musical parts; an exported file could be `C01_aa_C5.wav`. A short name that distinguishes the candidate is sufficient. Use `pitched` for tonal single sounds and `unpitched` for non-tonal ones. Record drum roles and sampler mappings separately so a transient is not mistaken for a melodic root.

Keep the mapping returned by `exports.wav` and use the corresponding file's mapping for time conversion. Short context clips help users identify the selected sound. Include the sample ID when one exists, so it can be found in the library.

## Render matching auditions

Use the same notes or drum pattern, durations and velocities for each candidate in a role. Read actual MIDI tempo events: one track can change channels or programs, and one channel can span tracks. Interpret musical parts and drum voices; track names, channel 10 and program numbers are clues to check against actual events.

Retain relevant polyphony, pedal and pitch bends, reading the bend range. If the file does not declare a range, state the rendering assumption. Choose a short representative active passage and add extreme notes or long sustains that reveal problems. Compute looping needs against target notes; a six-second audition does not establish whole-track coverage.

When matching levels, check peak headroom. For short sounds, consider RMS, peaks and listening together. Record normalization, envelope, looping, pitch method and effects. Keep original cuts intact and save processed auditions separately. When a candidate needs substantial processing, let users compare the original with the result.

## Comparison page

With several parts and alternatives, grouping candidates side by side by musical part is often easier to review than a long file list. Each card can show one meaningful difference, useful measures and the target-passage audition, with the original and context available on expansion. Let users stop playback, filter parts and open source files. Adapt type, layout and explanations to the task.

The optional `scripts/build_audition.py` builds local HTML from existing cuts and renders. It presents audio without calculating measures or rendering MIDI; custom pages also work. It uses only Python's standard library, resolves audio paths relative to the JSON file, and writes the page beside it. The page references the existing files; share the audio along with the page.

```sh
python scripts/build_audition.py review.json
```

Minimal input; `label`, `note` and `facts` may use the user's language. Group and candidate counts are flexible:

```json
{
  "title": "Instrument candidates",
  "note": "Same MIDI passage; level matched. Looped sustains are indicated.",
  "groups": [{
    "name": "Lead",
    "note": "MIDI 60-84; short notes",
    "candidates": [{
      "id": "C01",
      "label": "a / bright",
      "note": "Clear harmonics; the longest note needs a loop.",
      "facts": {"root MIDI": 72, "duration ms": 240},
      "audio": [
        {"label": "MIDI preview", "path": "previews/lead_C01.wav"},
        {"label": "Original", "path": "raw/C01.wav"},
        {"label": "Context", "path": "context/C01.wav"}
      ]
    }]
  }]
}
```

`facts`, all `note` fields and candidate `label` are optional. `audio` can contain only an original cut for a quick first pass. Relative paths and shared candidates can be reused. The layout stacks on narrow screens. Input order determines recommendation order; the script does not score candidates.

## Check the delivery

Reconcile selected parts with the deliverable. Check that audio decodes, is nonempty, corresponds to the source interval, and opens through the audition links. Root notes, processing descriptions and loop requirements on the page must match the final audio.

Report actual screening coverage, recommendations and alternatives by role, library entries or exports, and outstanding checks. Distinguish listening conclusions from measurement-based inferences so users can audition and choose directly.
