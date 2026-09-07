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


def _climb(m: dict, seeds, depth=None, up: bool = True) -> dict:
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
    a cycle is walked once; the frontier is sorted at every hop and the rows
    of one node are taken in the order `xrefs` holds them, so the hop a node
    is first found at, and the edge that found it, are the same on every run.
    `depth` of None walks until nothing new is found, which is what a question
    about the whole graph ("does anything at all reach this") needs and what a
    question about a change ("which tests, six hops out") does not.

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
    for row in index.get(f"{holder}:{name}", ()):
        settled = row.get("file")
        for target in ([settled] if settled
                       else sorted(row.get("candidates") or ())):
            yield (target, row.get("object")), row


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


def _spans_at(m: dict) -> tuple:
    """`(step_at, func_at)`: where each step phrase and each function sits.

    A behave step is two declarations on one line: the function, and the
    phrase its decorator binds. So a node is a step function when `spans` has
    it as a function and has a phrase starting on the same line of the same
    file, which is the join that identifies one without reading the source or
    guessing from a module's name.
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
    step_at, func_at = _spans_at(m)
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
            "total_scenarios": total, "unbound": unbound}


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


def suite_files(m: dict) -> set:
    """Every file the map names as part of the test suite, repo-relative.

    A path this returns is written the way the map's own keys write it, so
    the caller compares `_rank_graph.relative(...)` against it. A file the
    walk read under a product root keeps its absolute path there and is
    therefore never in this set, which is what makes the split work whether
    the product is a second root or a directory beside the suite.
    """
    out = set()
    for key in _SUITE_LISTS:
        out.update(str(rel) for rel in (m.get(key) or ()) if rel)
    for key in _SUITE_KEYED:
        out.update(str(rel) for rel in (m.get(key) or {}) if rel)
    for key in _SUITE_RUNNERS:
        for group in (m.get(key) or {}).values():
            out.update(str(rel) for rel in (group or {}) if rel)
    return out


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


def _inside(by_file: dict, holder: str, start, end) -> list:
    """The names declared inside one span, which is what a class owns.

    `spans` records no owner, so a method is not linked to its class
    anywhere in the map. What it does record is the range of the class and
    the line of each method, and a method's line inside a class's range is
    the join. Where the parser knew no `end` there is no range and a class
    owns nothing here, which the answer's head says out loud.
    """
    if not end:
        return []
    return [name for line, name, _kind, _end in by_file.get(holder, ())
            if start < line <= end]


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


REACHES_BLOCKS = (
    ("sites", "## Declared in", 15),
    ("scenarios", "## Scenarios that reach it, by feature file", 60),
    ("routes", "## Routes (named by the file each one is served from)", 25),
)
REACHES_NAMES = tuple(name for name, _head, _pct in REACHES_BLOCKS)
REACHES_HEADS = {name: head for name, head, _pct in REACHES_BLOCKS}


def reaches(m: dict, name: str) -> dict:
    """Which scenarios and routes reach one product function or class.

    The other direction of the same question `affected` asks, over the same
    walk: `affected` starts at what a change declares, this starts at one
    name, and both climb the `calls` rows callee to caller until they arrive
    at a step function, which is where a scenario begins. No depth cap,
    because the question is whether anything reaches this at all and a cap
    would answer "nothing" for a name seven hops under a step.

    A class is asked about by name and answered by its members: `spans`
    records the range of the class and the line of each method and links them
    to nothing, so a method's line inside a class's range is the only join
    the map holds, and without it `reaches CheckoutPage` answers nothing at
    all for a page object every step drives, because the constructor call
    sits at module level and no `calls` row is written for it.
    """
    root = m.get("repo") or ""
    defs = _definitions(m)
    by_file = _by_file(defs)

    sites, seeds, seen_at = [], set(), set()
    for site in ((m.get("spans") or {}).get(name) or ()):
        holder, start = site.get("file"), site.get("start")
        if (holder, start) in seen_at:
            continue
        seen_at.add((holder, start))
        sites.append((_rank_graph.relative(holder, root), start,
                      site.get("end"), site.get("kind") or "name"))
        # Both spellings: the identifier this site is counted under, and the
        # name the reader typed, because a `calls` row names whichever one
        # the caller wrote.
        seeds.add((holder, name))
        chosen = defs.get((holder, start))
        if chosen:
            seeds.add((holder, chosen[0]))
        if site.get("kind") == "class":
            for member in _inside(by_file, holder, start, site.get("end")):
                seeds.add((holder, member))
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

    routes = _routes_reached(m, {holder for holder, _name in walked})

    total = sum(len(f.get("scenarios") or ())
                for f in (m.get("features") or {}).values())
    step_at, _func_at = _spans_at(m)
    return {"name": name, "sites": sites, "scenarios": scenarios,
            "features": sorted({row[0] for row in scenarios}),
            "routes": routes, "steps": steps, "unbound": unbound,
            "total_scenarios": total, "map_steps": len(step_at)}


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
            f"{_plural(len(result['routes']), 'route')}, through "
            f"{_plural(len(result['steps']), 'step function')}. Walked "
            f"upward over the calls rows to any depth, {limit} characters.")
    if not result["map_steps"]:
        # Not "nothing reaches this": this map has nothing to reach from, and
        # the two read the same in an answer that only prints a count.
        head += (" This map holds no step function at all, so no scenario "
                 "can be named here whatever the code does.")
    elif result["unbound"]:
        head += (f" {result['unbound']} of {result['total_scenarios']} "
                 "scenarios hold no step this map binds to a step function.")
    return head


def reaches_lines(result: dict, block: str) -> list:
    """One `reaches` block's rows, whole, before anything is cut."""
    if block == "sites":
        return [f"- `{rel}:{start}-{end if end else '?'}` {kind}"
                for rel, start, end, kind in result["sites"]]
    if block == "scenarios":
        out = []
        for rel, name, line, why, chain in result["scenarios"]:
            out.append(f"- `{rel}:{line}` {name}, {why}")
            if chain:
                out.append(f"  chain: {chain}")
        return out
    if block == "routes":
        return [f"- {route}" for route in result["routes"]]
    return []


