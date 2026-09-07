"""PageRank over the map's own graph: which definitions matter structurally.

`ask` ranks sections and rows by how much they mention the words asked. That
answers "where is the word", and a reader opening an unfamiliar repository is
asking something else: what should I read first, and what should I read first
*given that I am editing these files*. Word matching cannot answer either one,
because importance is a property of the graph rather than of the text.

The graph is the one the map already holds. Nodes are files. An edge runs from
a file that mentions an identifier to a file that declares it, one edge per
identifier, weighted `sqrt(references)`: the tenth mention of a name in one
file says much less than the first. PageRank over that graph, personalised on
the files the reader named, ranks every file; each file's rank is then split
across its outgoing edges in proportion to their weight, and the share landing
on `(defining file, identifier)` is that definition's score.

The multipliers are aider's (`repomap.py`, `get_ranked_tags`), taken verbatim
because they encode judgement this walk has no other way to reach:

  x10   an identifier the reader just asked about
  x10   a long snake, kebab or camel name (domain vocabulary, not `i` or `tmp`)
  x0.1  a leading underscore (private by convention)
  x0.1  a name more than five files declare (`run`, `main`, `setup`)

`networkx` is not stdlib, so the power iteration is written out below: a fixed
100 iterations, damping 0.85, nodes visited in sorted order, values rounded to
nine digits before sorting and ties broken by path. Those four are what make
the ranking a byte of the map rather than a property of the machine that built
it: a dict iterated in insertion order, or an early exit on a convergence
test, would make two runs on two Python versions disagree in the last place
and the golden maps would move under a build that changed nothing.

No model, no embeddings, no network. Imports nothing from this package, so
both callers can have it: the build, which stores the unpersonalised ranking
under the map's `rank` key, and `ask`, which recomputes a personalised one
from the same two tables on disk.
"""

import math
import os
import re

# What counts as an identifier, on both sides of the graph: the name a
# language declares, and the token a file mentions. A step phrase or a
# scenario title is in `spans` too and is not identifier-shaped, so it
# declares no node here and no file can reference it.
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A lowercase letter followed by an uppercase one: `parseHeader` has a case
# change, `PARSER` and `parser` do not.
_CASE_CHANGE = re.compile(r"[a-z][A-Z]")

DAMPING = 0.85
ITERATIONS = 100
# Values are rounded to this many digits before they are sorted. Two builds of
# the same tree agree to far more than nine, and rounding first is what stops
# a difference in the last bit of a float from reordering two definitions that
# are, to any reader, equally important.
DIGITS = 9
# The length at which a snake, kebab or camel name reads as domain vocabulary.
LONG_NAME = 8
# More than this many files declaring one name makes it a word rather than a
# definition: `run`, `main`, `build`, `setup`.
COMMON_DECLARERS = 5
# How many definitions the stored key holds, and how many `--rank` prints when
# nothing says otherwise. The same number in both, so `--rank` with no files
# is the stored order rather than a prefix of it that has to be explained.
TOP = 200
# How much more of the personalisation vector the named files hold than every
# other file. The rest keep a uniform small share rather than none at all: a
# vector concentrated to zero elsewhere makes the ranking of a file nothing in
# the named set reaches undefined, and this way the graph beyond them is still
# ordered, just underneath.
PERSONAL_BOOST = 100.0


def relative(path: str, root: str) -> str:
    """`path` as the repository writes it: relative to the root, forward slashes.

    The map stores absolute paths. A reader naming `billing/refund.py` means
    the file at that path under the repository, and never types the checkout
    directory in front of it.
    """
    out = path.replace(os.sep, "/")
    stem = (root or "").replace(os.sep, "/").rstrip("/")
    if stem and out.startswith(stem + "/"):
        out = out[len(stem) + 1:]
    return out


