---
name: finding-op-ed
description: "Finds opening and ending songs in anime or series episodes by comparing the audio of several episodes. Use when OP/ED timings are needed and subtitles or chapters do not mark them."
---

# Finding the OP and ED

Episodes of a work usually share the same OP and ED song.

1. Cut the first and last few minutes of several episodes, for example with ffmpeg.
2. Compare them across episodes with any audio comparison you have, such as cross-correlation or audio fingerprints. The longest nearly identical stretch is the OP or ED.
3. Write the result in the form the user wants, with times for each episode.
4. Report episodes that do not match, such as a different version or no OP. Do not force a mark on them.

Check the chapters first if the file has them. They may already give the answer.

Tried on one anime series: the start was within 0.1 s and the end about 6 s late, so check the end.
