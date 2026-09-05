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
try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("where-are-we")
except Exception:  # noqa: BLE001 -- not installed: a loose checkout, no pip/uv
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


# Incremented on every parse actually done: an ast.parse, a tree-sitter parse,
# or an index_declarations regex pass over a file's body. A rebuild of a tree
# nobody touched should add nothing to it, and WAWE_DEBUG_PARSES=1 prints the
# count so that claim can be checked instead of taken on faith.
PARSE_COUNT = 0


_FILE_CACHE: dict[str, str] = {}
_WALK_CACHE: dict[tuple, list] = {}


_IGNORE_CACHE: dict[str, list] = {}


# What the walk had to leave out. A limit that stops quietly produces a map that
# looks complete and is not, and the reader has no way to tell — which is worse
# than a small map, because a small map that says so can be asked to grow. Named
# in the map itself, where whoever reads it is already looking.
TRUNCATED: list[str] = []


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
