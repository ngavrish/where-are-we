"""What each command line flag does to the disk, so a guard can tell a read
from a write without running the command.

A pre-execution check (HOL Guard and the like) sees an argv and has to decide
whether to allow it. Left to guess, it either blocks `--ask`, which writes
nothing anyone cares about, or waves through `--install-hook`, which edits
`~/.claude/settings.json`. So the answer ships with the tool: one table, and
the functions that read it.

This module imports json and nothing else, so the table drags nothing behind
it and `--effects` costs no tree walk. That is a property of this file, not of
the import: `import where_are_we.effects` goes through the package's
`__init__`, which imports the mapper, so the cost of asking is the cost of
starting the tool at all. The same table ships beside the code as
`effects.json` for a guard that would rather read JSON than import Python;
that file is what `as_json()` prints, and a CI step fails when the two differ.
Regenerate it with
`where-are-we --effects --json > src/where_are_we/effects.json`.
"""

import json

SCHEMA = "where-are-we-effects/1"

# Least to most: a command's class is the highest class any of its flags
# carries, so a line that both answers a question and installs a hook is a
# writes-config line.
ORDER = ["read", "writes-map-dir", "writes-repo", "writes-config", "network"]

# Every flag the command line parser knows, and what it does:
#
#   read            answers from what is already there. It may append one
#                   line to `<out>/.wawe-ask.log`, the map directory's own
#                   record of what was asked; nothing in the repository, the
#                   home directory or the network is touched.
#   writes-map-dir  writes the map files and the parse cache under `--out`.
#   writes-repo     writes into the repository being mapped: a manifest, an
#                   agent file, the READMEs a directory is missing.
#   writes-config   writes where a tool other than this one reads: git's
#                   `.git/hooks`, `~/.claude/settings.json`,
#                   `~/.codex/config.toml`, a Cursor rule, a Gemini setting.
#   network         goes off this machine: a tracker fetch, a runs API.
EFFECTS = {
    "-h": "read",
    "--help": "read",
    "--repo": "read",
    "--product": "read",
    "--also": "read",
    "--rules": "read",
    "--for": "read",
    "--only": "read",
    "--skip": "read",
    "--max-lines": "read",
    "--quiet": "read",
    "--ask": "read",
    "--more": "read",
    "--defines": "read",
    "--at": "read",
    "--context": "read",
    "--rank": "read",
    "--files": "read",
    "--limit": "read",
    "--callers": "read",
    "--callees": "read",
    "--impact": "read",
    "--impact-depth": "read",
    "--affected": "read",
    "--changed": "read",
    # `--changed` runs `git diff --name-only` in the repository the map was
    # built from, which reads that checkout and writes nothing in it.
    "--affected-format": "read",
    "--affected-depth": "read",
    "--sections": "read",
    "--cost": "read",
    "--pointer": "read",
    "--mcp": "read",
    "--lsp": "read",
    "--corpus": "read",
    "--no-semantic": "read",
    "--effects": "read",
    "--json": "read",
    "--dry-run": "read",
    # `--diff` builds the map to compare against the one on disk, and a build
    # leaves its parse cache in `--out`.
    "--diff": "writes-map-dir",
    "--out": "writes-map-dir",
    "--html": "writes-map-dir",
    "--ctags": "writes-map-dir",
    "--force": "writes-map-dir",
    "--watch": "writes-map-dir",
    "--agent-file": "writes-repo",
    # `--export` answers out of a map already on disk, which would make it a
    # read; the file it writes is at whatever path the caller named. That is
    # the same arbitrary-path property `--agent-file` and `--docs` have, and
    # it gets the same class they do. Not `writes-config`, which is for the
    # flags that write where another tool reads by convention: this one
    # writes exactly where it was told and nowhere else.
    "--export": "writes-repo",
    "--init": "writes-repo",
    # `--docs` alone only says what it would write; `--docs write` creates the
    # files. One flag, one class, and the class is the one that writes.
    "--docs": "writes-repo",
    "--install-hook": "writes-config",
    # The five that fetch tickets. `--spec-source cmd`, the default, runs the
    # command `--spec-cmd` names, and that command is a tracker call; naming
    # any of the five is asking for one.
    "--specs": "network",
    "--spec-cmd": "network",
    "--spec-source": "network",
    "--spec-depth": "network",
    "--spec-limit": "network",
    # A runs API is read over HTTP.
    "--runs-api": "network",
}

