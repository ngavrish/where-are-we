"""Serve the map over MCP, so asking it does not cost a shell transcript.

The command line works and is the wrong shape for an agent. Asked through a
shell, the question and the whole answer land in the conversation and are re-read
on every turn after — and the agent has to remember what the command is called,
which one of them did not: it spent a turn on `which where-are-us where-are-we`.

Through MCP the question is an argument and the answer is a tool result. Same
index, same regexes, same JSON file underneath. This module holds no model and
makes no network call; it reads what the mapper already wrote and hands back what
matches.

    where-are-we --mcp --out /runs/APF-1934

Speaks JSON-RPC over stdin and stdout, which is all MCP is on a pipe. No
dependencies, like the rest of this project.
"""

from __future__ import annotations

import json
import os
import sys

PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "ask",
        "description": (
            "Search this codebase's map for words or a name. Returns the exact "
            "file and line where a name is declared, then the sections of the "
            "map that mention the words — step phrases, page objects, features, "
            "and the ticket with everything it links to. Use this instead of "
            "grepping the repository: the map was built from the same files and "
            "is one lookup rather than a search."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "words": {
                    "type": "string",
                    "description": "a name, a phrase, or several words",
                },
            },
            "required": ["words"],
        },
    },
    {
        "name": "sections",
        "description": "List what the map contains, by section heading.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "defines",
        "description": (
            "Where a name is declared, exactly: file and line. Functions, "
            "classes, constants, types, step phrases, scenario names — from the "
            "code under test as well as the suite."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def _reply(result: dict, ident) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident,
                                 "result": result}) + "\n")
    sys.stdout.flush()


def _text(body: str) -> dict:
    return {"content": [{"type": "text", "text": body}]}


def serve(out_dir: str) -> int:
    """Read requests until stdin closes. One request, one answer, no state."""
    from . import mapper

    map_path = os.path.join(out_dir, "framework_map.md")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        method, ident = request.get("method"), request.get("id")
        params = request.get("params") or {}

        if method == "initialize":
            _reply({"protocolVersion": PROTOCOL,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "where-are-we",
                                   "version": "0.6.0"}}, ident)
        elif method == "tools/list":
            _reply({"tools": TOOLS}, ident)
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "ask":
                answer = mapper.ask(map_path, str(args.get("words") or ""))
                spec = os.path.join(out_dir, "spec_map.md")
                if os.path.exists(spec):
                    answer += "\n\n" + mapper.ask(spec, str(args.get("words") or ""))
                _reply(_text(answer), ident)
            elif name == "defines":
                hits = mapper._definitions_for(map_path,
                                               [str(args.get("name") or "").lower()])
                _reply(_text("\n".join(hits) if hits
                             else f"no declaration of {args.get('name')!r} in the map"),
                       ident)
            elif name == "sections":
                try:
                    with open(map_path, encoding="utf-8") as fh:
                        heads = [ln.rstrip() for ln in fh if ln.startswith("## ")]
                    _reply(_text("\n".join(heads)), ident)
                except OSError as exc:
                    _reply(_text(f"no map at {map_path}: {exc}"), ident)
            else:
                _reply(_text(f"no tool named {name!r}"), ident)
        elif ident is not None:
            _reply({}, ident)
    return 0
