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
import pathlib
import re
import sys
from urllib.parse import unquote, urlparse

# Top level, both ways round: `mapper` is the layer below this one and does
# not import back. This used to be an import inside `serve()`, because the
# facade re-exported the command line and the command line imported this
# module.
try:
    from . import mapper
except ImportError:  # run as a plain file, with no package around it
    import mapper  # type: ignore[no-redef]

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# definitions_for renders each hit as "- `name` <em dash> path:line"; the
# em dash is written as an escape here rather than the character itself so a
# grep for the character in new prose does not also flag a format this
# module only reads, never writes.
_HIT = re.compile(r"^- `(?P<name>.+)` \u2014 (?P<where>.+)$")

_ERR_METHOD_NOT_FOUND = -32601
_ERR_INVALID_PARAMS = -32602
_ERR_INTERNAL = -32603


class _BadParams(Exception):
    """A request's shape was wrong: reply -32602, do not touch the map."""


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
    # `Path.as_uri()` percent-encodes a space or a non-ASCII character; the
    # old "file://" + abspath concatenation left them raw, a URI no editor
    # could open.
    uri = pathlib.Path(abspath).as_uri()
    return {"uri": uri, "range": {"start": pos, "end": pos}}


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
    hits = mapper_mod.definitions_for(map_path, [name.lower()])
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


def _reply_error(code: int, message: str, ident) -> None:
    _write_message({"jsonrpc": "2.0", "id": ident,
                    "error": {"code": code, "message": message}})


def _dispatch(mapper, map_path: str, json_path: str, repo: str,
              method, ident, params) -> "bool | None":
    """One request. Returns True to end the session (an `exit` notification),
    otherwise None. Raises `_BadParams` for a malformed request."""
    if method == "initialize":
        _write_message({"jsonrpc": "2.0", "id": ident, "result": {
            "capabilities": {"definitionProvider": True,
                             "workspaceSymbolProvider": True},
            "serverInfo": {"name": "where-are-we"}}})
        return None
    if method == "initialized":
        return None  # a notification: nothing to answer
    if method in ("textDocument/definition", "workspace/symbol"):
        if not isinstance(params, dict):
            raise _BadParams("params must be an object")
    if method == "textDocument/definition":
        result = _definition(mapper, map_path, repo, params)
        _write_message({"jsonrpc": "2.0", "id": ident, "result": result})
    elif method == "workspace/symbol":
        result = _workspace_symbols(json_path, repo, params)
        _write_message({"jsonrpc": "2.0", "id": ident, "result": result})
    elif method == "shutdown":
        _write_message({"jsonrpc": "2.0", "id": ident, "result": None})
    elif method == "exit":
        return True
    elif ident is not None:
        _write_message({"jsonrpc": "2.0", "id": ident, "error": {
            "code": _ERR_METHOD_NOT_FOUND,
            "message": f"method not found: {method}"}})
    # else: an unknown notification, with no id to reply to, is ignored
    return None


def serve(out_dir: str, repo: str) -> int:
    """Read Content-Length framed requests until stdin closes or exit
    arrives. One request, one reply, no state kept across them: the same
    read-only shape as `mcp.serve`, framed for an editor instead of an
    agent.

    A malformed request never ends the session: its dispatch is wrapped so
    a bad shape gets -32602 and anything else gets -32603, and the loop
    reads the next frame either way. An editor that closes its end of the
    pipe mid-reply gets a quiet exit instead of a BrokenPipeError traceback.
    """
    map_path = os.path.join(out_dir, "framework_map.md")
    json_path = os.path.join(out_dir, "framework_map.json")
    stdin = sys.stdin.buffer

    try:
        while True:
            message = _read_message(stdin)
            if message is None:
                return 0
            if not isinstance(message, dict):
                continue  # not a JSON-RPC object; nothing sane to reply to
            method = message.get("method")
            ident = message.get("id")
            params = message.get("params")
            if params is None:
                params = {}
            try:
                if _dispatch(mapper, map_path, json_path, repo, method,
                             ident, params):
                    return 0
            except _BadParams as exc:
                _reply_error(_ERR_INVALID_PARAMS, str(exc), ident)
            except BrokenPipeError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep serving the pipe
                _reply_error(_ERR_INTERNAL, str(exc), ident)
    except BrokenPipeError:
        # The reader went away (an editor killed, `| head`). Redirect our
        # stdout to devnull first so the interpreter's own shutdown flush
        # does not raise the same error a second time on the way out.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
        return 0