UNREACHED_BLOCKS = (
    ("definitions", "## Product definitions no step function reaches "
                    "(a class counts as reached when anything inside its "
                    "span is)", 100),
)
UNREACHED_NAMES = tuple(name for name, _head, _pct in UNREACHED_BLOCKS)
UNREACHED_HEADS = {name: head for name, head, _pct in UNREACHED_BLOCKS}

# How many definitions one `unreached` answer ranks and prints by default.
# The map's `rank` key holds the top 200, so past this a definition has no
# score to be ranked by and the answer would be ordering a tail by nothing.
UNREACHED_LIMIT = 200


def unreached(m: dict, limit: int = UNREACHED_LIMIT) -> dict:
    """Product definitions with no call path up to any step function.

    The same walk as `affected` and `reaches`, run once and the other way
    round: from every step function down its callees, to exhaustion, and what
    that never arrives at is what no scenario runs. One walk for the whole
    map rather than one upward walk per definition, which is the same
    reachability read from the other end.

    Product is every indexed file the map does not name as suite (see
    `suite_files`), so a repository whose product sits under a root of its
    own and one whose product sits beside its suite are both answered from
    the keys the map already writes. A class counts as reached when anything
    declared inside its span is reached, because a page object is driven
    through its methods and its constructor is called at module level, where
    no `calls` row is written.
    """
    root = m.get("repo") or ""
    limit = max(1, int(limit))
    step_at, _func_at = _spans_at(m)
    defs = _definitions(m)
    by_file = _by_file(defs)

    seeds = sorted((holder, name)
                   for (holder, start), (name, kind, _end) in defs.items()
                   if kind == "function" and (holder, start) in step_at)
    walked = _climb(m, seeds, None, up=False) if seeds else {}
    hit = set(walked)
    # With no step function there is nothing to be unreached from, and a list
    # of every definition under a head that says so would be read as the
    # coverage report it is not. The head says it and the block is empty.
    if not seeds:
        product = {rel for rel in (_rank_graph.relative(holder, root)
                                   for holder, _start in defs)
                   if rel not in suite_files(m)}
        return {"definitions": [], "unreached": 0, "total": 0, "limit": limit,
                "steps": 0, "product_files": len(product),
                "suite_files": len(suite_files(m)), "rate": _rate(m)}

    scores: dict = {}
    for row in m.get("rank") or ():
        scores.setdefault((row.get("file"), row.get("name")),
                          row.get("score"))

    suite = suite_files(m)
    rows, total = [], 0
    for (holder, start), (name, kind, end) in defs.items():
        rel = _rank_graph.relative(holder, root)
        if rel in suite:
            continue
        total += 1
        if (holder, name) in hit:
            continue
        if kind == "class" and any(
                (holder, member) in hit
                for member in _inside(by_file, holder, start, end)):
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

    # Every file the product side declares anything in, whether or not
    # anything in it is unreached: the head divides one by the other.
    product = {rel for rel in (_rank_graph.relative(holder, root)
                               for holder, _start in defs)
               if rel not in suite}
    return {"definitions": rows[:limit], "unreached": len(rows),
            "total": total, "limit": limit, "steps": len(seeds),
            "product_files": len(product), "suite_files": len(suite),
            "rate": _rate(m)}


def unreached_summary(result: dict, limit: int) -> str:
    """The first line of an `unreached` answer, with what it cannot know.

    The resolution rate is in it because the whole answer turns on it: a
    graph that placed half its callee names calls half its product unreached
    whatever the suite covers, and a list of names under a head that does not
    say so reads as a coverage report.
    """
    files = result["product_files"] + result["suite_files"]
    if not result["steps"]:
        return ("This map holds no step function, so there are no steps to "
                "reach from and nothing here can be called unreached. "
                "Product here is every file with a declaration the map does "
                f"not name as suite: {result['product_files']} of {files}. "
                + result["rate"])
    if not result["total"]:
        return ("Every file with a declaration is one this map names as "
                "suite (features, steps, page objects, drivers, environment "
                "files, the test files of each runner), so there is no "
                "product side here to be unreached. " + result["rate"])
    one = result["unreached"] == 1
    return (f"Unreached: {result['unreached']} of {result['total']} product "
            f"definitions (function or class) "
            f"{'has' if one else 'have'} no call path up to a step function. "
            + result["rate"]
            + " A name below can be one the walk could not place rather than "
              "one nothing tests. Product is every file with a declaration "
              "the map does not name as suite: "
              f"{result['product_files']} of {files}. Ranked by the map's own "
              f"rank, showing {len(result['definitions'])}. "
              f"{limit} characters.")


def unreached_lines(result: dict, block: str) -> list:
    """The one `unreached` block's rows, whole, before anything is cut."""
    if block != "definitions":
        return []
    out = []
    for rel, line, name, kind, score in result["definitions"]:
        rank = "unranked" if score is None else f"rank {score:.9f}"
        out.append(f"- `{rel}:{line}` {name} ({kind}), {rank}")
    return out
