"""Rewrites `tests/golden/expected/` from scratch, and with `--maps` the
pinned fixture maps in `tests/golden/maps/` as well.

Run after a deliberate change to what `mapper.py` produces: a refactor that
is meant to leave the output alone (verify with `check.py` that it does), or
one of the two intended behaviour changes later in this plan (verify with
`check.py` that only the expected rows moved). This script does not judge
whether a change was intended; it only records the current output as golden.

`--maps` is separate because the two golden sets answer different questions.
`expected/` pins what `ask()` replies; `maps/` pins the three map files the
build writes, which is what a refactor of the mapper has to leave alone. A
refactor should move neither, so the flag is off by default: you have to say
that moving the maps is what you meant.

Run: `uv run --python 3.12 --with-editable . python tests/golden/regen.py`
"""

import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from where_are_we import mapper  # noqa: E402
import build_fixtures  # noqa: E402

HERE = pathlib.Path(__file__).parent

# Fixed, and the same path `check.py` builds its golden check under: `mkdtemp`'s
# random suffix ends up inside `## Defined here`'s absolute paths, and
# `ask()`'s BM25 ranking tokenises a section's whole text, paths included, so
# those random letters used to change a section's token count by a few and
# occasionally flip a near-tied ranking (`suite--pay_step--12000`, one run in
# three). A fixed root here has to be this same fixed root, or the case this
# script writes as golden is not the case `check.py` reproduces.
GOLDEN_ROOT = "/tmp/wawe-golden"


def _cases():
    for line in (HERE / "cases.txt").read_text().splitlines():
        fixture, words, limit = line.split("\t")
        yield fixture, words, int(limit)


def _write_maps(outs: dict) -> int:
    """Pin each fixture's three map files under `tests/golden/maps/<fixture>/`."""
    maps_dir = HERE / "maps"
    written = 0
    for fixture, out_dir in sorted(outs.items()):
        target = maps_dir / fixture
        target.mkdir(parents=True, exist_ok=True)
        for filename in build_fixtures.MAP_FILES:
            text = build_fixtures.normalised_map(out_dir, filename, GOLDEN_ROOT)
            (target / filename).write_text(text, encoding="utf-8")
            written += 1
    return written


def main() -> int:
    maps = "--maps" in sys.argv[1:]
    expected_dir = HERE / "expected"
    expected_dir.mkdir(exist_ok=True)
    written = 0
    shutil.rmtree(GOLDEN_ROOT, ignore_errors=True)
    os.makedirs(GOLDEN_ROOT, exist_ok=True)
    outs = build_fixtures.build_all(GOLDEN_ROOT)
    for fixture, words, limit in _cases():
        got = mapper.ask(os.path.join(outs[fixture], "framework_map.md"), words, limit)
        # `## Defined here` rows carry the absolute path a name was
        # declared at, so a case built from a defined-name match carries
        # this run's fixed root; `<root>` is the same marker `check.py`
        # substitutes back in before comparing.
        got = got.replace(GOLDEN_ROOT, "<root>")
        slug = words.replace(" ", "_")
        path = expected_dir / f"{fixture}--{slug}--{limit}.txt"
        path.write_text(got, encoding="utf-8")
        written += 1
    print(f"wrote {written} expected files to {expected_dir}")
    if maps:
        print(f"wrote {_write_maps(outs)} map files to {HERE / 'maps'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
