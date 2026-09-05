"""Rewrites `tests/golden/expected/` from scratch.

Run after a deliberate change to what `mapper.py` produces: a refactor that
is meant to leave the output alone (verify with `check.py` that it does), or
one of the two intended behaviour changes later in this plan (verify with
`check.py` that only the expected rows moved). This script does not judge
whether a change was intended; it only records the current output as golden.

Run: `uv run --python 3.12 --with-editable . python tests/golden/regen.py`
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


def main() -> int:
    expected_dir = HERE / "expected"
    expected_dir.mkdir(exist_ok=True)
    written = 0
    # `/tmp`, not the platform default: `## Defined here` rows are cut to a
    # character budget that includes the absolute path each name was
    # declared at, so this run's temp root has to be the same length as
    # `check.py`'s for a row to land on the same side of that cutoff.
    # macOS's default temp root is a long, per-login path; CI's Linux runner
    # (and `/tmp` here) gets a short, constant one instead.
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        outs = build_fixtures.build_all(tmp)
        for fixture, words, limit in _cases():
            got = mapper.ask(os.path.join(outs[fixture], "framework_map.md"), words, limit)
            # `## Defined here` rows carry the absolute path a name was
            # declared at, so a case built from a defined-name match carries
            # this run's temp directory; `<root>` is the same fixed marker
            # `check.py` substitutes back in before comparing.
            got = got.replace(tmp, "<root>")
            slug = words.replace(" ", "_")
            path = expected_dir / f"{fixture}--{slug}--{limit}.txt"
            path.write_text(got, encoding="utf-8")
            written += 1
    print(f"wrote {written} expected files to {expected_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
