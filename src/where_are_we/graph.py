"""What reaches what: the answers the map's own graph already holds.

Three questions over one walk. `affected` starts at the names a change
declares and climbs to the step functions above them, which is the test
selection. `reaches` starts at one name and climbs the same way, which is the
same question asked about a function rather than about a commit. `unreached`
runs that walk once in the other direction, down from every step function,
and names the product it never arrives at.

`xrefs` records every edge with the rule that placed it, `spans` every
declaration with its range, `steps` the phrases each step module binds and
`features` the scenarios of each feature file. Nothing here extracts anything
or opens a source file: it walks those tables upward, from the callee a
changed file declares to the callers that reach it, and stops at the step
functions, which is where a scenario begins.

Pure functions over one loaded map, so the command line, the MCP server and
`ask.more()` all answer from the same walk. The cutting to a budget, the tails
and the `more:aff:` handles are `ask.py`'s, which is where every other answer
in this project is cut.
"""

import json
import os
import re
import shlex
import subprocess

try:
    from ._mapper import rank as _rank_graph
except ImportError:  # run as a plain file, with no package around it
    from _mapper import rank as _rank_graph  # type: ignore[no-redef]

MAP_NAME = "framework_map.json"

# How many call hops upward one answer follows by default, and the most it
# will follow. Six because a step function is one hop from a page object
# method and three or four from a helper under it, so six covers the shape a
# suite actually has; past that the walk is reaching product code that no
# longer says anything about which test to run.
DEFAULT_DEPTH = 6
MAX_DEPTH = 12

# A Gherkin step line, and the keyword in front of the phrase. The same
# expression `_mapper/build.py` binds a feature to a step module with, because
# a scenario reached here and a scenario linked there have to be the same
# scenario.
_STEP_LINE = re.compile(r"\s*(?:Given|When|Then|And|But)\s+(.+)$")
_QUOTED = re.compile(r'"[^"]*"')
_PLACEHOLDER = re.compile(r"\{[^}]*\}")
# How much of a step phrase has to appear in a scenario's line. The map's own
# rule, from the same place: a phrase is normalised, cut to this, and looked
# for inside the line.
PHRASE_HEAD = 40

# The route rows the map writes end in the basename of the file serving them:
# `GET /invoice  (api.py)`. There is no handler name in that row, so a route
# is named here when the file it is served from is reached, which is what the
# block's head says out loud.
_ROUTE_FILE = re.compile(r"\(([^()]+)\)\s*$")

# A scenario outline's placeholder, in the name the map recorded. `re.escape`
# leaves the angle brackets alone, so this finds them after escaping.
_OUTLINE_SLOT = re.compile(r"<[^>]*>")

# What `_mapper/walk.py` writes in place of a value that looked like a
# secret. A line carrying it is not the line on disk, so `range` marks it
# rather than offering it as something an `Edit` can match on.
REDACTED = "[redacted]"

# How many `--name` arguments a behave selection prints one per scenario
# before it alternates each feature file's names into one argument instead.
# A command line has a length: 200 names of a suite's own scale is a few
# kilobytes, which every shell carries, and a selection ten times that is
# better sent as eight regular expressions than as two thousand arguments.
NAME_ARGS = 200


