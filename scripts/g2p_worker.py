"""Small JSON entry point; one tsqyomi/model lifetime per input batch."""
import json
import sys
from pathlib import Path
from ottosmasher.g2p_frontend import generate, compile_dictionary
from ottosmasher.workspace import write_json

request = json.loads(Path(sys.argv[1]).read_text())
if request.get('operation') == 'compile':
    result = compile_dictionary(request['text'], request['folder'])
else:
    result = [generate(text, dictionary=request.get('dictionary')) for text in request['texts']]
write_json(Path(sys.argv[2]), result)
