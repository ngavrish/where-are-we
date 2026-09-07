"""A map of the test framework, built from the checkout, for agents to read
instead of rediscovering it.

Every implementer session used to open with the same half hour: grep for where
the steps live, which page object owns the portal, how the driver is built, what
`environment.py` does, which scripts run a scenario. Forty tool calls at roughly
a minute each, in every branch, every run, and the answers are identical for all
of them and derivable without a model.

So they are derived here, deterministically, in a second or two, at the start of
the run and against this run's own checkout (the suite changes; a map from
yesterday would be a lie). The result goes to the run directory as JSON and as a
short Markdown digest the agents are pointed at.

This file is the facade. The five thousand lines that used to be here live in
`_mapper/`, one file per job (`_mapper/__init__.py` lists them); every name
callers use is re-exported below, so `from where_are_we import mapper` and
`mapper.anything` keep meaning what they meant.

It stays a module and does not become a package, because it is also run as a
plain script by path (`python src/where_are_we/mapper.py --repo . --out /tmp/m`)
and a directory cannot be. The same two-way import the rest of this project
uses is below: relative when there is a package around it, plain when there is
not.

The command line is not re-exported from here: `cli.py` is the layer above
this module, and importing it here is what used to put every module in the
package on an import cycle. `mapper.main`, `mapper.init_manifest`,
`mapper.install_hook` and `mapper.propose_docs` still resolve, through the
same attribute hook the shared state uses, by importing `cli` on first use.

Why this module has a class
---------------------------
`_mapper/state.py` owns what the whole package shares: `DEFINITIONS`,
`INDEXED`, `LINES`, `TRUNCATED`, the walk, file and ignore caches, the parse
cache, `PARSE_COUNT`, `POINTER_MAX`, `CACHE_SCHEMA`. Callers outside the
package reach them through this module. `tests/golden/build_fixtures.py`
clears the indexes with `mapper.DEFINITIONS.clear()`; `tests/golden/check.py`
measures a build with `mapper.PARSE_COUNT = 0` and then reads
`mapper.PARSE_COUNT` back to assert the parse cache was used.

Re-exporting the names cannot serve the second one. `mapper.PARSE_COUNT = 0`
would rebind a name in this module and leave `state.PARSE_COUNT` alone; the
build would count into `state` while the check read this module's stale zero,
and the check would pass without measuring anything, which is worse than
failing.

So this module's `__class__` is a subclass of `ModuleType` that forwards
exactly the names in `_STATE_NAMES` to `_mapper.state`. Reading
`mapper.PARSE_COUNT` reads the counter the package increments; assigning it
assigns that same counter. Nothing else changes: module-level code here still
writes straight to the module dict, and every other attribute is an ordinary
one.
"""

import sys
import types

try:
    from ._mapper import state
    from .ask import (_definitions_for, ask, at, context, definitions_for,
                      file_list, more, rank_lines, spans_for)
    from ._mapper.walk import (MAX_FILES, SKIP_DIRS, _PARSE_CACHE_FILE,
                               _SECRET_SHAPES, _cached, _config, _fingerprint,
                               _ignored, _ignores, _lines_matching,
                               _load_parse_cache, _looks_like_suite, _manifest,
                               _product_roots, _save_parse_cache, _slurp,
                               _walk, content_hash, content_pairs,
                               content_root, fingerprint, redact)
    from ._mapper.declare import (DECLARATIONS, STEP_DECORATORS,
                                  TS_LANG_BY_EXT, _DECLARES, _PER_FILE_CAP,
                                  TS_END_BY_EXT, _TS_PARSERS, _declared_names,
                                  _line_for_name, _read_for_declarations,
                                  _regex_declared_names, _step_texts,
                                  _tree_sitter, _ts_symbols, declarations_in,
                                  find_text, index_declarations, index_lines,
                                  record_span, spans_index)
    from ._mapper.render import (_PRODUCT_SIDE, _TEST_SIDE, _as_dict, _as_list,
                                 _cap_sections, brief, changed_since, ctags,
                                 digest, for_audience, meaning_tail, pointer)
    from ._mapper.build import _layer_line, build
except ImportError:  # run as a plain file, with no package around it
    from _mapper import state
    from ask import (_definitions_for, ask, at,  # type: ignore[no-redef]
                     context, definitions_for, file_list, more, rank_lines,
                     spans_for)
    from _mapper.walk import (MAX_FILES, SKIP_DIRS, _PARSE_CACHE_FILE,
                              _SECRET_SHAPES, _cached, _config, _fingerprint,
                              _ignored, _ignores, _lines_matching,
                              _load_parse_cache, _looks_like_suite, _manifest,
                              _product_roots, _save_parse_cache, _slurp, _walk,
                              content_hash, content_pairs, content_root,
                              fingerprint, redact)
    from _mapper.declare import (DECLARATIONS, STEP_DECORATORS, TS_END_BY_EXT,
                                 TS_LANG_BY_EXT,
                                 _DECLARES, _PER_FILE_CAP, _TS_PARSERS,
                                 _declared_names, _line_for_name,
                                 _read_for_declarations, _regex_declared_names,
                                 _step_texts, _tree_sitter, _ts_symbols,
                                 declarations_in, find_text,
                                 index_declarations, index_lines, record_span,
                                 spans_index)
    from _mapper.render import (_PRODUCT_SIDE, _TEST_SIDE, _as_dict, _as_list,
                                _cap_sections, brief, changed_since, ctags,
                                digest, for_audience, meaning_tail, pointer)
    from _mapper.build import _layer_line, build

