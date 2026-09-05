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
from typing import Protocol

from . import code, data, infra, tests

__all__ = ["Ctx", "Read", "code", "data", "infra", "tests"]


class Read(Protocol):
    """`build()`'s own reader, as an extractor sees it.

    Spelled out rather than left as `Callable[..., str]`, which said nothing
    about what an extractor may pass. It is not `Callable[[str, int], str]`
    either: every caller passes the path alone and takes the default limit,
    and that type would make each of those calls an error for a type checker
    while describing the same function.
    """

    def __call__(self, rel: str, limit: int = ...) -> str: ...


@dataclass(frozen=True)
class Ctx:
    """What an extractor is allowed to know.

    `read` is `build()`'s own reader: a path relative to `repo`, read through
    the file cache, so a file two topics both want costs one read.

    `code_files` is a tuple, and is turned into one here rather than trusted
    to arrive as one. `frozen=True` froze the three bindings and nothing else:
    the one field an extractor actually iterates was a list shared with the
    rest of `build()`, so any of the twenty could have appended to what the
    other nineteen were about to read, and the hashability that frozen
    dataclasses otherwise buy was lost to the same list.
    """

    repo: str
    code_files: tuple[str, ...]
    read: Read

    def __post_init__(self) -> None:
        object.__setattr__(self, "code_files", tuple(self.code_files))
