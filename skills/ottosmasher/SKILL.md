---
name: ottosmasher
description: "Operate the OttoSmasher desktop app (otomad / 音MAD sample library: anime sources, subtitles, vocal separation, Japanese speech alignment, samples, tags, rhythm and pitch search, WAV / video / REAPER exports) through its `otto` command line while the app is open. Use when the user asks to prepare otomad material or to work with their OttoSmasher library."
---

# OttoSmasher

OttoSmasher is a desktop app for building otomad sample libraries. You operate the **running** app through its command line `otto`:
everything you do shows up in the app (edits can be undone there; newly created samples and sources cannot). This skill is only an entry point — the instructions themselves come
from `otto`, so they always match the version the user has installed.

## Find `otto`

1. `otto` on the PATH (the app installs it: Settings › Command line & agent › Install the otto command).
2. Otherwise the full path shown in that same settings section — ask the user to copy it.
3. In a source checkout of the repository: `tools/otto` (Windows: `tools\otto.cmd`).

`otto status` tells you whether the app is running, which workspace it talks to and what is missing in the environment; if it is not running, ask the user to open the app.
If the user's workspace is not in the default place, set `OTTO_WORKSPACE` to it (or pass `--workspace`).

## Then

- `otto guide` — the overview and ground rules. Read it before your first command; read other topics (`otto guide <topic>`) only when you need them.
- `otto guide playbook` — the user's own conventions; they take precedence over general practice.
- `otto guide notes` — practices and experience (not rules), when you are stuck or looking for an approach.
- The guide is in Chinese by default; add `--lang en` for English.

Do not copy the guide into this skill or into memory files; it changes with the app.
