---
name: separating-audio
description: "Compares whole-episode and partial vocal separation in OttoSmasher, with time and disk costs. Use when many lines or episodes are involved and the user has not said what to separate. Not needed for a plain separation request."
---

# Separating audio

First run `tracks.separatedVocals {"sourceIds"}`. Every request separates again and makes new tracks, so reuse what exists.

## Choose

| Situation | Choice | Note |
|---|---|---|
| Cleaning subtitles, retiming, or building a library from the whole episode | Whole episode | The vocal then serves every later step and can be the default track. |
| Only a few lines, or a first look | `separation.submit` with `start` / `end` | Partial stems cannot be the default, so pass their `assetId`. Each stem also creates a sample. |
| Many short parts | `ranges` | Joins the parts into one input, which is much faster than one job per part. |
| A demanding line | A longer range or the whole episode | Results depend on the surrounding audio. |

Cleaning subtitles and retiming need a clear voice, so usually separate first. Submit all whole episodes at once, then wait as the overview describes under "Long jobs".

## Expected cost

Measured with HyperACE v2 on Apple silicon on 2026-10-30; other machines and models will differ:

- Each job takes about 8 s to start, then about 0.35 s per second of audio.
- A 24-minute episode takes about 9 minutes.
- With one job per line, a few dozen lines take about as long as the whole episode.
- 10 parts of 6 s took 31 s with `ranges`, against about 100 s as separate jobs.
- The same line separated alone, joined with others, or inside the surrounding minute differs by about −9 dB.

Check free disk space before a big batch and submit in groups.
