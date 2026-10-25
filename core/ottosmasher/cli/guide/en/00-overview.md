# OttoSmasher for agents: overview

OttoSmasher is a desktop app for otomad material: it registers videos and audio ("sources"), imports subtitles, separates vocals,
analyses Japanese speech (phonemes, pitch, rhythm), keeps a tagged library of **samples**, searches them by rhythm or pitch, and exports
WAV, video clips and REAPER items.

You drive it with the command line `otto`. `otto` talks to the **running app** (the owner has it open), using the same commands the
app's own interface uses, so everything you do shows up in the app and can be undone there.

## Division of labour

The app does the **deterministic work**: storing data, separation, alignment and analysis, search, beat-fitting, export; reliable and undoable.
**Judgement is yours**: how to clean messy subtitles, which lines "talk about games", where the OP is when there are no subtitles,
who is speaking in a clip… The app gives you primitives (read the data, get audio and pictures, write your conclusions back as tags,
text segments, OP/ED, default tracks…) and you chain them with your own reasoning and tools.
When a rule or automatic detection in the app falls short, do not wait for the app to change: read the data, decide, write the result back (topic `combine`).

## Ground rules

1. **The app must be running.** Check with `otto status`. If it says `"running": false` (exit code 2), ask the owner to open the app.
   Never open the database or the `Library/` folder yourself; use commands. The sources' own media and subtitle files may be read directly.
2. **Set a session id once per task**: `export OTTO_AGENT_SESSION=<short-task-name>`. Every change you make is recorded under it,
   and the owner (or you) can undo the whole session later (topic `undo`).
3. **Output is JSON on stdout**; progress lines go to stderr. Exit codes: `0` ok, `1` business error (JSON `error.code`),
   `2` usage / connection / bad parameters, `3` the owner declined or nobody confirmed.
4. **Discover before you guess**: `otto commands [--effect read|write|job] [--grep word]`, `otto describe <command>` (full
   parameter and result schema), `otto describe <event>`, `otto errors [code]`.
5. **Long work is a job.** Add `--wait` to follow a returned job, search or video export to its end:
   `otto call speech.submit '{...}' --wait`. Separation and speech analysis share one first-come-first-served queue (topic `prepare`).
6. **Commands that cannot be undone** (`"danger"` in `otto commands`: deleting sources or samples, renaming a work folder,
   cleaning storage, independence with source deletion) pop up a confirmation in the app; your call waits up to 2 minutes
   (stderr shows `"note": "waiting for the owner…"` meanwhile). Exit code 3 means it did not run: the owner declined
   (`agent-confirm-declined`) or nobody answered within 2 minutes (`agent-confirm-timeout`; the owner may be away, and the request
   stays in the app's history for them to see). **Do not retry.** Stop the work that depends on this step, tell the owner what you
   wanted to do and why, carry on with work that does not depend on it, and report at the end; send it again when the owner tells you to continue.
   On approval the app re-checks that the data is still as it was when you asked; if it changed, the owner is asked again with the new impact.
   The owner can turn the confirmation off in the app's settings (Settings › Command line & agent); then these commands run right away.
   Only the owner can change that setting; the command line cannot.

## Calling a command

```sh
otto call samples.list '{"limit": 5}'
otto call samples.list @query.json        # params from a file
echo '{"text": "ゲーム"}' | otto call samples.list -
otto run my_script.py                     # many calls at once: write a Python script (topic scripts)
```

Undeclared parameters are rejected (`bad-request` with the offending key). All ids are strings.

## Topics

`otto guide <topic>` (add `--lang en` or `--lang zh-CN`; `--all` prints everything; `--skill` prints a Claude Code skill):
`concepts`, `prepare`, `samples`, `search`, `export`, `combine`, `scripts`, `undo`, `example`.
