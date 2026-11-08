# Scripts: many calls at once

Single `otto call`s are good for exploring; for batch work (dozens of episodes, thousands of lines) write a Python script that uses one connection:

```sh
otto run my_script.py arg1 arg2
```

`otto run` runs your script with the app's own Python (it can `import ottosmasher` and has numpy) and passes it the workspace and session;
all changes of the script are recorded under one session (`--session` or `OTTO_AGENT_SESSION`).

```python
from ottosmasher.cli.client import LinkClient
from ottosmasher.core.errors import CoreError

with LinkClient.from_env() as c:
    for s in c.call("sources.list"):
        tl = c.call("textLayer.list", {"sourceId": s["id"]})
        print(s["episode"], len(tl["segments"]))
    job = c.call("speech.submit", {"entry": "samples", "ids": ["..."]})
```

* `c.call(command, params)` returns the result; business errors raise `CoreError` (`.code`, `.args_`).
* `c.request(...)` returns the raw response `{"ok", "r" | "e"}` without raising.
* `c.next_event(timeout)` returns the next event (`{"e": name, "d": data}`); to wait for a job, watch `job.updated` for its `id` and `status`,
  or simply use `otto wait job <id>` outside the script.
* To map a time from an external tool back to the source: `from ottosmasher.domain.mapping import Mapping; Mapping.of(m).to_source(t)`, where `m` is the `mapping` of a WAV export.
* Keeping one connection open through long external computations can let events pile up. For those, close it and use short calls, or `otto wait`.
* Commands that cannot be undone wait for the user's confirmation in scripts too (overview, "Commands that cannot be undone").

## Shells, pagination and binary results

Otto emits UTF-8. If the host decodes native output differently, set `$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)`. Save JSON with `otto call sources.list | Set-Content -Encoding utf8 sources.json`. Windows PowerShell 5.1 writes UTF-16LE with `>`; PowerShell 7.4+ preserves native stdout bytes when redirecting. These are different cases.

For complex JSON, especially in PowerShell, use a UTF-8 JSON file:

```powershell
@{ ids = @('sample-id'); } | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 params.json
& 'C:\path with spaces\otto.cmd' call samples.metrics '@params.json'
```

The CLI accepts a UTF-8 BOM. `-` reads JSON from stdin. Keep arrays intact when constructing PowerShell JSON, especially single-element arrays. For many calls, `otto run` keeps the arguments in Python.

```python
with LinkClient.from_env() as c:
    rows = list(c.iter_results("speech.alignResults", job["id"]))
```

`iter_results` supports `speech.alignResults`, `text.analyzeResults`, `f0.trackResults`; it reads through all pages, preserving failures. Raw calculation APIs default to 100 rows: read further pages to cover the job. CLI JSON encodes bytes as base64; Python LinkClient retains bytes (numpy.frombuffer directly).

Use `jobs.summaries` (offset/limit/session) for compact job lists, `jobs.get` for one full result, and `queuedAhead` for the number of earlier queued jobs on the same channel. `otto call ... --wait` and `otto wait` are quiet by default; `--progress` adds stderr progress. The final result is returned in full. `otto session --session ID` includes compact jobs and counts/latest IDs of created samples/assets; `--details` includes full job payloads. This view includes up to 200 edit-history entries. Use the existing deletion flow when tidying created objects.
