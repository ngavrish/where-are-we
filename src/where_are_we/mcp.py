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

try:
    from . import __version__
except ImportError:  # run as a plain file, with no package around it
    from __init__ import __version__  # type: ignore[no-redef]

try:
    from .ask import log_answer
except ImportError:  # run as a plain file, with no package around it
    from ask import log_answer  # type: ignore[no-redef]

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
            "is one lookup rather than a search. Ask everything you want to "
            "know at once: `words` takes a list, and a list is one turn where "
            "seven separate calls were seven."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "words": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": ("a name, a phrase, or several words — or a "
                                    "list of them, answered in one call"),
                },
            },
            "required": ["words"],
        },
    },
    {
        "name": "find",
        "description": (
            "Find a phrase anywhere in the indexed files, with the file and line "
            "of every hit. This is what a grep across the repository was for: the "
            "same files were already walked to build the map, so the answer is a "
            "lookup rather than a search. Use it for text — a step phrase, a "
            "scenario title, a label — and `defines` for a name. `phrase` takes "
            "a list: ask for every phrase you need in one call rather than one "
            "per turn."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "phrase": {"type": ["string", "array"],
                           "items": {"type": "string"},
                           "description": ("text to find, or a list of texts; "
                                           "case is ignored")},
                "limit": {"type": "integer",
                          "description": "how many hits to return (default 40)"},
            },
            "required": ["phrase"],
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
            "code under test as well as the suite. `name` takes a list; ask for "
            "all of them at once."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": ["string", "array"],
                                    "items": {"type": "string"}}},
            "required": ["name"],
        },
    },
]


def _reply(result: dict, ident) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident,
                                 "result": result}) + "\n")
    sys.stdout.flush()


def _each(value) -> list:
    """One argument or several. A list is one turn where seven calls were seven.

    Watched on APF-1934: a branch asked the map seven times in a row, then twice
    more, then twice more — thirty-four lookups in one session, each a round
    trip through the model at a hundred and fifty thousand tokens of context.
    Nothing about the questions needed the previous answer; they were simply the
    only shape the tool had.
    """
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if str(x).strip()]
    text = str(value or "").strip()
    return [text] if text else []


# What one call may put into the conversation, in characters. It is a budget for
# the call, not for each question in it: batching without one turns a saving into
# a multiplier — five phrases at the old per-question size would have been thirty
# thousand tokens arriving in a single answer, and every turn after that one pays
# for them again. Measured on APF-1934, `ask` alone was adding 9,808 tokens per
# call at two maps of twelve thousand characters each.
_ANSWER_BUDGET = 12000
# Hits, not characters, and the same reasoning: forty per phrase across a list of
# six is two hundred and forty lines nobody asked for as a block.
_HIT_BUDGET = 40


def _share(budget: int, n: int, floor: int) -> int:
    """A batch splits the budget it would have spent on one question."""
    return max(floor, budget // max(1, n))


def _joined(pairs) -> str:
    """Answers labelled by their question, so a batch stays readable.

    A single question keeps its bare answer: labelling one thing is noise.
    """
    pairs = list(pairs)
    if len(pairs) == 1:
        return pairs[0][1]
    return "\n\n".join(f"### {q}\n{a}" for q, a in pairs)


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
                                   "version": __version__}}, ident)
        elif method == "tools/list":
            _reply({"tools": TOOLS}, ident)
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "ask":
                spec = os.path.join(out_dir, "spec_map.md")
                has_spec = os.path.exists(spec)

                def _ask_one(words: str, room: int) -> str:
                    # Two maps, so the room is split between them rather than
                    # spent twice: the framework map and the spec map each used
                    # to return a full allowance, doubling every answer.
                    each = room // 2 if has_spec else room
                    answer = mapper.ask(map_path, words, each)
                    if has_spec:
                        answer += "\n\n" + mapper.ask(spec, words, each)
                    # The MCP is how sessions actually ask; leaving the
                    # semantic tail on the CLI alone gave meaning to the one
                    # caller nobody uses.
                    # The tail shares the answer's room rather than adding to it:
                    # a third of the room at most, and never more than is left.
                    # meaning_tail(room=0) is not safe — its header line is
                    # written before the room check, so it can come back
                    # non-empty even at room=0; guarded here instead.
                    left = max(room - len(answer), 0)
                    if left:
                        answer += mapper.meaning_tail(out_dir, words, answer,
                                                      room=min(room // 3, left))
                    return answer

                asked = _each(args.get("words")) or [""]
                room = _share(_ANSWER_BUDGET, len(asked), 1500)
                pairs = []
                for w in asked:
                    a = _ask_one(w, room)
                    log_answer(out_dir, "ask", w, a, room)
                    pairs.append((w, a))
                _reply(_text(_joined(pairs)), ident)
            elif name == "defines":
                wanted = _each(args.get("name"))
                # One pass over the map for the whole list: _definitions_for
                # already takes several names, and reading the map once per name
                # is the cost this batching exists to remove.
                hits = mapper._definitions_for(map_path,
                                               [w.lower() for w in wanted])
                answer = ("\n".join(hits) if hits
                          else "no declaration of "
                               + ", ".join(repr(w) for w in wanted)
                               + " in the map")
                log_answer(out_dir, "defines", ", ".join(wanted), answer,
                           len(answer))
                _reply(_text(answer), ident)
            elif name == "find":
                phrases = _each(args.get("phrase")) or [""]
                limit = int(args.get("limit") or _HIT_BUDGET)
                room = _share(limit, len(phrases), 5)
                pairs = []
                for p in phrases:
                    a = mapper.find_text(out_dir, p, room)
                    log_answer(out_dir, "find", p, a, room)
                    pairs.append((p, a))
                _reply(_text(_joined(pairs)), ident)
            elif name == "sections":
                try:
                    from .ask import map_heads
                    answer = "\n".join(map_heads(map_path))
                    log_answer(out_dir, "sections", "", answer, len(answer))
                    _reply(_text(answer), ident)
                except OSError as exc:
                    _reply(_text(f"no map at {map_path}: {exc}"), ident)
            else:
                _reply(_text(f"no tool named {name!r}"), ident)
        elif ident is not None:
            _reply({}, ident)
    return 0
