---
name: finding-op-ed
description: "Finds opening and ending songs in OttoSmasher sources by comparing episodes of a work. Use only when OP/ED ranges are missing and the subtitles do not mark them."
---

# Finding the OP and ED

Episodes of a work usually share the same OP and ED song.

1. Cut the first and last few minutes of several episodes.
2. Compare them across episodes. Nearly identical stretches are candidates; repeated dialogue, recaps and credits are alternatives to check.
3. Verify the complete music start and end in context at the agreed precision (`otto guide workflow`); lyric caption edges do not define the whole song. Write confirmed ranges with `oped.add`.
4. Report episodes that do not match, such as a different version or no OP. Do not force a mark on them.

Tried on Yuru Yuri on 2026-10-24: the start was within 0.1 s and the end about 6 s late, so check the end.
