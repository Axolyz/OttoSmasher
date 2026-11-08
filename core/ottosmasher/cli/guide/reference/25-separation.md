# Choosing separation ranges

First inspect `tracks.separatedVocals` and `assets.tracks`. Reuse available stems, set missing defaults with `tracks.defaultFromSeparation`. Every new separation request computes again, so a ready track is not a reason to submit another one.

| Task | Useful starting point |
|---|---|
| Subtitles, season-wide library | Whole-track vocals, useful across later steps |
| A few lines or a quality experiment | Local range with surrounding context |
| Many short ranges | One `separation.submit` with ranges, avoiding repeated startup |
| Difficult speech or music | Compare a small representative range before committing to a model or large batch |

The default vocal/sfx track must cover the source; local stems need explicit assetId. Partial separation creates a sample for each stem; whole-track separation does not. Keep the requested stem outputs. Original stem names are preserved; roles are determined through the case-insensitive role alias setting. See topic prepare for commands, the queue and measured costs (specific hardware/model, not a deadline).

`studio.status {"refresh": true}` refreshes the installed-model catalog, without downloading weights. Cache identity includes nested files; adding a model below a subdirectory invalidates it. Studio remains responsible for installing its models; Otto never modifies its environment. Do not delete arbitrary cache or model files to diagnose a stale list.
