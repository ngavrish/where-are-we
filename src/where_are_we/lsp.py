"""Serve the map over LSP, so an editor's go to definition and workspace
symbol search answer from the map instead of grepping or waiting on a real
language server.

`textDocument/definition` reads the word under the cursor straight off disk,
looks it up in the map's own index of what was declared where (the same
index `mcp.py`'s `defines` tool reads), and hands back a location. No
parsing of the editor's document beyond finding the identifier at a point:
the map already did the parsing once, at build time.

    where-are-we --lsp --out /runs/APF-1934 --repo .

Speaks JSON-RPC over stdin and stdout with `Content-Length` framing, the LSP
wire format. No dependencies, like the rest of this project.
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import unquote, urlparse

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# _definitions_for renders each hit as "- `name` <em dash> path:line"; the
# em dash is written as an escape here rather than the character itself so a
# grep for the character in new prose does not also flag a format this
# module only reads, never writes.
_HIT = re.compile(r"^- `(?P<name>.+)` \u2014 (?P<where>.+)$")

_ERR_METHOD_NOT_FOUND = -32601


def _uri_to_path(uri: str) -> str:
    return unquote(urlparse(uri).path)


def _identifier_at(line: str, character: int) -> str:
    for m in _IDENT.finditer(line):
        if m.start() <= character < m.end():
            return m.group(0)
    return ""


def _split_where(where: str):
    """Split 'path:line' into (path, line). A path can hold colons of its
    own, so this splits on the last one, where the line number lives."""
    path, sep, line = where.rpartition(":")
    if not sep or not line.isdigit():
        return None
    return path, int(line)


def _location(path: str, line: int, repo: str) -> dict:
    abspath = os.path.abspath(os.path.join(repo, path))
    pos = {"line": max(line - 1, 0), "character": 0}
    return {"uri": "file://" + abspath, "range": {"start": pos, "end": pos}}


def _definition(mapper_mod, map_path: str, repo: str, params: dict) -> list:
    text_doc = params.get("textDocument") or {}
    position = params.get("position") or {}
    path = _uri_to_path(text_doc.get("uri", ""))
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    line_no = position.get("line", 0)
    if not (0 <= line_no < len(lines)):
        return []
    name = _identifier_at(lines[line_no], position.get("character", 0))
    if not name:
        return []
    hits = mapper_mod._definitions_for(map_path, [name.lower()])
    locations = []
    for hit in hits:
        found = _HIT.match(hit)
        if not found:
            continue
        split = _split_where(found.group("where"))
        if split:
            locations.append(_location(split[0], split[1], repo))
    return locations


def _workspace_symbols(json_path: str, repo: str, params: dict) -> list:
    query = str(params.get("query") or "").lower()
    try:
        with open(json_path, encoding="utf-8") as fh:
            defs = (json.load(fh) or {}).get("definitions") or {}
    except (OSError, ValueError):
        return []
    names = sorted(n for n in defs if query in n.lower())
    out = []
    for name in names[:100]:
        split = _split_where(defs[name])
        if not split:
            continue
        out.append({"name": name, "kind": 12,
                    "location": _location(split[0], split[1], repo)})
    return out


def _read_message(stream) -> "dict | None":
    """One Content-Length framed message, or None at end of stream."""
    headers: dict = {}
    while True:
        line = stream.readline()
        if not line:
            return None  # stdin closed mid-headers: nothing more is coming
        line = line.rstrip(b"\r\n")
        if line == b"":
            break
        key, sep, value = line.partition(b":")
        if sep:
            headers[key.strip().lower()] = value.strip()
    try:
        length = int(headers.get(b"content-length", b"0"))
    except ValueError:
        return None
    if length <= 0:
        return None
    body = stream.read(length)
    if len(body) < length:
        return None  # truncated: stdin closed mid-body
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return None


def _write_message(obj: dict) -> None:
    body = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
    sys.stdout.buffer.flush()


def serve(out_dir: str, repo: str) -> int:
    """Read Content-Length framed requests until stdin closes or exit
    arrives. One request, one reply, no state kept across them: the same
    read-only shape as `mcp.serve`, framed for an editor instead of an
    agent."""
    from . import mapper

    map_path = os.path.join(out_dir, "framework_map.md")
    json_path = os.path.join(out_dir, "framework_map.json")
    stdin = sys.stdin.buffer

    while True:
        message = _read_message(stdin)
        if message is None:
            return 0
        method = message.get("method")
        ident = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            _write_message({"jsonrpc": "2.0", "id": ident, "result": {
                "capabilities": {"definitionProvider": True,
                                 "workspaceSymbolProvider": True},
                "serverInfo": {"name": "where-are-we"}}})
        elif method == "initialized":
            pass  # a notification: nothing to answer
        elif method == "textDocument/definition":
            result = _definition(mapper, map_path, repo, params)
            _write_message({"jsonrpc": "2.0", "id": ident, "result": result})
        elif method == "workspace/symbol":
            result = _workspace_symbols(json_path, repo, params)
            _write_message({"jsonrpc": "2.0", "id": ident, "result": result})
        elif method == "shutdown":
            _write_message({"jsonrpc": "2.0", "id": ident, "result": None})
        elif method == "exit":
            return 0
        elif ident is not None:
            _write_message({"jsonrpc": "2.0", "id": ident, "error": {
                "code": _ERR_METHOD_NOT_FOUND,
                "message": f"method not found: {method}"}})
        # else: an unknown notification, with no id to reply to, is ignored
