"""Feature environment worker: audio and explicit phone ranges in, immutable asset out."""

import json
import sys
from pathlib import Path

from ottosmasher.sample_flatten import flatten
from ottosmasher.workspace import write_json

p = Path(sys.argv[1])
request = json.loads(p.read_text())
write_json(p.with_suffix(".result.json"), flatten(request["path"], request["mode"], request["intervals"]))
