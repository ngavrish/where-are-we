"""What a change reaches: the test selection the map's own graph already holds.

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
    rows = m.get("xrefs") or []

    by_object: dict = {}
    subjects = []
    seen: dict = {}
    frontier = []
    for row in rows:
        edge = row.get("edge")
        if edge == "calls":
            by_object.setdefault(row.get("object"), []).append(row)
        subject_file = _subject_file(row)
        subjects.append(subject_file)
        if edge != "declares":
            continue
        node = (subject_file, row.get("object"))
        if node not in seen and _rank_graph.matches(subject_file, root, wanted):
            seen[node] = (0, None)
            frontier.append(node)

    frontier.sort()
    for hop in range(1, depth + 1):
        found = []
        for node in frontier:
            holder, name = node
            for row in by_object.get(name, ()):
                settled = row.get("file")
                if settled != holder and not (
                        settled is None and holder in (row.get("candidates") or ())):
                    continue
                caller_file, _, caller_name = str(
                    row.get("subject") or "").rpartition(":")
                reached = (caller_file, caller_name)
                if reached in seen:
                    continue
                seen[reached] = (hop, row)
                found.append(reached)
        if not found:
            break
        frontier = sorted(found)

    return _blocks_from(m, root, wanted, depth, seen, set(subjects))


def _blocks_from(m: dict, root: str, wanted: list, depth: int, seen: dict,
                 subjects: set) -> dict:
    """The reached nodes turned into the lists the answer prints.

    Split out of `affected()` because the walk is one idea and reading the
    other tables through its result is another: `spans` says which of the
    reached functions is a step, `steps` and `features` say which scenarios
    those steps are in, and `routes_served`, `page_objects` and
    `pytest_tests` each name a file the walk may have reached.
    """
    # Where each declaration of each kind sits, from `spans`. A behave step
    # is two declarations on one line: the function, and the phrase its
    # decorator binds. So a reached node is a step function when `spans` has
    # it as a function and has a phrase starting on the same line of the same
    # file, which is the join that identifies one without reading the source
    # or guessing from a module's name.
    step_at, func_at = {}, {}
    for name, sites in (m.get("spans") or {}).items():
        for site in sites or ():
            where = (site.get("file"), site.get("start"))
            if site.get("kind") == "step":
                step_at.setdefault(where, name)
            elif site.get("kind") == "function":
                func_at.setdefault((site.get("file"), name), site.get("start"))

    # By the site rather than by the name. One `def` can be declared under
    # two names here: a step module's own extractor writes `step_pay_1` and
    # `def step_pay_1` for the same line, and counting both would report
    # twice as many step functions as the suite has. The name kept is the one
    # that reads as an identifier, which is the shorter of the two and the
    # one without a space in it.
    by_site: dict = {}
    reached_files = set()
    for (holder, name), (hop, _row) in seen.items():
        reached_files.add(holder)
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

    # Nearest first, so where two step functions bind phrases that normalise
    # to the same forty characters the scenario is reported through the one
    # closer to the change. Ties by phrase, then by module and function, so
    # the choice does not depend on the order the walk happened to find them.
    by_phrase: dict = {}
    for phrase, holder, name, hop in sorted(steps, key=lambda s: (s[3],) + s[:3]):
        key = _normalise(phrase)[:PHRASE_HEAD]
        if key:
            by_phrase.setdefault(key, (phrase, holder, name, hop))

    scenarios, unbound = _scenarios(m, root, by_phrase)
    features = sorted({row[0] for row in scenarios})

    routes = []
    bases = {os.path.basename(f) for f in reached_files}
    for route in m.get("routes_served") or ():
        hit = _ROUTE_FILE.search(str(route))
        if hit and hit.group(1) in bases:
            routes.append(str(route))

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
            "tags": _tags(m, features)}


def _scenarios(m: dict, root: str, by_phrase: dict) -> tuple:
    """`(rows, unbound)`: the scenarios a reached step function is used by.

    A scenario's steps are its own lines, which the map already holds in
    `lines`, read from the scenario's line to the line before the next
    scenario in that file. A line is a step of this scenario when a reached
    phrase, normalised and cut to `PHRASE_HEAD`, appears in it: the rule
    `feature_links` is built with, so a scenario named here is a scenario the
    map already binds to that step module.

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
        marks = sorted((s.get("line") or 0, s.get("name") or "")
                       for s in (entry.get("scenarios") or ()))
        for i, (line, name) in enumerate(marks):
            end = marks[i + 1][0] - 1 if i + 1 < len(marks) else len(body)
            hits, bound = [], False
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
            if hits:
                hop, _offset, phrase, holder, func = min(hits)
                rows.append((rel, name, line, phrase, holder, func, hop))
    # By where each scenario is written rather than by what it is called, so
    # a feature file reads here in the order it reads on disk.
    rows.sort(key=lambda row: (row[0], row[2], row[1]))
    return rows, unbound


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


