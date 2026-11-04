---
name: picking-lines
description: "Picks lines by meaning from thousands of OttoSmasher segments without reading them all into context, then turns them into tagged samples. Use for requests such as finding every line that talks about games. Not needed for a handful of lines."
---

# Picking lines

Do not read thousands of lines into context.

1. Prefilter candidates locally with keywords or rules.
2. Judge each candidate together with the lines around it. Keywords mis-hit: in Kemono Friends 「ボス」 is a character and 「プレーリー」 an animal.
3. List the doubtful ones for the user.

## A complete task, in outline

"Make every line about games in these episodes a speech sample tagged `topic:game`, search them for a rhythm, export the hits":

1. Read the playbook and register the files.
2. Separate whole episodes and wait in the background (skill `separating-audio`).
3. Clean and import the subtitles (skill `cleaning-subtitles`).
4. Prefilter with a script and judge each line.
5. Create the samples with `samples.plan` and `samples.createPlanned`.
6. Analyse with `speech.submit`.
7. Tag with `samples.batchEdit`.
8. Search with `search.speech` and export with `hits.export`.
9. Report what you created, what you were unsure about and where the files are. To undo the edits, use `edits.undoSession`.