__version__ = state.__version__


# The names that live in `_mapper.state` and are read and written through this
# module. Deliberately not imported into this namespace: an imported name would
# sit in the module dict, ordinary attribute lookup would find it there, and
# `__getattr__` (which Python consults only when that lookup fails) would never
# run, so an assignment would go nowhere the package can see.
_STATE_NAMES = frozenset((
    "DEFINITIONS", "SPANS", "INDEXED", "LINES", "TRUNCATED", "CACHE_SCHEMA",
    "HASH_COUNT", "HASHES_MOVED", "PARSE_COUNT", "POINTER_MAX", "_FILE_CACHE",
    "_HASH_CACHE", "_IGNORE_CACHE", "_PARSE_CACHE", "_WALK_CACHE",
))


# The four names the command line owns. `cli.py` is the layer above this one:
# it imports the facade's world (build, render, ask, mcp, lsp, hooks, specs)
# and nothing imports it back except the console script. Importing it here
# would put `mapper` above `cli` and `cli` above `mapper` at once, which is
# what every one of the package's eight import cycles was made of.
#
# They are still reachable as `mapper.main` and friends, because the README
# documents them as this package's library API and a distribution's launcher
# script imports `main` from here. The import happens on first access, by
# which time this module has finished loading and there is no cycle to dodge.
_CLI_NAMES = frozenset(("init_manifest", "install_hook", "main", "propose_docs"))


def _cli():
    """`where_are_we.cli`, imported on first use."""
    try:
        from . import cli
    except ImportError:  # run as a plain file, with no package around it
        import cli  # type: ignore[no-redef]
    return cli


# What `from where_are_we.mapper import *` exports. Written out because the
# eleven shared names below are not in this module's dict: they are answered
# by the attribute hook, and a star import that goes by the dict alone would
# skip them, so `mapper.DEFINITIONS` worked and
# `from where_are_we.mapper import *; DEFINITIONS` raised NameError. Two
# documented ways of reaching the same public name disagreeing is worse than
# either being unavailable. With this list, `import *` asks for each name by
# attribute, and the hook answers.
#
# What it cannot fix is `inspect.getattr_static(mapper, "DEFINITIONS")`, which
# is defined as the lookup that skips `__getattr__`, so it still raises
# AttributeError. Anything reading these names statically (a type checker, a
# static analyser) should read them from `where_are_we._mapper.state`, where
# they are ordinary module-level names. That is the price of assignment
# reaching the counter the package increments, which is what
# `tests/golden/check.py` measures a build with.
#
# The command line's four names are deliberately absent: importing this module
# must not import the layer above it, and a star import that pulled in the MCP
# server and the language server would do exactly that.
__all__ = [
    "DECLARATIONS", "DEFINITIONS", "INDEXED", "LINES", "MAX_FILES",
    "SKIP_DIRS", "SPANS", "STEP_DECORATORS", "TRUNCATED", "TS_LANG_BY_EXT",
    "CACHE_SCHEMA", "HASHES_MOVED", "HASH_COUNT", "PARSE_COUNT",
    "POINTER_MAX", "_FILE_CACHE", "_HASH_CACHE", "_IGNORE_CACHE",
    "_PARSE_CACHE", "_WALK_CACHE", "ask", "at", "brief", "build",
    "changed_since", "content_hash", "content_pairs", "content_root",
    "context", "ctags", "declarations_in", "definitions_for", "digest",
    "file_list", "find_text", "fingerprint", "for_audience",
    "index_declarations", "index_lines", "meaning_tail", "more", "pointer",
    "rank_lines", "record_span", "redact", "spans_for", "spans_index",
]


class _Facade(types.ModuleType):
    """This module, with `_mapper.state` readable and writable through it."""

    def __getattr__(self, name):
        if name in _STATE_NAMES:
            return getattr(state, name)
        if name in _CLI_NAMES:
            return getattr(_cli(), name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _STATE_NAMES:
            setattr(state, name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self):
        return sorted(set(super().__dir__()) | _STATE_NAMES | _CLI_NAMES)


sys.modules[__name__].__class__ = _Facade


if __name__ == "__main__":
    # `python -m where_are_we.mapper` and `python src/where_are_we/mapper.py`
    # both still run the tool. The command line itself lives one module over.
    sys.exit(_cli().main())