def _tags(m: dict, features: list) -> list:
    """The tags that are on every affected feature file and on no other one.

    The map records tags per feature file, not per scenario, so this is the
    only tag question it can answer: a `--tags` run selects whole files here,
    and where one tag is also on a file this change does not reach the answer
    falls back to the include list instead of quietly running more than it
    said it would.
    """
    holds = m.get("features") or {}
    chosen = set(features)
    if not chosen:
        return []
    elsewhere = {t for rel, entry in holds.items() if rel not in chosen
                 for t in (entry.get("tags") or ())}
    shared = None
    for rel in features:
        mine = {t for t in ((holds.get(rel) or {}).get("tags") or ())
                if t not in elsewhere}
        shared = mine if shared is None else (shared | mine)
        if not mine:
            return []
    return sorted(shared or ())


def summary(result: dict, limit: int) -> str:
    """The first line of every answer: what was counted, and under what rules.

    Every character of it is a character no block gets, so it says the counts,
    the depth the walk ran to and the ceiling it was cut against, and then the
    one caveat a count of zero needs: how many scenarios hold no step this map
    can bind to a step function at all.
    """
    files = result["files"]
    named = ", ".join(files) if len(files) <= 3 else _plural(len(files), "file")
    head = (f"Affected by a change to {named}: {len(result['scenarios'])} of "
            f"{result['total_scenarios']} scenarios, "
            f"{_plural(len(result['features']), 'feature file')}, "
            f"{_plural(len(result['routes']), 'route')}, "
            f"{_plural(len(result['pages']), 'page object')}, "
            f"{_plural(len(result['steps']), 'step function')}. Depth "
            f"{result['depth']}, {limit} characters.")
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


def block_lines(result: dict, block: str) -> list:
    """One block's rows, whole, before anything is cut to a budget.

    Empty for a block with nothing in it: the first line already printed the
    count, and five heads with nothing under them are five rows of a budget
    spent saying nothing. The two `--affected-format` blocks are the
    exception, because there the block is the whole answer.
    """
    if block == "scenarios":
        return [f"- `{rel}:{line}` {name}, via `{phrase}` in "
                f"`{holder}:{func}`, {_plural(hop, 'hop')}"
                for rel, name, line, phrase, holder, func, hop
                in result["scenarios"]]
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

    A caller pasting this into a pipeline has to know whether it is running
    whole feature files or a tag expression, and why the answer picked that
    one, because the two select different things.
    """
    if block == "pytest":
        return "## pytest node ids, one per line"
    if result["tags"]:
        return ("## behave tags, one per line: these are on every affected "
                "feature file and on no other")
    if not result["features"]:
        return "## behave include patterns, one per line for -i"
    return ("## behave include patterns, one per line for -i: the map records "
            "tags per feature file rather than per scenario, and no tag here "
            "is on the affected files alone")


def _behave_lines(result: dict) -> list:
    """The include list, as `--tags` values where the map holds a tag that
    separates these feature files and as `-i` patterns otherwise.

    `-i` matches a feature file path, so the pattern is anchored on a path
    separator and on the end of the name: without that, `features/pay.feature`
    would also select `features/pay.feature.bak` and a directory whose name
    ends in the same letters.
    """
    if result["tags"]:
        return [f"@{tag}" for tag in result["tags"]]
    if not result["features"]:
        return ["no feature file in this map is reached by a change to "
                "these files"]
    return [f"(^|/){re.escape(rel)}$" for rel in result["features"]]
