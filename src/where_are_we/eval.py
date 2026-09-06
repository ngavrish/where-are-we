"""Does the budget lose answers? Measured, not asserted.

`ask()` cuts every answer to a byte budget, and a cut is a claim: that what
was dropped was worth less than what was kept. This module tests the weaker
and more important half of that claim, which is that nothing is lost for
good. It generates questions from the map itself, takes `ask(words, 10**9)`
as the reference (every row the map holds for those words), then for each
budget compares two numbers: how many of those rows the first answer holds
on its own, and how many the first answer plus its `more` handles holds
between them. The second number should be 1.0 at every budget; anything less
is a defect in `more`, and the exit code says so.

There is no model in the deterministic half. It reads the same map files the
tools read and calls the same functions, so it runs in CI in a second and
its numbers can go into the README without a caveat about sampling.

`--agent` is the other half, and it does call a model: the same questions
asked two ways, once with the map tools and once with grep and read over the
repository, scored against answers taken out of `framework_map.json`. That
one needs `ANTHROPIC_API_KEY` and the optional `eval-agent` extra, is not run
in CI, and costs real money, so it refuses rather than guesses when either
is missing.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sys

try:
    from . import ask as _ask
except ImportError:  # run as a plain file, with no package around it
    import ask as _ask  # type: ignore[no-redef]

try:
    from . import mapper as _mapper
except ImportError:  # run as a plain file, with no package around it
    import mapper as _mapper  # type: ignore[no-redef]


# A handle as it appears in a tail line: `… 37 more matching rows
# (more:rows:steps-that-overlap:invoice:12)`. The brackets are optional
# because the "more sections match" note ends in a bare handle, and the
# payload stops at the first bracket or space so a tail that carries two
# notes on one line yields two handles rather than one long one.
_HANDLE = re.compile(r"\(?(more:[a-z]+:[^)\s]+)\)?")

# `unmatched` handles are the rows of a section that do *not* mention the
# words. The reference answer never holds those rows, so following them
# could only add rows outside the set being measured, at the cost of a
# `more` call per section. Every other kind is chased.
_SKIP_KINDS = ("unmatched",)

# A directory head written by `_group_dirs` (`- ``app/```) and the rows
# printed under it. Rendering only: the row set is compared with full paths
# put back, or the same row would look different at two budgets purely
# because a neighbour did or did not fit beside it.
_DIR_HEAD = re.compile(r"^- `([^`]*/)`$")

_STOPWORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "here", "in", "is", "it", "its", "of", "on", "or", "that", "the", "then",
    "they", "this", "to", "was", "were", "when", "which", "with", "you",
))


def handles_available() -> bool:
    """Whether this build has the `more` tool.

    `eval.py` was written beside `more` and merged after it, so it has to
    work on a tree that does not have it yet: without `more` there is no
    recall-with-handles to report, and the run says so rather than printing
    a column of zeros that reads like a failure.
    """
    return hasattr(_ask, "more")


def rows(answer: str) -> set:
    """Every map row in an answer, with the directory grouping undone.

    A row is a `- ` line. Heads (`## ...`), tails (`… ...`), bold subheads
    and the "(also matched: ...)" note are not rows and are dropped: they
    are the answer talking about itself, not content the map holds.
    """
    out, directory = set(), None
    for line in answer.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - `") and directory is not None:
            out.add("- `" + directory + line[len("  - `"):])
            continue
        head = _DIR_HEAD.match(line)
        if head:
            directory = head.group(1)
            continue
        directory = None
        if line.startswith("- "):
            out.add(line)
    return out


def handles(answer: str) -> list:
    """Every `more:` handle in an answer, in order, deduplicated."""
    return list(dict.fromkeys(_HANDLE.findall(answer)))


def _chaseable(handle: str) -> bool:
    kind = handle.split(":", 2)[1] if handle.count(":") >= 2 else ""
    return kind not in _SKIP_KINDS


# ---------------------------------------------------------------- questions


def _distinctive(phrase: str, frequency: collections.Counter) -> str:
    """The word of a step phrase that separates it from the others.

    Rarest across every phrase in the map wins, then longest, then
    alphabetical, so the answer is the same on every run. "pay step 17"
    gives "17" (one phrase has it) rather than "pay" (forty do), and a
    phrase whose every word is common falls back to its longest word.
    Words shorter than two characters are skipped because `ask()` drops
    them from a question anyway.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9_]+", phrase.lower())
             if len(w) > 1 and w not in _STOPWORDS]
    if not words:
        return ""
    return min(words, key=lambda w: (frequency[w], -len(w), w))


