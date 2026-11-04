---
name: ottosmasher
description: "Operate the OttoSmasher desktop app (otomad / 音MAD sample library: anime sources, subtitles, vocal separation, Japanese speech alignment, samples, tags, rhythm and pitch search, WAV / video / REAPER exports) through its `otto` command line while the app is open. Use when the user asks to prepare otomad material or to work with their OttoSmasher library."
---

# OttoSmasher

OttoSmasher is a desktop app for building otomad sample libraries. You operate the **running** app through its command line `otto`:
everything you do shows up in the app (edits can be undone there; newly created samples and sources cannot). This skill is only an entry point — the instructions themselves come
from `otto`, so they always match the version the user has installed.

## Find `otto`

1. `otto` on the PATH (the installed app sets this up by itself when it starts).
2. Otherwise read the files in the app's registry: `~/Library/Application Support/OttoSmasher/instances/*.json` (Windows: `%APPDATA%\OttoSmasher\instances\*.json`). Each running app has one, with its `otto` path, `app` path and `workspace`.
3. On macOS, the default install: `/Applications/OttoSmasher.app/Contents/Resources/bin/otto`.
4. In a source checkout of the repository: `tools/otto` (Windows: `tools\otto.cmd`).

`otto status` tells you whether the app is running, where it is, which workspace it talks to and what is missing in the environment. If it is not running, run `otto open`; it starts the app with its normal window and waits until it is ready.
`otto` follows the running app of its own kind. To use another workspace, set `OTTO_WORKSPACE` (or pass `--workspace`).

## Then

- `otto guide` — the overview and ground rules. Read it before your first command; read other topics (`otto guide <topic>`) only when you need them.
- `otto guide playbook` — the user's own conventions; they take precedence over general practice.
- `otto guide notes` — practices and experience (not rules), when you are stuck or looking for an approach.
- The guide is in Chinese by default; add `--lang en` for English.

Do not copy the guide into this skill or into memory files; it changes with the app.
