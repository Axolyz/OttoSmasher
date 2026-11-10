# Match sounds to musical roles

## Describe what the part needs

Turn the project into a few comparable features. For example, “high register, dense notes around 40 ms, with distinct attacks” and “four simultaneous notes held for half a second without harshness” point to different material. Reference audio can also guide brightness, weight, breathiness, roughness and source recognizability.

Use these as starting points, adapting them to the reference and user direction.

| Role | Starting material | What to compare |
|---|---|---|
| Lead | Clear vowels, shouts, harmonically rich effects | Presence in the target register, consistent articulation, recognizability through bends |
| Bass | Low vowels, nasals, low effects | Balance of fundamental and upper harmonics; whether downshifting leaves only sub energy, and whether an envelope should shape a plucked sound |
| Chords, pads | Longer, steady-pitch vowels or effects | Weight, harshness and beating in polyphony, usable sustain or loop length |
| Arp, chip | Short sounds with controllable edges and a distinct spectrum | Clarity at the densest rhythm, duration remaining after transposition to the highest notes |
| Kick | Low impacts, bursts, strikes | Relationship between attack and low tail, whether the tail needs pitch adjustment |
| Snare, clap | Broadband impacts, bursts, short noise | Transient, noise body and tail; separation from the kick |
| Cymbal, hi-hat, shaker | High-frequency friction, breath, metallic sounds | High-frequency texture, open/closed durations and repeated triggering |

A nasal may provide a strong bass foundation but lack the reference bass's upper detail. A clear shout may suggest brass yet dominate four-note chords. Layering is also possible; explain each layer's role. Use character expression and the original line's emotion as selection criteria when the user includes them in the task.

## Combine measurements

Compare a few real excerpts before choosing useful measures. Reuse existing analysis and measure more as needed; inspect scoped counts with `metrics.status` before batch preparation. `samples.metrics` accepts explicit sample IDs when reading caches.

- For tonal sounds, inspect fundamental frequency, pitch variation and voiced duration. High confidence only means the model favors a pitch; use harmonic spacing or another measurement to check suspected octave errors, stacked voices and background music.
- For brightness, compare centroid, rolloff and band energy, and inspect harmonic/noise distribution. Interpret values from different sample rates, window sizes and algorithms separately.
- For drums, inspect attack rise, crest factor, decay, band energy and noise content. Brief fundamentals or pitch sweeps may be useful timbral features; drums without a stable pitch need not receive a root note.
- Steady pitch alone is insufficient: vowel changes, breath, another voice or residual accompaniment can change a loop or chord. Check context and the spectrum.

Measures explain differences; one score cannot rank every musical role. Write screening code for the current register and material when helpful, retaining representative sounds for closer comparison.

## Evaluate transposition and duration together

With varispeed, transposing up by `s` semitones gives a playback ratio of `2 ** (s / 12)`, leaving approximately the original duration divided by that ratio. A 160 ms sound shifted up an octave lasts about 80 ms. Check actual notes rather than comparing source length only with the longest note.

Estimate the root from a stable region and declare the note convention, such as C4 = MIDI 60. A measured pitch of 71.8 needs about +20 cents of correction when assigned root 72; an audition renderer can instead use the measured value directly for its playback ratio.

Useful test points include register extremes, longest notes, densest runs and stacked chords. Loops can extend sustain; duration-preserving pitch shift and flattening can also change a sound's suitability. Compare the processed results. Trying another original often helps when transposition weakens the low end, changes formants or stretches noise.

## Refine boundaries

For tonal samples, usually take a stable body, retaining some consonant attack if useful. For drums, locate the actual transient in the waveform and retain the wanted decay. Inspect changes near the edges, try short fades or a phase-matched loop, and check for clicks and abrupt tails.

Forced alignment helps locate phones in a known utterance, but sustained shouts, nasals and singing can still be misplaced. A successful job means it produced a result; check waveform, spectrum and context. After trimming or switching sounds, update the root, duration and other measures.