def _key_noun(head: str) -> str:
    """A section heading's key noun: its longest word that is not furniture.

    "## Step definitions" gives "definitions", "## Routes served" gives
    "served". Later words win ties, because an English heading puts the
    thing it is about last.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9_]+", head[2:].lower())
             if len(w) > 1 and w not in _STOPWORDS]
    if not words:
        return ""
    best = ""
    for w in words:
        if len(w) >= len(best):
            best = w
    return best


def question_pool(out_dir: str) -> list:
    """Every question the map can ask itself, sorted.

    Three sources, as the brief names them: every declared name, every step
    phrase's distinctive word, every section heading's key noun. Sorted
    rather than left in map order so a seed picks the same sample whatever
    order the map happened to write its indexes in.
    """
    map_path = os.path.join(out_dir, "framework_map.md")
    try:
        with open(os.path.join(out_dir, "framework_map.json"), encoding="utf-8") as fh:
            m = json.load(fh) or {}
    except (OSError, ValueError):
        m = {}

    pool = set()
    for name in (m.get("definitions") or {}):
        name = str(name).strip()
        if len(name) > 1:
            pool.add(name)

    phrases = []
    for value in (m.get("steps") or {}).values():
        if isinstance(value, list):
            phrases += [str(p) for p in value]
    frequency = collections.Counter()
    for phrase in phrases:
        for w in set(re.split(r"[^A-Za-z0-9_]+", phrase.lower())):
            if len(w) > 1:
                frequency[w] += 1
    for phrase in phrases:
        word = _distinctive(phrase, frequency)
        if word:
            pool.add(word)

    try:
        for head in _ask.map_heads(map_path):
            noun = _key_noun(head)
            if noun:
                pool.add(noun)
    except OSError:
        pass

    return sorted(pool)


def _shuffled(items: list, seed: int) -> list:
    """`items` in one seed's order. Callers walk this until they have as
    many usable questions as they wanted, so the order is the sample: a
    question dropped for matching nothing does not shift the rest."""
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


# ------------------------------------------------------------ deterministic


def _chase(map_path: str, answer: str, budget: int, max_calls: int) -> tuple:
    """Every row reachable from an answer's handles, and how many calls it
    took. Follows handles the replies carry too, until none is left."""
    pending = [h for h in handles(answer) if _chaseable(h)]
    seen = set(pending)
    found, calls = set(), 0
    while pending and calls < max_calls:
        handle = pending.pop(0)
        calls += 1
        reply = _ask.more(map_path, handle, budget)
        found |= rows(reply)
        for nxt in handles(reply):
            if nxt not in seen and _chaseable(nxt):
                seen.add(nxt)
                pending.append(nxt)
    return found, calls, bool(pending)


def evaluate(out_dir: str, n: int, budgets: list, seed: int,
             max_calls: int = 400) -> dict:
    """The deterministic report: per budget, what the first answer holds and
    what the first answer plus its handles holds, against the whole answer."""
    map_path = os.path.join(out_dir, "framework_map.md")
    have = handles_available()
    pool = question_pool(out_dir)

    asked, references, skipped = [], {}, 0
    for word in _shuffled(pool, seed):
        if len(asked) >= n:
            break
        reference = rows(_ask.ask(map_path, word, 10 ** 9))
        if not reference:
            # A question the map cannot answer at any budget measures
            # nothing about the budget. Counted, not scored.
            skipped += 1
            continue
        asked.append(word)
        references[word] = reference

    report = {
        "map": out_dir,
        "seed": seed,
        "pool": len(pool),
        "questions": len(asked),
        "skipped_no_rows": skipped,
        "handles": have,
        "budgets": [],
        "losses": [],
    }

    for budget in budgets:
        first_recalls, full_recalls, sizes = [], [], []
        worst_calls, truncated = 0, 0
        for word in asked:
            reference = references[word]
            answer = _ask.ask(map_path, word, budget)
            sizes.append(len(answer))
            first = rows(answer) & reference
            first_recalls.append(len(first) / len(reference))
            if not have:
                continue
            found, calls, unfinished = _chase(map_path, answer, budget, max_calls)
            worst_calls = max(worst_calls, calls)
            truncated += 1 if unfinished else 0
            full = (first | (found & reference))
            recall = len(full) / len(reference)
            full_recalls.append(recall)
            if recall < 1.0:
                report["losses"].append({
                    "budget": budget, "words": word,
                    "recall": round(recall, 4),
                    "missing": len(reference) - len(full),
                    "reference_rows": len(reference),
                })
        row = {
            "budget": budget,
            "questions": len(asked),
            "first_answer_recall": round(_mean(first_recalls), 4),
            "recall_with_handles": (round(_mean(full_recalls), 4) if have else None),
            "mean_bytes": round(_mean(sizes), 1),
            "max_more_calls": worst_calls if have else None,
            "chains_cut_short": truncated if have else None,
        }
        report["budgets"].append(row)
    return report


def _mean(values: list) -> float:
    return (sum(values) / len(values)) if values else 0.0


_COLUMNS = ("budget", "questions", "first_answer_recall", "recall_with_handles",
            "mean_bytes")


def print_table(report: dict) -> None:
    rows_out = []
    for row in report["budgets"]:
        rows_out.append({c: ("-" if row.get(c) is None else row.get(c))
                         for c in _COLUMNS})
    widths = {c: len(c) for c in _COLUMNS}
    for row in rows_out:
        for c in _COLUMNS:
            widths[c] = max(widths[c], len(str(row[c])))
    print("  ".join(c.rjust(widths[c]) for c in _COLUMNS))
    for row in rows_out:
        print("  ".join(str(row[c]).rjust(widths[c]) for c in _COLUMNS))
    print(f"map: {report['map']}  questions: {report['questions']} "
          f"of {report['pool']} in the pool  seed: {report['seed']}")
    if not report["handles"]:
        print("handles: not available in this build")


# -------------------------------------------------------------------- agent


def _relative(path: str, repo: str) -> str:
    """A definition's path as the repository sees it. The map records some
    declarations absolutely and some already relative; both come back the
    same shape here so an answer can be compared to one string."""
    text = str(path)
    # Three spellings of the same directory, because a map built through a
    # symlinked temp directory records the resolved path and the caller
    # passes the one they typed. Longest first, so `/a/b` never strips a
    # prefix `/a` would have matched too.
    roots = {repo, os.path.abspath(repo), os.path.realpath(repo)}
    for prefix in sorted((r.rstrip(os.sep) + os.sep for r in roots), key=len,
                         reverse=True):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def agent_questions(out_dir: str, repo: str, n: int, seed: int) -> list:
    """Questions whose answer is already written in `framework_map.json`.

    Four kinds, the ones the map is asked in practice: where a name is
    defined, who calls a function, which scenarios carry a tag, and which
    file serves a route. Each carries the strings an answer has to contain
    to count as right. Kinds are interleaved before sampling so a five
    question run is not five of one kind.
    """
    try:
        with open(os.path.join(out_dir, "framework_map.json"), encoding="utf-8") as fh:
            m = json.load(fh) or {}
    except (OSError, ValueError):
        return []

    by_kind = collections.OrderedDict(
        (k, []) for k in ("definition", "caller", "tag", "route"))

    for name, where in sorted((m.get("definitions") or {}).items()):
        by_kind["definition"].append({
            "kind": "definition", "key": name,
            "question": f"Where is `{name}` defined in this repository? "
                        "Answer with the file path and line number.",
            "expected": [_relative(where, repo)],
        })

    callees = set()
    for calls in (m.get("call_graph_files") or {}).values():
        for c in calls:
            callees.add(str(c).split(" (", 1)[0])
    for calls in (m.get("call_graph") or {}).values():
        for c in calls:
            callees.add(str(c))
    json_path = os.path.join(out_dir, "framework_map.json")
    for name in sorted(callees):
        hits = _ask.callers(json_path, name)
        if not hits:
            continue
        by_kind["caller"].append({
            "kind": "caller", "key": name,
            "question": f"Which functions call `{name}`? Answer with every "
                        "`<file>:<function>` that does.",
            "expected": list(hits),
        })

    features = m.get("features") or {}
    tagged = collections.defaultdict(list)
    for feature in sorted(features):
        info = features.get(feature) or {}
        for scenario in info.get("scenarios") or []:
            name = scenario.get("name") if isinstance(scenario, dict) else None
            for tag in (scenario.get("tags") if isinstance(scenario, dict) else None) or info.get("tags") or []:
                if name:
                    tagged[str(tag)].append(name)
    for tag in sorted(tagged):
        by_kind["tag"].append({
            "kind": "tag", "key": tag,
            "question": f"Which scenarios are tagged {tag}? Answer with every "
                        "scenario name.",
            "expected": sorted(set(tagged[tag])),
        })

    for route in sorted(m.get("routes_served") or []):
        text = str(route)
        if "(" not in text:
            continue
        where, served = text.rsplit("(", 1)
        by_kind["route"].append({
            "kind": "route", "key": where.strip(),
            "question": f"Which file serves the route {where.strip()}? "
                        "Answer with the file name.",
            "expected": [served.rstrip(")").strip()],
        })

    # Round robin over the kinds that have anything, each kind shuffled by
    # the seed first: five questions on a map with eight definitions and
    # three routes come back as three and two, not five definitions.
    queues = [_shuffled(items, seed) for items in by_kind.values() if items]
    interleaved = []
    while queues:
        for queue in list(queues):
            interleaved.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    return interleaved[:n]


def _map_tools() -> list:
    """The map tools exactly as the MCP server declares them, renamed to the
    Messages API's `input_schema`. Read from `mcp.TOOLS` rather than copied,
    so a tool added there is evaluated here without an edit."""
    try:
        from . import mcp as _mcp
    except ImportError:  # run as a plain file, with no package around it
        import mcp as _mcp  # type: ignore[no-redef]
    out = []
    for tool in _mcp.TOOLS:
        out.append({"name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool.get("inputSchema") or {"type": "object",
                                                                "properties": {}}})
    return out


def _run_map_tool(name: str, args: dict, out_dir: str) -> str:
    """One map tool answered in this process, the way the MCP server answers
    it: same functions, same map, no server and no subprocess."""
    map_path = os.path.join(out_dir, "framework_map.md")
    json_path = os.path.join(out_dir, "framework_map.json")
    if name == "ask":
        words = args.get("words")
        words = " ".join(words) if isinstance(words, list) else str(words or "")
        return _ask.ask(map_path, words, 4000)
    if name == "defines":
        wanted = args.get("name")
        wanted = wanted if isinstance(wanted, list) else [str(wanted or "")]
        hits = _mapper.definitions_for(map_path, [str(w).lower() for w in wanted])
        return "\n".join(hits) if hits else "no declaration of " + ", ".join(wanted)
    if name == "callers":
        wanted = args.get("name")
        wanted = wanted if isinstance(wanted, list) else [str(wanted or "")]
        lines = []
        for w in wanted:
            hits = _ask.callers(json_path, str(w))
            lines.append(f"{w}: " + ", ".join(hits) if hits
                         else f"nothing in the map calls {w}")
        return "\n".join(lines)
    if name == "find":
        phrase = args.get("phrase")
        phrase = phrase if isinstance(phrase, list) else [str(phrase or "")]
        return "\n\n".join(_mapper.find_text(out_dir, str(p), 40) for p in phrase)
    if name == "sections":
        return "\n".join(_ask.map_heads(map_path))
    if name == "more" and hasattr(_ask, "more"):
        return _ask.more(map_path, str(args.get("handle") or ""), 4000)
    return f"no tool named {name!r}"


_GREP_TOOLS = [
    {
        "name": "grep",
        "description": ("Search the repository for a regular expression. "
                        "Returns `<file>:<line number>: <line>` for every hit, "
                        "up to 80."),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "a Python regular expression"},
                "path": {"type": "string",
                         "description": "a directory or file to search, relative "
                                        "to the repository root (default: the whole repository)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read",
        "description": "Read a file from the repository, with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "a path relative to the repository root"},
                "start": {"type": "integer", "description": "first line, 1 based (default 1)"},
                "end": {"type": "integer", "description": "last line (default: start plus 200)"},
            },
            "required": ["path"],
        },
    },
]


def _inside(repo: str, path: str) -> str | None:
    """`path` resolved under `repo`, or None when it points outside it.

    The grep arm reads real files, so it gets a real boundary: no absolute
    path, no `..` out of the tree, and symlinks resolved before the check
    rather than after.
    """
    root = os.path.realpath(repo)
    full = os.path.realpath(os.path.join(root, path or "."))
    return full if full == root or full.startswith(root + os.sep) else None


def _walk(root: str):
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "node_modules",
                                                      "__pycache__", ".venv"))
        for name in sorted(files):
            yield os.path.join(base, name)


def _run_grep_tool(name: str, args: dict, repo: str) -> str:
    """grep and read, over this repository only, reading nothing else and
    running nothing. There is no shell here on purpose: the point of the
    comparison is what the map saves an agent that searches files, not what
    a sandbox does with a command line."""
    root = os.path.realpath(repo)
    if name == "grep":
        try:
            pattern = re.compile(str(args.get("pattern") or ""), re.IGNORECASE)
        except re.error as exc:
            return f"bad pattern: {exc}"
        where = _inside(root, str(args.get("path") or "."))
        if where is None:
            return "path is outside the repository"
        paths = [where] if os.path.isfile(where) else list(_walk(where))
        hits = []
        for path in paths:
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if pattern.search(line):
                            hits.append(f"{os.path.relpath(path, root)}:{i}: "
                                        f"{line.rstrip()[:200]}")
                            if len(hits) >= 80:
                                return "\n".join(hits) + "\n… more hits not shown"
            except OSError:
                continue
        return "\n".join(hits) if hits else "no hits"
    if name == "read":
        where = _inside(root, str(args.get("path") or ""))
        if where is None or not os.path.isfile(where):
            return "no such file in the repository"
        start = max(1, int(args.get("start") or 1))
        end = int(args.get("end") or (start + 200))
        try:
            with open(where, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            return f"cannot read: {exc}"
        chunk = lines[start - 1:end]
        return "".join(f"{start + i}: {line}" for i, line in enumerate(chunk)) or "empty"
    return f"no tool named {name!r}"


_SYSTEM = ("You answer questions about one repository. Use the tools to find "
           "the answer, then state it. Be exact and be brief: give the file, "
           "line, name or scenario asked for, with no commentary around it. "
           "If several answers apply, list them all.")


def _scored(answer: str, expected: list) -> bool:
    """Every expected string present in the answer, verbatim. Exact match,
    not similarity: these are paths, line numbers and identifiers, and an
    answer that has the right shape and the wrong name is wrong."""
    return all(str(e) in answer for e in expected)


def _one_arm(client, model: str, tools: list, run_tool, question: dict,
             max_turns: int) -> dict:
    """One question, one tool set, until the model stops calling tools."""
    messages = [{"role": "user", "content": question["question"]}]
    tokens_in = tokens_out = calls = 0
    text = ""
    for _ in range(max_turns):
        response = client.messages.create(
            model=model, max_tokens=4096, system=_SYSTEM,
            tools=tools, messages=messages,
        )
        usage = getattr(response, "usage", None)
        tokens_in += getattr(usage, "input_tokens", 0) or 0
        tokens_out += getattr(usage, "output_tokens", 0) or 0
        text = "\n".join(b.text for b in response.content
                         if getattr(b, "type", "") == "text")
        uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if not uses:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for use in uses:
            calls += 1
            body = run_tool(use.name, dict(use.input or {}))
            results.append({"type": "tool_result", "tool_use_id": use.id,
                            "content": body[:20000] or "(empty)"})
        messages.append({"role": "user", "content": results})
    return {"answer": text, "correct": _scored(text, question["expected"]),
            "tokens_in": tokens_in, "tokens_out": tokens_out, "tool_calls": calls}


def run_agent(out_dir: str, repo: str, n: int, seed: int, model: str,
              json_path: str, max_turns: int) -> int:
    """The A/B: the same questions asked with the map tools and with grep."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("wawe-eval --agent calls the Claude API and found no key: set "
              "ANTHROPIC_API_KEY in the environment and run it again. Nothing "
              "was sent.", file=sys.stderr)
        return 2
    try:
        import anthropic
    except ImportError:
        print("wawe-eval --agent needs the anthropic package, which the core "
              "does not depend on: pip install 'where-are-we[eval-agent]'.",
              file=sys.stderr)
        return 2

    questions = agent_questions(out_dir, repo, n, seed)
    if not questions:
        print(f"no questions with known answers in {out_dir}: the map has no "
              "definitions, callers, tags or routes.", file=sys.stderr)
        return 2

    client = anthropic.Anthropic()
    arms = (
        ("map", _map_tools(), lambda name, args: _run_map_tool(name, args, out_dir)),
        ("grep", _GREP_TOOLS, lambda name, args: _run_grep_tool(name, args, repo)),
    )
    results = []
    for question in questions:
        for arm, tools, run_tool in arms:
            row = _one_arm(client, model, tools, run_tool, question, max_turns)
            row.update({"arm": arm, "kind": question["kind"],
                        "key": question["key"], "question": question["question"],
                        "expected": question["expected"]})
            results.append(row)

    report = {"model": model, "map": out_dir, "repo": repo, "seed": seed,
              "questions": len(questions), "results": results, "arms": []}
    headers = ("arm", "questions", "correct", "accuracy", "tokens_in",
               "tokens_out", "tool_calls")
    table = []
    for arm, _, _ in arms:
        mine = [r for r in results if r["arm"] == arm]
        correct = sum(1 for r in mine if r["correct"])
        summary = {"arm": arm, "questions": len(mine), "correct": correct,
                   "accuracy": round(correct / len(mine), 4) if mine else 0.0,
                   "tokens_in": sum(r["tokens_in"] for r in mine),
                   "tokens_out": sum(r["tokens_out"] for r in mine),
                   "tool_calls": sum(r["tool_calls"] for r in mine)}
        report["arms"].append(summary)
        table.append(summary)

    widths = {h: max(len(h), *(len(str(r[h])) for r in table)) for h in headers}
    print("  ".join(h.rjust(widths[h]) for h in headers))
    for row in table:
        print("  ".join(str(row[h]).rjust(widths[h]) for h in headers))

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print(f"wrote {json_path}")
    return 0


