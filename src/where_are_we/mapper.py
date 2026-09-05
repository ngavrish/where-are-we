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
they define is re-exported below, so `from where_are_we import mapper` and
`mapper.anything` keep meaning what they meant.

It stays a module and does not become a package, because it is also run as a
plain script by path (`python src/where_are_we/mapper.py --repo . --out /tmp/m`)
and a directory cannot be. The same two-way import the rest of this project
uses is below: relative when there is a package around it, plain when there is
not.

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
    from .ask import ask
    from ._mapper.walk import (MAX_FILES, SKIP_DIRS, _PARSE_CACHE_FILE,
                               _SECRET_SHAPES, _cached, _config, _fingerprint,
                               _ignored, _ignores, _lines_matching,
                               _load_parse_cache, _looks_like_suite, _manifest,
                               _product_roots, _save_parse_cache, _slurp,
                               _walk, redact)
    from ._mapper.declare import (DECLARATIONS, STEP_DECORATORS,
                                  TS_LANG_BY_EXT, _DECLARES, _PER_FILE_CAP,
                                  _TS_PARSERS, _declared_names, _line_for_name,
                                  _read_for_declarations,
                                  _regex_declared_names, _step_texts,
                                  _tree_sitter, _ts_symbols, declarations_in,
                                  find_text, index_declarations, index_lines)
    from ._mapper.render import (_PRODUCT_SIDE, _TEST_SIDE, _as_dict, _as_list,
                                 _cap_sections, _definitions_for, brief,
                                 changed_since, digest, for_audience,
                                 meaning_tail, pointer)
    from ._mapper.build import _layer_line, build
    from ._mapper.cli import init_manifest, install_hook, main, propose_docs
except ImportError:  # run as a plain file, with no package around it
    from _mapper import state
    from ask import ask
    from _mapper.walk import (MAX_FILES, SKIP_DIRS, _PARSE_CACHE_FILE,
                              _SECRET_SHAPES, _cached, _config, _fingerprint,
                              _ignored, _ignores, _lines_matching,
                              _load_parse_cache, _looks_like_suite, _manifest,
                              _product_roots, _save_parse_cache, _slurp, _walk,
                              redact)
    from _mapper.declare import (DECLARATIONS, STEP_DECORATORS, TS_LANG_BY_EXT,
                                 _DECLARES, _PER_FILE_CAP, _TS_PARSERS,
                                 _declared_names, _line_for_name,
                                 _read_for_declarations, _regex_declared_names,
                                 _step_texts, _tree_sitter, _ts_symbols,
                                 declarations_in, find_text,
                                 index_declarations, index_lines)
    from _mapper.render import (_PRODUCT_SIDE, _TEST_SIDE, _as_dict, _as_list,
                                _cap_sections, _definitions_for, brief,
                                changed_since, digest, for_audience,
                                meaning_tail, pointer)
    from _mapper.build import _layer_line, build
    from _mapper.cli import init_manifest, install_hook, main, propose_docs

__version__ = state.__version__


# The names that live in `_mapper.state` and are read and written through this
# module. Deliberately not imported into this namespace: an imported name would
# sit in the module dict, ordinary attribute lookup would find it there, and
# `__getattr__` (which Python consults only when that lookup fails) would never
# run, so an assignment would go nowhere the package can see.
_STATE_NAMES = frozenset((
    "DEFINITIONS", "INDEXED", "LINES", "TRUNCATED", "CACHE_SCHEMA",
    "PARSE_COUNT", "POINTER_MAX", "_FILE_CACHE", "_IGNORE_CACHE",
    "_PARSE_CACHE", "_WALK_CACHE",
))


class _Facade(types.ModuleType):
    """This module, with `_mapper.state` readable and writable through it."""

    def __getattr__(self, name):
        if name in _STATE_NAMES:
            return getattr(state, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _STATE_NAMES:
            setattr(state, name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self):
        return sorted(set(super().__dir__()) | _STATE_NAMES)


sys.modules[__name__].__class__ = _Facade


if __name__ == "__main__":
    sys.exit(main())
