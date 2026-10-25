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
* Commands that cannot be undone wait for the owner's confirmation in scripts too (overview rule 6).
