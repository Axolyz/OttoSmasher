# Search: rhythm (speech) and pitch

Both searches run over a **scope** (the same filter as `samples.ids`) and end in a **fixed result** that does not change when data
changes later. Readiness: `search.coverage` (index built / pitch measured); `search.prepare` queues the missing parts.

These two searches cover **samples** only (usable pieces already cut; to search a whole season, first create samples from its segments in bulk). To find where a line is in the **raw material** (which episode, what time), use `textLayer.search`:
it searches the text layer's segments and sound hints (normalised text substring or reading substring, the same rules as the samples' "line" filter); hits are positions on sources (source seconds), not samples, and nothing is stored.
`sourceIds` omitted = all sources; `notImported` = sources with an associated subtitle but an empty text layer (not searchable); `readingPending` = segments whose reading is not computed yet (matched by text only).

## Speech / rhythm search

```sh
otto call search.speech '{"query": {"blocks": [{"vowel": "a"}, {"vowel": "i"}]}, "scope": {"tags": {"expr": "topic:game"}}}' --wait
```
A query is a list of **blocks** (one block ≈ one syllable nucleus) with optional conditions: `vowel` (a/e/i/o/u), `consonants`,
`pitch` (0–11) and `octave`, `duration`, `trend` (up/down), `relPitch`, `loudnessMin`, `character`, ...
`strategy`: `free` (default: order only), `strict` / `rank` (rhythm: every block needs `note: [startBeat, endBeat]`, ascending,
not overlapping; onsets more than 2 × `tolerance` apart; default `tolerance` 0.1 beat). `edge`, `scope`, `speedRange`,
`maxGap`, `length` refine it — `otto describe search.speech` lists them all.
Bad queries fail with `speech-query-invalid` naming the field and block.

## Pitch search

```sh
otto call search.pitchCheck '{"text": "0.3 C4\n0.3 E4"}'       # validate / convert the text form (one "seconds note" per line)
otto call search.pitch '{"blocks": [{"seconds": 0.3, "low": "C4"}, {"seconds": 0.3, "low": "E4"}], "mode": "samples"}' --wait
```
`mode: "samples"` searches saved samples; `"sources"` searches analysed source tracks. `params` sets cents tolerance (50),
coverage (0.8), `ignoreOctave`, `elastic` duration range, and more. Results are complete (not truncated) and approximate.

## Read results

`--wait` prints the final status with `resultId`. Then:
```sh
otto call results.page '{"id": "<resultId>", "offset": 0, "limit": 100}'
```
Each row has `sampleId` (or `assetId` in source mode), `state` (ok / deleted / changed / stale) and `hits[]` with ranges.
A hit can be rendered or exported: `hits.export`, `hits.video`, `hits.render` (with its evidence's stretch scheme), and saved as
a sample with `samples.create` (`via: "hit"`). Close a result you no longer need: `results.close`.
