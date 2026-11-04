# OttoSmasher for agents: overview

OttoSmasher is a desktop app for otomad material: it registers videos and audio ("sources"), imports subtitles, separates vocals,
analyses Japanese speech (phonemes, pitch, rhythm), keeps a tagged library of **samples**, searches them by rhythm or pitch, and exports
WAV, video clips and REAPER items.

You drive it with the command line `otto`. `otto` talks to the **running app** (the owner has it open), using the same commands the
app's own interface uses, so everything you do shows up in the app; edits to the data can be undone there, but newly created samples, sources and tracks cannot (topic `undo`).

## Division of labour

The app does the **deterministic work**: storing data, separation, alignment and analysis, search, beat-fitting, export; reliable and undoable.
**Judgement is yours**: how to clean messy subtitles, which lines "talk about games", where the OP is when there are no subtitles,
who is speaking in a clip… The app gives you primitives (read the data, get audio and pictures, write your conclusions back as tags,
text segments, OP/ED, default tracks…) and you chain them with your own reasoning and tools.
Commands come in two layers: **library commands** change objects in the library; **primitives** only compute (alignment, readings, pitch, reading subtitle files…) and accept any file as sound.
Whether to register a file first (separation requires it; so do results you want to keep, samples and search): see "Register first, or call directly?" in topic `primitives`.
When a rule or automatic detection in the app falls short, do not wait for the app to change: read the data, decide, write the result back (topic `combine`).
When you need to judge sound (checking an alignment, finding the OP, telling who speaks…) and you cannot hear: use an audio tool in your environment
(spectrograms, timed transcripts); if there is none, ask the owner to run `otto setup audio --for <your tool>` (e.g. audio-mcp) instead of guessing from text.

## Three layers of instructions

1. **This guide** (`otto guide`): how to operate the app correctly — objects, commands, what the app does, the rules you must follow; it always matches the running app.
2. **Practices and experience** (`otto guide notes`): cleaning subtitles, retiming, finding the OP, separation strategy, pitfalls… not rules, may be out of date.
3. **The owner's playbook** (`otto guide playbook`, the file `Agent/playbook.md` in the workspace): the owner's own habits and requirements; they change it any time.
   When the owner asks you to "remember this approach", write it into that file.

The owner's playbook wins over practices and experience; the ground rules below cannot be overridden by anyone. **Look at the playbook when you start.**

## Ground rules

1. **The app must be running.** Start with `otto status` (it also reports the environment: models, PyMSS Studio, whether there is a playbook). If it says `"running": false` (exit code 2), run `otto open`: it starts the app with its normal window and returns once it is ready; if the app is already running it does nothing.
   `otto status` also shows which **workspace** it talks to (`workspace`), where the app is (`app`) and which copies are running (`runningApps`). `otto` uses the workspace of the running app of its own kind (the installed `otto` talks to the installed app, `tools/otto` to the dev version); to use another one set `OTTO_WORKSPACE` (or `--workspace`).
   Never read or write the database directly; in `Library/` only read or copy paths that commands returned to you, never rename, delete or write there.
   **The owner's files** (source media and subtitles) may be read; before changing one (e.g. writing a same-name subtitle file) keep a copy with a `backup_` prefix next to it, and never change or delete media files. Keep your own working files in your own temporary folder, not in the workspace or the material folders, and say what you left behind.
2. **Set a session id once per task**: `export OTTO_AGENT_SESSION=<short-task-name>`. Every change you make is recorded under it,
   and the owner (or you) can undo the whole session later (topic `undo`).
3. **Output is JSON on stdout**; progress lines go to stderr. Exit codes: `0` ok, `1` business error (JSON `error.code`),
   `2` usage / connection / bad parameters, `3` the owner declined or nobody confirmed.
   Binary fields such as pitch frames and spectrograms are base64 strings, as declared by `contentEncoding: base64` in the schema; the Python client in `otto run` returns native `bytes`.
4. **Discover before you guess**: `otto commands [--effect read|write|job] [--grep word]`, `otto describe <command>` (full
   parameter and result schema), `otto describe <event>`, `otto errors [code]`.
5. **Long work is a job.** Add `--wait` to follow a returned job, search or video export to its end:
   `otto call speech.submit '{...}' --wait`. Separation, speech analysis and pitch measurement share the "model" channel (queueing: topic `prepare`).
   A `succeeded` batch job does not mean every item worked: per-item failures are in the result; check them (topic `concepts`).
   **Do not idle-wait on long jobs** (separating an episode takes ten to several tens of minutes, batch analysis a few minutes): do not poll the status over and over.
   If your environment can run a command in the background and wake you when it ends, run `otto wait job <id>` in the background (it exits only when the job ends).
   If it cannot, **tell the owner plainly**: what you submitted, roughly how long it takes, that your environment cannot wait without spending tokens,
   so you stop here and they should say "continue" when it is done — then end your turn. When you resume, `otto session` shows this session's jobs and changes.
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

`otto guide <topic>` (add `--lang en` or `--lang zh-CN`; `--all` prints every topic of this guide, not notes or playbook):
`concepts`, `prepare`, `samples`, `search`, `primitives`, `export`, `combine`, `scripts`, `undo`; plus `notes` (practices and experience) and `playbook` (the owner's playbook).
Helpers: `otto setup playbook` (create the owner's playbook template in the workspace), `otto setup audio --for claude-code|codex|other` (commands or config to connect an audio tool).
