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

# Read once, at import, like every other knob this project reads: the check
# happens under --agent, but where the value comes from is one named place.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

try:
    from . import ask as _ask
except ImportError:  # run as a plain file, with no package around it
    import ask as _ask  # type: ignore[no-redef]

try:
    from . import mapper as _mapper
except ImportError:  # run as a plain file, with no package around it
    import mapper as _mapper  # type: ignore[no-redef]

# Three names the facade holds but does not publish, taken from the modules
# that define them: the optional tree-sitter parser factory, and the bounded
# reader every other pass over a tree reads through, with its cap.
try:
    from ._mapper.declare import _tree_sitter
    from ._mapper.walk import AST_LIMIT, _slurp
except ImportError:  # run as a plain file, with no package around it
    from _mapper.declare import _tree_sitter  # type: ignore[no-redef]
    from _mapper.walk import AST_LIMIT, _slurp  # type: ignore[no-redef]

# The MCP server is the shape an agent actually asks in, so `--agent` splits
# its budget with the server's own helpers rather than a second copy of the
# arithmetic. Optional because eval.py has to import on a tree where mcp.py
# is not reachable (run as a plain file); the constants below are then the
# fallback, and they are the same numbers.
try:
    from . import mcp as _mcp
except ImportError:  # run as a plain file, with no package around it
    try:
        import mcp as _mcp  # type: ignore[no-redef]
    except ImportError:
        _mcp = None  # type: ignore[assignment]

_ANSWER_BUDGET = 12000
_HIT_BUDGET = 40


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
#
# A tail that reports both counts ("… 37 more matching rows; 210 rows in
# this section do not mention these words (more:rows:...)") carries the
# `rows` handle only: the `unmatched` one is the same payload with the kind
# swapped, so it is derived rather than printed, and there is nothing extra
# for the parser to find. An `unmatched` handle appears on its own only when
# a section has no unshown matching rows left to offer, and that one is
# skipped here.
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


