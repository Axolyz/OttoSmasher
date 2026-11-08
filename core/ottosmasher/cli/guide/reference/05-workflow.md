# Scope, precision and evidence

## Agree once

For judgement tasks, establish sources/episodes, input versions, intended output, existing usable work, and precision. Reuse explicit requests and applicable playbook preferences. Otherwise ask once with quick / standard / fine and explain what changes for this task. Extra requirements override the preset; a user asking to check every suspicious item has already chosen that coverage.

| Precision | Subtitle work | Selection / timbre / separation work |
|---|---|---|
| quick | Clean text, check version offsets and actual annotation patterns; investigate obvious defects, report unrefined parts | Small candidate set, limited comparisons, usable first selection |
| standard | Screen the whole scope; inspect high-risk cases and samples across patterns, scenes and speakers | Broader candidate search, compare representative results against the goal |
| fine | Screen the whole scope; review every suspicious start/end, turn and overlap; sample normal scenes | Iterative search and review of every agreed candidate |

Precision changes coverage and effort, not permission to invent identities, cut words, skip failures or claim unchecked results are verified. Every-line review is an explicit extension of fine. Explain relative time/token cost; do not invent estimates. Ask before a material downgrade; lack of a reply is not approval to reduce agreed coverage.

## Freedom within the contract

Use scripts for pagination, clocks, inventory and completeness. Follow the skill's prerequisite dependencies (single-speaker intervals before voiceprints, for example), but choose analysis methods to suit the material. A reproducible default route helps; it is not a fixed sequence of tool calls. Document why an alternative meets the same goal. Do not classify models as smart or weak to change correctness requirements.

Read the task skill and relevant references before planning. Discover each source's conventions, including unlisted ones. Example numbers and measured performance belong to their experiment, not to every work. For sustained tasks keep a small report in your temporary task folder, rather than a new workflow database in the app.

## Checks and judgements

The subtitle skill includes `scripts/review.py`. It consumes the app's `subtitles.parse` JSON, inventories raw annotation patterns and builds a candidate ledger. Optional waveform screening includes both starts and ends, even without silence between sentences. Screening produces questions, never boundary changes. The packet command exports whole-cue audio with context and its time mapping; inspect the actual curve and content with your audio tool. ASR, energy, alignment and CC timing can each be wrong. Select a boundary from the combined evidence and keep uncertain cases explicit.

The ledger stores input fingerprints, candidates, decisions and evidence references. Its check catches pending items, changed inputs and missing evidence files; it cannot prove that a model actually listened or made a correct judgement. App readiness and content verification are distinct: `sources.prep` has no knowledge of these reviews.

## Completion

Before declaring completion reconcile requested scope, processed scope, reviewed scope, unresolved items, failed/skipped analysis items, saved files and app state. Fine requires zero unreviewed suspicious items; reviewed-but-uncertain items remain reported, not guessed. Recompute overlap and coverage after applying confirmed changes. A new input version invalidates affected reports. For an updated media arrangement, either refresh all dependent timing rows or label exactly which rows still belong to an older snapshot.

If independent work remains, continue it. If a required capability or external limit prevents completion, state the blocker and preserve resumable progress. Never turn a sample check into a claim of full review.
