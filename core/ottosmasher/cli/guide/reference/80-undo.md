# Undo and history

* Everything you change is recorded with your **session** (`OTTO_AGENT_SESSION`) and kind `agent`.
* `otto call edits.history '{"session": "<session>"}'` lists your edits, newest first (`label`, `changes`, `undoneBy`).
* `otto call edits.undoSession '{"session": "<session>"}'` undoes all of them, newest first. It stops at the first edit that
  was changed again afterwards (by the user or another session) and reports it in `blocked`; `remaining` says how many are left.
* `edits.undoOne {"editId"}` undoes one specific edit (when `edits.history` marks it `undoable`: nothing it changed was edited again since).
* `edits.undo` undoes the most recent safe edit of anyone; prefer `edits.undoSession` for your own work.
* The user sees all of this in the app's **History** panel (who changed what), and can undo your session there too.
* **Not part of the edit history** (so not undone by `edits.undoSession`): newly created samples, sources and tracks
  (registration, separation results, reimports), finished jobs, exported files.
  Created samples can only be removed with `samples.delete`, which needs the user's confirmation — so plan before creating,
  and keep the ids you created (`samples.createPlanned` returns them) to report to the user.
* Dangerous commands (overview, "Commands that cannot be undone") are never undoable.