def ordered_rows(answer: str) -> list:
    """Every map row in an answer, in the order the answer printed them,
    with the directory grouping undone and repeats dropped.

    A row is a `- ` line. Heads (`## ...`), tails (`… ...`), bold subheads
    and the "(also matched: ...)" note are not rows and are dropped: they
    are the answer talking about itself, not content the map holds.

    The order matters for one column: `ask` ranks what it shows, so the
    first rows of the unbudgeted answer are the ones a reader was most
    likely after, and `top5_recall` asks whether those in particular
    survived the cut.
    """
    out, seen, directory = [], set(), None

    def add(row):
        if row not in seen:
            seen.add(row)
            out.append(row)

    for line in answer.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - `") and directory is not None:
            add("- `" + directory + line[len("  - `"):])
            continue
        head = _DIR_HEAD.match(line)
        if head:
            directory = head.group(1)
            continue
        directory = None
        if line.startswith("- "):
            add(line)
    return out


def rows(answer: str) -> set:
    """`ordered_rows` as a set, for the callers that only ask what is in it."""
    return set(ordered_rows(answer))


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


def _longest_word(head: str) -> str:
    """The longest word of a section heading, skipping the small words that
    carry no subject.

    "## Step definitions" gives "definitions", "## Routes served" gives
    "served". Later words win ties, because an English heading puts the
    thing it is about last. It is the longest word and nothing cleverer:
    no part of speech is known here, so calling it the heading's noun would
    claim more than the code does.
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


KINDS = ("name", "step", "heading")


def question_pool(out_dir: str) -> dict:
    """Every question the map can ask itself, sorted, by where it came from.

    Three sources, as the brief names them: every declared name, every step
    phrase's distinctive word, and the longest word of every section
    heading. Sorted rather than left in map order so a seed picks the same
    sample whatever order the map happened to write its indexes in.

    A word that two sources produce is kept once, under the first source in
    `KINDS` that produced it, so the per-kind counts add up to the pool and
    the same question is never asked twice under two names.
    """
    map_path = os.path.join(out_dir, "framework_map.md")
    try:
        with open(os.path.join(out_dir, "framework_map.json"), encoding="utf-8") as fh:
            m = json.load(fh) or {}
    except (OSError, ValueError):
        m = {}

    pool = {kind: set() for kind in KINDS}
    seen = set()

    def add(kind, word):
        if word not in seen:
            seen.add(word)
            pool[kind].add(word)

    for name in (m.get("definitions") or {}):
        name = str(name).strip()
        if len(name) > 1:
            add("name", name)

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
            add("step", word)

    try:
        for head in _ask.map_heads(map_path):
            word = _longest_word(head)
            if word:
                add("heading", word)
    except OSError:
        pass

    return {kind: sorted(words) for kind, words in pool.items()}


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


# One question is asked at the reference limit and once per budget, and a
# run that repeats a budget, or asks at a budget the reference limit already
# covered, would otherwise read and rank the whole map again for an answer it
# already has. Keyed on what the answer depends on and nothing else.
_ANSWERS: dict = {}


def answer_for(map_path: str, words: str, budget: int,
               tool: str = "ask") -> str:
    """The tool under test, through a memo keyed on (map, words, budget, tool).

    `ask` and `context` are budgeted the same way and cut by the same rules,
    so the same recall measurement answers for both: the reference is the
    tool's own answer at a budget nothing could exceed, and the arms are the
    tool at each budget plus everything its handles return.
    """
    key = (map_path, words, budget, tool)
    if key not in _ANSWERS:
        _ANSWERS[key] = (_ask.context(map_path, words, budget)
                         if tool == "context"
                         else _ask.ask(map_path, words, budget))
    return _ANSWERS[key]


def _pick(map_path: str, pools: dict, n: int, seed: int,
          tool: str = "ask") -> tuple:
    """`n` questions that actually match something, balanced across the
    sources that have anything.

    Up to a third of the run from each kind first, then the rest filled from
    whatever is left over, so a map with two thousand declared names and
    thirty headings does not answer for the headings with two questions. A
    question the map cannot answer at any budget measures nothing about the
    budget: it is counted, not scored, and the walk carries on.
    """
    quota = max(1, -(-n // 3))
    asked, references, per_kind, leftovers, skipped = [], {}, collections.Counter(), [], 0

    def take(word):
        reference = ordered_rows(answer_for(map_path, word, 10 ** 9, tool))
        if not reference:
            return False
        asked.append(word)
        references[word] = reference
        return True

    for kind in KINDS:
        for word in _shuffled(pools.get(kind) or [], seed):
            if len(asked) >= n or per_kind[kind] >= quota:
                leftovers.append((kind, word))
                continue
            if take(word):
                per_kind[kind] += 1
            else:
                skipped += 1
    for kind, word in _shuffled(leftovers, seed):
        if len(asked) >= n:
            break
        if take(word):
            per_kind[kind] += 1
        else:
            skipped += 1
    return asked, references, per_kind, skipped


def evaluate(out_dir: str, n: int, budgets: list, seed: int,
             max_calls: int = 400, tool: str = "ask") -> dict:
    """The deterministic report: per budget, what the first answer holds and
    what the first answer plus its handles holds, against the whole answer.

    `tool` is which budgeted answer is measured: `ask`, or `context`, which
    composes five of them and cuts each block by the same rules. The
    questions differ with it. `ask` takes words and is asked the map's own
    three sources; `context` takes a name, so it is asked the declared names
    and nothing else - a section heading's longest word is not a name, and
    measuring `context` on one would measure the four empty blocks it would
    have.
    """
    map_path = os.path.join(out_dir, "framework_map.md")
    have = handles_available()
    pools = question_pool(out_dir)
    if tool == "context":
        pools = {kind: (words if kind == "name" else [])
                 for kind, words in pools.items()}
    asked, references, per_kind, skipped = _pick(map_path, pools, n, seed, tool)

    report = {
        "map": out_dir,
        "tool": tool,
        "seed": seed,
        "pool": sum(len(v) for v in pools.values()),
        "pool_by_kind": {kind: len(pools.get(kind) or []) for kind in KINDS},
        "questions": len(asked),
        "questions_by_kind": {kind: per_kind[kind] for kind in KINDS},
        "skipped_no_rows": skipped,
        "handles": have,
        "budgets": [],
        "losses": [],
    }

    for budget in budgets:
        first_recalls, full_recalls, sizes, top5 = [], [], [], []
        pooled_hit, pooled_total = 0, 0
        worst_calls, truncated = 0, 0
        oversize_total, oversize_by_question = 0, {}
        for word in asked:
            reference = references[word]
            wanted = set(reference)
            answer = answer_for(map_path, word, budget, tool)
            sizes.append(len(answer))
            shown = rows(answer)
            first = shown & wanted
            # Over-budget rows count here. A row longer than the whole
            # budget is a real thing the reader asked for and did not get,
            # and hiding it would flatter the budget.
            first_recalls.append(len(first) / len(wanted))
            # Macro above, micro here: the mean of per question recalls
            # weights a question with two rows the same as one with three
            # hundred, and the ratio of all rows shown to all rows there is
            # weights by size. They answer different questions and both are
            # reported rather than one being called the recall.
            pooled_hit += len(first)
            pooled_total += len(wanted)
            head = reference[:5]
            top5.append(sum(1 for row in head if row in shown) / len(head))
            # A row longer than the budget cannot be printed at that budget
            # by anything: not the first answer, and not `more`, which
            # reports it rather than skipping it. Measured on the suite
            # fixture, one 446 character row does this at budget 350. It is
            # counted and named here, and left out of the recall the exit
            # code asserts, which is about rows a handle could have returned.
            oversize = {row for row in wanted if len(row) > budget}
            if oversize:
                oversize_total += len(oversize)
                oversize_by_question[word] = len(oversize)
            if not have:
                continue
            found, calls, unfinished = _chase(map_path, answer, budget, max_calls)
            worst_calls = max(worst_calls, calls)
            truncated += 1 if unfinished else 0
            full = first | (found & wanted)
            fits = wanted - oversize
            if not fits:
                continue  # nothing at this budget could have come back
            recall = len(full & fits) / len(fits)
            full_recalls.append(recall)
            if recall < 1.0:
                report["losses"].append({
                    "budget": budget, "words": word,
                    "recall": round(recall, 4),
                    "missing": len(fits) - len(full & fits),
                    "reference_rows": len(wanted),
                    "rows_that_fit": len(fits),
                    "rows_over_budget": len(oversize),
                })
        report["budgets"].append({
            "budget": budget,
            "questions": len(asked),
            "first_answer_recall": round(_mean(first_recalls), 4),
            "pooled_recall": round(pooled_hit / pooled_total, 4) if pooled_total else 0.0,
            "top5_recall": round(_mean(top5), 4),
            "recall_with_handles": (round(_mean(full_recalls), 4) if have else None),
            "rows_over_budget": oversize_total,
            "rows_over_budget_by_question": dict(sorted(oversize_by_question.items())),
            "mean_bytes": round(_mean(sizes), 1),
            "max_more_calls": worst_calls if have else None,
            "chains_cut_short": truncated if have else None,
        })
    return report


def _mean(values: list) -> float:
    return (sum(values) / len(values)) if values else 0.0


_COLUMNS = ("budget", "questions", "first_answer_recall", "pooled_recall",
            "top5_recall", "recall_with_handles", "rows_over_budget",
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
    by_kind = ", ".join(f"{kind} {report['questions_by_kind'][kind]}"
                        f"/{report['pool_by_kind'][kind]}" for kind in KINDS)
    print(f"map: {report['map']}  tool: {report.get('tool', 'ask')}  "
          f"questions: {report['questions']} "
          f"of {report['pool']} in the pool ({by_kind})  seed: {report['seed']}")
    if not report["handles"]:
        print("handles: not available in this build")


# -------------------------------------------------------------- call graphs


# The three language groups `build()` counts call sites for, in the order a
# reader wants to read them, and the grammar `--graph` parses each extension
# with when tree-sitter is installed. `python` has no second opinion here: the
# map already resolves Python by AST, so a parse would be the same parse.
GRAPH_LANGS = ("python", "ts_js", "go")
_GRAMMAR_BY_EXT = {".ts": "typescript", ".tsx": "tsx", ".js": "javascript",
                   ".jsx": "javascript", ".go": "go"}
_GROUP_BY_EXT = {".ts": "ts_js", ".tsx": "ts_js", ".js": "ts_js",
                 ".jsx": "ts_js", ".go": "go"}
# A function, as each grammar spells one. `variable_declarator` is handled
# separately: `const pay = () => {}` declares the name on the declarator and
# the body on its value.
_FUNC_NODES = {"function_declaration", "method_definition", "method_declaration",
               "function_definition"}
_LAMBDA_NODES = {"arrow_function", "function", "function_expression",
                 "func_literal"}


def _rate(part: int, whole: int) -> float:
    """A share of `whole`, and 0.0 when there is no whole to take it of."""
    return round(part / whole, 4) if whole else 0.0


def _graph_row(lang: str, counts: dict) -> dict:
    """One language's line: what the walk looked at, and what it wrote.

    `sites`, `resolved` and `ambiguous` describe the tree that was read;
    `edges` and `marked` describe the graph that came out of it, and are 0 in
    a row computed from a parse rather than read out of a map, because a
    second opinion on the counts writes no edges.
    """
    sites = int(counts.get("sites") or 0)
    resolved = int(counts.get("resolved") or 0)
    ambiguous = int(counts.get("ambiguous") or 0)
    return {"language": lang, "sites": sites, "resolved": resolved,
            "ambiguous": ambiguous,
            "edges": int(counts.get("edges") or 0),
            "marked": int(counts.get("marked") or 0),
            "resolution_rate": _rate(resolved, sites),
            "ambiguous_share": _rate(ambiguous, sites)}


def _walk_source(repo: str) -> list:
    """Every TypeScript, JavaScript and Go file under `repo`, sorted.

    The map's own walk, minus the manifest: it is a second opinion on the same
    tree, so it reads the tree. It keeps the map's two bounds, `MAX_FILES`
    entries and a bounded read per file, because a pass over a tree that
    stops for nothing is a pass that never ends on a large one, and this pass
    runs from a command line the same person runs the build from.

    Entries are counted, not matches: a tree of a million files with three
    `.ts` in it is the case the cap is for. Directories and names are sorted
    before the cap applies, so which files a capped walk keeps is the same on
    every filesystem.
    """
    out, seen = [], 0
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in _mapper.SKIP_DIRS
                         and not d.startswith("."))
        for name in sorted(files):
            seen += 1
            if seen > _mapper.MAX_FILES:
                return sorted(out)
            if os.path.splitext(name)[1] in _GROUP_BY_EXT:
                out.append(os.path.join(root, name))
    return sorted(out)


def _ts_functions(node) -> list:
    """(name, body node) for every named function in one parse tree."""
    found = []

    def named(n):
        field = n.child_by_field_name("name")
        return field.text.decode("utf-8", "replace") if field is not None else ""

    def walk(n):
        if n.type in _FUNC_NODES:
            name = named(n)
            if name:
                found.append((name, n))
        elif n.type == "variable_declarator":
            value = n.child_by_field_name("value")
            name = named(n)
            if name and value is not None and value.type in _LAMBDA_NODES:
                found.append((name, n))
        for child in n.children:
            walk(child)

    walk(node)
    return found


def _ts_callees(node) -> set:
    """The callee names called anywhere inside `node`, as the map spells them.

    A plain call gives its identifier; a call through a receiver
    (`page.click()`, `srv.Serve()`) gives the member or field name, which is
    what the map's pattern pass records too, so the two counts compare.
    """
    names = set()

    def walk(n):
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None:
                if fn.type == "identifier":
                    names.add(fn.text.decode("utf-8", "replace"))
                else:
                    part = (fn.child_by_field_name("property")
                            or fn.child_by_field_name("field"))
                    if part is not None:
                        names.add(part.text.decode("utf-8", "replace"))
        for child in n.children:
            walk(child)

    walk(node)
    return names


def tree_sitter_stats(repo: str) -> dict:
    """`call_graph_stats` for TypeScript, JavaScript and Go, from a real parse.

    The same three numbers the map records from its pattern pass, counted the
    same way (one per function per distinct callee name) over a parse tree
    instead. Returns `{"skipped": reason}` when the optional `precise` extra
    is not installed or the repository is not there to read, because a
    comparison nobody can run is a note, not a zero.
    """
    if not repo or not os.path.isdir(repo):
        return {"skipped": f"the map's repository is not readable here: {repo!r}"}
    grammars = {}
    for ext, lang in sorted(_GRAMMAR_BY_EXT.items()):
        parser = _tree_sitter(lang)
        if parser is not None:
            grammars[ext] = parser
    if not grammars:
        return {"skipped": "tree-sitter is not installed: "
                           "pip install 'where-are-we[precise]'"}

    homes: dict = {}
    bodies: dict = {}
    for path in _walk_source(repo):
        ext = os.path.splitext(path)[1]
        parser = grammars.get(ext)
        if parser is None:
            continue
        try:
            # The same bounded read the map parses through, to the same cap:
            # a parser is handed at most `AST_LIMIT` bytes of any one file.
            tree = parser.parse(_slurp(path, AST_LIMIT).encode("utf-8"))
        except Exception:  # noqa: BLE001 - an optional third-party parser over
            # a file this package did not write; a file it cannot read counts
            # as a file with no functions in it.
            continue
        group = _GROUP_BY_EXT[ext]
        for name, node in _ts_functions(tree.root_node):
            homes.setdefault(group, {}).setdefault(name, set()).add(path)
            bodies.setdefault(group, []).append((path, name, node))

    stats: dict = {}
    for group in sorted(bodies):
        row = {"sites": 0, "resolved": 0, "ambiguous": 0}
        table = homes.get(group) or {}
        for _path, _name, node in bodies[group]:
            for callee in _ts_callees(node):
                row["sites"] += 1
                where = table.get(callee) or set()
                if where:
                    row["resolved"] += 1
                if len(where) > 1:
                    row["ambiguous"] += 1
        stats[group] = row
    return stats


def graph_report(out_dir: str) -> dict:
    """How much of its call tree the map resolved, per language.

    Reads `call_graph_stats`, which `build()` writes from the same walk that
    writes `call_graph_files`, and turns its counters into the two fractions a
    reader asks for: the share of callee names some indexed file declares, and
    the share several files declare, which are the edges the map marks `?`.

    `resolution_rate` is a property of the tree rather than of the graph. Its
    denominator holds every name a function calls, builtins, methods and the
    standard library included, and its numerator holds a call to a name the
    caller's own file declares, which is never an edge. `edges` and `marked`
    are the graph: how many cross-file edges came out of the walk, and how
    many of them name more than one file.

    Where the `precise` extra is installed the same numbers are computed from
    a tree-sitter parse of the TypeScript, JavaScript and Go the map read by
    pattern, and both are printed. The pattern pass counts a function's own
    name off its signature line and reads `if (` as a call; the parse does
    neither, so a regex site count above the parse's is the pattern pass
    admitting how much of what it counted was never a call.
    """
    path = os.path.join(out_dir, "framework_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            m = json.load(fh) or {}
    except (OSError, ValueError):
        m = {}
    stats = m.get("call_graph_stats")
    repo = str(m.get("repo") or "")
    report = {"map": out_dir, "repo": repo,
              "has_call_graph_stats": isinstance(stats, dict),
              "languages": [], "tree_sitter": {}}
    stats = stats if isinstance(stats, dict) else {}
    for lang in list(GRAPH_LANGS) + [k for k in sorted(stats) if k not in GRAPH_LANGS]:
        counts = stats.get(lang)
        if isinstance(counts, dict):
            report["languages"].append(_graph_row(lang, counts))

    ts = tree_sitter_stats(repo)
    if "skipped" in ts:
        report["tree_sitter"] = {"skipped": ts["skipped"]}
        return report
    rows = []
    for lang in sorted(set(ts) | {r["language"] for r in report["languages"]
                                  if r["language"] != "python"}):
        parsed = _graph_row(lang, ts.get(lang) or {})
        regex = next((r for r in report["languages"] if r["language"] == lang),
                     _graph_row(lang, {}))
        rows.append({"language": lang,
                     "regex": regex, "tree_sitter": parsed,
                     "delta_sites": parsed["sites"] - regex["sites"],
                     "delta_resolved": parsed["resolved"] - regex["resolved"],
                     "delta_resolution_rate":
                         round(parsed["resolution_rate"] - regex["resolution_rate"], 4)})
    if not rows:
        # tree-sitter is here and there is nothing for it to read. Said out
        # loud, because a silent absence reads as agreement.
        report["tree_sitter"] = {
            "skipped": "there is no TypeScript, JavaScript or Go under "
                       f"{repo} to compare"}
        return report
    report["tree_sitter"] = {"languages": rows}
    return report


_GRAPH_COLUMNS = ("language", "sites", "resolved", "ambiguous", "edges",
                  "marked", "resolution_rate", "ambiguous_share")


def print_graph(report: dict) -> None:
    """`graph_report` as a table, the same shape `print_table` prints."""
    rows = report["languages"]
    if not rows:
        print(f"no call graph statistics in {report['map']}: the map has no "
              "Python, TypeScript, JavaScript or Go in it, or predates "
              "call_graph_stats")
        return
    widths = {c: len(c) for c in _GRAPH_COLUMNS}
    for row in rows:
        for c in _GRAPH_COLUMNS:
            widths[c] = max(widths[c], len(str(row[c])))
    print("  ".join(c.rjust(widths[c]) for c in _GRAPH_COLUMNS))
    for row in rows:
        print("  ".join(str(row[c]).rjust(widths[c]) for c in _GRAPH_COLUMNS))
    print(f"map: {report['map']}  sites are callee names the walk looked at, "
          "one per function per name; resolved are the ones some indexed file "
          "declares; ambiguous are the ones several files declare; edges and "
          "marked are the cross-file edges written, plain and with a ?")
    print("resolution_rate is the share of a function's distinct callee names "
          "that are declared somewhere in the tree, so builtins, methods and "
          "the standard library are in the denominator and a call inside the "
          "caller's own file is in the numerator: it says how first-party the "
          "calls are, and the graph itself is edges and marked")
    ts = report.get("tree_sitter") or {}
    if ts.get("skipped"):
        print(f"regex vs tree-sitter: not compared, {ts['skipped']}")
        return
    for row in ts.get("languages") or []:
        r, t = row["regex"], row["tree_sitter"]
        print(f"regex vs tree-sitter, {row['language']}: sites {r['sites']} vs "
              f"{t['sites']} ({row['delta_sites']:+d}), resolved "
              f"{r['resolved']} vs {t['resolved']} ({row['delta_resolved']:+d}), "
              f"rate {r['resolution_rate']} vs {t['resolution_rate']} "
              f"({row['delta_resolution_rate']:+})")


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


def _each(value) -> list:
    """`mcp._each`: one argument or several."""
    if _mcp is not None:
        return _mcp._each(value)
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if str(x).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _share(budget: int, n: int, floor: int) -> int:
    """`mcp._share`: a batch splits the budget one question would have had."""
    if _mcp is not None:
        return _mcp._share(budget, n, floor)
    return max(floor, budget // max(1, n))


def _joined(pairs) -> str:
    """`mcp._joined`: answers labelled by their question, one left bare."""
    if _mcp is not None:
        return _mcp._joined(pairs)
    pairs = list(pairs)
    if len(pairs) == 1:
        return pairs[0][1]
    return "\n\n".join(f"### {q}\n{a}" for q, a in pairs)


def _map_tools() -> list:
    """The map tools exactly as the MCP server declares them, renamed to the
    Messages API's `input_schema`. Read from `mcp.TOOLS` rather than copied,
    so a tool added there is evaluated here without an edit."""
    if _mcp is None:
        return []
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
        # The server answers a list of words as several questions sharing one
        # budget, and labels them. Same split here, through the server's own
        # `_each`, `_share` and `_joined`, so the arm is measured on the
        # answers a real session gets rather than on a second arrangement of
        # the same map.
        asked = _each(args.get("words")) or [""]
        room = _share(_ANSWER_BUDGET, len(asked), 1500)
        spec = os.path.join(out_dir, "spec_map.md")
        each = room // 2 if os.path.exists(spec) else room
        pairs = []
        for words in asked:
            body = _ask.ask(map_path, words, each)
            if os.path.exists(spec):
                body += "\n\n" + _ask.ask(spec, words, each)
            pairs.append((words, body))
        return _joined(pairs)
    if name == "defines":
        wanted = args.get("name")
        wanted = wanted if isinstance(wanted, list) else [str(wanted or "")]
        hits = _mapper.spans_for(map_path, [str(w).lower() for w in wanted])
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
    if name == "callees" and hasattr(_ask, "callees_line"):
        wanted = args.get("name")
        wanted = wanted if isinstance(wanted, list) else [str(wanted or "")]
        return "\n".join(_ask.callees_line(json_path, str(w)) for w in wanted)
    if name == "impact" and hasattr(_ask, "impact"):
        wanted = args.get("name")
        wanted = wanted if isinstance(wanted, list) else [str(wanted or "")]
        asked_depth = args.get("depth")
        depth = int(asked_depth) if isinstance(asked_depth, int) else 3
        return _joined([(str(w), _ask.impact(json_path, str(w), depth))
                        for w in wanted])
    if name == "find":
        # `limit` is in the tool's schema, so an agent that sets it gets what
        # it asked for; the batch splits it the way the server does.
        phrases = _each(args.get("phrase")) or [""]
        asked_limit = args.get("limit")
        limit = int(asked_limit) if isinstance(asked_limit, int) else _HIT_BUDGET
        room = _share(limit, len(phrases), 5)
        return _joined([(p, _mapper.find_text(out_dir, p, room)) for p in phrases])
    if name == "at" and hasattr(_ask, "at"):
        places = _each(args.get("place")) or [""]
        room = _share(_ANSWER_BUDGET, len(places), 1500)
        return _joined([(p, _ask.at(map_path, p, room)) for p in places])
    if name == "context" and hasattr(_ask, "context"):
        wanted = _each(args.get("name")) or [""]
        asked_limit = args.get("limit")
        limit = (int(asked_limit) if isinstance(asked_limit, int)
                 else _ANSWER_BUDGET)
        room = _share(limit, len(wanted), 1500)
        return _joined([(w, _ask.context(map_path, w, room)) for w in wanted])
    if name == "sections":
        return "\n".join(_ask.map_heads(map_path))
    if name == "more" and hasattr(_ask, "more"):
        return _ask.more(map_path, str(args.get("handle") or ""), _ANSWER_BUDGET)
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
    if not ANTHROPIC_API_KEY:
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
        # After every question, not at the end. Each question is two model
        # calls that cost money, and a rate limit or a dropped connection on
        # question nine used to throw the eight already paid for away.
        # `asked` says how far the file got, so a partial file reads as a
        # partial run rather than a complete one with a suspicious total.
        _write_agent_json(json_path, model, out_dir, repo, seed,
                          len(questions), results, arms)

    summaries = _write_agent_json(json_path, model, out_dir, repo, seed,
                                  len(questions), results, arms)
    headers = ("arm", "questions", "correct", "accuracy", "tokens_in",
               "tokens_out", "tool_calls")
    widths = {h: max(len(h), *(len(str(r[h])) for r in summaries)) for h in headers}
    print("  ".join(h.rjust(widths[h]) for h in headers))
    for row in summaries:
        print("  ".join(str(row[h]).rjust(widths[h]) for h in headers))
    print(f"wrote {json_path}")
    return 0


def _write_agent_json(json_path: str, model: str, out_dir: str, repo: str,
                      seed: int, planned: int, results: list, arms) -> list:
    """The report as it stands, written to a temporary and renamed into
    place, the way every other artefact this project writes is: a reader
    that opens the file mid-run sees the previous whole one, never half of
    this one. Returns the per arm summaries so the caller can print them."""
    summaries = []
    for arm, _, _ in arms:
        mine = [r for r in results if r["arm"] == arm]
        correct = sum(1 for r in mine if r["correct"])
        summaries.append({"arm": arm, "questions": len(mine), "correct": correct,
                          "accuracy": round(correct / len(mine), 4) if mine else 0.0,
                          "tokens_in": sum(r["tokens_in"] for r in mine),
                          "tokens_out": sum(r["tokens_out"] for r in mine),
                          "tool_calls": sum(r["tool_calls"] for r in mine)})
    report = {"model": model, "map": out_dir, "repo": repo, "seed": seed,
              "questions": planned, "asked": len(results) // max(1, len(arms)),
              "complete": len(results) == planned * len(arms),
              "results": results, "arms": summaries}
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    os.replace(tmp, json_path)
    return summaries


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
    parser.add_argument("--tool", default="ask", choices=["ask", "context"],
                        help="which budgeted answer to measure: ask, or "
                             "context, which composes five of them and cuts "
                             "each block by the same rules (default ask). "
                             "context is asked declared names only, since "
                             "that is what it takes")
    parser.add_argument("--assert-from", type=int, default=1500, metavar="BYTES",
                        help="fail (exit 1) on rows no handle returned only at "
                             "budgets of at least BYTES (default 1500, the MCP "
                             "server's floor); smaller budgets are reported, not "
                             "asserted, since an answer that small may not hold "
                             "both a row and the handle that points at the rest")
    parser.add_argument("--max-more", type=int, default=400, metavar="N",
                        help="stop chasing a question's handles after N calls "
                             "(default 400)")
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON, no table")
    parser.add_argument("--graph", action="store_true",
                        help="print how much of its call tree the map "
                             "resolved, per language, from call_graph_stats; "
                             "with the precise extra installed, the same "
                             "numbers from a tree-sitter parse beside them")
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

    if args.graph:
        # Its own mode, not a section under the recall table: it reads three
        # counters out of the map and, with tree-sitter installed, parses the
        # repository again. Neither has anything to do with what a budget
        # loses, and a run that wants the graph numbers should not pay for a
        # hundred budgeted questions to get them.
        report = graph_report(out_dir)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_graph(report)
        return 0

    if args.agent:
        repo = args.repo
        if not repo:
            parser.error("--agent needs --repo: the repository the map was built from")
        return run_agent(out_dir, repo, args.questions, args.seed, args.model,
                         args.agent_json, args.max_turns)

    try:
        budgets = [int(b) for b in str(args.budgets).split(",") if b.strip()]
    except ValueError:
        parser.error(f"--budgets takes comma separated whole numbers, not "
                     f"{args.budgets!r}")
    if not budgets:
        parser.error("--budgets needs at least one number")
    if any(b < 0 for b in budgets):
        parser.error("--budgets takes byte counts, which are not negative")
    if args.tool == "context" and not hasattr(_ask, "context"):
        print("this build has no context tool", file=sys.stderr)
        return 2
    report = evaluate(out_dir, args.questions, budgets, args.seed,
                      args.max_more, args.tool)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_table(report)

    fatal = [loss for loss in report["losses"]
             if loss["budget"] >= args.assert_from]
    if report["handles"] and report["losses"]:
        # A row the map holds, that fits the budget, that the budgeted answer
        # cut, and that no handle gave back. At a budget the MCP server ever
        # uses (1500 and up) that is a bug in `more`, not a property of the
        # budget, so it fails the run rather than printing a number nobody
        # reads. Below --assert-from the answer may be too small to carry a
        # row and the handle that points at the rest, so those losses are
        # printed and not asserted. A row longer than the budget is neither:
        # it is counted in rows_over_budget and named.
        print(f"{len(report['losses'])} question(s) lost rows no handle "
              f"returned ({len(fatal)} at budgets of {args.assert_from} or "
              "more, which fail the run):", file=sys.stderr)
        for loss in report["losses"][:10]:
            print(f"- budget {loss['budget']}, {loss['words']!r}: "
                  f"{loss['missing']} of {loss['rows_that_fit']} rows that fit "
                  f"the budget missing ({loss['rows_over_budget']} more were "
                  "longer than the budget and are not counted)", file=sys.stderr)
        return 1 if fatal else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
