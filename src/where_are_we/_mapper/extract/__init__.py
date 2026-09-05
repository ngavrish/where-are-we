"""Topics of the map that are a function of the file list alone.

An extractor is one file, one topic, one `(ctx) -> dict`: it is handed the
repository root, the list of code files and a reader, and hands back the map
sections it owns, keyed the way `build()` and `framework_map.json` name them.
Nothing else reaches it, so nothing else can change what it answers.

`build()` keeps every topic that is not that shape. Most of what it does reads
locals an earlier section filled, or extends a dict a later section extends
again, and moving one of those out would be a rewrite rather than a move.
"""

from dataclasses import dataclass
from typing import Callable

from . import code, data, infra, tests

__all__ = ["Ctx", "code", "data", "infra", "tests"]


@dataclass(frozen=True)
class Ctx:
    """What an extractor is allowed to know.

    `read` is `build()`'s own reader: a path relative to `repo`, read through
    the file cache, so a file two topics both want costs one read.
    """

    repo: str
    code_files: list
    read: Callable[..., str]