def load(map_dir: str) -> dict:
    """`framework_map.json` under `map_dir`, or `{}` when there is none.

    Every caller here is answering a question rather than building anything,
    so a missing or unreadable map is an empty map: the answer then says the
    graph holds nothing about these files, which is true, instead of raising
    at a reader who asked a fair question of a directory with no map in it.
    """
    try:
        with open(os.path.join(map_dir, MAP_NAME), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def changed_files(repo: str, ref: str = "HEAD") -> tuple:
    """`(files, problem)`: what `git diff --name-only <ref>` names in `repo`.

    The paths git prints are relative to the repository root, which is what
    every other file argument in this tool is relative to, so the list goes
    straight into `affected()`. `repo` is the repository the map was built
    from (the map's own `repo` key) rather than whatever directory the caller
    happens to be in: the answer is about the tree the graph describes.

    `problem` is a sentence when there is one and empty otherwise, so the
    caller prints it rather than a traceback: no git on the machine, no
    repository at that path, or a ref this checkout does not have.
    """
    if not repo:
        return [], "the map does not say which repository it was built from"
    if ref.startswith("-"):
        return [], f"{ref!r} is not a ref; it reads as an option to git"
    try:
        done = subprocess.run(["git", "-C", repo, "diff", "--name-only", ref, "--"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git diff --name-only {ref} in {repo} did not run: {exc}"
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        return [], (f"git diff --name-only {ref} in {repo} failed: "
                    + (detail[0] if detail else f"exit {done.returncode}"))
    return [line.strip() for line in done.stdout.splitlines() if line.strip()], ""


def _subject_file(row: dict) -> str:
    """The file one `xrefs` row is about.

    A `calls` row's subject is `<file>:<func>` and every other row's subject
    is the file itself, which is the same split `ask.py` makes when it reads
    a resolution off this table.
    """
    subject = str(row.get("subject") or "")
    if row.get("edge") == "calls":
        return subject.rpartition(":")[0]
    return subject


def _normalise(phrase: str) -> str:
    """One step phrase as the map compares it: placeholders dropped, lowered."""
    return _PLACEHOLDER.sub("", phrase or "").strip().lower()


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _climb(m: dict, seeds, depth=None, up: bool = True,
           goal=None) -> dict:
    """The one walk over the map's `calls` rows, in whichever direction.

    `seeds` are `(file, name)` nodes at hop 0, and each hop takes the `calls`
    rows that touch a node of the frontier. Upward the row's object is the
    node's name and the row's settled file is the node's file, so the reached
    node is the caller; downward the row's subject is the node itself, so the
    reached node is the callee. A row that settled on no file counts either
    way when the node is among its candidates, which is the ambiguous edge
    naming every file that declares the callee: an answer that skipped it
    would say a scenario reaches nothing where the truth is that the graph
    does not know which of two files it reaches.

    Nodes are `(file, name)` pairs and the visited set carries across hops, so
    a cycle is walked once; the frontier is sorted at every hop, so the hop a
    node is first found at, and the edge that found it, are the same on every
    run. Downward, one node's rows are sorted by callee, call-site line and
    resolution before they are followed, which `path` needs to print the same
    chain every time and which the mapper's emission order happens to give
    already: measured over this repository's own graph and the golden suite,
    no calling node's rows are out of that order. Sorting them here rather
    than relying on that habit costs nothing and pins the determinism.
    `depth` of None walks until nothing new is found, which is what a question
    about the whole graph ("does anything at all reach this") needs and what a
    question about a change ("which tests, six hops out") does not.

    `goal`, when given, stops the walk at the end of the hop that first
    reaches one of those nodes. A node is recorded at the first hop it is
    found at, so the chain read back from a goal is the shortest one either
    way; what the early stop changes is how much of the graph was walked,
    which is the number `path` reports as its reach.

    Returns `{node: (hop, row, parent)}`. `parent` is the node this one was
    found from, so a chain of hops can be read back off it without the walk
    keeping paths.
    """
    index: dict = {}
    for row in m.get("xrefs") or ():
        if row.get("edge") != "calls":
            continue
        key = row.get("object") if up else str(row.get("subject") or "")
        index.setdefault(key, []).append(row)

    seen: dict = {}
    for node in seeds:
        seen.setdefault(node, (0, None, None))
    frontier = sorted(seen)
    hop = 0
    while frontier and (depth is None or hop < depth):
        hop += 1
        found = []
        for node in frontier:
            for reached, row in _next_nodes(index, node, up):
                if reached in seen:
                    continue
                seen[reached] = (hop, row, node)
                found.append(reached)
        frontier = sorted(found)
        if goal and any(node in goal for node in frontier):
            break
    return seen


def _next_nodes(index: dict, node: tuple, up: bool):
    """The nodes one hop from `node`, with the row that gets there."""
    holder, name = node
    if up:
        for row in index.get(name, ()):
            settled = row.get("file")
            if settled != holder and not (
                    settled is None and holder in (row.get("candidates") or ())):
                continue
            caller_file, _, caller_name = str(
                row.get("subject") or "").rpartition(":")
            yield (caller_file, caller_name), row
        return
    rows = sorted(index.get(f"{holder}:{name}", ()),
                  key=lambda r: (str(r.get("object") or ""), r.get("line") or 0,
                                 str(r.get("resolution"))))
    for row in rows:
        settled = row.get("file")
        for target in ([settled] if settled
                       else sorted(str(c) for c in (row.get("candidates") or ()))):
            yield (target, str(row.get("object") or "")), row


def affected(m: dict, files, depth: int = DEFAULT_DEPTH) -> dict:
    """What a change to `files` reaches, walked upward over the `calls` rows.

    `files` are repo-relative paths or directory prefixes, matched by the
    same rule `--files` uses: a prefix stops at a path separator, so `pages/`
    is that directory and `page` is nothing.

    The walk starts at every name the changed files declare (their `declares`
    rows) at hop 0, and each hop takes the `calls` rows whose object is one of
    those names and whose settled file is the file declaring it. A row that
    settled on no file counts when the declaring file is one of its
    candidates, which is the ambiguous edge naming every file that declares
    the callee. Nodes are `(file, name)` pairs and a visited set carries
    across hops, so a cycle is walked once; the frontier is sorted at every
    hop, so the hop a node is first found at, and the edge that found it, are
    the same on every run.

    Returns the blocks the answer prints, each already sorted:
    `scenarios` (feature file, name, line, the step that reaches the change
    and how many hops it is), `features`, `routes`, `pages`, `steps`,
    `unreachable` (a named file with no `xrefs` row at all, so this answer
    says nothing about it), `pytest` node ids, and the counts the first line
    of the answer states.
    """
    wanted = [f for f in files if f]
    depth = max(1, min(int(depth), MAX_DEPTH))
    root = m.get("repo") or ""

    subjects, seeds = [], []
    for row in m.get("xrefs") or ():
        subject_file = _subject_file(row)
        subjects.append(subject_file)
        if row.get("edge") == "declares" and _rank_graph.matches(
                subject_file, root, wanted):
            seeds.append((subject_file, row.get("object")))

    seen = _climb(m, seeds, depth)
    return _blocks_from(m, root, wanted, depth, seen, set(subjects))


def _declaration_sites(m: dict) -> tuple:
    """`(step_at, func_at)`, both read off `spans` in one pass.

    Where each declaration of each kind sits. A behave step is two
    declarations on one line: the function, and the phrase its decorator
    binds. So a node is a step function when `spans` has it as a function and
    has a phrase starting on the same line of the same file, which is the
    join that identifies one without reading the source or guessing from a
    module's name.

    `step_at` is `{(file, line): phrase}` and `func_at` is
    `{(file, name): line}`. `affected` uses both to say which reached node is
    a step, and `dead` uses `step_at` to leave a step function out of a list
    of things nothing calls: nothing calls a step function, because behave
    does, off a phrase in a feature file.
    """
    step_at, func_at = {}, {}
    for name, sites in (m.get("spans") or {}).items():
        for site in sites or ():
            where = (site.get("file"), site.get("start"))
            if site.get("kind") == "step":
                step_at.setdefault(where, name)
            elif site.get("kind") == "function":
                func_at.setdefault((site.get("file"), name), site.get("start"))
    return step_at, func_at


def _routes_reached(m: dict, reached_files: set) -> list:
    """The `routes_served` rows served from a file the walk reached.

    That key ends in the basename of the file serving each route and holds no
    handler name, so a route is named when the file it is served from is
    reached and the block's head says so out loud. Two files of one basename
    would both match; nothing in the map distinguishes them at this key.
    """
    bases = {os.path.basename(f) for f in reached_files}
    out = []
    for route in m.get("routes_served") or ():
        hit = _ROUTE_FILE.search(str(route))
        if hit and hit.group(1) in bases:
            out.append(str(route))
    return out


def _steps_reached(m: dict, root: str, seen: dict) -> tuple:
    """`(steps, by_phrase)`: the step functions among the walked nodes.

    `steps` is `(phrase, module, function, hops)` per step function reached,
    counted by the site rather than by the name. One `def` can be declared
    under two names here: a step module's own extractor writes `step_pay_1`
    and `def step_pay_1` for the same line, and counting both would report
    twice as many step functions as the suite has. The name kept is the one
    that reads as an identifier, which is the shorter of the two and the one
    without a space in it.

    `by_phrase` is those steps by the key a feature line is matched against,
    nearest first: where two step functions bind phrases that normalise to
    the same forty characters, the scenario is reported through the one
    closer to what was asked about. Ties by phrase, then by module and
    function, so the choice does not depend on the order the walk found them.
    """
    step_at, func_at = _declaration_sites(m)
    by_site: dict = {}
    for (holder, name), found in seen.items():
        hop = found[0]
        start = func_at.get((holder, name))
        if step_at.get((holder, start)) is None:
            continue
        by_site.setdefault((holder, start), []).append(
            ((1 if " " in name else 0, len(name), name), hop))
    steps = []
    for (holder, start), found in by_site.items():
        steps.append((step_at[(holder, start)],
                      _rank_graph.relative(holder, root),
                      min(found)[0][2], min(hop for _rank, hop in found)))
    steps.sort()

    by_phrase: dict = {}
    for phrase, holder, name, hop in sorted(steps, key=lambda s: (s[3],) + s[:3]):
        key = _normalise(phrase)[:PHRASE_HEAD]
        if key:
            by_phrase.setdefault(key, (phrase, holder, name, hop))
    return steps, by_phrase


def _blocks_from(m: dict, root: str, wanted: list, depth: int, seen: dict,
                 subjects: set) -> dict:
    """The reached nodes turned into the lists the answer prints.

    Split out of `affected()` because the walk is one idea and reading the
    other tables through its result is another: `spans` says which of the
    reached functions is a step, `steps` and `features` say which scenarios
    those steps are in, and `routes_served`, `page_objects` and
    `pytest_tests` each name a file the walk may have reached.
    """
    steps, by_phrase = _steps_reached(m, root, seen)
    reached_files = {holder for holder, _name in seen}

    scenarios, unbound = _scenarios(m, root, wanted, by_phrase)
    features = sorted({row[0] for row in scenarios})

    routes = _routes_reached(m, reached_files)

    relative = {_rank_graph.relative(f, root) for f in reached_files}
    pages = sorted(p for p in (m.get("page_objects") or ()) if p in relative)

    cases = []
    for rel, names in sorted((m.get("pytest_tests") or {}).items()):
        for holder, name in seen:
            if _rank_graph.relative(holder, root) == rel and name in (names or ()):
                cases.append(f"{rel}::{name}")
    cases.sort()

    unreachable = sorted(
        f for f in wanted
        if not any(_rank_graph.matches(s, root, [f]) for s in subjects))

    total = sum(len(f.get("scenarios") or ())
                for f in (m.get("features") or {}).values())
    return {"files": list(wanted), "depth": depth, "scenarios": scenarios,
            "features": features, "routes": routes, "pages": pages,
            "steps": steps, "pytest": cases, "unreachable": unreachable,
            "total_scenarios": total, "unbound": unbound,
            "no_edges": edge_count(m) == 0}


def _scenarios(m: dict, root: str, wanted: list, by_phrase: dict) -> tuple:
    """`(rows, unbound)`: the scenarios this change reaches, and why each one.

    A row is `(feature file, name, line, why)`, and there are two kinds of
    why. A scenario's steps are its own lines, which the map already holds in
    `lines`, read from the scenario's line to the line before the next
    scenario in that file; a line is a step of this scenario when a reached
    phrase, normalised and cut to `PHRASE_HEAD`, appears in it, which is the
    rule `feature_links` is built with, so a scenario named here is a scenario
    the map already binds to that step module.

    The other kind is the feature file itself being one of the changed files.
    A feature file is a test rather than something a test calls, so every
    scenario in it is affected at no hops at all, and a commit that edits or
    adds a scenario is the commonest change a suite gets. Without this the
    answer to such a commit was no block at all, which reads as an all clear.

    `unbound` counts the scenarios no step phrase in this map binds to at all,
    reached or not. Without it a zero in the first line reads as "this change
    is safe", when what it can also mean is that the suite's phrases and its
    features do not meet.
    """
    known = []
    for phrases in (m.get("steps") or {}).values():
        for phrase in phrases or ():
            key = _normalise(phrase)[:PHRASE_HEAD]
            if key:
                known.append(key)
    rows, unbound = [], 0
    for rel, entry in sorted((m.get("features") or {}).items()):
        body = (m.get("lines") or {}).get(os.path.join(root, rel)) or []
        itself = _rank_graph.matches(os.path.join(root, rel), root, wanted)
        marks = sorted((s.get("line") or 0, s.get("name") or "")
                       for s in (entry.get("scenarios") or ()))
        for i, (line, name) in enumerate(marks):
            end = marks[i + 1][0] - 1 if i + 1 < len(marks) else len(body)
            hits = []
            for offset, text in enumerate(body[line:end], line + 1):
                step = _STEP_LINE.match(text)
                if not step:
                    continue
                low = _QUOTED.sub("", step.group(1)).strip().lower()
                for key, (phrase, holder, func, hop) in by_phrase.items():
                    if key in low:
                        hits.append((hop, offset, phrase, holder, func))
                        break
            if not _binds(known, body, line, end):
                unbound += 1
            if itself:
                # The file the change is in. That beats any path through a
                # step, because the scenario is going to run whatever its
                # steps call.
                rows.append((rel, name, line, "the feature file itself changed"))
            elif hits:
                hop, _offset, phrase, holder, func = min(hits)
                rows.append((rel, name, line, _via(phrase, holder, func, hop)))
    # By where each scenario is written rather than by what it is called, so
    # a feature file reads here in the order it reads on disk.
    rows.sort(key=lambda row: (row[0], row[2], row[1]))
    return rows, unbound


def _via(phrase: str, holder: str, func: str, hop: int) -> str:
    """Why one scenario is named: the step it goes through, and how far.

    One function rather than one f-string in two files, because `reaches`
    hangs its hop chain off this exact string: the chain is printed under the
    first scenario of each feature file, and it finds that scenario by the
    reason written beside it.
    """
    return f"via `{phrase}` in `{holder}:{func}`, {_plural(hop, 'hop')}"


def _binds(known: list, body: list, line: int, end: int) -> bool:
    """Whether any step phrase in this map matches any line of one scenario.

    Every phrase, not only the reached ones: a scenario whose steps no module
    binds cannot be reached by any change, and saying so is the difference
    between "your change touches nothing this scenario does" and "this map
    cannot tell you either way".
    """
    for text in body[line:end]:
        step = _STEP_LINE.match(text)
        if not step:
            continue
        low = _QUOTED.sub("", step.group(1)).strip().lower()
        if any(key in low for key in known):
            return True
    return False


def edge_count(m: dict) -> int:
    """How many cross-file `calls` edges the walk wrote, over every language.

    `resolution()` counts callee names some indexed file declares, and a name
    the caller's own file declares is resolved without ever becoming an edge,
    so a map can report 100 percent resolution and hold no edge at all. A
    JavaScript suite does exactly that: the call sits in the arrow passed to
    `it(...)`, which is not a declared function, so the extractor never scans
    it and `call_graph_stats` comes back `{'ts_js': {'sites': 3, 'resolved':
    3, 'edges': 0}}`. Every upward walk then stops where it starts, and a
    list of names under a head that does not say so reads as a coverage
    report when it is a fact about the walk.
    """
    stats = m.get("call_graph_stats") or {}
    return sum(int((row or {}).get("edges") or 0) for row in stats.values())


# The one sentence `affected`, `reaches` and `unreached` add when the graph
# all three walk holds nothing. One string, because the three answers are
# wrong in the same way on such a map and a reader who learns the phrase in
# one place should meet the same words in the other two. In the first line
# and not only in a block, for the reason the `unreachable` sentence is:
# a block is what a small budget gives up first.
NO_EDGES = (" There are no call graph edges in this map, so every walk here "
            "stops where it starts: what is missing is the graph, not the "
            "tests.")


def summary(result: dict, limit: int) -> str:
    """The first line of every answer: what was counted, and under what rules.

    Every character of it is a character no block gets, so it says the counts,
    the depth the walk ran to and the ceiling it was cut against, and then the
    one caveat a count of zero needs: how many scenarios hold no step this map
    can bind to a step function at all.

    A `limit` of zero is the `--affected-format` answer, which has no ceiling
    at all: a runner's selection is a machine artefact rather than prose, and
    a selection cut in half is a test run that misses tests. The line says
    "printed whole" there rather than a number nothing was measured against.
    """
    files = result["files"]
    named = ", ".join(files) if len(files) <= 3 else _plural(len(files), "file")
    head = (f"Affected by a change to {named}: {len(result['scenarios'])} of "
            f"{result['total_scenarios']} scenarios, "
            f"{_plural(len(result['features']), 'feature file')}, "
            f"{_plural(len(result['routes']), 'route')}, "
            f"{_plural(len(result['pages']), 'page object')}, "
            f"{_plural(len(result['steps']), 'step function')}. Depth "
            f"{result['depth']}, "
            + (f"{limit} characters." if limit else "printed whole."))
    if result["unbound"]:
        head += (f" {result['unbound']} of {result['total_scenarios']} "
                 "scenarios hold no step this map binds to a step function.")
    left = len(result["unreachable"])
    if left:
        # In the first line and not only in the block, because the block is
        # the one this answer gives up first at a small budget, and a
        # selection that drops the sentence saying it is partial is the one
        # way this tool can be actively wrong.
        head += (f" No xrefs row names {left} of the files given, so this "
                 f"answer says nothing about {'it' if left == 1 else 'them'}.")
    if result["no_edges"]:
        head += NO_EDGES
    return head


# The blocks one answer prints, in order: the name a `more:aff:` handle
# carries, the head, and the percentage of the budget the block is guaranteed
# as a floor. `ask.py` hands on what a block does not want, in this order, so
# a block is never cut while room the answer was allowed goes unspent.
#
# `unreachable` is last and holds a quarter of the floor because it is the
# block that says the answer is partial. A file the graph has no row for is
# not "not affected", and a selection that quietly drops it is the one way
# this tool can be actively wrong.
BLOCKS = (
    ("scenarios", "## Scenarios", 40),
    ("features", "## Feature files", 10),
    ("routes", "## Routes (named by the file each one is served from)", 10),
    ("pages", "## Page objects", 15),
    ("unreachable", "## Unreachable from the graph (no xrefs row names them)",
     25),
)
NAMES = tuple(name for name, _head, _pct in BLOCKS)
HEADS = {name: head for name, head, _pct in BLOCKS}

# The two forms `--affected-format` prints instead of the blocks. Each is one
# block of its own, so it is cut and handed back by the same rules.
FORMATS = ("behave", "pytest")


def selectors(result: dict, fmt: str) -> list:
    """The runner's own arguments and nothing else, for the file form.

    Empty where the change reaches nothing, which is where this differs from
    `block_lines`: the block a person reads says "nothing to run" in words,
    and a file a pipeline runs `xargs behave <` on says it by being empty. A
    sentence in that file is an argument to behave, and behave fails on it.
    """
    if fmt == "behave":
        return _behave_lines(result) if result["scenarios"] else []
    if fmt == "pytest":
        return list(result["pytest"])
    return []


def block_lines(result: dict, block: str) -> list:
    """One block's rows, whole, before anything is cut to a budget.

    Empty for a block with nothing in it: the first line already printed the
    count, and five heads with nothing under them are five rows of a budget
    spent saying nothing. The two `--affected-format` blocks are the
    exception, because there the block is the whole answer.
    """
    if block == "scenarios":
        return [f"- `{rel}:{line}` {name}, {why}"
                for rel, name, line, why in result["scenarios"]]
    if block == "features":
        return [f"- `{rel}`" for rel in result["features"]]
    if block == "routes":
        return [f"- {route}" for route in result["routes"]]
    if block == "pages":
        return [f"- `{rel}`" for rel in result["pages"]]
    if block == "unreachable":
        return [f"- `{rel}`" for rel in result["unreachable"]]
    if block == "behave":
        return _behave_lines(result)
    if block == "pytest":
        return result["pytest"] or [
            "no pytest case in this map is reached by a change to these files"]
    return []


def format_head(result: dict, block: str) -> str:
    """The head of a `--affected-format` block, which says which form it is.

    A caller pastes this into a pipeline without reading the block above it,
    so the head has to say what the lines under it select and how exactly.
    """
    if block == "pytest":
        return "## pytest node ids, one per line"
    if not result["scenarios"]:
        return "## behave selection"
    if _combined(result):
        return ("## behave selection, one argument pair per line for `xargs "
                f"behave`: more than {NAME_ARGS} scenarios, so one --name per "
                "feature file alternating its affected scenarios; two "
                "scenarios of one name are one selector and behave runs both")
    return ("## behave selection, one argument pair per line for `xargs "
            "behave`: one --name per affected scenario; two scenarios of one "
            "name are one selector and behave runs both")


def _behave_lines(result: dict) -> list:
    """The behave arguments that select exactly the scenarios named above.

    One `--name` per affected scenario, anchored on the whole name, and
    nothing else. `--name` is the only behave option that can express this
    selection: it is `action="append"`, so several of them are a union, and
    it is matched against a scenario's name wherever that scenario lives.

    `-i` cannot. It was tried, for a feature file every scenario of which is
    affected, and it is wrong twice over in behave 1.3.3: `--include` is a
    plain `store`, so the last `-i` on the line overwrites every earlier one,
    and it filters which files are collected at all, so it intersects with
    `--name` rather than adding to it. Measured: a change affecting all 24
    scenarios of 8 feature files selected 3 of them, and a change affecting
    one whole file and half of another selected none of the three it named.
    Under-selection, again, so brevity loses to correctness and every
    scenario gets its own argument.

    Above `NAME_ARGS` scenarios the names of one feature file are alternated
    into a single `--name` for that file, because a command line has a length
    and a selection of a thousand scenarios has to survive it. Same regular
    expression, same anchors, one argument per file rather than per scenario.

    Two scenarios of one name in one file are one `--name`, and behave runs
    both. That over-selects rather than under-selects, and the block above
    names each of them with its own line.

    No tag is ever emitted. behave applies `--tags` per scenario, and the map
    records the tags of a feature file as every `@word` anywhere in it,
    scenario tags and the `@` of an email address in a step line included,
    with nothing saying which line each came from. A tag built from that key
    selected the wrong scenarios, and once selected nothing at all: the
    reviewer's suite with `@slow` on the one scenario the change does not
    reach ran that one and skipped the two it does, and the same suite with
    `billing@example.com` in a step line emitted `@example.com` and ran none
    of the three. Under-selection in a test selection tool is the fault this
    whole answer is shaped to prevent, so the tag branch is gone rather than
    narrowed.

    `--name` is a regular expression behave searches the scenario's name
    with, and `_name_pattern` is how one is written.
    """
    if not result["scenarios"]:
        return ["nothing to run: no scenario in this map is reached by a "
                "change to these files"]
    by_file = _behave_names(result)
    combined = _combined(result)
    out = []
    for rel, names in by_file.items():
        if combined:
            out.append("--name " + shlex.quote(_name_pattern(*names)))
            continue
        out += ["--name " + shlex.quote(_name_pattern(name)) for name in names]
    return out


def _behave_names(result: dict) -> dict:
    """`{feature file: [scenario names]}` for the scenarios this change
    reaches, both keys and names sorted, each name once."""
    by_file: dict = {}
    for rel, name, _line, _why in result["scenarios"]:
        names = by_file.setdefault(rel, [])
        if name not in names:
            names.append(name)
    return {rel: sorted(by_file[rel]) for rel in sorted(by_file)}


def _combined(result: dict) -> bool:
    """Whether this selection is more `--name` arguments than one command
    line should carry, and so is alternated one per feature file."""
    return sum(len(names) for names in _behave_names(result).values()) > NAME_ARGS


def _name_pattern(*names: str) -> str:
    """Scenario names as the regular expression `behave --name` takes.

    Anchored at both ends, with two allowances for a scenario outline, whose
    rows behave runs under a name of its own: it substitutes each example's
    values into the name and appends ` -- @1.1` to it, so `Scenario Outline:
    Pay in <currency>` runs as `Pay in GBP -- @1.1`. A `<placeholder>` is
    therefore matched by anything and the suffix is allowed after the name.
    Measured with behave 1.3.3: without those two an outline is skipped by its
    own selector, which is the silent under-selection this whole answer is
    shaped to prevent.

    Several names alternate inside one group, which is what the combined form
    of a large selection prints.
    """
    inner = "|".join(_OUTLINE_SLOT.sub(".*", re.escape(name)) for name in names)
    return "^" + (inner if len(names) == 1 else f"({inner})") + "( -- @|$)"


# The head every graph answer's rules go under. The first line of an answer
# carries the counts and the one clause that decides what they mean; every
# other rule is a row of this block, where the budget can cut it without
# taking the count or the caveat with it. `unreached` prints the same head
# for the same reason.
HOW_COUNTED = "## How this was counted"


# --------------------------------------------------------------------- path
#
# One chain from A to B over the same `calls` rows `affected` walks, in the
# other direction: caller to callee, forward, which is how a reader asks "how
# does this reach that". `affected` walks upward because it starts at a change
# and wants the tests above it; `path` walks downward because it starts at a
# caller and wants the callee under it. Same rows, same resolutions, same
# ambiguous-edge rule, so a hop printed here is a hop the map already holds.


def _edge_files(row: dict) -> list:
    """The files one `calls` row's callee may be declared in.

    The settled file where the edge named one, and every candidate where it
    named several. An ambiguous edge is walked into each candidate rather
    than dropped or guessed at: the map says it could not choose, and a walk
    that chose for it would print a chain the graph does not hold.
    """
    settled = row.get("file")
    if settled:
        return [settled]
    return sorted(str(c) for c in (row.get("candidates") or ()))


def _file_named(path: str, root: str, hint: str) -> bool:
    """Whether `hint` names `path`: the repo-relative path, a suffix of it,
    or its basename. The rule `at()` resolves a stack trace's file with, so
    `cli.py:main` and `src/where_are_we/cli.py:main` are one question."""
    rel = _rank_graph.relative(path, root)
    want = hint.replace(os.sep, "/").lstrip("./")
    return bool(want) and (rel == want or rel.endswith("/" + want)
                           or os.path.basename(rel) == want)


def _graph_nodes(m: dict) -> dict:
    """`{name: {files}}`: every node this walk can stand on.

    `spans` first, which is where a declaration and its file live. Then the
    `xrefs` table itself, both ends of every row, because the walk is over
    that table and a graph can hold a node the declaration index does not: a
    repository mapped with no product root writes its `calls` rows and no
    `spans` at all, and a path through those rows is still a path. An
    endpoint this can name is exactly an endpoint the walk can start or
    finish on.
    """
    out: dict = {}
    for name, sites in (m.get("spans") or {}).items():
        for site in sites or ():
            if site.get("file"):
                out.setdefault(name, set()).add(site["file"])
    for row in m.get("xrefs") or []:
        edge = row.get("edge")
        if edge == "declares":
            out.setdefault(str(row.get("object") or ""),
                           set()).add(_subject_file(row))
        elif edge == "calls":
            caller = str(row.get("subject") or "")
            out.setdefault(caller.rpartition(":")[2],
                           set()).add(caller.rpartition(":")[0])
            for file in _edge_files(row):
                out.setdefault(str(row.get("object") or ""), set()).add(file)
    out.pop("", None)
    return out


def _endpoint(m: dict, root: str, spec: str) -> tuple:
    """`(nodes, name, problem)`: the `(file, name)` pairs one endpoint names.

    `spec` is a name, or `FILE:NAME` where the file narrows a name several
    files declare. A node of this walk is one name in one file, which is what
    a `calls` row's settled file and object name are together.

    A dotted name falls back to its last segment: `spans` holds a method
    under both `CheckoutPage.click_1` and `click_1`, and a `calls` row's
    object is always the bare form, so the bare form is the node's name and a
    reader who typed the qualified one is answered about the same node.
    """
    text = (spec or "").strip()
    hint, sep, name = text.rpartition(":")
    if not sep:
        hint, name = "", text
    if not name:
        return [], text, f"{spec!r} is not a name; give me NAME or FILE:NAME"
    known = _graph_nodes(m)
    files = known.get(name) or set()
    if not files and "." in name:
        bare = name.rpartition(".")[2]
        if known.get(bare):
            name, files = bare, known[bare]
    nodes = sorted((file, name) for file in files)
    if not nodes:
        return [], name, f"no declaration of {name!r} in this map"
    if hint:
        narrowed = [n for n in nodes if _file_named(n[0], root, hint)]
        if not narrowed:
            return [], name, (f"{name!r} is declared in this map, but not in "
                              f"a file called {hint!r}")
        nodes = narrowed
    return nodes, name, ""


def path(m: dict, a: str, b: str, depth: int = DEFAULT_DEPTH) -> dict:
    """The shortest call chain from `a` to `b`, over the `calls` rows.

    Breadth first from every declaration `a` names, following each node's own
    `calls` rows forward. The rows out of one node are sorted by callee,
    call-site line and resolution, and each hop's frontier is sorted, so the
    hop a node is first reached at and the edge that reached it are the same
    on every run and the chain printed is the same chain.

    A visited set carries across hops, so a cycle is walked once and the walk
    terminates on a graph that holds one; a node reached at hop 3 is not
    reached again at hop 5, which is what makes the first chain found the
    shortest one.

    An ambiguous edge is followed into every candidate. The map says several
    files declare that name and nothing said which, and a walk that picked
    one would print a chain the graph does not hold; the hop's own line names
    the candidates and says which of them this chain took.

    Returns the blocks the answer prints: `hops`, each
    `(caller file, caller name, row, callee file, callee name)`; `nearest`,
    the deepest frontier the walk reached when there is no chain, as
    `(file, name, hop)`; and the counts and complaints the first line states.
    """
    depth = max(1, min(int(depth), MAX_DEPTH))
    root = m.get("repo") or ""
    starts, a_name, a_bad = _endpoint(m, root, a)
    targets, b_name, b_bad = _endpoint(m, root, b)
    out = {"a": a, "b": b, "a_name": a_name, "b_name": b_name, "depth": depth,
           "root": root, "hops": [], "nearest": [], "reached": 0,
           "problem": a_bad or b_bad, "same": False}
    if out["problem"]:
        return out
    goal = set(targets)
    if goal & set(starts):
        out["same"] = True
        return out

    # The same walk `affected`, `reaches` and `unreached` run, pointed the
    # other way. `_climb` sorts each node's rows and stops on the goal, which
    # is what this used its own breadth-first loop for; keeping two loops over
    # one table is how the two come to disagree about a chain.
    seen = _climb(m, starts, depth, up=False, goal=set(targets))

    # The start counted itself, so the reach is what the walk added to it.
    out["reached"] = len(seen) - len(starts)
    # A goal node the walk actually arrived at, rather than one that was a
    # start: `_climb` seeds the starts at hop 0 with no parent, and a start
    # that is also a goal was handled above.
    landed = sorted(n for n in seen if n in goal and seen[n][2] is not None)
    hit = landed[0] if landed else None
    if hit is None:
        # Where the walk stopped: the last frontier it reached, which is the
        # honest answer to "how close did you get". Not the nodes nearest `b`
        # by any other measure: a node the forward walk reached that a walk
        # back from `b` also reached would be a path, so there is no such
        # node to name.
        deepest = max((hop for hop, _row, _parent in seen.values()), default=0)
        frontier = [n for n, (hop, _r, _p) in seen.items() if hop == deepest]
        out["nearest"] = sorted((_rank_graph.relative(f, root), n,
                                 seen[(f, n)][0]) for f, n in frontier)
        return out

    chain = []
    node = hit
    while seen[node][2] is not None:
        _hop, row, parent = seen[node]
        chain.append((parent[0], parent[1], row, node[0], node[1]))
        node = parent
    out["hops"] = list(reversed(chain))
    return out


# The blocks a `path` answer prints, as `(name, floor percentage)`. Only one
# of the two ever holds a row: a walk that arrived prints its chain and a
# walk that did not prints where it stopped, so the percentages decide
# nothing and are there because every block in this project has one.
PATH_BLOCKS = (("path", 55), ("nearest", 25), ("counted", 20))
PATH_NAMES = tuple(name for name, _pct in PATH_BLOCKS)


def path_head(result: dict, block: str) -> str:
    """The head of one `path` block."""
    if block == "path":
        return "## The chain, one hop per line, with how each edge was resolved"
    if block == "counted":
        return HOW_COUNTED
    hop = result["nearest"][0][2] if result["nearest"] else 0
    if not hop:
        # Hop 0 is the start itself, which the walk did not reach: it began
        # there. The block still prints, because naming the node the question
        # was asked about is the answer to "where did it get to".
        return "## Where the walk stopped: the start, which calls nothing here"
    return f"## Where the walk stopped: the names it reached at hop {hop}"


def path_summary(result: dict, limit: int) -> str:
    """The first line of a `path` answer: the counts, and the one clause that
    decides what a missing chain means.

    Short, because a first line is read on every turn after and the rules
    behind it are not: they are rows of `## How this was counted`, where they
    can be cut without taking the count with them. The clause that stays is
    cross-file, because it is the reason a chain a reader can see in the
    source is missing here, and a reader who does not know it will conclude
    the code does not call what it calls.
    """
    rule = "Only cross-file calls are in this graph."
    room = f"{limit} characters."
    if result["problem"]:
        return f"{result['problem']}. {room}"
    if result["same"]:
        return (f"{result['a']} and {result['b']} are the same declaration, "
                f"so the chain is empty. {room}")
    if result["hops"]:
        return (f"`{result['a']}` reaches `{result['b']}` in "
                f"{_plural(len(result['hops']), 'hop')}, the shortest chain "
                f"the graph holds. Depth {result['depth']}, {room}")
    if not result["reached"]:
        # It never left the start. Saying "0 names reached, the ones it
        # stopped at are below" over a block naming the start itself reads as
        # a walk that got somewhere, which it did not.
        return (f"No path from `{result['a']}` to `{result['b']}`: nothing "
                f"`{result['a_name']}` calls is in this graph, so the walk "
                f"had nowhere to go from it. {room}")
    return (f"No path from `{result['a']}` to `{result['b']}` within "
            f"{_plural(result['depth'], 'hop')}. "
            f"{_plural(result['reached'], 'name')} reached; where the walk "
            f"stopped is below. {rule} Depth {result['depth']}, {room}")


def path_lines(result: dict, block: str) -> list:
    """One `path` block's rows, whole, before anything is cut to a budget."""
    if block == "path":
        rows = []
        for i, (holder, name, row, target, callee) in enumerate(result["hops"],
                                                                1):
            rel = _rank_graph.relative(holder, result["root"])
            where = _rank_graph.relative(target, result["root"])
            line = (f"{i}. `{rel}:{name}` calls `{callee}` at line "
                    f"{row.get('line')}, {row.get('resolution')}, declared in "
                    f"`{where}`")
            if row.get("resolution") == "ambiguous":
                every = [_rank_graph.relative(c, result["root"])
                         for c in _edge_files(row)]
                line += (f"; {_plural(len(every), 'file')} declare "
                         f"`{callee}` and nothing said which: "
                         + ", ".join(f"`{c}`" for c in every))
            rows.append(line)
        return rows
    if block == "nearest":
        return [f"- `{rel}:{name}`, "
                + ("the start itself" if not hop
                   else f"{_plural(hop, 'hop')} out")
                for rel, name, hop in result["nearest"]]
    if block == "counted":
        rows = ["- only cross-file calls are in this graph: a call inside the "
                "file that declares the callee is not written to `xrefs` at "
                "all, so a hop through one is a hop this cannot walk",
                f"- breadth first to {_plural(result['depth'], 'hop')}, the "
                "rows out of a node sorted by callee, call-site line and "
                "resolution and every frontier sorted, so the same question "
                "gives the same chain on every run",
                "- a visited set carries across hops, so a cycle is walked "
                "once and the first chain found is the shortest",
                "- an ambiguous edge is followed into every file that "
                "declares the callee rather than guessed at, and the hop says "
                "which of them the chain took"]
        amb = sum(1 for hop in result["hops"]
                  if hop[2].get("resolution") == "ambiguous")
        if amb:
            rows.append(f"- {_plural(amb, 'hop')} of the chain above "
                        f"{'goes' if amb == 1 else 'go'} through such an edge")
        if not result["hops"] and result["reached"]:
            rows.append("- the names below are the last frontier the walk "
                        "reached; a name both this walk and a walk back from "
                        "the other end reached would be a path, so there is "
                        "no nearer set to name")
        return rows
    return []


# -------------------------------------------------------------------- range


def _end_reason(m: dict, site: dict) -> str:
    """Why one declaration's end is `?`.

    `spans` records an end where a parser knew one and null where nothing
    did, which is either the language being read by the pattern table or the
    file having been read to a limit, so the last declaration in it ends at
    the cut. The two are told apart here by whether this is the last
    declaration the map holds for that file: below the last one, a cut cannot
    be the reason.
    """
    file = site.get("file")
    starts = [s.get("start") or 0 for sites in (m.get("spans") or {}).values()
              for s in sites or () if s.get("file") == file]
    base = ("this map records an end only where a parser knew one, and "
            "nothing here measured where the declaration stops")
    if starts and (site.get("start") or 0) >= max(starts):
        return (base + "; it is the last declaration in the file, so a read "
                "cut short would end it here too")
    return (base + "; it is not the last declaration in the file, so the "
            "read limit is not the reason")


def symbol_range(m: dict, name: str) -> dict:
    """Every home of one name with its range, and the shortest one's text.

    The move an agent makes before an `Edit`: it needs the file, the first
    line, the last line, and the line after the last so an insertion lands
    outside the definition rather than inside it. All three are in `spans`
    and the text is in `lines`, so this is a lookup rather than a read of the
    file at a guessed offset.

    The shortest site is the one whose text is printed, because a name
    declared in two places is usually a small real one and a large one that
    shadows it, and the small one fits an answer. Ties by file then start.
    Sites whose end nothing measured cannot be the shortest, because their
    length is unknown; they are still listed, with `?` and the reason.

    Returns `sites` (every home, in path order), `shortest`, `text` (its
    lines), `anchor` (start, end and the line after end, each with its own
    text) and the complaint when the map holds no such name.
    """
    root = m.get("repo") or ""
    spans = m.get("spans") or {}
    wanted = (name or "").strip()
    sites = spans.get(wanted) or []
    if not sites and "." in wanted:
        bare = wanted.rpartition(".")[2]
        if spans.get(bare):
            wanted, sites = bare, spans[bare]
    out = {"name": wanted, "asked": name, "root": root, "sites": [],
           "shortest": None, "text": [], "anchor": [], "unknown": 0,
           "redacted": 0, "problem": ""}
    if not wanted:
        out["problem"] = "give me a name"
        return out
    if not sites:
        out["problem"] = f"no declaration of {name!r} in this map"
        return out
    ordered = sorted(sites, key=lambda s: (str(s.get("file")),
                                           s.get("start") or 0,
                                           str(s.get("kind"))))
    # Each site with the reason its end is `?`, empty where an end is known,
    # so the row that prints the `?` prints why beside it rather than sending
    # the reader to a sentence somewhere else in the answer.
    out["sites"] = [(site, "" if site.get("end") is not None
                     else _end_reason(m, site)) for site in ordered]
    out["unknown"] = sum(1 for site in ordered if site.get("end") is None)
    measured = [s for s in ordered if s.get("end") is not None]
    if not measured:
        return out
    shortest = min(measured, key=lambda s: (s["end"] - s["start"],
                                            str(s.get("file")), s["start"]))
    out["shortest"] = shortest
    body = (m.get("lines") or {}).get(shortest["file"]) or []
    start, end = shortest["start"], shortest["end"]
    out["text"] = list(body[start - 1:end])
    # The three numbers an editor anchors on, each with the line it names, so
    # an `Edit` can match on text rather than trusting a number alone. The
    # line after the end is the one an insertion goes above; where the
    # definition ends the file there is no such line and the row says so.
    after = body[end] if end < len(body) else None
    out["anchor"] = [("start", start, body[start - 1] if start <= len(body)
                      else None),
                     ("end", end, body[end - 1] if end <= len(body) else None),
                     ("after", end + 1, after)]
    # Whether any line this answer prints was redacted on the way into the
    # map. `_mapper/walk.py` replaces a value that looks like a secret, so
    # such a line is not the line on disk and an `Edit` anchored on it either
    # fails to match or writes the marker into the source. The rows say so
    # and the first line says so; reading the file to recover the real text
    # is the other way out and this does not take it, because nothing in this
    # module opens a source file and a map is often read far from the tree it
    # was built from, where the file would be a different file or no file.
    out["redacted"] = sum(1 for line in out["text"] if REDACTED in line) + sum(
        1 for _label, _n, line in out["anchor"] if line and REDACTED in line)
    return out


RANGE_BLOCKS = (("sites", 20), ("text", 45), ("anchor", 20), ("counted", 15))
RANGE_NAMES = tuple(name for name, _pct in RANGE_BLOCKS)


def range_head(result: dict, block: str) -> str:
    """The head of one `range` block."""
    if block == "sites":
        return "## Every home of this name, as file:start-end kind"
    if block == "text":
        site = result["shortest"] or {}
        where = _rank_graph.relative(str(site.get("file")), result["root"])
        return (f"## The shortest of them whole: `{where}:"
                f"{site.get('start')}-{site.get('end')}`")
    if block == "counted":
        return HOW_COUNTED
    return ("## The lines an editor anchors on: first, last, and the one "
            "after the last")


def range_summary(result: dict, limit: int) -> str:
    """The first line of a `range` answer: how many homes, and the one clause
    an agent about to anchor an edit has to read before it does.

    Redaction is that clause. Everything else about how the sites were chosen
    and why an end can be unknown is a row of `## How this was counted`,
    where the budget can cut it; a line that is not the line on disk cannot
    be cut, because the whole answer is sold on anchoring an edit on it.
    """
    if result["problem"]:
        return f"{result['problem']}. {limit} characters."
    head = (f"`{result['name']}` is declared in "
            f"{_plural(len(result['sites']), 'place')}"
            + (f", {result['unknown']} of them ending at `?`"
               if result["unknown"] else "") + f". {limit} characters.")
    if result["redacted"]:
        head += (f" {_plural(result['redacted'], 'line')} below "
                 f"{'holds' if result['redacted'] == 1 else 'hold'} "
                 f"`{REDACTED}` and {'is' if result['redacted'] == 1 else 'are'}"
                 " not the line on disk: do not anchor an edit there.")
    if not result["shortest"]:
        head += " No site has a measured end, so there is no text to print."
    return head


def range_lines(result: dict, block: str) -> list:
    """One `range` block's rows, whole, before anything is cut to a budget.

    The `text` block's rows are source lines and carry no bullet: they are
    the file's own text, and a marker in front of them would have to be
    stripped by whoever pastes them back.
    """
    if block == "sites":
        rows = []
        for site, reason in result["sites"]:
            where = _rank_graph.relative(str(site.get("file")),
                                         result["root"])
            end = site.get("end")
            row = (f"- `{where}:{site.get('start')}-"
                   f"{end if end is not None else '?'}` "
                   f"{site.get('kind') or 'name'}")
            if reason:
                row += f" (end unknown: {reason})"
            rows.append(row)
        return rows
    if block == "text":
        return list(result["text"])
    if block == "counted":
        rows = ["- every home comes from the map's `spans` key, in path "
                "order, and nothing here opens a source file",
                "- the text printed is the shortest site with a measured "
                "end, ties by file then start: a name declared twice is "
                "usually a small real one and a large one shadowing it",
                "- an end of `?` is a declaration nothing measured, and the "
                "site's own row says whether a read cut short is ruled out",
                "- the three anchors are the first line of the definition, "
                "the last, and the one after the last, so an insertion after "
                "the last lands outside the definition rather than inside it"]
        if result["redacted"]:
            rows.append("- a line holding `" + REDACTED + "` had a value "
                        "that looked like a secret written over on the way "
                        "into the map, so it is not the line on disk. This "
                        "answer marks it rather than reading the file back: "
                        "nothing in this module opens a source file, and a "
                        "map is often read far from the tree it was built "
                        "from, where that path is a different file or none")
        return rows
    if block == "anchor":
        rows = []
        for label, number, text in result["anchor"]:
            if text is None:
                rows.append(f"- {label} {number}: the file ends at "
                            f"{number - 1}, so there is no line here")
            elif not text.strip():
                rows.append(f"- {label} {number}: a blank line")
            else:
                rows.append(f"- {label} {number}: `{text}`"
                            + (f"  (this map redacted a value on this line, "
                               f"so it is not the line on disk; do not anchor "
                               f"on it)" if REDACTED in text else ""))
        return rows
    return []


# --------------------------------------------------------------- dead, hot

# The declaration kinds a `calls` row can name. The graph this walks is a
# call graph, so a constant or a type is never reached by it and would sit in
# `unreached` for ever whatever the tests do; naming those would drown the
# definitions the answer is about.
#
# The cost is one language idiom. `const charge = (amount) => amount` is a
# function everywhere but in the map, which records it as kind `constant`,
# with nothing beside it saying the value is callable: the pattern table sees
# `export const NAME =` and stops there, and `spans` keeps no initialiser. So
# an untested arrow function is neither in this list nor in its denominator.
# `reaches` has no such limit and answers for a constant like any other name,
# which is where a reader who suspects one goes. Stated in the block that
# says how the count was made.
CALLABLE_KINDS = ("class", "function")

# `dead` asks the same of the same graph and wants the same answer: a
# constant or a module nothing calls is not dead code either, because
# `xrefs` records calls and imports rather than every read of every name,
# so every constant in the map would be listed and the list would say
# nothing. One tuple under one name, so the two answers cannot drift.



# The names left out whatever the graph says, because something other than a
# call reaches them. Printed in the answer's first line, so a reader knows
# what the list is not.
DEAD_EXCLUDED = (
    "a dunder the language itself calls (`__init__` and every other "
    "`__name__`)",
    "`main`",
    "a name starting with `test`, and every case `pytest_tests` records",
    "a step function, which behave calls off a phrase in a feature file",
    "a definition in a file a `routes_served` row is served from",
    "a definition in a file `entry_points` names as a launch script",
)

# How many files `dead` and how many definitions `hot` print when nobody
# says. The same order of magnitude as `--rank`'s own default cut down to
# what a reader scans: a hundred dead files is a project to work through
# rather than an answer to read.
DEAD_LIMIT = 40
HOT_LIMIT = 40

# How many commit lines `_mapper/build.py` keeps for one file in
# `git_history`. Only used to mark a count read off that key as a floor,
# which is what a map built before `git_commits` existed can offer.
_CAPPED_LINES = 5


def _called(m: dict) -> set:
    """`{(file, name)}` every `calls` row lands on.

    An ambiguous row lands on each of its candidates, so a name several files
    declare is called in all of them. That over-counts, and it over-counts in
    the direction that keeps a definition out of `dead`: calling something
    dead that is called is worse than leaving something dead off the list.
    """
    out = set()
    for row in m.get("xrefs") or []:
        if row.get("edge") != "calls":
            continue
        for file in _edge_files(row):
            out.add((file, str(row.get("object") or "")))
    return out


def _call_suffixes(m: dict) -> set:
    """The file extensions this map's `calls` rows actually reach.

    Read off the table rather than hard coded, because which languages the
    call graph covers is a property of the build: Python by `ast`, several
    more by pattern, and more again under the `[precise]` extra. A
    declaration in a file of any other kind can never have an incoming row,
    so calling it dead would report a bound of this graph as a fact about the
    code: a `def` quoted inside a Markdown fence is not dead code, it is
    documentation.

    Both ends of every row, so a language whose files only ever declare and
    never call is still covered.

    What it costs: real code in a language this particular build's call graph
    did not reach is dropped with the prose. On this repository's own map a
    `--no-semantic` build places no `.ts` or `.tsx` edge, so `App.tsx:App`
    and `api.ts:getUser` are not judged either way. That is the trade this
    rule makes, and the row of `## How this was counted` that names the
    suffixes counted says so, so a reader can see which languages were left
    out rather than read an absence as a clean bill.

    Empty when the graph holds no `calls` row at all, which is a repository
    this cannot answer the question for; `dead` says that rather than
    printing a clean nothing.
    """
    out = set()
    for row in m.get("xrefs") or []:
        if row.get("edge") != "calls":
            continue
        for file in [_subject_file(row)] + _edge_files(row):
            out.add(os.path.splitext(str(file))[1].lower())
    out.discard("")
    return out


def _excluded_files(m: dict, root: str) -> tuple:
    """`(files, ambiguous)`: the files whose definitions are left out.

    A file a route is served from, and a file `entry_points` names as a
    launch script. `routes_served` records the basename of the serving file
    and no path (`GET /invoice  (api.py)`), so where two files of one
    basename exist the map cannot say which of them serves the route and
    both are excluded. `ambiguous` counts the basenames that matched more
    than one file, and a row of `## How this was counted` says how many
    were taken out on a guess, because silently dropping a file's rows is the
    one way this list can be wrong rather than long.
    """
    bases = set()
    for route in m.get("routes_served") or ():
        hit = _ROUTE_FILE.search(str(route))
        if hit:
            bases.add(hit.group(1))
    scripts = {str(k) for k in (m.get("entry_points") or {})}
    by_base: dict = {}
    out = set()
    for name, sites in (m.get("spans") or {}).items():
        for site in sites or ():
            file = site.get("file")
            if not file:
                continue
            rel = _rank_graph.relative(file, root)
            base = os.path.basename(rel)
            if base in bases:
                by_base.setdefault(base, set()).add(file)
            if base in bases or rel in scripts:
                out.add(file)
    return out, sum(1 for files in by_base.values() if len(files) > 1)


def _readable(name: str) -> tuple:
    """How to choose between the spellings one declaration is held under.

    A site is in `spans` more than once: a class is there as `LoginPage` and
    as `class LoginPage`, and a method as `LoginPage.sign_in` and `sign_in`.
    The name a reader greps for is the one that reads as an identifier, so a
    spelling with a space in it loses to one without, and among those the
    qualified one wins, because `LoginPage.sign_in` says which class and
    `sign_in` does not.
    """
    return (" " in name, -len(name), name)


def _entry_name(name: str) -> bool:
    """Whether a name is an entry point rather than something called.

    The last segment, so `Case.test_pay` and `test_pay` are both test entry
    points and `Thing.__init__` is a dunder.
    """
    bare = name.rpartition(".")[2]
    return (bare == "main" or bare.startswith("test")
            or (bare.startswith("__") and bare.endswith("__")))


def dead(m: dict, limit: int = DEAD_LIMIT) -> dict:
    """The definitions no `calls` row lands on, grouped by file.

    A site rather than a name: `spans` holds a method under both
    `CheckoutPage.click_1` and `click_1`, one declaration on one line, and a
    list that named both would report twice the dead code a file has. The
    qualified spelling is the one printed, because it is the one a reader
    greps for; a site is called when any of its spellings is called.

    `DEAD_EXCLUDED` says what is left out and the answer's first line prints
    it, because a list of things nothing calls is only readable when the
    reader knows which callers it does not count.

    The caveat that matters most is not an exclusion: `xrefs` holds cross
    file calls and nothing else, so a function called only from the file that
    declares it has no incoming row and is here. The first line says so.
    """
    root = m.get("repo") or ""
    limit = max(1, int(limit))
    called = _called(m)
    step_at, _func_at = _declaration_sites(m)
    skip_files, guessed = _excluded_files(m, root)
    cases = {name for names in (m.get("pytest_tests") or {}).values()
             for name in names or ()}

    # By site, with every name that site is declared under, so one `def` is
    # one row and a call on any of its spellings keeps it off the list.
    reachable = _call_suffixes(m)
    at_site: dict = {}
    for name, sites in (m.get("spans") or {}).items():
        for site in sites or ():
            if site.get("kind") not in CALLABLE_KINDS or not site.get("file"):
                continue
            if os.path.splitext(str(site["file"]))[1].lower() not in reachable:
                continue
            at_site.setdefault((site["file"], site.get("start") or 0),
                               []).append(name)

    rows = []
    for (file, start), names in at_site.items():
        if file in skip_files or step_at.get((file, start)) is not None:
            continue
        if any(_entry_name(n) or n in cases for n in names):
            continue
        if any((file, n) in called or (file, n.rpartition(".")[2]) in called
               for n in names):
            continue
        rows.append((_rank_graph.relative(file, root),
                     min(names, key=_readable), start))

    by_file: dict = {}
    for rel, name, start in sorted(rows, key=lambda r: (r[0], r[2], r[1])):
        by_file.setdefault(rel, []).append((name, start))
    files = sorted(by_file.items())
    return {"files": files[:limit], "held": len(files), "total": len(rows),
            "considered": len(at_site), "limit": limit, "guessed": guessed,
            "graph": bool(reachable), "declared": sum(
                1 for sites in (m.get("spans") or {}).values()
                for site in sites or () if site.get("kind") in CALLABLE_KINDS),
            "suffixes": ", ".join(sorted(reachable)) or "none"}


DEAD_BLOCKS = (("dead", 70), ("counted", 30))
DEAD_NAMES = tuple(name for name, _pct in DEAD_BLOCKS)


def dead_head(_result: dict, block: str) -> str:
    """The head of one `dead` block."""
    if block == "counted":
        return HOW_COUNTED
    return "## Definitions with no incoming call row, by file, in path order"


def dead_summary(result: dict, limit: int) -> str:
    """The first line of a `dead` answer: the counts, and the one sentence
    that decides what they mean.

    Short. It used to carry both caveats, the file-kind rule, the whole
    exclusion list and the route guess, which came to about a thousand
    characters: a first line that long is re-read on every turn of a
    conversation, and it put the whole answer out of reach below its own
    length. Everything but the sentence a reader has to have is a row of
    `## How this was counted`, which the budget may cut.

    The sentence that stays is the one the flag's name argues against. Most
    of this list, on a library, is a call the map could not place rather than
    a definition nothing calls, and a reader who takes the rows for dead code
    and deletes them will break the build.

    A map whose graph holds no `calls` row cannot answer the question at all,
    and says so instead of printing a clean nothing, which is the reading a
    small repository would otherwise get.
    """
    if not result["graph"]:
        return (f"No call graph in this map: not one `xrefs` calls row, so "
                f"nothing here can be called dead. The map holds "
                f"{result['declared']} function"
                f"{'' if result['declared'] == 1 else 's'} and classes. "
                f"{limit} characters.")
    return (f"{result['total']} of {result['considered']} definitions in "
            f"{_plural(result['held'], 'file')} have no incoming calls row. "
            f"Most of a list like this is calls the map could not place, not "
            f"dead code. Top {result['limit']} files, {limit} characters.")


def dead_lines(result: dict, block: str) -> list:
    """The one `dead` block's rows: one file per row, its dead definitions
    with the line each starts on.

    One row per file rather than per definition, so a block cut to a budget
    loses whole files and never a file's header with its names below it. It
    is also the shape the map's own "Page-object methods nothing calls"
    section prints, which is the same question asked of a different table.
    """
    if block == "counted":
        if not result["graph"]:
            # No calls row at all, so there is no list above and no rule that
            # made one. What is worth saying is what the map does hold and
            # what would have to change for the question to have an answer.
            return ["- a definition is called dead here when no `xrefs` "
                    "calls row lands on it, and this map holds no such row, "
                    "so the question has no answer rather than the answer no",
                    f"- the map does hold {result['declared']} function"
                    f"{'' if result['declared'] == 1 else 's'} and classes, "
                    "in every language it indexed",
                    "- `calls` rows are written for the languages this build "
                    "resolves calls in; a tree of any other, or a map from "
                    "before 1.5.0, has none"]
        rows = ["- only cross-file calls are in this graph, so a definition "
                "called from the file that declares it has no incoming row "
                "and is above",
                "- so is one whose callers this map's resolver could not "
                "place, which is what a call through an imported module "
                "looks like: on a library that is most of the list, and on a "
                "test suite, where a page object is called from step modules, "
                "it is few",
                f"- counted over the {result['considered']} functions and "
                "classes this map holds in the file kinds its call graph "
                f"reaches ({result['suffixes']}); a declaration in any other "
                "language is not judged either way, because no row could ever "
                "land on it",
                # Measured rather than guessed at: the resolver looks a callee
                # name up in the table of function declarations, and a class
                # name is in a table of its own beside it, so `Widget()`
                # writes no row from inside a function either. That is why
                # `dead` on this project's own `suite` fixture returns
                # `CheckoutPage`, which a step module constructs at module
                # level: it is the construction that is missing from the
                # graph, not the module level.
                "- a class is reached here only through something declared "
                "inside it: the resolver places a callee by the function "
                "declarations it indexed and holds class names in a table of "
                "its own, so constructing a class writes no calls row and a "
                "class only ever constructed is above"]
        rows += [f"- left out: {rule}" for rule in DEAD_EXCLUDED]
        if result["guessed"]:
            rows.append(
                f"- {_plural(result['guessed'], 'route file basename')} "
                f"{'names' if result['guessed'] == 1 else 'name'} more than "
                "one file in this map and `routes_served` records no path, so "
                "every one of them was left out on a guess")
        rows.append(f"- grouped by file in path order, showing "
                    f"{len(result['files'])} of {result['held']}")
        return rows
    if block != "dead":
        return []
    return [f"- `{rel}`: "
            + ", ".join(f"{name} ({start})" for name, start in names)
            for rel, names in result["files"]]


def hot(m: dict, limit: int = HOT_LIMIT) -> dict:
    """The ranked definitions weighted by how often their file changes.

    `rank` says what the repository is built around and `git_history` says
    what it keeps editing; either alone is half an answer. A file nothing
    reaches that changes every day is churn, and a file everything reaches
    that has not moved in a year is settled. What a reviewer wants is the
    product, and both numbers are printed so a reader can see which of the
    two put a row where it is.

    A file with no row in the most-changed-files section counts 1 rather than
    0: that section is the last ninety days, so a file missing from it has
    not changed lately, not never, and a zero would erase every definition in
    it from the ranking. That section is itself the forty busiest files, so a
    file outside it may have changed a great deal and still count 1; the
    first line says so, because a cap a reader cannot see is a number that
    lies.

    The count comes from `git_commits`, which is the real number of commits
    in the window. `git_history` is not it: that key keeps at most five
    commit lines a file, so counting its lines made every file in the section
    weigh exactly five and the multiplier two-valued, which reordered
    nothing. A map built before `git_commits` existed has only those lines,
    and then every count at the cap is written `5+` and two rows of
    `## How this was counted` say where the number came from and why it is a
    floor. Not the first line: that carries the counts and the one bound
    that decides what the ranking is, which is the forty-file one.

    `rank` is the map's top 200, so this ranks within those.
    """
    root = m.get("repo") or ""
    limit = max(1, int(limit))
    history = m.get("git_history") or {}
    counts = m.get("git_commits") or {}
    capped = bool(history) and not counts
    churn = ({rel: int(n or 0) for rel, n in counts.items()} if counts
             else {rel: len(entries or ()) for rel, entries in history.items()})
    rows = []
    for entry in m.get("rank") or ():
        rel = _rank_graph.relative(str(entry.get("file") or ""), root)
        commits = churn.get(rel) or 1
        score = float(entry.get("score") or 0.0)
        rows.append((score * commits, rel, entry.get("line") or 0,
                     str(entry.get("name") or ""), score, commits))
    rows.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))
    return {"rows": rows[:limit], "held": len(rows), "limit": limit,
            "churned": len(churn), "capped": capped,
            "section": len(history) or len(churn)}


HOT_BLOCKS = (("hot", 70), ("counted", 30))
HOT_NAMES = tuple(name for name, _pct in HOT_BLOCKS)


def hot_head(_result: dict, block: str) -> str:
    """The head of one `hot` block."""
    if block == "counted":
        return HOW_COUNTED
    return "## Rank score times commits, highest first"


def hot_summary(result: dict, limit: int) -> str:
    """The first line of a `hot` answer: the counts, and the bound that
    decides what the ranking is.

    One bound, not both. The most-changed section is the forty busiest files,
    so everything outside it weighs the same and the tail of this answer is
    `rank`'s own order: a reader who does not know that will read a ranking
    into rows that carry none. The rest, including the older-map cap, is a
    row of `## How this was counted`.
    """
    return (f"The top {len(result['rows'])} of {result['held']} ranked "
            f"definitions by rank score times commits, both numbers shown. "
            f"Churn covers the {_plural(result['churned'], 'busiest file')} "
            f"only, so anything outside them counts 1. {limit} characters.")


def hot_lines(result: dict, block: str) -> list:
    """One `hot` block's rows, with both numbers behind each product."""
    # A count the map capped is written `5+`, not `5`: that row is then a
    # floor rather than a measurement, and a reader multiplying it out can
    # see which it is without going back to the first line. Only the rows at
    # the cap are marked; a file with two commit lines really has two.
    def count(n: int) -> str:
        if result["capped"] and n >= _CAPPED_LINES:
            return f"{n}+ commits"
        return f"{n} commit{'' if n == 1 else 's'}"

    if block == "counted":
        rows = ["- the score is the map's own `rank`, which holds the top "
                f"{result['held']} definitions of this repository, so this "
                "ranks within those"]
        if result["capped"]:
            # Say where the number came from and what is wrong with it in
            # one breath. Naming `git_commits` as the source and then, five
            # rows later, saying the map has no such key is two rows that
            # cannot both be true.
            rows += ["- the commits are the commit lines `git_history` keeps, "
                     "because this map has no `git_commits` key",
                     f"- that key caps those lines at {_CAPPED_LINES} a file, "
                     f"so every count written `{_CAPPED_LINES}+` is a floor "
                     "and not a measurement; `--force` rebuilds the map with "
                     "the real numbers"]
        else:
            rows.append("- the commits are `git_commits`, what the "
                        "most-changed-files section counted over the last "
                        "ninety days")
        rows += [f"- that section is the "
                 f"{_plural(result['churned'], 'busiest file')} and no more, "
                 "so a file outside it counts 1 however often it changed and "
                 "this ranking is `rank`'s own order for those",
                 "- a merge commit names no file in the log that section is "
                 "built from and is not counted",
                 "- ties by path, then line, then name, so two builds of one "
                 "tree print the same order"]
        return rows
    if block != "hot":
        return []
    return [f"- `{rel}:{line}` {name}, rank {score:.9f} x {count(commits)} "
            f"= {product:.9f}"
            for product, rel, line, name, score, commits in result["rows"]]


# Definitions no answer about coverage counts, whatever the graph says. A
# module's entry point is called by the runtime rather than by anything the
# map can see, and `__init__` is called by every construction of its class
# without a `calls` row naming it. One tuple, here, because `dead` asks the
# same question of the same graph and two answers disagreeing about the same
# definition is worse than either rule.
ENTRY_POINTS = ("main", "__main__", "__init__")

# What a path looks like when the file on it is test scaffolding rather than
# product: the runner's own helpers, a conftest, a fixture builder. The map
# names the files each runner holds cases in, and those are handled as suite;
# this catches the modules beside them that declare no case and would
# otherwise be counted as product nothing tests, which is true and useless.
# `features/` and `e2e/` are not here on purpose: a product with a
# `features/` package is commoner than a suite this rule would catch that the
# map's own `features` key does not, and the cost of a false positive is a
# whole directory of product silently leaving the answer.
_TEST_DIRS = ("tests/", "test/", "spec/", "specs/")
_TEST_NAMES = ("conftest.py",)


def _is_test_path(rel: str) -> bool:
    """Whether one repository-relative path is test scaffolding."""
    here = rel.replace(os.sep, "/")
    base = here.rpartition("/")[2]
    if base in _TEST_NAMES or base.startswith("test_"):
        return True
    stem = base.rpartition(".")[0] or base
    if stem.endswith(("_test", "_spec", ".test", ".spec", "Test", "Spec")):
        return True
    return any(here.startswith(d) or f"/{d}" in here for d in _TEST_DIRS)


# Where the map already says the suite is, key by key. Nothing here guesses
# from a directory name: `page_objects` and `drivers` are lists of paths,
# `features`, `steps`, `pytest_tests`, `js_tests`, `fixtures`, `perf_suites`
# and `helpers` are keyed by path, and `other_suites`/`more_suites` hold one
# such mapping per runner. Everything the walk indexed and none of these
# names is the product side: the code the tests are about, whether it sits
# under a product root of its own (`indexed` counts that side separately) or
# beside the suite in one repository.
#
# The precision of that split is the precision of the heuristics that filled
# those keys. A product module the mapper miscalls a page object is not
# product here, is not in the count, and is not in the list. So the files set
# aside are printed, in a block of their own, rather than only counted.
_SUITE_LISTS = ("page_objects", "drivers", "behave_environment_files",
                "api_tests")
_SUITE_KEYED = ("features", "steps", "pytest_tests", "js_tests", "fixtures",
                "perf_suites", "helpers")
_SUITE_RUNNERS = ("other_suites", "more_suites")

# The subset of those that hold tests rather than what a test drives. A page
# object method nothing calls is a question for `dead`; a test case nothing
# calls is the entry point every other answer here is walked from.
_TEST_LISTS = ("api_tests",)
_TEST_KEYED = ("js_tests", "perf_suites")
_TEST_RUNNERS = _SUITE_RUNNERS


def _paths(m: dict, lists: tuple, keyed: tuple, runners: tuple) -> set:
    """The repository-relative paths those keys name, whatever their shape."""
    out = set()
    for key in lists:
        out.update(str(rel) for rel in (m.get(key) or ()) if rel)
    for key in keyed:
        out.update(str(rel) for rel in (m.get(key) or {}) if rel)
    for key in runners:
        for group in (m.get(key) or {}).values():
            out.update(str(rel) for rel in (group or {}) if rel)
    return out


def suite_files(m: dict) -> set:
    """Every file the map names as part of the test suite, repo-relative.

    A path this returns is written the way the map's own keys write it, so
    the caller compares `_rank_graph.relative(...)` against it. A file the
    walk read under a product root keeps its absolute path there and is
    therefore never in this set, which is what makes the split work whether
    the product is a second root or a directory beside the suite.
    """
    return _paths(m, _SUITE_LISTS, _SUITE_KEYED, _SUITE_RUNNERS)


def resolution(m: dict) -> tuple:
    """`(resolved, sites)` over every language group in `call_graph_stats`.

    `sites` is every callee name the walk looked at and `resolved` how many
    of them some indexed file declares. Their ratio is how much of the call
    graph this map could place at all, which is the number that says whether
    "nothing reaches this" is a fact about the tests or about the walk.
    """
    stats = m.get("call_graph_stats") or {}
    sites = sum(int((row or {}).get("sites") or 0) for row in stats.values())
    resolved = sum(int((row or {}).get("resolved") or 0)
                   for row in stats.values())
    return resolved, sites


def _rate(m: dict) -> str:
    """The one sentence every `unreached` answer carries about its own reach."""
    resolved, sites = resolution(m)
    if not sites:
        return "This map records no call graph statistics."
    return (f"The graph resolved {resolved} of {sites} callee names "
            f"({round(100 * resolved / sites)} percent).")


def crosses_roots(m: dict) -> bool:
    """Whether any `calls` row names a file outside the repository root.

    The call graph is extracted from the files under `--repo` and from
    nothing else (`_mapper/build.py` builds `code_files` from a walk of that
    one tree and the per-language extractors loop over it); a product root
    named by `PRODUCT_SRC` is walked for declarations and lines only. So on a
    suite checked out beside its product, no edge crosses into the product
    and every name in it is reached by nothing. That is a property of the
    map rather than of the tests, and an answer about coverage that does not
    say so is wrong in the one direction that matters.
    """
    root = (m.get("repo") or "").replace(os.sep, "/").rstrip("/")
    if not root:
        return True
    for row in m.get("xrefs") or ():
        if row.get("edge") != "calls":
            continue
        for path in [row.get("file")] + list(row.get("candidates") or ()):
            if path and not str(path).replace(os.sep, "/").startswith(root + "/"):
                return True
    return False


def _definitions(m: dict, kinds=CALLABLE_KINDS) -> dict:
    """`{(file, start): (name, kind, end)}`: one identifier per declaration.

    `spans` can hold two names for one declaration: a Python class is
    recorded as `CheckoutPage` and `class CheckoutPage`, a method as `pay`
    and `CheckoutPage.pay`, a step function as `step_pay` and `def step_pay`.
    Counting both would double every count this module prints. The name kept
    is the one that reads as an identifier, which is the one without a space
    in it and then the shorter, the same rule the step functions are counted
    by.
    """
    best: dict = {}
    for name, sites in (m.get("spans") or {}).items():
        for site in sites or ():
            kind = site.get("kind")
            if kind not in kinds:
                continue
            where = (site.get("file"), site.get("start"))
            order = (1 if " " in name else 0, len(name), name)
            if where not in best or order < best[where][0]:
                best[where] = (order, name, kind, site.get("end"))
    return {where: (row[1], row[2], row[3]) for where, row in best.items()}


def _by_file(defs: dict) -> dict:
    """Those declarations as `{file: [(start, name, kind, end)]}`, sorted.

    A class is reached when anything declared inside it is, and a class is
    asked about by asking about its methods, so both answers need the
    declarations of one file in line order.
    """
    out: dict = {}
    for (holder, start), (name, kind, end) in defs.items():
        out.setdefault(holder, []).append((start, name, kind, end))
    for rows in out.values():
        rows.sort()
    return out


def _members(m: dict, defs: dict, by_file: dict, holder: str, name: str,
             start, end) -> tuple:
    """`(members, extent)`: the names one class owns, and whether it is whole.

    Two joins, because `spans` records no owner and either of them can be
    missing. The first is the dotted spelling: an `ast` walk writes
    `CheckoutPage.pay` beside `pay` for the same line, so every name in
    `spans` beginning `<class>.` and declared in this file is a member, and
    that holds whether or not the parser found where the class stops. The
    second is containment: a declaration whose line is inside the class's
    range is a member, which is what the languages read by the pattern table
    have instead of a dotted name.

    `extent` is False where the parser knew no `end` and no dotted name was
    found either. Then the class owns nothing here, the answer covers its own
    name and nothing under it, and `reaches_summary` says so: a page object
    every step drives answers "nothing" in that state, and a count that is a
    floor has to say it is one.
    """
    members, dotted = set(), f"{name}."
    for spelled, sites in (m.get("spans") or {}).items():
        if not spelled.startswith(dotted):
            continue
        for site in sites or ():
            if site.get("file") != holder:
                continue
            found = defs.get((holder, site.get("start")))
            members.add(found[0] if found else spelled)
    if end:
        for line, member, _kind, _end in by_file.get(holder, ()):
            if start < line <= end:
                members.add(member)
    return sorted(members), bool(end or members)


def _chain(seen: dict, root: str, node) -> str:
    """One hop chain, from a caller down to the name that was asked about.

    `_climb` records the node each node was found from, so the chain is read
    back off the walk rather than kept during it. The guard is the size of
    the walk: a parent chain cannot be longer than the nodes it visited, and
    a map hand-edited into a loop should not hang a reader's answer.
    """
    out = []
    while node is not None and len(out) <= len(seen):
        holder, name = node
        out.append(f"`{_rank_graph.relative(holder, root)}:{name}`")
        node = seen[node][2]
    return " -> ".join(out)


def _pytest_at(m: dict, root: str) -> dict:
    """`{(file, name): rel}` for every pytest case the map names.

    `pytest_tests` is `{file: [case names]}` and those names are the
    functions themselves, so a case is a node of the call graph like any
    other and needs no join to reach it.
    """
    out = {}
    for rel, names in (m.get("pytest_tests") or {}).items():
        for name in names or ():
            out[(os.path.join(root, rel) if root else rel, name)] = rel
    return out


def entry_points(m: dict, defs: dict = None) -> tuple:
    """`(nodes, counts)`: every place this map says a test starts.

    Three kinds, because a repository has more than one runner and a
    coverage-shaped answer that knows about one of them under-reports the
    rest. A behave step function is the join of two `spans` sites on one
    line. A pytest case is a name `pytest_tests` records, which is the
    function itself. For every other runner the map records case titles
    rather than function names (`js_tests` holds `describe`/`it` strings and
    `api_tests` holds paths), so there every function and class declared in
    the file counts, which reaches more than the cases do and is said out
    loud in the block that says how the count was made.
    """
    root = m.get("repo") or ""
    defs = _definitions(m) if defs is None else defs
    step_at, _func_at = _declaration_sites(m)
    steps = sorted((holder, name)
                   for (holder, start), (name, kind, _end) in defs.items()
                   if kind == "function" and (holder, start) in step_at)
    cases = sorted(_pytest_at(m, root))
    others = _paths(m, _TEST_LISTS, _TEST_KEYED, _TEST_RUNNERS)
    runner = sorted((holder, name) for (holder, _start), (name, _k, _e)
                    in defs.items()
                    if _rank_graph.relative(holder, root) in others)
    nodes = sorted(set(steps) | set(cases) | set(runner))
    return nodes, {"steps": len(steps), "pytest": len(cases),
                   "runners": len(runner)}


REACHES_BLOCKS = (
    ("sites", "## Declared in", 15),
    ("scenarios", "## Scenarios that reach it, by feature file (the chain "
                  "under the first scenario of each is a line of its own)",
     45),
    ("pytest", "## pytest cases that reach it", 20),
    ("routes", "## Routes (named by the file each one is served from)", 20),
)
REACHES_NAMES = tuple(name for name, _head, _pct in REACHES_BLOCKS)
REACHES_HEADS = {name: head for name, head, _pct in REACHES_BLOCKS}


def reaches(m: dict, name: str) -> dict:
    """Which scenarios, pytest cases and routes reach one function or class.

    The other direction of the same question `affected` asks, over the same
    walk: `affected` starts at what a change declares, this starts at one
    name, and both climb the `calls` rows callee to caller until they arrive
    at something that starts a test. No depth cap, because the question is
    whether anything reaches this at all and a cap would answer "nothing"
    for a function seven hops under a step.

    A class is asked about by name and answered by its members, found by the
    dotted spelling `spans` writes beside a method and by containment in the
    class's range. Without that join `reaches CheckoutPage` answers nothing
    at all for a page object every step drives, because the constructor call
    sits at module level and no `calls` row is written for it.
    """
    root = m.get("repo") or ""
    defs = _definitions(m)
    by_file = _by_file(defs)

    sites, seeds, seen_at, partial = [], set(), set(), []
    for site in ((m.get("spans") or {}).get(name) or ()):
        holder, start = site.get("file"), site.get("start")
        if (holder, start) in seen_at:
            continue
        seen_at.add((holder, start))
        rel = _rank_graph.relative(holder, root)
        kind = site.get("kind") or "name"
        # Both spellings: the identifier this site is counted under, and the
        # name the reader typed, because a `calls` row names whichever one
        # the caller wrote.
        seeds.add((holder, name))
        chosen = defs.get((holder, start))
        if chosen:
            seeds.add((holder, chosen[0]))
        members: list = []
        if kind == "class":
            members, extent = _members(m, defs, by_file, holder, name, start,
                                       site.get("end"))
            for member in members:
                seeds.add((holder, member))
            if not extent:
                partial.append(rel)
        sites.append((rel, start, site.get("end"), kind, members))
    sites.sort()

    walked = _climb(m, sorted(seeds), None) if seeds else {}
    steps, by_phrase = _steps_reached(m, root, walked)
    rows, unbound = _scenarios(m, root, [], by_phrase)

    # The chain under the first scenario of each feature file, found by the
    # reason written beside that scenario, which `_via` writes in both places.
    nodes = {(_rank_graph.relative(holder, root), func): (holder, func)
             for holder, func in walked}
    chains = {}
    for phrase, holder, func, hop in by_phrase.values():
        node = nodes.get((holder, func))
        if node is not None:
            chains[_via(phrase, holder, func, hop)] = _chain(walked, root, node)
    scenarios, told = [], set()
    for rel, scenario, line, why in rows:
        chain = "" if rel in told else chains.get(why, "")
        told.add(rel)
        scenarios.append((rel, scenario, line, why, chain))

    cases = sorted((rel, node[1], walked[node][0])
                   for node, rel in _pytest_at(m, root).items()
                   if node in walked)

    total = sum(len(f.get("scenarios") or ())
                for f in (m.get("features") or {}).values())
    step_at, _func_at = _declaration_sites(m)
    return {"name": name, "sites": sites, "scenarios": scenarios,
            "features": sorted({row[0] for row in scenarios}),
            "routes": _routes_reached(m, {f for f, _n in walked}),
            "pytest": cases, "steps": steps, "unbound": unbound,
            "total_scenarios": total, "map_steps": len(step_at),
            "partial": sorted(set(partial)),
            # Declared under a root of its own, on a map whose call graph
            # never leaves the repository root. Then this answer is a fact
            # about the map and not about the tests, and it has to say so.
            "offside": bool(sites) and not crosses_roots(m) and all(
                os.path.isabs(rel) for rel, _s, _e, _k, _m in sites),
            "no_edges": edge_count(m) == 0}


def reaches_summary(result: dict, limit: int) -> str:
    """The first line of a `reaches` answer: what was found and under what."""
    name = result["name"]
    if not result["sites"]:
        return (f"no declaration of {name!r} in the map, so nothing here "
                "reaches it")
    head = (f"`{name}` is declared in "
            f"{_plural(len(result['sites']), 'file')} and reached by "
            f"{len(result['scenarios'])} of {result['total_scenarios']} "
            f"scenarios, {_plural(len(result['features']), 'feature file')}, "
            f"{_plural(len(result['pytest']), 'pytest case')}, "
            f"{_plural(len(result['routes']), 'route')}, through "
            f"{_plural(len(result['steps']), 'step function')}. Walked "
            f"upward over the calls rows to any depth, {limit} characters.")
    if result["offside"]:
        head += (" This name is declared under a root of its own, and no "
                 "calls row in this map names a file outside the repository "
                 "root: the call graph is extracted from the files under "
                 "--repo and from no other root, so nothing here can reach "
                 "it whatever the tests do.")
    if result["partial"]:
        # The count below is a floor, and saying so is the difference between
        # "no test drives this class" and "this map cannot tell you".
        head += (" The parser did not find where this class stops and `spans`"
                 " records no method of it by name, so the walk covered the "
                 "class's own name and nothing declared inside it: the counts"
                 " above are a floor.")
    if not result["map_steps"]:
        head += (" This map holds no step function at all, so no scenario "
                 "can be named here whatever the code does.")
    elif result["unbound"]:
        head += (f" {result['unbound']} of {result['total_scenarios']} "
                 "scenarios hold no step this map binds to a step function.")
    if result["no_edges"]:
        head += NO_EDGES
    return head


def reaches_lines(result: dict, block: str) -> list:
    """One `reaches` block's rows, whole, before anything is cut."""
    if block == "sites":
        out = []
        for rel, start, end, kind, members in result["sites"]:
            line = f"- `{rel}:{start}-{end if end else '?'}` {kind}"
            if kind == "class":
                # What the class owns, because that is what was walked from
                # and there is no other way for a reader to see the join.
                line += (", " + _plural(len(members), "member") + " walked"
                         + (": " + ", ".join(members) if members else
                            " (its extent is unknown and `spans` names none "
                            "of them)"))
            out.append(line)
        return out
    if block == "scenarios":
        out = []
        for rel, name, line, why, chain in result["scenarios"]:
            out.append(f"- `{rel}:{line}` {name}, {why}")
            if chain:
                out.append(f"  chain: {chain}")
        return out
    if block == "pytest":
        return [f"- `{rel}::{name}`, {_plural(hop, 'hop')}"
                for rel, name, hop in result["pytest"]]
    if block == "routes":
        return [f"- {route}" for route in result["routes"]]
    return []


UNREACHED_BLOCKS = (
    ("definitions", "## Product definitions no test reaches", 50),
    ("counted", "## How this was counted", 25),
    ("set_aside", "## Files the map names as suite, so nothing declared in "
                  "them is counted above", 25),
)
UNREACHED_NAMES = tuple(name for name, _head, _pct in UNREACHED_BLOCKS)
UNREACHED_HEADS = {name: head for name, head, _pct in UNREACHED_BLOCKS}

# How many definitions one `unreached` answer ranks and prints by default.
# The map's `rank` key holds the top 200, so past this a definition has no
# score to be ranked by and the answer would be ordering a tail by nothing.
UNREACHED_LIMIT = 200


def unreached(m: dict, limit: int = UNREACHED_LIMIT) -> dict:
    """Product definitions with no call path up to anything that starts a test.

    The same walk as `affected` and `reaches`, run once and the other way
    round: from every entry point `entry_points` names down its callees, to
    exhaustion, and what that never arrives at is what no test runs. One walk
    for the whole map rather than one upward walk per definition, which is
    the same reachability read from the other end.

    Product is every indexed file the map does not name as suite (see
    `suite_files`), so a repository whose product sits under a root of its
    own and one whose product sits beside its suite are both answered from
    the keys the map already writes. A class counts as reached when anything
    declared inside its span is, because a page object is driven through its
    methods and its constructor is called at module level, where no `calls`
    row is written. A definition named in `ENTRY_POINTS`, and any file on a
    test path, are out: the runtime calls one and the other is scaffolding,
    and neither is what a reader means by untested product.
    """
    root = m.get("repo") or ""
    limit = max(1, int(limit))
    defs = _definitions(m)
    by_file = _by_file(defs)
    suite = suite_files(m)

    seeds, counts = entry_points(m, defs)
    walked = _climb(m, seeds, None, up=False) if seeds else {}
    hit = set(walked)

    product = {rel for rel in (_rank_graph.relative(holder, root)
                               for holder, _start in defs)
               if rel not in suite}
    # A product path that is still absolute after `relative()` is a file
    # under a root of its own: `relative` only strips the repository root, so
    # what it hands back whole came from somewhere else.
    base = {"limit": limit, "entry": counts, "entries": len(seeds),
            "product_files": len(product), "suite": sorted(suite),
            "suite_files": len(suite), "rate": _rate(m), "skipped": 0,
            "crosses": crosses_roots(m),
            "no_edges": edge_count(m) == 0,
            "outside": sorted(rel for rel in product if os.path.isabs(rel))}
    # With no entry point there is nothing to be unreached from, and a list
    # of every definition under a head that says so would be read as the
    # coverage report it is not. The head says it and the block is empty.
    if not seeds:
        return dict(base, definitions=[], unreached=0, total=0)

    scores: dict = {}
    for row in m.get("rank") or ():
        scores.setdefault((row.get("file"), row.get("name")),
                          row.get("score"))

    rows, total, skipped = [], 0, 0
    for (holder, start), (name, kind, end) in defs.items():
        rel = _rank_graph.relative(holder, root)
        if rel in suite:
            continue
        if name in ENTRY_POINTS or _is_test_path(rel):
            skipped += 1
            continue
        total += 1
        if (holder, name) in hit:
            continue
        if kind == "class" and any(
                (holder, member) in hit
                for member in _members(m, defs, by_file, holder, name, start,
                                       end)[0]):
            continue
        rows.append((rel, start, name, kind, scores.get((holder, name))))

    # Grouped by file, and the files ordered by the best rank in each, so a
    # reader works down from the file the repository is most built around.
    # An unranked definition sorts below every ranked one: the map's `rank`
    # holds 200 names and past that there is no score to order by.
    def order(row):
        score = row[4]
        return (-(score if score is not None else -1.0), row[1], row[2])

    best: dict = {}
    for row in rows:
        keep = order(row)[0]
        best[row[0]] = min(best.get(row[0], keep), keep)
    rows.sort(key=lambda row: (best[row[0]], row[0]) + order(row))
    return dict(base, definitions=rows[:limit], unreached=len(rows),
                total=total, skipped=skipped)


def unreached_summary(result: dict, limit: int) -> str:
    """The first line of an `unreached` answer, with what it cannot know.

    The resolution rate is in it because the whole answer turns on it: a
    graph that placed half its callee names calls half the product unreached
    whatever the suite covers, and a list of names under a head that does not
    say so reads as a coverage report. Everything else about how the count
    was made is a row of the block below, where it can be cut without taking
    the caveat with it.
    """
    gap = ("" if result["crosses"] or not result["outside"] else
           " No calls row names a file outside the repository root, so this "
           "walk never crosses into the product checked out beside the suite"
           f" ({_plural(len(result['outside']), 'file')}) and every name in "
           "it is below.")
    # Beside the rate rather than after the gap: the rate is the caveat this
    # line exists to carry, and an empty graph is the extreme case of it. A
    # map can read 100 percent resolved and hold no edge, which is the one
    # combination where the rate alone reassures a reader wrongly.
    rate = result["rate"] + (NO_EDGES if result["no_edges"] else "")
    if not result["entries"]:
        return ("This map names no step function and no test case, so there "
                "is nothing to reach from and nothing here can be called "
                "unreached. " + rate + gap)
    if not result["total"]:
        return ("Every file with a declaration is one this map names as "
                "suite, so there is no product side here to be unreached. "
                + rate + gap)
    one = result["unreached"] == 1
    return (f"Unreached: {result['unreached']} of {result['total']} product "
            f"definitions {'has' if one else 'have'} no path up to a test. "
            + rate
            + " A name below can be one the walk could not place rather "
              "than one nothing tests." + gap)


def unreached_lines(result: dict, block: str) -> list:
    """One `unreached` block's rows, whole, before anything is cut."""
    if block == "definitions":
        out = []
        for rel, line, name, kind, score in result["definitions"]:
            rank = "unranked" if score is None else f"rank {score:.9f}"
            out.append(f"- `{rel}:{line}` {name} ({kind}), {rank}")
        return out
    if block == "set_aside":
        return [f"- `{rel}`" for rel in result["suite"]]
    if block != "counted":
        return []
    entry = result["entry"]
    out = [f"- entry points: {_plural(entry['steps'], 'step function')}, "
           f"{_plural(entry['pytest'], 'pytest case')}, "
           f"{_plural(entry['runners'], 'declaration')} in the files another "
           "runner holds its cases in (the map records those cases by title "
           "rather than by function, so every declaration in them counts)",
           "- product: every file with a declaration the map does not name "
           f"as suite, {result['product_files']} of "
           f"{result['product_files'] + result['suite_files']}, and the "
           "precision of that split is the precision of the map's own suite "
           "heuristics",
           "- kinds counted: function and class; a const bound to an arrow "
           "function is recorded as a constant and is not one of them, "
           "because nothing in the map says which constants are callable",
           "- a class counts as reached when anything declared inside its "
           "span is, found by the dotted name `spans` writes beside a method "
           "and by containment in the class's range",
           "- not counted: a definition named "
           + " or ".join((", ".join(ENTRY_POINTS[:-1]), ENTRY_POINTS[-1]))
           + f", and any file on a test path ({result.get('skipped', 0)} "
             "left out this way)",
           f"- ranked by the map's own rank, showing "
           f"{len(result['definitions'])} of {result['unreached']}"]
    if not result["crosses"] and result["outside"]:
        out.append("- the call graph is extracted from the files under the "
                   "repository root and from no other root, so no edge "
                   "crosses into a product checked out beside the suite")
    return out
