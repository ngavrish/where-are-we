#!/usr/bin/env python3
"""Live smoke check for `where-are-we --lsp`, run against a map already
built with `--force` (this script does not build one). Talks the actual
Content-Length wire protocol to the actual `where-are-we` executable,
prints every reply, and exits non-zero if any of the three checks the map
promises for `--lsp` fail: initialize's capabilities, a go-to-definition
hit, and a workspace symbol hit.

Usage:

    where-are-we --repo REPO --out OUT --force
    python docs/examples/lsp-smoke.py REPO OUT

REPO must hold `billing.py` (`def charge(x): return x`) and `api.py`
(`from billing import charge`, then `def pay(): return charge(1)`), the
same fixture the brief for this feature specifies, so the position and
query below land on the same identifier every time.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _frame(obj: dict) -> bytes:
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def _unframe(data: bytes) -> list:
    out = []
    while data:
        head, _, rest = data.partition(b"\r\n\r\n")
        length = int(head.split(b":")[1])
        out.append(json.loads(rest[:length]))
        data = rest[length:]
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: lsp-smoke.py REPO OUT", file=sys.stderr)
        return 2
    repo, out = sys.argv[1], sys.argv[2]

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": f"file://{repo}/api.py"},
                    "position": {"line": 3, "character": 13}}},
        {"jsonrpc": "2.0", "id": 3, "method": "workspace/symbol",
         "params": {"query": "cha"}},
        {"jsonrpc": "2.0", "id": 4, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    stdin = b"".join(_frame(m) for m in messages)

    proc = subprocess.run(
        ["where-are-we", "--out", out, "--repo", repo, "--lsp"],
        input=stdin, capture_output=True, timeout=30)
    if proc.stderr:
        sys.stderr.write(proc.stderr.decode(errors="replace"))

    replies = {r["id"]: r for r in _unframe(proc.stdout) if "id" in r}
    for ident in sorted(replies):
        print(f"reply {ident}: {json.dumps(replies[ident])}")

    ok = True

    caps = replies.get(1, {}).get("result", {}).get("capabilities", {})
    if caps.get("definitionProvider") is not True or \
            caps.get("workspaceSymbolProvider") is not True:
        print("FAIL: initialize did not advertise both capabilities",
              file=sys.stderr)
        ok = False

    locations = replies.get(2, {}).get("result") or []
    if not (locations and locations[0]["uri"].endswith("/billing.py")
            and locations[0]["range"]["start"]["line"] == 0):
        print("FAIL: definition for charge did not point at billing.py:1",
              file=sys.stderr)
        ok = False

    symbols = [s["name"] for s in replies.get(3, {}).get("result") or []]
    if symbols != ["charge"]:
        print(f"FAIL: workspace/symbol 'cha' returned {symbols!r}, "
              "expected ['charge']", file=sys.stderr)
        ok = False

    if proc.returncode != 0:
        print(f"FAIL: where-are-we --lsp exited {proc.returncode}",
              file=sys.stderr)
        ok = False

    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
