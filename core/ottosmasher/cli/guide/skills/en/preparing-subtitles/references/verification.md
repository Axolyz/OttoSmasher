# Reviewing evidence and finishing

## Build a ledger

Save `subtitles.parse` output to parsed.json. Keep the original caption backup as an input; planned output is not a baseline. In your task directory:

```sh
otto run /skill/scripts/review.py scan parsed.json task.json --input backup_original.srt --precision fine --goal "retime and identify every suspicious turn"
```

The helper counts observed raw-line patterns, not an exhaustive list of conventions. Interpret them on examples from each source, including standalone names, dash turns, reading brackets and sound-only lines. It initially includes multi-line, withheld/multi-speaker, overlapping and very short cues. These are candidates, not verdicts. A single-line boundary may also be wrong.

For full start/end screening, first save a full vocal `exports.wav` response to audio.json and pass `--audio-export audio.json`. It decodes once and flags energy on both sides of a boundary even when no gap exists. Screening uses a per-file relative threshold, which can overflag music or miss quiet speech. Add cases from other evidence through --extra-cases cases.json (array of id, start, end, text, flags), and sample normal scenes. Energy screening alone is never a complete quality audit.

## Review each selected case

Export the complete cue plus neighbouring context:

```sh
otto run /skill/scripts/review.py packet task.json cue:12 --asset-id TRACK_ID --directory /task/evidence
```

The packet contains WAV coordinates/mapping, not a new analysis claim. Inspect the actual waveform/energy curve and sentence content with audio-mcp. Expand context for a long trailing word, adjacent speech or ambiguous ownership. ASR on full sentences with more/less context can help confirm content; recognition differences and word times alone are not boundaries. Use alignment or voiceprints if helpful. Look at starts as well as ends and compare neighbouring content even where there is no silence.

Record status kept / changed / uncertain, a reason, evidence [{path, note}], and proposed new source start/end when changed. Unknown identity does not remove the need to split a known turn. Do not fill every status from a threshold script. Packet creation is not review. In standard/quick mode state how much was actually checked; fine mode requires every candidate reviewed.

## Verify and write

`otto run /skill/scripts/review.py check task.json` checks fingerprints, duplicate cases, existing evidence files and remaining cases. Fine with pending cases exits nonzero. A reviewed uncertain case remains explicit. File existence cannot prove listening or correct judgement.

Only confirmed proposals should be included in a versioned `edits.apply` batch, or used to generate final captions before import. Recheck overlap, coverage, names and requested scope after revisions. Do not force overlaps away by midpoint, preserve only those actually simultaneous. Avoid expanding all intervals with fixed padding. Inspect per-item analysis outcomes and refresh affected results; readiness does not certify caption quality. New input versions require a new ledger revision, not overwriting old decisions.
