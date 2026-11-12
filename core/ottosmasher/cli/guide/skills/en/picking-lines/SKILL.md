---
name: picking-lines
description: "Find dialogue by meaning, character, delivery or emotion across an OttoSmasher library and curate reusable samples. Use for semantic searches, rap selection and expressive voice requests; exporting named samples can use app commands directly."
---

# Pick dialogue

Choose scope and precision with otto guide workflow and try the audio tools with otto guide audio. Follow the user's requirements: who says each part, the desired emotion, whether lines may be recontextualized and which tags to add. Search each side of a dialogue separately: someone praising a character and the character introducing herself are different candidates.

## Scope and precision

If there is no explicit precision or applicable preference, ask once: **quick** gives a small initial selection, **standard** broadens the search and compares representative candidates, and **fine** repeats the search and reviews all agreed candidates. Explain the added effort and let the user choose the scope.

## Find candidates

textLayer.search suits known phrases; textLayer.list with a local script helps collect broader semantic candidates. Use keywords to narrow the range, then expand to synonyms, reactions and paraphrases. When results cluster in a few scenes, explore other episodes and situations. If the exact line is absent, offer alternatives with a similar meaning.

Check the actual words, speaker and delivery. For happiness, pride or victory, try celebrations, successful actions, pleased laughter and introductions. High pitch also occurs in fear or pain, so consider emotion and compare the character's ordinary voice. Where pictures matter, inspect the frames: previews and offscreen dialogue may show somebody else.

## Check search coverage

For meaning, character or emotion, start with text and auditioning. Analyse the relevant candidates when you need to verify vowels, syllables or beat placement. For a reading-based text search, check `readingPending`. Account for any agreed sources whose text has not been imported.

Before using `search.speech` for vowels, block order or rhythm, call `search.coverage` on the same scope and follow `otto guide search` for pending indexes and missing usable analyses. For a quick first pass, search the ready subset. If the task calls for all matches, or you want to say there are no matches or name the best match across the scope, first prepare the analyses and indexes that can be filled. Report how many items were searched out of the total in scope and why any items remain uncovered.

## Keep useful material

Reuse samples and analysis. When candidates are to be kept in the library, create the selected full lines or excerpts as agreed. Retain source ranges and selection reasons. Preview tag changes with samples.batchEdit and pass changes to edits.apply. Keep earlier selections when adding candidates; revise them when the user asks for replacements.

Review candidates at the chosen precision and report the finds, semantic alternatives and points still needing confirmation, ready for arrangement.
