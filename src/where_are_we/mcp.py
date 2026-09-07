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
    from . import graph
    from .ask import (AFFECTED_BUDGET, AT_BUDGET, CONTEXT_BUDGET,
                       IMPACT_MAX_DEPTH, MCP_SELECTORS, RANK_LIMIT,
                       affected_tool_answer, at, context, file_list,
                       log_answer, callees_line, callers, impact, map_heads,
                       rank_lines)
except ImportError:  # run as a plain file, with no package around it
    import graph  # type: ignore[no-redef]
    from ask import (AFFECTED_BUDGET, AT_BUDGET,  # type: ignore[no-redef]
                     CONTEXT_BUDGET, IMPACT_MAX_DEPTH, MCP_SELECTORS,
                     RANK_LIMIT, affected_tool_answer, at, context, file_list,
                     log_answer, callees_line, callers, impact, map_heads,
                     rank_lines)

# Top level, both ways round: `mapper` is the layer below this one and does
# not import back. This and the `map_heads` above used to be imports inside
# functions, because the facade re-exported the command line and the command
# line imported this module.
try:
    from . import mapper
except ImportError:  # run as a plain file, with no package around it
    import mapper  # type: ignore[no-redef]

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
                "files": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": ("the files you are working in: rows "
                                    "naming one of them are printed first "
                                    "inside every section, the rest follow. "
                                    "A path or a directory prefix, relative "
                                    "to the repository root"),
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
        "name": "more",
        "description": (
            "Fetch what an answer left out, by the handle it printed. Every "
            "place `ask` and `find` cut a list short they end with one, in "
            "parentheses: `… 37 more matching rows (more:rows:step-phrases:"
            "invoice:12)`. Pass that string here and the rest of that same "
            "list comes back, continuing where the answer stopped, with the "
            "next handle when there is still more after it. Use it instead of "
            "asking the same question again at a bigger budget: this returns "
            "the part you have not seen rather than the part you have. "
            "`handle` takes a list."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handle": {"type": ["string", "array"],
                           "items": {"type": "string"},
                           "description": ("a handle an answer printed, or a "
                                           "list of them")},
            },
            "required": ["handle"],
        },
    },
    {
        "name": "sections",
        "description": "List what the map contains, by section heading.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "callers",
        "description": (
            "Who calls a function or step, by name: every `<file>:<func>` "
            "whose call graph mentions it. Reads the same call graphs `ask` "
            "draws its 'Called by' block from, across Python, TypeScript, "
            "JavaScript and Go, and behave step functions. Cross-file only: "
            "a call from within the same file it is defined in is not "
            "counted. Matching is case-sensitive and exact, like the "
            "identifier itself. `name` takes a list; ask for several "
            "callees in one call."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": ["string", "array"],
                                    "items": {"type": "string"}}},
            "required": ["name"],
        },
    },
    {
        "name": "callees",
        "description": (
            "What a function calls, the other direction of `callers`: every "
            "callee of the functions named this, each with the file it is "
            "defined in. Same graphs, same languages, cross-file only: a "
            "call to a function defined in the same file is not in them. "
            "Matching is case-sensitive and exact. `name` takes a list."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": ["string", "array"],
                                    "items": {"type": "string"}}},
            "required": ["name"],
        },
    },
    {
        "name": "impact",
        "description": (
            "The blast radius of a name: every `<file>:<func>` that reaches "
            "it through the call graph, grouped by how many calls away it "
            "is. Depth 1 is what `callers` returns, depth 2 is who calls "
            "those, and so on to `depth` (1 to 6, 3 by default). Cycles are "
            "walked once. Ask this before changing a function, instead of "
            "chasing call sites outward by hand. Capped at 200 entries: "
            "there is no handle for the rest, because narrowing the depth "
            "is the better answer than paging."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "array"],
                         "items": {"type": "string"}},
                "depth": {"type": "integer", "minimum": 1, "maximum": 6,
                          "description": "how many hops back to follow "
                                         "(default 3)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "defines",
        "description": (
            "Where a name is declared, exactly, and everywhere it is declared: "
            "one line per name, each home as `file:start-end (kind)` in path "
            "order, so a name two files declare says both. Functions, classes, "
            "constants, types, step phrases and scenario names, from the code "
            "under test as well as the suite. An end of `?` means the language "
            "was read by the pattern table, which knows where a declaration "
            "starts and not where it stops. `name` takes a list; ask for all "
            "of them at once."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": ["string", "array"],
                                    "items": {"type": "string"}}},
            "required": ["name"],
        },
    },
    {
        "name": "at",
        "description": (
            "The whole definition that encloses a line: hand it the "
            "`file:line` a stack trace or a review comment names and get back "
            "the function or class it is inside, from its first line to its "
            "last. Use this instead of reading a file at a guessed offset. "
            "The innermost definition, whole lines, cut to a budget with a "
            "`more:` handle for the rest. When nothing encloses the line the "
            "answer says so and names the nearest declarations. `place` takes "
            "a list."),
        "inputSchema": {
            "type": "object",
            "properties": {"place": {"type": ["string", "array"],
                                     "items": {"type": "string"},
                                     "description": ("FILE:LINE, or a list of "
                                                     "them")}},
            "required": ["place"],
        },
    },
    {
        "name": "context",
        "description": (
            "Everything the map holds about one name, in one call: where it "
            "is declared and how far each declaration runs, the rows of the "
            "map that mention it, who calls it, what it calls, and its blast "
            "radius one hop out. This is `defines`, `ask`, `callers`, "
            "`callees` and `impact` fused, so landing on a name costs one "
            "round trip rather than five. Each block gets a fixed share of "
            "the budget and ends with a `more:` handle when it was cut; pass "
            "that handle to `more` for the rest of that block. `name` takes "
            "a list, and `limit` sets the budget in characters."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "array"],
                         "items": {"type": "string"},
                         "description": ("a declared name, or a list of them")},
                "limit": {"type": "integer",
                          "description": ("characters one answer may take "
                                          "(default 12000)")},
            },
            "required": ["name"],
        },
    },
    {
        "name": "affected",
        "description": (
            "Which tests a change reaches: hand it the files a change "
            "touched and get back the scenarios whose steps call into them, "
            "the feature files those scenarios are in, the routes and page "
            "objects reached, and the files the graph holds no row for, so "
            "you know what the answer does not cover. Walks the map's own "
            "`xrefs` call rows upward, callee to caller, to `depth` hops (1 "
            "to 12, 6 by default). Ask it before running a suite: it is the "
            "selection, not a search. `format` returns a runner's own list "
            "instead of the blocks, `behave` arguments (one --name per "
            "affected scenario) or `pytest` node ids. A selection that fits "
            "this reply comes back whole; one that does not comes back as "
            f"its count, its first {MCP_SELECTORS} selectors and the "
            "`--affected-out FILE` command that writes all of it, because a "
            "selection cut in half is a test run that misses tests. `files` "
            "takes a list, relative to the repository root, and a directory "
            "prefix counts."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {"type": ["string", "array"],
                          "items": {"type": "string"},
                          "description": ("the files a change touched, or a "
                                          "directory prefix, relative to the "
                                          "repository root")},
                "depth": {"type": "integer", "minimum": 1, "maximum": 12,
                          "description": ("how many call hops to follow "
                                          "upward (default 6)")},
                "format": {"type": "string", "enum": ["behave", "pytest"],
                           "description": ("a runner's own selection instead "
                                           "of the blocks")},
            },
            "required": ["files"],
        },
    },
    {
        "name": "rank",
        "description": (
            "What this repository is built around, best first: the "
            "definitions with the most of the codebase behind them, by "
            "PageRank over the graph of which file references which file's "
            "names. Ask it before reading anything in an unfamiliar tree, "
            "and give `files` to ask the better question: what should I "
            "read given that I am editing these. A definition ten files "
            "reach outranks one nothing calls, which is not something "
            "counting word matches can tell you. `words` weighs the names "
            "in your question ten times. Not a search: `ask` answers what "
            "mentions a word, this answers what matters."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {"type": ["string", "array"],
                          "items": {"type": "string"},
                          "description": ("the files you are working in, or "
                                          "a directory prefix; the ranking "
                                          "is personalised on them. Omit for "
                                          "the repository's own order")},
                "words": {"type": ["string", "array"],
                          "items": {"type": "string"},
                          "description": ("names you are asking about, worth "
                                          "ten times an identifier you did "
                                          "not mention")},
                "limit": {"type": "integer",
                          "description": "how many definitions (default 200)"},
            },
        },
    },
]