def matches(path: str, root: str, wanted) -> bool:
    """Whether one file is one the reader named: exact, or under a prefix.

    `--files billing/` is every file in that directory; `--files a.py` is that
    file. Compared relative to the repository root, because that is how the
    reader writes a path and how every row of the map that is not a
    definition prints one.
    """
    if not wanted:
        return False
    rel = relative(path, root)
    for want in wanted:
        want = want.replace(os.sep, "/").lstrip("./")
        if want and (rel == want or rel.startswith(want)):
            return True
    return False


def multiplier(name: str, declarers: int, asked) -> float:
    """Aider's four multipliers for one identifier, multiplied together."""
    mul = 1.0
    if name.lower() in asked:
        mul *= 10.0
    if len(name) >= LONG_NAME and ("_" in name or "-" in name
                                   or _CASE_CHANGE.search(name)):
        mul *= 10.0
    if name.startswith("_"):
        mul *= 0.1
    if declarers > COMMON_DECLARERS:
        mul *= 0.1
    return mul


def _definers(spans: dict) -> tuple:
    """`({name: [file]}, {(file, name): line}, {(file, name): {line}})`.

    One entry per file that declares the name, in path order; the first line
    that file declares it on, because a definition's row has to name a line;
    and every line it declares it on, because those lines are not references
    to it. `def charge(` reads as a call to `charge` to anything without a
    parser, and six files declaring one name would then each reference the
    other five and rank each other up as a clique -- which is the opposite of
    what the "declared in more than five files" multiplier is there to say.
    """
    homes: dict = {}
    line_at: dict = {}
    declared: dict = {}
    for name in sorted(spans):
        if not IDENT.fullmatch(name):
            continue
        files = []
        for site in spans[name] or ():
            path = site.get("file")
            if not path:
                continue
            if path not in files:
                files.append(path)
            key = (path, name)
            start = site.get("start") or 0
            if key not in line_at or start < line_at[key]:
                line_at[key] = start
            declared.setdefault(key, set()).add(start)
        if files:
            homes[name] = sorted(files)
    return homes, line_at, declared


def _references(lines: dict, wanted: set, declared: dict) -> dict:
    """`{file: {name: count}}`: how often each file uses each known name.

    Only names something declares are counted, so this is a lookup per token
    rather than a table of every word in the repository.

    A use is the name written the way code writes one: called, subscripted,
    assigned, or reached through a dot. Aider takes its references from
    tree-sitter captures and never sees a comment; the only text here is the
    lines the walk kept, and counting every occurrence in them ranks the
    English words at the top. Measured on this repository: `of` is declared
    once, appears 1,196 times in prose, and beat `find_text` (18 uses, a
    function three modules call) for first place. `at(` is a call and `at the`
    is a sentence, and those five characters of punctuation are all that
    separates them without a parser.

    A line that declares the name is not a use of it. `spans` says which
    lines those are, per file and per name, and skipping them is what stops
    `def charge(` from reading as a call.
    """
    out: dict = {}
    for path in sorted(lines):
        counts: dict = {}
        for lineno, line in enumerate(lines[path] or (), 1):
            for hit in IDENT.finditer(line):
                token = hit.group()
                if token not in wanted:
                    continue
                before = line[hit.start() - 1] if hit.start() else ""
                after = line[hit.end()] if hit.end() < len(line) else ""
                if before != "." and after not in ".([=":
                    continue
                if lineno in (declared.get((path, token)) or ()):
                    continue
                counts[token] = counts.get(token, 0) + 1
        if counts:
            out[path] = counts
    return out


def _edges(homes: dict, refs: dict, asked) -> tuple:
    """`(nodes, {src: [(dst, name, weight), ...]})`: the graph, sorted.

    One edge per (referencing file, defining file, identifier), weighted by
    the identifier's multipliers and the square root of how many times the
    referencing file mentions it. A file's edge to itself is not an edge: it
    would say that a file matters because it uses what it declares.
    """
    nodes = set()
    out: dict = {}
    for src in sorted(refs):
        counts = refs[src]
        for name in sorted(counts):
            files = homes.get(name) or ()
            mul = multiplier(name, len(files), asked)
            weight = mul * math.sqrt(counts[name])
            if weight <= 0.0:
                continue
            for dst in files:
                if dst == src:
                    continue
                out.setdefault(src, []).append((dst, name, weight))
                nodes.add(src)
                nodes.add(dst)
    return sorted(nodes), out


