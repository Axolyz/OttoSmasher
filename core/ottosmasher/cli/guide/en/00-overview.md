# OttoSmasher for agents: overview

OttoSmasher is a desktop app for otomad (音MAD) material: it registers videos and audio ("sources"), imports their subtitles,
separates vocals, analyses Japanese speech (phonemes, pitch, rhythm), keeps a library of tagged **samples**, finds samples by
rhythm or pitch, and exports WAV files, video clips and REAPER items.

You drive it with the `otto` command line. `otto` talks to the **running app** (the owner keeps it open); it calls the same
commands the app's own interface uses, so everything you do shows up in the app and can be undone there.

## Ground rules

1. **The app must be open.** `otto status` tells you. If it says `"running": false` (exit code 2), ask the owner to open it.
   Never open the database or the `Library/` folder yourself; only use commands.
2. **Set a session id once per task**: `export OTTO_AGENT_SESSION=<short-task-name>`. Every change you make is recorded under it,
   and the owner (or you) can undo the whole session later (topic `undo`).
3. **Output is JSON on stdout**; progress lines go to stderr. Exit codes: `0` ok, `1` business error (JSON `error.code`),
   `2` usage / connection / bad parameters, `3` the owner declined or nobody confirmed.
4. **Discover before you guess**: `otto commands [--effect read|write|job] [--grep word]`, `otto describe <command>` (full
   parameter and result schema), `otto describe <event>`, `otto errors [code]`.
5. **Long work is a job.** Add `--wait` to follow a returned job, search or video export to its end:
   `otto call speech.submit '{...}' --wait`.
6. **Commands that cannot be undone** (`"danger"` in `otto commands`: deleting sources or samples, renaming a work folder,
   cleaning storage, independence with source deletion) pop up a confirmation in the app, and your call **waits until the owner
   answers** (they may be away from the computer for hours). While it waits, stderr shows `"note": "waiting for the owner…"`.
   So run such calls in the background or without a timeout, and preferably leave them to the end of the task; if your process
   is killed, the request is withdrawn. Exit code 3 means the owner declined. Do not retry a declined command; ask the owner instead.
   The owner can turn the confirmation off in the app's settings (Settings › Command line & agent); then these commands run right away.
   Only the owner can change that setting; the command line cannot.

## Calling a command

```sh
otto call samples.list '{"limit": 5}'
otto call samples.list @query.json        # params from a file
echo '{"text": "ゲーム"}' | otto call samples.list -
```

Parameters that the command does not declare are rejected (`bad-request` with the location). Every id is a string.

## What the app does not do

Anything outside the command list is yours to do with your own tools: cleaning subtitle files, speech recognition, judging what
a line means, image work such as cut-outs, video editing, building a REAPER project. Combine: export from the app, process
with your tools, bring results back (new subtitle files, picture bindings, tags). Topic `combine` shows how.

## Topics

`otto guide <topic>` (add `--lang en` or `--lang zh-CN`; `--all` prints everything; `--skill` prints a Claude Code skill):
`concepts`, `prepare`, `samples`, `search`, `export`, `combine`, `undo`, `example`.