class _BadParams(Exception):
    """A request's shape was wrong: reply -32602, do not touch the map."""


def _reply(result: dict, ident) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident,
                                 "result": result}) + "\n")
    sys.stdout.flush()


def _reply_error(code: int, message: str, ident) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident,
                                 "error": {"code": code,
                                           "message": message}}) + "\n")
    sys.stdout.flush()


def _is_str_or_str_list(value) -> bool:
    """`words`/`name`/`phrase` accept a bare string or a list of strings."""
    if isinstance(value, str):
        return True
    if isinstance(value, (list, tuple)):
        return all(isinstance(x, str) for x in value)
    return False


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


def _dispatch(mapper, out_dir: str, map_path: str, method, ident, params) -> None:
    """One request, fully validated before anything is read or written.

    Raises `_BadParams` for a malformed request (the caller replies -32602)
    and lets any other exception through (the caller replies -32603); a
    request that dispatches cleanly always replies for itself.
    """
    if method == "initialize":
        _reply({"protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "where-are-we",
                               "version": __version__}}, ident)
        return
    if method == "tools/list":
        _reply({"tools": TOOLS}, ident)
        return
    if method != "tools/call":
        if ident is not None:
            _reply({}, ident)
        return

    if not isinstance(params, dict):
        raise _BadParams("params must be an object")
    name = params.get("name")
    args = params.get("arguments")
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        raise _BadParams("arguments must be an object")

    if name == "ask":
        words_field = args.get("words")
        if words_field is not None and not _is_str_or_str_list(words_field):
            raise _BadParams("words must be a string or a list of strings")
        files_field = args.get("files")
        if files_field is not None and not _is_str_or_str_list(files_field):
            raise _BadParams("files must be a string or a list of strings")
        # `-` is the command line's "read the list on stdin", and stdin here
        # is the JSON-RPC pipe: an argument that named it would take the
        # session's next request for a file list. A client that wants a list
        # sends a list.
        scope = [f for f in file_list(files_field) if f != "-"]
        spec = os.path.join(out_dir, "spec_map.md")
        has_spec = os.path.exists(spec)

        def _ask_one(words: str, room: int) -> str:
            # Two maps, so the room is split between them rather than
            # spent twice: the framework map and the spec map each used
            # to return a full allowance, doubling every answer.
            each = room // 2 if has_spec else room
            answer = mapper.ask(map_path, words, each, scope)
            if has_spec:
                answer += "\n\n" + mapper.ask(spec, words, each, scope)
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

        asked = _each(words_field) or [""]
        room = _share(_ANSWER_BUDGET, len(asked), 1500)
        pairs = []
        for w in asked:
            a = _ask_one(w, room)
            log_answer(out_dir, "ask", w, a, room)
            pairs.append((w, a))
        _reply(_text(_joined(pairs)), ident)
    elif name == "defines":
        name_field = args.get("name")
        if name_field is not None and not _is_str_or_str_list(name_field):
            raise _BadParams("name must be a string or a list of strings")
        wanted = _each(name_field)
        # One pass over the map for the whole list: spans_for
        # already takes several names, and reading the map once per name
        # is the cost this batching exists to remove.
        hits = mapper.spans_for(map_path, [w.lower() for w in wanted])
        answer = ("\n".join(hits) if hits
                  else "no declaration of "
                       + ", ".join(repr(w) for w in wanted)
                       + " in the map")
        log_answer(out_dir, "defines", ", ".join(wanted), answer,
                   len(answer))
        _reply(_text(answer), ident)
    elif name == "at":
        place_field = args.get("place")
        if place_field is not None and not _is_str_or_str_list(place_field):
            raise _BadParams("place must be a string or a list of strings")
        wanted = _each(place_field)
        room = _share(AT_BUDGET, len(wanted), 1500)
        pairs = []
        for place in wanted:
            answer = at(map_path, place, room)
            log_answer(out_dir, "at", place, answer, room)
            pairs.append((place, answer))
        _reply(_text(_joined(pairs) if pairs
                     else "give me a place: FILE:LINE"), ident)
    elif name == "context":
        name_field = args.get("name")
        if name_field is not None and not _is_str_or_str_list(name_field):
            raise _BadParams("name must be a string or a list of strings")
        limit_field = args.get("limit")
        if limit_field is not None and not isinstance(limit_field, int):
            raise _BadParams("limit must be an integer")
        wanted = _each(name_field)
        # The same split every other batching tool here makes, off the budget
        # `--context` prints at, so one name through the tool and one name
        # through the flag are the same answer byte for byte.
        limit = int(limit_field or CONTEXT_BUDGET)
        room = _share(limit, len(wanted), 1500)
        pairs = []
        for w in wanted:
            answer = context(map_path, w, room)
            log_answer(out_dir, "context", w, answer, room)
            pairs.append((w, answer))
        _reply(_text(_joined(pairs) if pairs else "give me a name"), ident)
    elif name == "affected":
        files_field = args.get("files")
        if files_field is not None and not _is_str_or_str_list(files_field):
            raise _BadParams("files must be a string or a list of strings")
        depth_field = args.get("depth")
        if depth_field is not None and (not isinstance(depth_field, int)
                                        or isinstance(depth_field, bool)
                                        or depth_field < 1
                                        or depth_field > graph.MAX_DEPTH):
            raise _BadParams("depth must be an integer from 1 to "
                             f"{graph.MAX_DEPTH}")
        fmt_field = args.get("format")
        if fmt_field is not None and (not isinstance(fmt_field, str)
                                      or fmt_field not in graph.FORMATS):
            raise _BadParams("format must be one of "
                             + ", ".join(graph.FORMATS))
        # `-` is the command line's "read the list on stdin", and stdin here
        # is the JSON-RPC pipe, as it is for `ask`.
        chosen = [f for f in file_list(files_field) if f != "-"]
        depth = graph.DEFAULT_DEPTH if depth_field is None else int(depth_field)
        # One question, so the whole budget: the files are one change rather
        # than a list of separate questions, and the flag prints at the same
        # ceiling, which is what makes the two byte for byte identical.
        answer = affected_tool_answer(map_path, chosen, depth,
                                      fmt_field or "", AFFECTED_BUDGET)
        log_answer(out_dir, "affected", ",".join(chosen), answer,
                   AFFECTED_BUDGET)
        _reply(_text(answer), ident)
    elif name == "rank":
        files_field = args.get("files")
        if files_field is not None and not _is_str_or_str_list(files_field):
            raise _BadParams("files must be a string or a list of strings")
        words_field = args.get("words")
        if words_field is not None and not _is_str_or_str_list(words_field):
            raise _BadParams("words must be a string or a list of strings")
        limit_field = args.get("limit")
        if limit_field is not None and (not isinstance(limit_field, int)
                                        or isinstance(limit_field, bool)
                                        or limit_field < 1):
            raise _BadParams("limit must be a positive integer")
        chosen = [f for f in file_list(files_field) if f != "-"]
        answer = rank_lines(map_path, chosen, _each(words_field),
                            int(limit_field or RANK_LIMIT))
        log_answer(out_dir, "rank", ",".join(chosen), answer, len(answer))
        _reply(_text(answer), ident)
    elif name == "callers":
        name_field = args.get("name")
        if name_field is not None and not _is_str_or_str_list(name_field):
            raise _BadParams("name must be a string or a list of strings")
        json_path = os.path.join(out_dir, "framework_map.json")
        wanted = _each(name_field)
        lines = []
        for w in wanted:
            hits = callers(json_path, w)
            lines.append(f"{w}: " + ", ".join(hits) if hits
                         else f"nothing in the map calls {w}")
        answer = "\n".join(lines)
        log_answer(out_dir, "callers", ", ".join(wanted), answer,
                   len(answer))
        _reply(_text(answer), ident)
    elif name == "callees":
        name_field = args.get("name")
        if name_field is not None and not _is_str_or_str_list(name_field):
            raise _BadParams("name must be a string or a list of strings")
        json_path = os.path.join(out_dir, "framework_map.json")
        wanted = _each(name_field)
        lines = []
        for w in wanted:
            a = callees_line(json_path, w)
            # One log line per name, as `impact` does: a batch of five names
            # is five answers, and one row holding all of them says nothing
            # about what any of them cost.
            log_answer(out_dir, "callees", w, a, len(a))
            lines.append(a)
        _reply(_text("\n".join(lines)), ident)
    elif name == "impact":
        name_field = args.get("name")
        if name_field is not None and not _is_str_or_str_list(name_field):
            raise _BadParams("name must be a string or a list of strings")
        depth_field = args.get("depth")
        # The schema says 1 to 6, and a request outside it is a malformed
        # request, not a question to answer: it used to come back as a
        # result whose text complained, which a client reads as an answer.
        if depth_field is not None and (not isinstance(depth_field, int)
                                        or isinstance(depth_field, bool)
                                        or depth_field < 1
                                        or depth_field > IMPACT_MAX_DEPTH):
            raise _BadParams("depth must be an integer from 1 to "
                             f"{IMPACT_MAX_DEPTH}")
        json_path = os.path.join(out_dir, "framework_map.json")
        depth = 3 if depth_field is None else int(depth_field)
        wanted = _each(name_field)
        pairs = []
        for w in wanted:
            a = impact(json_path, w, depth)
            log_answer(out_dir, "impact", w, a, len(a))
            pairs.append((w, a))
        _reply(_text(_joined(pairs) if pairs else ""), ident)
    elif name == "find":
        phrase_field = args.get("phrase")
        if phrase_field is not None and not _is_str_or_str_list(phrase_field):
            raise _BadParams("phrase must be a string or a list of strings")
        limit_field = args.get("limit")
        if limit_field is not None and not isinstance(limit_field, int):
            raise _BadParams("limit must be an integer")
        phrases = _each(phrase_field) or [""]
        limit = int(limit_field or _HIT_BUDGET)
        room = _share(limit, len(phrases), 5)
        pairs = []
        for p in phrases:
            a = mapper.find_text(out_dir, p, room)
            log_answer(out_dir, "find", p, a, room)
            pairs.append((p, a))
        _reply(_text(_joined(pairs)), ident)
    elif name == "more":
        handle_field = args.get("handle")
        if handle_field is not None and not _is_str_or_str_list(handle_field):
            raise _BadParams("handle must be a string or a list of strings")
        handles = _each(handle_field) or [""]
        # The same budget `ask` gets, split the same way across a list: what
        # a handle fetches lands in the conversation exactly like the answer
        # that printed it, and costs the same on every turn after.
        room = _share(_ANSWER_BUDGET, len(handles), 1500)
        pairs = []
        for h in handles:
            a = mapper.more(map_path, h, room)
            log_answer(out_dir, "more", h, a, room)
            pairs.append((h, a))
        _reply(_text(_joined(pairs)), ident)
    elif name == "sections":
        try:
            answer = "\n".join(map_heads(map_path))
            log_answer(out_dir, "sections", "", answer, len(answer))
            _reply(_text(answer), ident)
        except OSError as exc:
            _reply(_text(f"no map at {map_path}: {exc}"), ident)
    else:
        _reply(_text(f"no tool named {name!r}"), ident)


def serve(out_dir: str) -> int:
    """Read requests until stdin closes. One request, one answer, no state.

    A malformed request never takes the server down with it: its dispatch is
    wrapped so a bad shape gets a JSON-RPC -32602 and anything else gets a
    -32603, and the loop reads the next line either way. The client that
    closes its end of the pipe mid-answer (`| head`, a killed editor) gets a
    quiet exit instead of a BrokenPipeError traceback.
    """
    map_path = os.path.join(out_dir, "framework_map.md")

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                continue
            if not isinstance(request, dict):
                continue  # not a JSON-RPC object; nothing sane to reply to
            method, ident = request.get("method"), request.get("id")
            params = request.get("params")
            if params is None:
                params = {}
            try:
                _dispatch(mapper, out_dir, map_path, method, ident, params)
            except _BadParams as exc:
                _reply_error(-32602, str(exc), ident)
            except BrokenPipeError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep serving the pipe
                _reply_error(-32603, str(exc), ident)
    except BrokenPipeError:
        # The reader went away (`| head`, a killed editor). Redirect our
        # stdout to devnull first so the interpreter's own shutdown flush
        # does not raise the same error a second time on the way out.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    return 0
