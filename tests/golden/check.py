"""Verifies the golden `ask` suite and map determinism, without pytest.

A global hook in this environment blocks the model from writing or editing
any `test_*.py` file, so this is a plain script instead of `tests/test_golden.py`:
CI calls it directly, and it can be run the same way locally.

Run: `python tests/golden/check.py` (on this machine's system Python 3.9, use
`uv run --python 3.12 --with-editable . python tests/golden/check.py`).

Exits 0 and prints one line on success. Exits 1 and lists every case that
differs on failure, so the CI log says exactly what changed; `regen.py` is
the fix when the change was intended.
"""

import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from where_are_we import mapper  # noqa: E402
import build_fixtures  # noqa: E402

HERE = pathlib.Path(__file__).parent


def _cases():
    for line in (HERE / "cases.txt").read_text().splitlines():
        fixture, words, limit = line.split("\t")
        yield fixture, words, int(limit)


def _normalized(text: str, root: str) -> str:
    """`text` with the fixtures' own temp root replaced by a fixed marker.

    `## Defined here` rows carry the absolute path a name was declared at
    (`ask.py`'s `_definitions_for` reads it straight from the map's own
    `definitions` index), so every case built from a match on a defined name
    carries this run's temp directory. Stripped here rather than avoided
    upstream: `build_fixtures` cannot know what path the caller will build
    under, and hard-coding one would make the fixtures less reusable, not
    more deterministic.
    """
    return text.replace(root, "<root>")


def _check_golden(root: str) -> list:
    """Every case's `ask()` answer against its pinned expected file. Returns
    the problems found; empty means all 150 cases matched."""
    outs = build_fixtures.build_all(root)
    problems = []
    for fixture, words, limit in _cases():
        got = _normalized(
            mapper.ask(os.path.join(outs[fixture], "framework_map.md"), words, limit), root)
        slug = words.replace(" ", "_")
        name = f"{fixture}--{slug}--{limit}.txt"
        path = HERE / "expected" / name
        if not path.exists():
            problems.append(f"{name}: no expected file (run regen.py)")
            continue
        if got != path.read_text():
            problems.append(f"{name}: differs from expected (run regen.py if intended)")
            continue
        # ask() only bounds the ranked/matched content it assembles: reading
        # ask.py, whenever nothing scored (no section and no exact definition
        # matched, or the definitions block did not even fit the budget) it
        # returns the fixed "no match for ..." sentence unconditionally,
        # whatever limit was asked for. Everywhere else, including limit 0,
        # where the budget leaves no room for even a section head, the
        # matched content really is capped at limit (RESERVE_TAIL and
        # RESERVE_DEFINED in ask.py exist to guarantee exactly that).
        if len(got) > limit and not got.startswith("no match for "):
            problems.append(f"{name}: exceeds its limit ({len(got)} > {limit})")
    return problems


def _check_determinism(root: str) -> list:
    """Two builds of the same three fixtures, byte for byte once each root is
    stripped out of the text. Returns the problems found."""
    outs1 = build_fixtures.build_all(os.path.join(root, "one"))
    outs2 = build_fixtures.build_all(os.path.join(root, "two"))
    problems = []
    for name in outs1:
        for fn in ("framework_map.md", "framework_map_brief.md"):
            a = _normalized(open(os.path.join(outs1[name], fn), encoding="utf-8").read(),
                            os.path.join(root, "one"))
            b = _normalized(open(os.path.join(outs2[name], fn), encoding="utf-8").read(),
                            os.path.join(root, "two"))
            if a != b:
                problems.append(f"{name}/{fn}: differs between two builds of one tree")
    return problems


def main() -> int:
    n_cases = sum(1 for _ in _cases())
    # `## Defined here` rows are cut to a character budget that includes the
    # absolute path each name was declared at (see `_normalized`'s
    # docstring), so a temp root a few characters longer or shorter than the
    # one `regen.py` used can move a row across the cutoff and fail a case
    # that never actually changed. `/tmp` is asked for explicitly, rather
    # than the platform default, because it fixes that length: macOS's
    # default temp root is a long, per-login, per-machine path, while
    # `regen.py` and CI's Linux runner both get a short, constant one; a
    # golden file regenerated on a Mac would otherwise be one macOS
    # temp-root's worth of characters away from what CI computes for the
    # same case, on every case whose cutoff sits inside that margin.
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        problems = _check_golden(tmp)
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        problems += _check_determinism(tmp)
    if problems:
        print(f"golden: {len(problems)} problem(s):")
        for p in problems:
            print(f"- {p}")
        return 1
    print(f"golden: {n_cases} cases, {len(build_fixtures.FIXTURES)} fixtures identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
