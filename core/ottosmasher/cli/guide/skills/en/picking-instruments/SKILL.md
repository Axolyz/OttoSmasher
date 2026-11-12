---
name: picking-instruments
description: "Pick drum, lead, bass, chord and other instrument samples from OttoSmasher material; compare timbres against MIDI, reference audio or musical roles, and prepare candidates and auditions. Use for single sounds and timbre matching; use picking-lines for semantic rap selection, and app commands directly for named exports."
---

# Pick instrument samples

Read `otto guide workflow` and carry forward the agreed scope, precision and preferences. Connect what each musical part needs with sounds available in the material: locate the original, cut a reusable portion, then compare it in its intended register and rhythm. Voices, effects and sounds from songs can all become instruments; the task determines the choice.

## User options and precision

Look for answers in the project, reference and existing conventions first. Ask only about unresolved choices that affect selection. These are common options, not a questionnaire to run in full.

| Option | How to decide |
|---|---|
| Source scope | Works, episodes and characters; whether voices, effects and songs are eligible. Keep the sources the user has chosen |
| Matching target | With MIDI, match parts, registers and durations; with reference audio, compare timbre and function; a musical role alone is enough to start with representative sounds |
| Timbre direction | Resemblance to the reference instrument, recognizability of the source character, or a balance. Without a preference, balance both and retain distinct alternatives |
| Processing | Follow the project. Otherwise start with varispeed and short attack/release fades, trying loops when sustain is insufficient. Choose duration-preserving pitch shift, flattening or distortion as needed |
| Candidates and delivery | A standard pass can start with about three distinct candidates per role, original cuts, reasons and matching auditions; adjust the count. Library entries, exports and an audition page follow the requested deliverable |

If precision is unspecified and no applicable preference exists, ask once and explain the difference:

| Level | What to do |
|---|---|
| Quick | Find a usable first selection for the selected roles from a small representative source set, and check basic cut boundaries and register; state the actual search scope |
| Standard | Broaden screening within the agreed sources, compare scenes and timbres, check selected candidates' single-sound boundaries and target register, and supply matching auditions with reasons |
| Fine | Repeat screening, reviewing context, boundaries, transposition, sustain and layering for every agreed candidate; revise the selection after comparisons |

## Understand the musical parts

With MIDI, read actual notes and controllers. Summarize the selected tracks' ranges, common and extreme durations, density, polyphony and bends; track names and programs are clues. Separate percussion roles by drum voice: one drum track may need kicks, snares and cymbals. Without MIDI, infer these needs from the reference passage or user description.

Read `references/matching.md` when choosing sounds by role or interpreting measurements. Try a small set of contrasting sounds before expanding to other parts. One sound can serve several tracks; compare whether the parts remain distinguishable when played together.

## Find and refine candidates

Reuse existing samples, stems and analyses. Sustained vowels, nasals and shouts, or impacts, bursts and friction from effects, can be starting points. Subtitles locate characters and context; the audio determines cut boundaries. If candidates cluster in a few scenes, explore other scenes within scope.

Inspect waveform, spectrum and pitch in the original utterance or effect context. A stable-pitch window can span several phones; use alignment when helpful to narrow it to one vowel or nasal, then measure again. Preserve a drum sound's actual attack and useful tail. Update measures and auditions when a candidate's boundaries change.

`samples.metrics` reads cached single-sound measures, `measure.f0` reads pitch frames, and `spectrum.get` shows the spectrum; consult `otto describe` for parameters. Before creating samples, analyze asset ranges or exported cuts and register the selected ones as agreed. Use measures to narrow the set and performance in the target part to choose; calibrate thresholds to the current material.

## Check search coverage

Before searching by pitch, call `search.coverage` on the same scope and follow `otto guide search` to fill gaps in fundamental frequency (F0). For timbre or transient filters, call `metrics.status` on the scope before applying metric thresholds and check each metric you plan to use. Fill gaps with `metrics.prepare` as needed, then check again. F0 and acoustic measures can be prepared independently. Use phoneme alignment for voice candidates whose cut points need to follow phoneme boundaries.

For a quick first pass, compare the measured subset. If the task calls for all matches, an answer about whether a match exists, or the best sound across the scope, first fill the measurements you can. Report how many items were checked out of the total in scope and what data is still missing.

## Compare and deliver

Compare original cuts, then audition each candidate with the same notes, chords or drum pattern. Match levels when loudness differences obscure the comparison, and state processing used for the audition. Describe what you heard, or explain when a conclusion comes from spectral or other analysis.

Read `references/auditions.md` for MIDI auditions, naming or a comparison page. It includes the optional `scripts/build_audition.py` helper to organize rendered audio into a page; custom designs also work.

Keep the original sound, source and selection reason so candidates can be located and reused. Save the selected items in the requested form, check that each selected part has candidates or an explicit gap, and report recommendations, differences and remaining processing needs.