# --------------------------------------------------------------------- main


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wawe-eval",
        description="Does the budget lose answers? Recall of a budgeted map "
                    "answer against the whole answer, and an optional agent A/B.",
    )
    parser.add_argument("--map", default=None, metavar="OUT_DIR",
                        help="the directory holding framework_map.md/.json")
    parser.add_argument("--out", default=None, metavar="OUT_DIR",
                        help="same as --map, spelled the way --agent's brief spells it")
    parser.add_argument("--questions", type=int, default=100,
                        help="how many questions to ask (default 100)")
    parser.add_argument("--budgets", default="350,1500,12000",
                        help="comma separated byte budgets (default 350,1500,12000)")
    parser.add_argument("--seed", type=int, default=0,
                        help="seed for the question sample (default 0)")
    parser.add_argument("--max-more", type=int, default=400, metavar="N",
                        help="stop chasing a question's handles after N calls "
                             "(default 400)")
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON, no table")
    parser.add_argument("--agent", action="store_true",
                        help="ask the same map two ways through the Claude API "
                             "and score both; needs ANTHROPIC_API_KEY")
    parser.add_argument("--repo", default=None,
                        help="the repository the map was built from (--agent only)")
    parser.add_argument("--model", default="claude-sonnet-5",
                        help="model id for --agent (default claude-sonnet-5)")
    parser.add_argument("--agent-json", default="eval-agent.json", metavar="PATH",
                        help="where --agent writes its rows (default eval-agent.json)")
    parser.add_argument("--max-turns", type=int, default=12,
                        help="tool call rounds per question in --agent (default 12)")
    args = parser.parse_args(argv)

    out_dir = args.map or args.out
    if not out_dir:
        parser.error("--map (or --out) is required: the directory holding the map")
    if not os.path.exists(os.path.join(out_dir, "framework_map.md")):
        print(f"no framework_map.md in {out_dir}", file=sys.stderr)
        return 2

    if args.agent:
        repo = args.repo
        if not repo:
            parser.error("--agent needs --repo: the repository the map was built from")
        return run_agent(out_dir, repo, args.questions, args.seed, args.model,
                         args.agent_json, args.max_turns)

    budgets = [int(b) for b in str(args.budgets).split(",") if b.strip()]
    if not budgets:
        parser.error("--budgets needs at least one number")
    report = evaluate(out_dir, args.questions, budgets, args.seed, args.max_more)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_table(report)

    if report["handles"] and report["losses"]:
        # A row the map holds, that the budgeted answer cut, that no handle
        # gave back. That is a bug in `more`, not a property of the budget,
        # so it fails the run rather than printing a number nobody reads.
        print(f"{len(report['losses'])} question(s) lost rows no handle "
              "returned:", file=sys.stderr)
        for loss in report["losses"][:10]:
            print(f"- budget {loss['budget']}, {loss['words']!r}: "
                  f"{loss['missing']} of {loss['reference_rows']} rows missing",
                  file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