# What each class means, in the file as well as on the screen: a guard reading
# `effects.json` is told what a `read` may still do, which until now only a
# human reading the README was.
NOTES = {
    "read": "answers from what is already there. The flags that answer from a "
            "map (--ask, --more, --callers, --callees, --impact, --defines, "
            "--at, --context, --affected, --changed, --rank, --sections, "
            "--cost) "
            "append one line to <out>/.wawe-ask.log unless WAWE_ASK_LOG=0; "
            "nothing else is written, and nothing outside <out> is.",
    "writes-map-dir": "writes the map files and the parse cache under --out.",
    "writes-repo": "writes into the repository being mapped: a manifest, an "
                   "agent file, the READMEs a directory has none of, and the "
                   "file --export was told to write, which is at whatever "
                   "path the caller named.",
    "writes-config": "writes where a tool other than this one reads: "
                     ".git/hooks, ~/.claude/settings.json, "
                     "~/.codex/config.toml, a Cursor rule, a Gemini setting.",
    "network": "goes off this machine: a tracker fetch, a runs API.",
}

# The flags a run returns on before it writes any map into `--out`. A command
# line that names none of them builds the map there, whatever else it says, so
# the floor of its class is writes-map-dir even when every flag on it is a
# read: `where-are-we --repo .` carries no write flag at all and writes three
# files into the current directory. `--specs` is in the set because it returns
# before the build: it writes spec_map.json and spec_map.md and no map.
NO_MAP_BUILD = frozenset({
    "-h", "--help", "--effects", "--dry-run", "--ask", "--more", "--callers",
    "--callees", "--impact", "--defines", "--at", "--rank", "--sections",
    "--pointer", "--mcp", "--lsp", "--init", "--install-hook", "--specs",
    "--cost", "--export", "--context", "--affected", "--changed",
})

# The pseudo flag `classify` reports when the floor above is what decided the
# class: no flag said "write the map", the command line simply builds one.
BUILD = "build"

UNKNOWN = "unknown"


def worst(classes) -> str:
    """The highest class in `classes`, or `read` for nothing at all."""
    found = [c for c in classes if c in ORDER]
    return max(found, key=ORDER.index) if found else ORDER[0]


def option_strings(parser) -> list[str]:
    """Every option one argparse parser knows, sorted.

    argparse keeps its actions in `_actions` and offers no public accessor;
    this is the same list `--help` is rendered from.
    """
    return sorted({o for a in parser._actions for o in a.option_strings})


def flags_in(argv, known) -> list[str]:
    """The options one command line names, in the order it names them.

    `--out=/tmp/m` is `--out`, a unique prefix stands for the whole flag the
    way argparse resolves it, a bare `--` ends the options, and a token that
    is not an option this parser knows is returned as written so the caller
    can say so rather than quietly calling it a read.
    """
    known = list(known)
    out = []
    for token in argv:
        if token == "--":
            break
        if not token.startswith("-") or token == "-":
            continue
        name = token.split("=", 1)[0]
        if name not in known and name.startswith("--"):
            hits = [k for k in known if k.startswith(name)]
            if len(hits) == 1:
                name = hits[0]
        if name not in out:
            out.append(name)
    return out


def classify(argv, known=None) -> tuple[str, list[tuple[str, str]]]:
    """`(class, reasons)` for one command line.

    `reasons` is `(flag, class)` per option named, in the order given, plus
    `("build", "writes-map-dir")` when nothing on the line stops the run from
    building a map into `--out`. An option the table does not hold is
    reported as `unknown` and left out of the class, so a guard reading this
    sees a name it has to decide about rather than a silent `read`.
    """
    flags = flags_in(argv, known if known is not None else sorted(EFFECTS))
    reasons = [(f, EFFECTS.get(f, UNKNOWN)) for f in flags]
    if not any(f in NO_MAP_BUILD for f in flags):
        reasons.append((BUILD, "writes-map-dir"))
    return worst(c for _f, c in reasons), reasons


def table() -> dict:
    """The manifest, exactly as `effects.json` holds it."""
    return {"schema": SCHEMA, "flags": dict(sorted(EFFECTS.items())),
            "order": list(ORDER), "notes": dict(NOTES)}


def as_json() -> str:
    """The manifest as JSON, one text for the file and for `--effects
    --json`, so the two can be compared byte for byte."""
    return json.dumps(table(), indent=2) + "\n"


def as_text() -> str:
    """The manifest as lines: the schema, the order, then one flag per line
    with its class, sorted."""
    width = max(len(f) for f in EFFECTS)
    lines = [SCHEMA, " < ".join(ORDER), ""]
    lines += [f"{flag:<{width}}  {cls}" for flag, cls in sorted(EFFECTS.items())]
    lines.append("")
    lines += [f"{cls}: {NOTES[cls]}" for cls in ORDER]
    lines.append("")
    lines.append("A command line naming none of "
                 + ", ".join(sorted(NO_MAP_BUILD))
                 + " builds the map into --out.")
    return "\n".join(lines) + "\n"
