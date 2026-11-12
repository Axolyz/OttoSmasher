# Samples: creating, speech analysis, tags, finding

## Read the lines

```sh
otto call textLayer.list '{"sourceId": "<id>"}'
```
`segments[]` has `id`, `text`, `speakers`, `start`/`end` (source seconds), `oped` (inside OP/ED), `analysis`, `usedBy`
(how many samples already read it). Decide yourself which lines you want (for example "the line talks about games").
Text search over existing samples (names, segment text and readings): `samples.list {"text": "..."}`.

## Create samples from chosen segments

```sh
otto call samples.plan '{"from": {"kind": "segments", "sourceId": "<id>", "ids": ["<segId>", ...], "track": "default"}}'
```
The plan has `token`, `missingDefault` (a default track the source still needs — set it first), and `items[]` with `key`,
`name` (= the line), `nature`, `status`. Only `status: "pending"` items can be created (`oped`, `no-name`, `out-of-track` cannot).

```sh
otto call samples.createPlanned '{"from": <same from>, "token": "<token>", "keys": ["<key>", ...], "nature": "speech"}'
```
Returns `ids` of the new samples. Use `overrides` to set names or local tags per item, for example `{"<key>": {"name": "...", "localTags": ["project:demo"]}}`. The tags are saved in the same transaction as the sample.
Other sources of samples: `kind: "whole"` (whole sources, `sourceIds`), `"hints"` (sfx hints), `"selection"`
(`assetId`, `start`, `end` in asset seconds), or one range directly with `samples.create {"assetId", "start", "end"}`.

## Analyse speech

```sh
otto call speech.preview '{"entry": "samples", "ids": ["<sampleId>", ...]}'   # run / fresh / blocked with reasons
otto call speech.submit  '{"entry": "samples", "ids": [...]}' --wait
otto call speech.results '{"jobId": "<job>"}'
```
Analysis belongs to segments, not samples; deleting a sample keeps it. Up-to-date segments are skipped (`rerunFresh: true` forces).
After analysis the app prepares search indexes in the background (event `search.coverage`).

## Tag

```sh
otto call samples.batchEdit '{"ids": [...], "fields": {"addTags": ["topic:game"]}}'   # preview, nothing written
otto call edits.apply '{"batch": <batch from the preview>}'
```
`fields` can also set `name`, `nature`, `starred`, `rating`, `removeTags`. Effective tags of samples: `tags.ofSamples {"ids"}`.
Rename or remove a tag everywhere: `tags.globalPlan` → `edits.apply`.

## Find samples

`samples.ids` (all matching ids) and `samples.list` (pages, `limit`/`offset`, `sort`) take the same filter:
`natures`, `starred`, `text`, `sourceId`, `expr` (main expression), `tags: {"facets": [{"facet": "other", "values": ["topic:game"]}], "expr": "..."}`.
Example: `otto call samples.ids '{"tags": {"expr": "topic:game AND character:*"}}'`.
Use `projectTag: "project:dil"` to match that exact local tag.

## Add products to a project

Read the current project and exact `projectTag` from `otto call workflow.context`. New samples stay outside any project by default, regardless of the desktop auto-add toggle. If the user asks to add them to the current project, pass `useCurrentProject: true` to `samples.create` or `samples.createPlanned`. For a plan, it applies to all selected keys. The app reads the project at creation time. If no project is selected, the call returns `current-project-unset` before creating samples.

For a task spanning multiple calls, capture the exact tag at the start to keep the same project throughout. Pass `localTags` to `samples.create` or `overrides[key].localTags` for chosen items in `samples.createPlanned`. For existing samples, use `addTags` in `samples.batchEdit` and apply the returned batch.


## Cached acoustic metrics

`samples.metrics {"ids": [...]}` reads existing metrics with ready/stale/missing state for each sample. Use `metrics.prepare` to compute missing measures. Fields with no measured value remain null. For a pitch curve, read measure.f0 over the sample's asset range; the list's glyphs show its speech shape.

`spectrum.get` returns data bytes with the scale, nyquist and row-center frequencies in Hz, useful for interpreting log/mel rows. List sorting accepts created / name / source / duration. createdBySession filters samples by their creation session and also works with samples.ids. Use IDs to identify tracks or samples with repeated names.
