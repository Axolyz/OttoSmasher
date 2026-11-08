# Reviewing evidence and finishing

## Understand this source

Read the original captions and relevant style/track information before choosing how to count annotations. Input formats and conventions are open-ended. The examples in cleaning.md are examples, not a recognized-format list. A parser's empty speakers or non-dialogue classification does not prove that the original has no speaker information or speech.

Form hypotheses from this source's actual writing and check representative audio/context. If scripting counts or candidate collection, derive that temporary script from the observations, preserve unknown cases and revise it when a new convention appears. Do not force an unfamiliar form into a known class or treat unflagged cues as correct. The app's parsing rules describe the destination format; they are not an interpretation of every possible input.

## Review at the agreed coverage

Choose suitable evidence and screening for the material. Inspect both starts and ends, sequential turns and overlaps, including adjacent speech with no silence. Do not prescribe a universal energy threshold, short-cue duration or bracket pattern. In fine mode review every suspicious case identified across the agreed scope and sample normal scenes; explain what the screening can miss.

Use `exports.wav` to obtain full sentences and sufficient context, retaining the returned mapping. Use audio-mcp to view the actual curve and check content, expanding the context when needed. ASR word times, energy and forced alignment are clues, not ground truth or proof of sound ownership. Unknown identity does not cancel splitting a known sequential turn.

For a long task, keep enough notes to resume: input version, actual coverage, observations, decisions, evidence and unresolved cases. Choose a useful format; no fixed ledger schema or script exit code certifies completion. Do not mark cases reviewed from threshold output or from generating audio files.

## Reconcile and write

Only confirmed changes go into a versioned `edits.apply` batch or final captions before import. Use `subtitles.parse` to check the final output against the current app rules; successful parsing proves neither the interpretation of the input nor timing quality.

Recheck overlaps, coverage, names and requested scope after revisions. Do not remove every overlap by midpoint or extend every cue with fixed padding. Inspect per-item analysis failures and refresh affected results. App readiness is not content verification. Changed inputs invalidate affected conclusions; report what remains uncertain or unchecked rather than turning a sample check into a full-review claim.