def page_rank(nodes: list, out_edges: dict, personal: dict) -> dict:
    """Power iteration over the file graph. Forty lines, no networkx.

    A fixed number of iterations rather than a convergence test: a test
    stops at a different iteration on a different machine, and the number it
    stops at is then part of the answer. Damping is 0.85 and the mass a file
    with no outgoing edge holds is redistributed by the personalisation
    vector, which is what makes a personalised run stay near the files it was
    given rather than leak uniformly.
    """
    rank = dict(personal)
    for _ in range(ITERATIONS):
        nxt = {node: 0.0 for node in nodes}
        dangling = 0.0
        for src in nodes:
            edges = out_edges.get(src)
            share = rank[src]
            if not edges:
                dangling += share
                continue
            total = 0.0
            for _dst, _name, weight in edges:
                total += weight
            if total <= 0.0:
                dangling += share
                continue
            for dst, _name, weight in edges:
                nxt[dst] += DAMPING * share * (weight / total)
        leak = (1.0 - DAMPING) + DAMPING * dangling
        for node in nodes:
            nxt[node] += leak * personal[node]
        rank = nxt
    return rank


def _personal(nodes: list, root: str, files) -> dict:
    """The personalisation vector: the named files heavy, the rest uniform."""
    weights = {node: (PERSONAL_BOOST if matches(node, root, files) else 1.0)
               for node in nodes}
    total = 0.0
    for node in nodes:
        total += weights[node]
    if total <= 0.0:
        return {node: 0.0 for node in nodes}
    return {node: weights[node] / total for node in nodes}


def rows(map_obj: dict, files=(), words=(), limit: int = TOP) -> list:
    """The top definitions of one map, best first.

    `[{"name", "file", "line", "score"}]`, sorted by score and then by path
    and name, so two builds of the same tree write the same bytes. `files`
    personalises the walk on the files the reader named; `words` are the
    identifiers they asked about, worth ten times an identifier they did not.

    Reads two keys and nothing else: `spans`, for what each file declares,
    and `lines`, for what each file mentions. The build passes them before
    they are written and `ask` reads them back off disk, so the stored
    ranking and an unpersonalised `--rank` are the same list rather than two
    lists that ought to agree.
    """
    spans = map_obj.get("spans") or {}
    lines = map_obj.get("lines") or {}
    root = map_obj.get("repo") or ""
    asked = {w.lower() for w in (words or ()) if w}
    homes, line_at, declared = _definers(spans)
    if not homes:
        return []
    refs = _references(lines, set(homes), declared)
    nodes, out_edges = _edges(homes, refs, asked)
    scores: dict = {}
    if nodes:
        ranked = page_rank(nodes, out_edges, _personal(nodes, root, files))
        for src in nodes:
            edges = out_edges.get(src)
            if not edges:
                continue
            total = 0.0
            for _dst, _name, weight in edges:
                total += weight
            if total <= 0.0:
                continue
            share = ranked[src]
            for dst, name, weight in edges:
                key = (dst, name)
                scores[key] = scores.get(key, 0.0) + share * (weight / total)
    # Every declaration site, including the ones nothing points at: a
    # definition with no incoming edge scores zero rather than going missing,
    # so "this file is called by nothing" is an answer this list can give.
    out = []
    for name in sorted(homes):
        for path in homes[name]:
            out.append({"name": name, "file": path,
                        "line": line_at.get((path, name), 0),
                        "score": round(scores.get((path, name), 0.0), DIGITS)})
    out.sort(key=lambda row: (-row["score"], row["file"], row["name"]))
    return out[:limit] if limit else out
