# OttoSmasher for agents: overview

OttoSmasher is a desktop app for otomad material. It registers videos and audio ("sources"), imports subtitles, separates vocals,
analyses Japanese speech (phonemes, pitch, rhythm), keeps a tagged library of **samples**, searches them by rhythm or pitch, and exports
WAV, video clips and REAPER items.

You drive the **running app** with the command line `otto`, which uses the same commands as the app's own interface. Everything you do shows up in the app.
Edits to the data can be undone there; newly created samples, sources and tracks cannot (topic `undo`).

## What the app does and what you do

The app does the deterministic work: storing data, separation, alignment and analysis, search, beat-fitting, export.
Judgement is yours: how to clean messy subtitles, which lines "talk about games", where the OP is without subtitles, who is speaking in a clip.
Read the data, decide with your own reasoning and tools, and write the conclusions back as tags, segments, OP/ED or default tracks (topic `combine`).
When a rule or automatic detection in the app falls short, do not wait for the app to change: decide yourself and write the result back.

Commands come in two layers. **Library commands** change objects in the library; **primitives** only compute (alignment, readings, pitch, reading subtitle files) and accept any file as sound.
Topic `primitives` explains when to register a file first.

## First-time setup

Before setting up external tools or models, check what can be reused and explain the new downloads, known sizes and storage locations, and planned configuration changes. Get the user's agreement before proceeding. Read-only checks and presenting a plan can come first. Reuse existing environments and an agreed plan; ask again when adding downloads or expanding configuration changes.

## Where instructions come from

| Source | What it holds | Who changes it |
|---|---|---|
| This reference (`otto guide`) | Objects, commands, app behaviour, rules. Always matches the running app. | The app's developers |
| Skills (the folder `Agent/skills/` in the workspace) | Procedures for a few specific tasks. Listed at the end of `otto guide`. Read one only when your task matches its description; most tasks need none. | The user |
| Playbook (`Agent/playbook.md` in the workspace) | The user's standing conventions. Read it when you start. | The user |

The playbook wins over skills. Neither can override the ground rules below.
When the user asks you to remember something, write a standing preference into the playbook and a change to a procedure into that skill's `SKILL.md`. Do not change either file unless asked.

## Ground rules

### Start with `otto status`

The app must be running. `otto status` reports the workspace, the app, the environment (models, PyMSS Studio, playbook, skills) and hints about anything missing.
If it says `"running": false` (exit code 2), run `otto open`, which starts the app with its normal window and returns once it is ready.

The installed `otto` talks to the installed app and `tools/otto` to the development version. To use another workspace, set `OTTO_WORKSPACE` or pass `--workspace`.

### Set a session id once per task

`export OTTO_AGENT_SESSION=my-task` (bash), `$env:OTTO_AGENT_SESSION='my-task'` (PowerShell), or `--session my-task` before or after the subcommand. Your changes are recorded under it, and the whole session can be undone later (topic `undo`).

### Files you may touch

- The database: never read or write it directly.
- `Library/`: only read or copy paths that commands returned to you. Never rename, delete or write there.
- The user's subtitle files: you may read them. Before changing one, keep a copy with a `backup_` prefix next to it.
- The user's media files: read only.
- Your own working files: keep them in your own temporary folder, not in the workspace or the material folders. Say what you left behind.

### Check your audio tool before any task that needs judgement

Only tasks that follow fixed steps can skip this, such as registering files or exporting samples the user named.
Every other task needs you to hear the material: arranging an otomad rap, choosing a timbre, picking lines, cleaning subtitles, checking an alignment.

Try the needed tools on a short real clip before starting. Read `otto guide audio` for connection methods, short inputs and using the results. If setup takes time, continue other preparation and note which sound checks are still pending.

### Agree on scope and precision

Read `otto guide workflow` and the relevant skill before planning judgement work. Follow existing user requirements; if precision is open, ask once for quick / standard / fine and explain the difference for this task. Keep a short record of decisions and remaining work. `sources.prep` shows the app's preparation state; content review is recorded with the task.

### Output and exit codes

Output is UTF-8 JSON on stdout. Progress goes to stderr only with `--progress`; non-interactive calls omit the one-off session note. Check the exit code, not whether stderr is nonempty.

| Exit code | Meaning |
|---|---|
| `0` | OK |
| `1` | Business error (`error.code` in the JSON) |
| `2` | Usage, connection or bad parameters |
| `3` | The user declined or nobody confirmed |

Binary fields such as pitch frames and spectrograms are base64 strings (`contentEncoding: base64` in the schema). The Python client in `otto run` returns native `bytes`.

### Look things up before you guess

- `otto commands [--effect read|write|job] [--grep text]`: list commands. `--grep` is a plain case-insensitive substring of the name and summary.
- `otto describe <command or event>`: the full schema.
- `otto errors [code]`: what an error means.

### Long jobs

Add `--wait` to follow a returned job, search or video export to its end: `otto call speech.submit '{...}' --wait`.
Use `jobs.summaries` for compact status and the number of queued jobs ahead on the same channel, or `jobs.get` for a full job by ID. Waiting returns the complete final result.
A `succeeded` batch job does not mean every item worked; check per-item failures in the result (topic `concepts`).

Separating an episode takes ten to several tens of minutes and batch analysis a few minutes. Do not poll the status over and over:

- If your environment can run a command in the background and wake you when it ends, run `otto wait job <id>` in the background.
- If it cannot, tell the user what you submitted and roughly how long it takes, that you cannot wait without spending tokens, and that they should say "continue" when it is done. Then end your turn. When you resume, `otto session` shows this session's jobs and changes.

### Commands that cannot be undone

Commands marked `"danger"` in `otto commands` (deleting sources or samples, renaming a work folder, cleaning storage, independence with source deletion) pop up a confirmation in the app.
Your call waits up to 2 minutes, and stderr shows `"note": "waiting for the user…"` meanwhile.

Exit code 3 means the command did not run: the user declined (`agent-confirm-declined`) or nobody answered (`agent-confirm-timeout`; the request stays in the app's history).
**Do not retry.** Stop the work that depends on this step, carry on with the rest, and report what you wanted to do and why. Send it again when the user tells you to continue.

On approval the app re-checks the data; if it changed, the user is asked again with the new impact.
The user can turn this confirmation off in Settings › Command line & agent; the command line cannot change that setting.

## Current project and BPM

The `context` in `otto status` and `otto call workflow.context` both report the current project name, its exact `projectTag`, and the target BPM. Rhythm search and stretched exports use the desktop BPM directly. Add selected products to a project when the user's task calls for it. See the `samples` topic for write commands.

## Calling a command

```sh
otto call samples.list '{"limit": 5}'
otto call samples.list @query.json        # params from a file
echo '{"text": "ゲーム"}' | otto call samples.list -   # bash; PowerShell: see scripts
otto run my_script.py                     # many calls at once: write a Python script (topic scripts)
```

PowerShell/.cmd may lose JSON quotes. Prefer a UTF-8 `@params.json` or stdin, and see topic `scripts` for examples.

Undeclared parameters are rejected (`bad-request` with the offending key). All ids are strings.

## More

- `otto guide --lang en|zh-CN` selects the reference language; Chinese and English have the same topics.
- `otto guide <topic>` prints a topic; `--all` prints the whole reference without skills or playbook.
- `otto guide <skill>` prints a skill; `otto guide playbook` prints the playbook.
- `otto setup playbook` creates the playbook from a template.
- `otto setup skills` checks the skills folder, including commands that edited skills name but this version no longer has.
- `otto setup audio --for claude-code|codex|other` prints the commands or config to connect an audio tool.
