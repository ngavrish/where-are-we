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
import shlex
import subprocess
from typing import Any, Callable

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

# What a GitHub owner or repo name is allowed to look like. `_github_owner_repo`
# reads both off the `origin` remote and hands them straight to a `shell=True`
# command; without this check, an origin crafted to fail the pattern below
# would instead smuggle shell syntax into that command.
GITHUB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# GitHub spells a key "#12", never as a bare number: a bare number is as
# common in a body as a test count, but nothing else writes "#12" on purpose.
# The captured group is the part `gh issue view` actually wants; walk() reads
# it back out to build the fetch, and writes the whole match ("#12") onto the
# ticket so links_of and digest see the same shape as every other source.
GITHUB_KEY = re.compile(r"(?<![\w/])#(\d+)\b")

# The GraphQL body Linear's API takes on stdin, one ticket at a time. `{key}`
# is substituted the same way the command's own `{key}` would be, just kept
# out of the command line because a query this shaped does not belong there.
LINEAR_QUERY = (
    '{"query":"{ issue(id: \\"{key}\\") { identifier title description '
    'state { name } url parent { identifier } children { nodes { identifier } } '
    'relations { nodes { relatedIssue { identifier } } } '
    'comments { nodes { body } } } }"}'
)


def fetch(command: str, key: str, timeout: int = 60,
          stdin: str | None = None) -> dict[str, Any] | None:
    """One ticket, through whatever the caller uses to reach its tracker.

    `stdin` is fed to the command as-is (Linear's GraphQL body goes this way,
    since it does not belong on a command line).
    """
    try:
        out = subprocess.run(command.replace("{key}", key), shell=True,
                             capture_output=True, text=True, timeout=timeout,
                             input=stdin)
    except subprocess.TimeoutExpired:
        return {"key": key, "error": f"the tracker did not answer in {timeout}s"}
    if out.returncode != 0:
        return {"key": key, "error": (out.stderr or out.stdout).strip()[:300]}
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"key": key, "error": "the fetcher did not return JSON"}


def links_of(ticket: dict[str, Any], key_re: re.Pattern = KEY) -> list[str]:
    """Every ticket key this one points at, however the tracker spells it.

    Read out of the whole document rather than out of the fields a particular
    tracker happens to use: a key mentioned in a comment is a link somebody made
    on purpose, and no schema records it. The whole match is the key, even when
    `key_re` also captures a group for its own use (GitHub's does, for the
    fetch); a group changes what `findall` returns, so this walks matches
    instead and keeps `group(0)`.
    """
    text = json.dumps(ticket, ensure_ascii=False)
    return sorted(set(m.group(0) for m in key_re.finditer(text)))


def command_for(source: str, repo: str) -> tuple[str, re.Pattern]:
    """A ready-made command for a tracker this tool already knows how to reach.

    `source` is "github" or "linear". `repo` is a local checkout; for github
    it supplies the `origin` remote that names the repository, since `gh`
    needs owner/name and this tool otherwise has no notion of "the repo".
    Returns the same `(command, key_re)` shape a caller would otherwise write
    by hand for `--spec-cmd`, so `walk` never has to know which source it is.
    """
    if source == "github":
        owner_repo = _github_owner_repo(repo)
        cmd = (f"gh issue view {{key}} --repo {shlex.quote(owner_repo)} "
               "--json number,title,body,state,labels,url,comments")
        return cmd, GITHUB_KEY
    if source == "linear":
        cmd = ('[ -n "$LINEAR_API_KEY" ] || '
               '{ echo "LINEAR_API_KEY is not set" >&2; exit 1; }\n'
               'curl -sS -H "Authorization: $LINEAR_API_KEY" '
               '-H "Content-Type: application/json" '
               'https://api.linear.app/graphql -d @-')
        return cmd, KEY
    raise ValueError(f"unknown spec source: {source!r} (want github or linear)")


def linear_query(key: str) -> str:
    """The GraphQL body for one Linear issue, ready for `curl -d @-`."""
    return LINEAR_QUERY.replace("{key}", key)


def _github_owner_repo(repo: str) -> str:
    """The `owner/name` a `gh --repo` flag wants, read off `origin`.

    Handles both remote forms git actually hands out: `git@github.com:o/n.git`
    and `https://github.com/o/n`.
    """
    out = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"],
                         capture_output=True, text=True, timeout=10)
    url = out.stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m or not GITHUB_NAME.match(m.group(1)) or not GITHUB_NAME.match(m.group(2)):
        raise ValueError("origin is not a github remote: "
                          f"{url or out.stderr.strip() or '(no origin set)'}")
    return f"{m.group(1)}/{m.group(2)}"


def walk(command: str, roots: list[str], depth: int = DEFAULT_DEPTH,
         limit: int = DEFAULT_LIMIT, say=None, key_re: re.Pattern = KEY,
         stdin: str | Callable[[str], str] | None = None) -> dict[str, Any]:
    """Everything within `depth` hops of the roots, fetched once each.

    The limit is a stop, not a target: a tracker is a graph and a graph is
    happy to hand over a thousand tickets. Whatever it stops at is said out
    loud — a map that quietly ends is worse than a small one.

    `key_re` is the pattern a key matches. Most trackers fetch by the same
    string a key is written as, but not every one does: GitHub's key is
    written "#12" and fetched as "12", so a source like that captures the part
    to fetch with in group 1, and this reads it back out and writes the whole
    key onto the ticket afterwards, so links_of and digest never have to know.

    `stdin` feeds the fetcher's standard input, for a tracker whose query does
    not belong on a command line (Linear's GraphQL body). It is a string sent
    to every fetch as-is, or a callable of the key that builds one per ticket.
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
        fetch_key = key
        if key_re.groups:
            m = key_re.match(key)
            if m:
                fetch_key = m.group(1)
        one_stdin = stdin(key) if callable(stdin) else stdin
        ticket = fetch(command, fetch_key, stdin=one_stdin)
        if ticket is None:
            continue
        if isinstance(ticket, dict) and key_re.groups:
            ticket["key"] = key
        seen[key] = ticket
        if say:
            say(f"  {key} ({len(seen)} so far)")
        found = [k for k in links_of(ticket, key_re) if k != key]
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
