---
name: ottosmasher
description: "Operates the OttoSmasher desktop app (otomad / 音MAD sample library: anime sources, subtitles, vocal separation, Japanese speech alignment, samples, tags, rhythm and pitch search, WAV / video / REAPER exports) through its `otto` command line. Use when the user asks to prepare otomad material or to work with their OttoSmasher library."
---

# OttoSmasher

You operate the running OttoSmasher app through its command line `otto`. This skill is only an entry point. The instructions come from `otto`, so they always match the installed version; do not copy them into this skill or into memory files.

## Find `otto`

Try these in order:

1. `otto` on the PATH. The installed app sets this up when it starts.
2. The files in the app's registry: `~/Library/Application Support/OttoSmasher/instances/*.json` (Windows: `%APPDATA%\OttoSmasher\instances\*.json`). Each running app has one, with its `otto` path, `app` path and `workspace`.
3. On macOS, the default install: `/Applications/OttoSmasher.app/Contents/Resources/bin/otto`.
4. In a source checkout of the repository: `tools/otto` (Windows: `tools\otto.cmd`).

## Start

1. Run `otto status`. If the app is not running, run `otto open`.
2. Run `otto guide`: the overview, the ground rules and the list of skills. Read it before your first command.
3. Run `otto guide playbook`: the user's own conventions.
4. Read a skill only when your task matches its description in that list. Those skills are files in the workspace, and the user may have edited them.

For judgement tasks, use `otto guide workflow` to choose scope and precision, then read the relevant skill and references. Try the needed audio tools on a short real clip as described in `otto guide audio`.
