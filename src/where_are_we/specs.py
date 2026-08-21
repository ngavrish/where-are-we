"""Map the specifications the way the code is mapped: once, to a file.

A codebase is not the only thing an agent gropes around in. The other is the
tracker — the ticket, its parents, the tickets it links to and the ones that
mention it — and it gropes there the same way, for the same reason: it has no
map, so it asks, and asks again.

Measured on one run of a real pipeline: sixteen tickets, fetched over and over.
One agent pulled fourteen neighbours to understand the task; the next agent
pulled the same fourteen again, because a session cannot see another session's
memory. Three of them were fetched three times inside a single session, since
finding an answer already in a conversation costs more than asking for it fresh.
Every one of those answers — full JSON, comments included — then sat in the
context for ever, and every later turn paid to re-read it.

So: walk the tracker once, write what was found to a file, and let sessions carry
the path.

This module knows nothing about any tracker. It is handed a command that turns a
ticket key into JSON and it walks from there, which is the same contract as the
rest of this project: the tool indexes, the caller supplies the source.

    where-are-we --specs APF-1934 --spec-cmd 'python3 fetch.py {key}'
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

# How far from the starting ticket to walk. Two hops reaches a parent's other
# children — the sibling work that explains why a ticket is worded as it is —
# and stops before the whole project arrives.
DEFAULT_DEPTH = int(os.getenv("WAWE_SPEC_DEPTH", "2"))

# How many tickets to fetch at most. A stop, not a target: a tracker is a graph
# and a graph will hand over a thousand tickets if asked, each one a document
# with comments. Whatever is left out is named in the map, because a map that
# quietly ends is worse than a small one — a small one that says so can be asked
# to grow.
DEFAULT_LIMIT = int(os.getenv("WAWE_SPEC_LIMIT", "60"))

# Keys look like PROJ-123 in every tracker worth the name; a bare number is not
# a key and matching one turns every "fixed 42 tests" into a fetch.
KEY = re.compile(r"\b[A-Z][A-Z0-9_]{1,9}-\d+\b")


def fetch(command: str, key: str, timeout: int = 60) -> dict[str, Any] | None:
    """One ticket, through whatever the caller uses to reach its tracker."""
    try:
        out = subprocess.run(command.replace("{key}", key), shell=True,
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"key": key, "error": f"the tracker did not answer in {timeout}s"}
    if out.returncode != 0:
        return {"key": key, "error": (out.stderr or out.stdout).strip()[:300]}
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"key": key, "error": "the fetcher did not return JSON"}


def links_of(ticket: dict[str, Any]) -> list[str]:
    """Every ticket key this one points at, however the tracker spells it.

    Read out of the whole document rather than out of the fields a particular
    tracker happens to use: a key mentioned in a comment is a link somebody made
    on purpose, and no schema records it.
    """
    text = json.dumps(ticket, ensure_ascii=False)
    return sorted(set(KEY.findall(text)))


def walk(command: str, roots: list[str], depth: int = DEFAULT_DEPTH,
         limit: int = DEFAULT_LIMIT, say=None) -> dict[str, Any]:
    """Everything within `depth` hops of the roots, fetched once each.

    The limit is a stop, not a target: a tracker is a graph and a graph is
    happy to hand over a thousand tickets. Whatever it stops at is said out
    loud — a map that quietly ends is worse than a small one.
    """
    seen: dict[str, Any] = {}
    edges: dict[str, list[str]] = {}
    frontier = [(k, 0) for k in roots]
    dropped: list[str] = []

    while frontier:
        key, hop = frontier.pop(0)
        if key in seen:
            continue
        if len(seen) >= limit:
            dropped.append(key)
            continue
        ticket = fetch(command, key)
        if ticket is None:
            continue
        seen[key] = ticket
        if say:
            say(f"  {key} ({len(seen)} so far)")
        found = [k for k in links_of(ticket) if k != key]
        edges[key] = found
        if hop < depth:
            frontier += [(k, hop + 1) for k in found if k not in seen]

    return {"roots": roots, "depth": depth, "tickets": seen, "links": edges,
            "not_fetched": sorted(set(dropped))}


def digest(spec: dict[str, Any]) -> str:
    """The map as something to read and to grep.

    Text as well as JSON for the same reason the code map is: a reader wants the
    shape, and grep wants lines.
    """
    tickets = spec["tickets"]
    lines = [
        "# Spec map",
        "",
        f"{len(tickets)} ticket(s) from {', '.join(spec['roots'])}, "
        f"{spec['depth']} hop(s) out. Fetched once — read from here rather than "
        "asking the tracker again.",
        "",
    ]
    if spec.get("not_fetched"):
        lines += [f"Not fetched (the walk stopped at its limit): "
                  f"{', '.join(spec['not_fetched'][:20])}", ""]

    lines += ["## Tickets", ""]
    for key, ticket in tickets.items():
        if not isinstance(ticket, dict):
            continue
        if ticket.get("error"):
            lines.append(f"- `{key}` — could not be read: {ticket['error']}")
            continue
        fields = ticket.get("fields") if isinstance(ticket.get("fields"), dict) else ticket
        summary = str(fields.get("summary") or ticket.get("summary") or "").strip()
        status = fields.get("status")
        if isinstance(status, dict):
            status = status.get("name")
        kind = fields.get("issuetype")
        if isinstance(kind, dict):
            kind = kind.get("name")
        bits = " · ".join(str(x) for x in (kind, status) if x)
        lines.append(f"- `{key}` — {summary}" + (f" ({bits})" if bits else ""))
    lines.append("")

    lines += ["## What links to what", ""]
    for key, found in spec["links"].items():
        if found:
            lines.append(f"- `{key}` → {', '.join(f'`{k}`' for k in found)}")
    lines += ["", "## The text, ticket by ticket", "",
              "Everything the tracker returned, so a requirement can cite the "
              "paragraph it came from instead of a memory of it.", ""]
    for key, ticket in tickets.items():
        lines.append(f"### {key}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(ticket, ensure_ascii=False, indent=2)[:20000])
        lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"
