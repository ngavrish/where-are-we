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


# Every site of every name, not only the first: `[path, start, end, kind]` per
# declaration, appended as files are parsed and written into the map as
# `spans`.
#
# `DEFINITIONS` is filled with `setdefault`, so a name declared in two files
# keeps the first and says nothing about the second. That was the one place
# this map was quiet about a bound instead of naming it: `defines charge`
# answered with one home for a name that has three, and which of the three it
# named depended on walk order. This table keeps them all. `end` is None where
# the language was read by the regex table, which has seen the first line of a
# declaration and nothing that says where it stops.
SPANS: dict[str, list] = {}


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
#
# 2: the declaration kinds carry a span. `ts:<lang>` is why the number had to
# move: it stored a list of names and now stores a list of
# `[name, start, end, kind]` rows, so a 1.4 entry read back under the new code
# would take `row[0]` of a string and index a character. `spans:<ext>` is a
# new kind an old cache simply misses, and `step_texts` gained a list the
# reader treats as optional; neither of those alone would need a bump.
#
# 3: an entry is validated against the sha256 of the file's bytes rather than
# against its mtime and size, so the entry holds `sha` where it used to hold
# `mtime` and `size`. A schema 2 entry read under this rule has no `sha` at
# all and would be discarded one by one; discarding the file is the same
# answer arrived at once.
CACHE_SCHEMA = 3
_PARSE_CACHE: dict = {}


# What each file's bytes hashed to, and the (mtime, size, ctime) it had when
# that hash was taken: `path -> {"mtime", "size", "ctime", "sha"}`. Persisted
# beside the parse cache in the same file, and loaded from it.
#
# This is the pre-filter that keeps content addressing affordable. Hashing
# every indexed file on every build would read the whole tree twice; hashing
# only the files whose stat block moved reads nothing on a tree nobody
# touched, and a build that reads nothing is the warm build the README
# publishes a number for.
#
# `ctime` is in there because `mtime` and `size` alone are exactly the blind
# spot this cache exists to close. A same-size rewrite with the timestamp put
# back (rsync --times, cp -p, tar -p, a restore from a build cache, `git
# checkout` of a line the same length) leaves both unchanged, and a pre-filter
# reading only those two would skip the hash and serve the stale parse. The
# inode change time cannot be set from userland: writing the file moves it,
# and so does the `utimes` call that puts the mtime back. On a filesystem
# where `st_ctime` means creation time instead (Windows), this degrades to
# the mtime-and-size pre-filter, which is what the tool did before.
_HASH_CACHE: dict = {}


# Incremented on every sha256 actually computed, the way `PARSE_COUNT` counts
# parses: a rebuild of a tree nobody touched should add nothing to either, and
# WAWE_DEBUG_PARSES=1 prints both so the claim can be checked.
HASH_COUNT = 0


# Where this invocation's hashing started, for a caller that hashes before it
# builds. The command line asks for a content root before deciding whether to
# build at all, and those hashes are part of what the run cost; a build that
# counted from its own entry would report only the hashes it took itself and
# the debug line would say half. None means "count from build entry", which is
# every other caller.
HASH_MARK: int | None = None


# What the cache file on disk says each file hashed to, as it was read, before
# anything this process took is merged over the top. That is the record of the
# tree the map in the same directory was built from, and it is the baseline
# `--diff` measures against, so it has to be kept apart from the live cache:
# the command line hashes a changed file on its way to deciding whether to
# build, and the live cache therefore already holds the new answer by the time
# `build()` looks.
HASHES_AT_LOAD: dict = {}


# The files this build has already hashed, so `--force` can distrust the hash
# cache without reading a file twice. `--force` means nothing on disk from a
# previous run is believed; it does not mean the same file is read once for
# its parse and again for the content root.
_HASHED_THIS_BUILD: set = set()


# The files whose content hash differs from the one the loaded cache holds for
# them, which files are in the tree that the cache had never hashed, and which
# the cache had hashed and are no longer there. All relative to the repository,
# filled by `build()` and read by `--diff`. The map's `content_root` says the
# tree moved; these say what moved it.
HASHES_MOVED: list[str] = []
HASHES_ADDED: list[str] = []
HASHES_GONE: list[str] = []


# Whether this build may answer from the parse cache, as opposed to only
# writing into it. `--force` sets it False: the cache validates an entry
# against a file's mtime and size, which cannot tell apart a rewrite of the
# same byte count that kept its timestamp (rsync --times, cp -p, tar -p, a
# restore from a build cache), and before this there was no flag that made the
# tool distrust what it thought it knew. Only the undocumented WAWE_NO_CACHE=1
# did, and that also stops the cache being written, so the next build paid for
# a cold parse too.
PARSE_CACHE_READS = True


# Whether this build may write the parse cache back. `--diff` sets it False: it
# builds a whole map only to compare it against the one already in `--out`, and
# the cache beside that map is the record of what the map was built from. A
# `--diff` that rewrote it moved its own baseline, so the same command run
# twice over the same tree answered differently the second time. Set back to
# True at the end of every build, the way `PARSE_CACHE_READS` is: both are one
# build's setting and not the process's.
PARSE_CACHE_WRITES = True


# Whether `index_lines` redacts a file's lines as it records them, so that
# `build()` returns the same text every consumer of the published map reads.
# `tests/golden/build_fixtures.py` turns it off through `build(redact_lines=
# False)`, for the reason written there: a fixture holds nothing to protect,
# and the base64-like rule occasionally matches a stretch of a real temporary
# path, which would make the pinned maps depend on what the OS named that
# run's directory.
REDACT_LINES = True


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

    `_PARSE_CACHE` and `_HASH_CACHE` are deliberately not cleared. They are
    not this build's working state: both are loaded from `out_dir` at the top
    of every build and validated per file against what `os.stat` says now,
    and they are the whole reason a rebuild of a tree nobody touched parses
    nothing and hashes nothing.
    """
    HASHES_MOVED.clear()
    HASHES_ADDED.clear()
    HASHES_GONE.clear()
    _HASHED_THIS_BUILD.clear()
    _WALK_CACHE.clear()
    _IGNORE_CACHE.clear()
    _TRACKED_CACHE.clear()
    _FILE_CACHE.clear()
    _LINK_CACHE.clear()
    if keep_indexes:
        return
    DEFINITIONS.clear()
    SPANS.clear()
    INDEXED.clear()
    LINES.clear()
    TRUNCATED.clear()
    CUT_FILES.clear()


# Whether this process may use the parse cache at all. Read here, once, and
# named, rather than out of the environment in the middle of `build()` and
# again in the middle of `_cached()`: the configuration a run was started with
# belongs where the rest of it is, and a reader looking for what this package
# is configured by should not have to find two `os.environ` calls a thousand
# lines apart. Set to anything, it makes every build parse every file and
# leaves the cache on disk exactly as it was.
NO_CACHE = bool(os.environ.get("WAWE_NO_CACHE"))


# Whether a build prints the number of files it actually parsed and the number
# it actually hashed, to stderr, so an incremental rebuild's claim can be
# checked instead of taken on faith. Both, because the parse count alone
# cannot tell a tree that was hashed and found unchanged from one the
# pre-filter never read at all.
DEBUG_PARSES = bool(os.environ.get("WAWE_DEBUG_PARSES"))


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
