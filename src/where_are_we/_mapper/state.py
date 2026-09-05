"""Everything the mapper keeps for the length of a process, in one place.

These names are module-level state by design: the walk fills the indexes and
the renderers read them, `--also` merges a second root into the first root's
map, and the parse cache carries answers from one build to the next.

They live here, in a module nobody rebinds, so every part of the package reads
and writes the same object. `mapper.py` forwards attribute access for these
names straight to this module, which is what makes `mapper.PARSE_COUNT = 0` in
a caller reset the counter this package increments. The facade's docstring says
why that forwarding has to exist.
"""

import os


# Not `from ... import __version__`: `where_are_we`'s own `__init__.py`
# imports `mapper`, which imports this module, so that relative import is
# circular, and the
# "run as a plain file" fallback every other import in this block uses
# (`from __init__ import ...`) re-enters that same circular import from the
# other side and fails too. This goes around the package entirely instead,
# reading what pip/uv actually installed, the same way in both cases.
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("where-are-we")
except PackageNotFoundError:  # a loose checkout: nothing installed it
    # Every such checkout stamps the cache the same fixed "0", whatever
    # commit or release it actually is: a release-to-release stale cache
    # (the thing the version stamp exists to catch) is only possible here,
    # between two of these unnumbered checkouts, since the number itself
    # never changes to tell them apart.
    __version__ = "0"


# Every name this walk has seen, and the file and line it was defined on.
# Filled as files are parsed, written into the map, and searched first by --ask:
# a question about a name is a question about where it is.
DEFINITIONS: dict[str, str] = {}


# What was actually indexed, so an answer of "not found" can say what it looked
# at. The first version said "this is a real absence rather than a search that
# missed" about a constant sitting on line 31 of the product — because the
# product's language was not indexed at all. A map that overstates its reach is
# worse than a small one: it turns "I did not look" into "it is not there", and
# the reader stops looking too.
INDEXED: dict[str, int] = {}


# Every line of every file the walk read, so a phrase can be found without
# searching the repository again.
#
# A scenario author looking for the words "second Portal tab" or a label like
# "A 15" is asking about text, not about a name — half of one session's hundred
# and sixty-six searches were of that kind, and an index of declarations cannot
# answer them. The same walk already opens every file; keeping the lines costs
# one pass and turns a repository-wide grep into a lookup.
LINES: dict[str, list] = {}


# Bumped whenever what a kind stores, or how it is computed, changes. Tagged
# onto the file alongside the package version so a cache written by a
# different build of this tool is never trusted: a release that changes what
# `"symbols"` means, say, must not hand back an old value as if it still
# answered the same question. Both are checked, not just the schema number,
# because a release can change extraction logic without needing a new kind.
CACHE_SCHEMA = 1
_PARSE_CACHE: dict = {}


# Whether this build may answer from the parse cache, as opposed to only
# writing into it. `--force` sets it False: the cache validates an entry
# against a file's mtime and size, which cannot tell apart a rewrite of the
# same byte count that kept its timestamp (rsync --times, cp -p, tar -p, a
# restore from a build cache), and before this there was no flag that made the
# tool distrust what it thought it knew. Only the undocumented WAWE_NO_CACHE=1
# did, and that also stops the cache being written, so the next build paid for
# a cold parse too.
PARSE_CACHE_READS = True


# Incremented on every parse actually done: an ast.parse, a tree-sitter parse,
# or an index_declarations regex pass over a file's body. A rebuild of a tree
# nobody touched should add nothing to it, and WAWE_DEBUG_PARSES=1 prints the
# count so that claim can be checked instead of taken on faith.
PARSE_COUNT = 0


_FILE_CACHE: dict[str, str] = {}
_WALK_CACHE: dict[tuple, list] = {}


_IGNORE_CACHE: dict[str, list] = {}


# What `git ls-files` says a root already tracks, per root. One subprocess per
# build, because the answer is needed once per walked file and git is not.
_TRACKED_CACHE: dict[str, tuple] = {}


# Whether a walked path is a symlink leaving the tree, per (root, path). One
# build walks the same repository about a dozen times, once per topic, and
# the answer costs an lstat; asking it once per file instead of once per file
# per pass is the difference between a measurable slowdown and none.
_LINK_CACHE: dict[tuple, bool] = {}


# Files a parser was handed only the first AST_LIMIT bytes of, so the map can
# name them rather than look complete. Filled by `_slurp_source`, turned into
# one bounded note by `build()`.
CUT_FILES: list[str] = []


# What the walk had to leave out. A limit that stops quietly produces a map that
# looks complete and is not, and the reader has no way to tell — which is worse
# than a small map, because a small map that says so can be asked to grow. Named
# in the map itself, where whoever reads it is already looking.
TRUNCATED: list[str] = []


def reset(keep_indexes: bool = False) -> None:
    """Clear what one build accumulated, so the next one starts from nothing.

    Everything above is module-level by design, and that design assumed one
    build per process. A second `build()` in the same process inherited the
    first repository's names: `DEFINITIONS` is filled with `setdefault`, so
    the first writer of a name kept it, and a second repository's own map
    pointed a name at a file in the first one, counted the first one's files
    in `indexed`, and carried its lines. Which answer came back depended on
    the order the two were built in. `--watch` is the same process building
    the same repository over and over, so its map only ever grew: a name
    deleted from the tree stayed in the map for the life of the watcher, and
    the file counts climbed by one per rebuild.

    `keep_indexes` is for the one caller that means it. `--also` folds a
    service and its client into one map, so a second root's names have to
    stay searchable in the first root's map; that path says so here instead
    of relying on the absence of a reset.

    The five caches always go, `--also` included: they answer "which files
    are under this root", "what does this file say", "does this path leave the
    tree" and "what does git already track here", and a second root is a
    different question with the same key.

    `_PARSE_CACHE` is deliberately not cleared. It is not this build's
    working state: it is loaded from `out_dir` at the top of every build and
    validated per file against mtime and size, and it is the whole reason a
    rebuild of a tree nobody touched parses nothing.
    """
    _WALK_CACHE.clear()
    _IGNORE_CACHE.clear()
    _TRACKED_CACHE.clear()
    _FILE_CACHE.clear()
    _LINK_CACHE.clear()
    if keep_indexes:
        return
    DEFINITIONS.clear()
    INDEXED.clear()
    LINES.clear()
    TRUNCATED.clear()
    CUT_FILES.clear()


# What may go in a prompt, in bytes. Not a preference: a prompt is re-sent in
# full on every turn of a session, so anything put there is paid for on every
# turn whether it is read or not. Measured on one real run — the brief inlined
# whole, 253 KB, one agent taking 424 turns — the map alone came to 27.4 million
# tokens re-sent, a quarter of everything that run consumed, and it emptied a
# five-hour allowance in seventy-four minutes.
#
# So this project answers a prompt with a pointer and keeps the map on disk. The
# number is small on purpose: it is a signpost, and a signpost the size of the
# town is a town.
POINTER_MAX = int(os.getenv("WAWE_POINTER_MAX", "4000"))
