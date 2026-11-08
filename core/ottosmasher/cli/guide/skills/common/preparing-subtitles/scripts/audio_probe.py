# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp"]
# ///
"""Run real audio-mcp calls without editing the host agent's MCP configuration.

uv run audio_probe.py requests.json results.json
Requests: [{"name":"audio_view", "arguments":{"path":"short.wav", "kind":"both"}},
           {"name":"audio_transcribe", "arguments":{"path":"short.wav", "language":"ja"}}]
Use short prepared clips. First transcription may download a ~1.6 GB model.
This helper runs the local MCP server, not Otto. Errors remain errors.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys


async def run(requests, output):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command="uvx", args=["--from", "audio-mcp[speech]==0.4.0", "audio-mcp"],
                                   env={**os.environ, "AUDIO_MCP_WHISPER_MODEL": "turbo"})
    results = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for request in requests:
                response = await session.call_tool(request["name"], request["arguments"])
                wire = response.model_dump(mode="json")
                images = []
                for index, block in enumerate(wire.get("content", [])):
                    if block.get("type") == "image":
                        suffix = ".jpg" if block.get("mimeType") == "image/jpeg" else ".png"
                        path = output.with_name(f"{output.stem}-{len(results)}-{index}{suffix}")
                        path.write_bytes(base64.b64decode(block["data"], validate=True))
                        images.append(str(path.resolve()))
                results.append({"request": request, "response": wire, "images": images})
                temp = output.with_suffix(output.suffix + ".tmp")
                temp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(output)
                print(json.dumps({"tool": request["name"], "isError": bool(getattr(response, "isError", getattr(response, "is_error", False))), "images": images}, ensure_ascii=False), flush=True)
    return 1 if any(r["response"].get("isError") or r["response"].get("is_error") for r in results) else 0


if __name__ == "__main__":
    requests = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    raise SystemExit(asyncio.run(run(requests, Path(sys.argv[2]))))
