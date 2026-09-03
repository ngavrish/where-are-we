# ask rows and brief cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ask` answers end on whole rows and say what they left out, rows under one directory are printed under it once, and `--max-lines` caps the brief per section instead of chopping it at a line.

**Architecture:** All three are rendering changes in `src/where_are_we/mapper.py`: `ask()` (the answer to a question over the map), a new `_group_dirs()` helper applied to its rows, and a new `_cap_sections()` used where `--max-lines` is applied to the brief. The on-disk map, `find`, `defines` and the MCP budgets do not change.

**Tech Stack:** Python 3.10+, stdlib only. Verification scripts (not pytest files) run with `uv run --python 3.12 --with numpy python <script>`; the existing `tests/` suite is run once per task with `uv run --python 3.12 --with pytest --with numpy python -m pytest tests/ -q` and never edited.

**Spec:** `/Users/boberit/work/agentic-v-model/docs/superpowers/specs/2026-09-03-context-per-turn-design.md` (sections M1–M3)

## Global Constraints

- Rendering only: nothing that writes `framework_map.md`/`.json` changes.
- The MCP `_ANSWER_BUDGET` stays 12000: with whole rows it is a ceiling, not a target.
- No test files are written or edited (operator's standing order of 2026-08-18, enforced by a hook on `tests/test*`). Each task's checks live in a verification script under `.superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/` — real text in, assertions on what comes out, no mocks — written first, run to see it fail, run again to see it pass. Its output goes in the report verbatim. The existing `tests/` suite must still pass and is never touched.
- Work on branch `ask-rows`; bump the version to 0.12.0 and add a CHANGELOG entry in the last task.

---

### Task 1: `ask` cuts on rows and counts what it left out (M1)

**Files:**
- Modify: `src/where_are_we/mapper.py` — `ask()`, the loop beginning `for hits, h, b in scored:`
- Verify: `.superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-ask.py` (new, not committed)

**Interfaces:**
- Produces: `ask(map_path, words, limit)` unchanged signature. Answer rows are never cut mid-line; a section that did not fit ends with `… N more matching rows; M rows in this section do not mention these words`.

- [ ] **Step 1: Write the failing checks**

```python
"""ask() over a map written for the purpose: whole rows, and an honest tail."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from where_are_we import mapper  # noqa: E402


def _map(tmp_path, rows_with, rows_without):
    body = ["# Framework map", "", "## Step modules and what they declare", ""]
    body += [f"- `steps/pay_{i}.py`: pays the invoice {i}" for i in range(rows_with)]
    body += [f"- `steps/other_{i}.py`: something else {i}" for i in range(rows_without)]
    path = os.path.join(str(tmp_path), "framework_map.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body) + "\n")
    return path


def _rows(out):
    """The answer's rows: top-level or, after directory grouping, indented under
    a `dir/` line — that line itself is not a row."""
    return [l for l in out.splitlines()
            if l.lstrip().startswith("- `") and not l.rstrip().endswith("/`")]


def test_ask_never_cuts_a_row_in_half(tmp_path):
    path = _map(tmp_path, rows_with=40, rows_without=0)
    out = mapper.ask(path, "invoice", limit=400)
    assert _rows(out)
    for line in _rows(out):
        assert line.endswith(tuple(f"invoice {i}" for i in range(40))), line


def test_ask_says_how_many_matching_rows_did_not_fit(tmp_path):
    path = _map(tmp_path, rows_with=40, rows_without=0)
    out = mapper.ask(path, "invoice", limit=400)
    shown = len(_rows(out))
    assert 0 < shown < 40
    assert f"… {40 - shown} more matching rows" in out


def test_ask_says_how_many_rows_did_not_match(tmp_path):
    path = _map(tmp_path, rows_with=2, rows_without=7)
    out = mapper.ask(path, "invoice", limit=4000)
    assert "7 rows in this section do not mention these words" in out
    assert "more matching rows" not in out


def test_ask_section_that_fits_has_no_tail(tmp_path):
    path = _map(tmp_path, rows_with=3, rows_without=0)
    out = mapper.ask(path, "invoice", limit=4000)
    assert "…" not in out


def test_ask_never_exceeds_its_limit(tmp_path):
    body = ["# m", "", "## " + "H" * 3000, "", "- `steps/a.py`: invoice " + "x" * 5000,
            "- `steps/b.py`: invoice small"]
    path = os.path.join(str(tmp_path), "framework_map.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body) + "\n")
    for limit in (0, 50, 100, 1500):
        out = mapper.ask(path, "invoice", limit=limit)
        assert len(out) <= max(limit, 0), (limit, len(out))
    small = _map(tmp_path, rows_with=40, rows_without=5)
    out = mapper.ask(small, "invoice", limit=1500)
    assert len(out) <= 1500, len(out)
```

The script is a plain program, not a pytest module: the same functions as above, with `tmp_path` replaced by `pathlib.Path(tempfile.mkdtemp())` created inside a `__main__` block that calls each function in turn and prints `PASS <name>` or `FAIL <name>: <exception>` — never stopping at the first failure — and exits 1 if any failed. Keep the function bodies exactly as written here so the report's output is readable against the plan.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --python 3.12 --with numpy python .superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-ask.py`
Expected: `test_ask_never_cuts_a_row_in_half` and the two "says how many" checks print FAIL (a row is sliced; no tail text exists). The last one may already pass.

- [ ] **Step 3: Rewrite the loop in `ask()`**

Replace from `for hits, h, b in scored:` to the `return` with:

```python
    seen = 0
    for hits, h, b in scored:
        # Whole rows or nothing. Slicing the section at `room` characters left
        # the last row of every answer cut mid-word, and nothing said how much
        # of the section had not been shown — the reader took the fragment
        # for the whole.
        matching, unmatched = [], 0
        for line in b:
            if not line.strip():
                continue
            low = line.lower()
            if any(t in low for t in terms) or line.startswith(("**", "- **")):
                matching.append(line)
            else:
                unmatched += 1
        # `limit` is a ceiling, not a target. The tail line is paid for up
        # front, the head is included only if it fits, and no row is forced
        # in: a first row longer than the room is a dropped row, not an
        # exception. Measured at review: a 3 KB head with limit=50 came back
        # 68 times over budget when the head and first row were forced.
        budget = room - _TAIL_RESERVE
        if budget <= len(h):
            break
        seen += 1
        kept, used, dropped = [h], len(h), 0
        for line in _group_dirs(matching):
            if used + len(line) + 1 > budget:
                dropped += 1
                continue
            kept.append(line)
            used += len(line) + 1
        tail = []
        if dropped:
            tail.append(f"… {dropped} more matching rows")
        if unmatched:
            tail.append(f"{unmatched} rows in this section do not mention these words")
        if tail:
            kept.append("; ".join(tail) if dropped else "… " + tail[0])
        if len(kept) == 1:
            continue
        chunk = "\n".join(kept)
        out.append(chunk)
        room -= len(chunk) + 2
    if seen < len(scored):
        # Only when a matching section really went unshown, and only if the
        # note itself fits: a note that says "more" when there is no more, or
        # that pushes the answer past its limit, is the defect this guards.
        note = "… more sections match; ask for something narrower"
        if len(note) + 2 <= room:
            out.append(note)
    return "\n\n".join(out)
```

Above `ask()`, one constant for the reserve:

```python
# Room kept back for a section's tail line ("… 37 more matching rows; 210 rows
# in this section do not mention these words") so the tail never pushes an
# answer past its limit. Longer than any tail the two counts can produce.
_TAIL_RESERVE = 96
```

For this task, define `_group_dirs` as the identity so the tests here pass on their own; Task 2 gives it its behaviour:

```python
def _group_dirs(rows: list) -> list:
    return list(rows)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --python 3.12 --with numpy python .superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-ask.py` then `uv run --python 3.12 --with pytest --with numpy python -m pytest tests/ -q`
Expected: every check prints PASS; the existing suite still passes (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/where_are_we/mapper.py
git commit -m "ask: whole rows, and a tail that says what was left out"
```

---

### Task 2: Rows under one directory are printed under it once (M2)

**Files:**
- Modify: `src/where_are_we/mapper.py` — `_group_dirs`
- Verify: `.superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-ask.py`

**Interfaces:**
- Produces: `_group_dirs(rows: list[str]) -> list[str]`. Two or more consecutive rows of the shape ``- `dir/file`…`` sharing `dir` become ``- `dir/` `` followed by ``  - `file`…`` lines. A lone row, and rows without a slash, are returned as they are.

- [ ] **Step 1: Write the failing checks**

Append to `.superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-ask.py` (and add the new functions to its `__main__` list):

```python
def test_group_dirs_folds_consecutive_rows_under_their_directory():
    rows = ["- `features/checkout/payment.feature`: 12 scenarios",
            "- `features/checkout/refund.feature`: 4 scenarios",
            "- `features/login.feature`: 2 scenarios"]
    assert mapper._group_dirs(rows) == [
        "- `features/checkout/`",
        "  - `payment.feature`: 12 scenarios",
        "  - `refund.feature`: 4 scenarios",
        "- `features/login.feature`: 2 scenarios",
    ]


def test_group_dirs_leaves_a_lone_row_and_a_bare_name_alone():
    rows = ["- `steps/a.py`: x", "- `pages/b.py`: y", "- `click_pay`: z", "**bold**"]
    assert mapper._group_dirs(rows) == rows


def test_ask_answer_groups_rows_by_directory(tmp_path):
    body = ["# m", "", "## Feature files", "",
            "- `features/checkout/payment.feature`: invoice paid",
            "- `features/checkout/refund.feature`: invoice refunded"]
    path = os.path.join(str(tmp_path), "framework_map.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body) + "\n")
    out = mapper.ask(path, "invoice", limit=4000)
    assert "- `features/checkout/`" in out
    assert "  - `payment.feature`: invoice paid" in out
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --python 3.12 --with numpy python .superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-ask.py`
Expected: the two `group_dirs` checks and `test_ask_answer_groups_rows_by_directory` print FAIL (identity returns the rows unchanged); the Task 1 checks still PASS.

- [ ] **Step 3: Implement**

```python
_ROW_PATH = re.compile(r"^- `([^`]*/)([^`/]+)`(.*)$")


def _group_dirs(rows: list) -> list:
    """Consecutive rows under one directory, printed under it once.

    `features/checkout/payment.feature`, `features/checkout/refund.feature`
    is the directory twice; an answer that lists forty rows of one package
    spends a third of its room on the same prefix. Rendering only — the map on
    disk keeps full paths, and so does everything that parses it.
    """
    out, i = [], 0
    while i < len(rows):
        m = _ROW_PATH.match(rows[i])
        if not m:
            out.append(rows[i])
            i += 1
            continue
        d = m.group(1)
        run = [m]
        j = i + 1
        while j < len(rows):
            n = _ROW_PATH.match(rows[j])
            if not n or n.group(1) != d:
                break
            run.append(n)
            j += 1
        if len(run) < 2:
            out.append(rows[i])
            i += 1
            continue
        out.append(f"- `{d}`")
        out += [f"  - `{r.group(2)}`{r.group(3)}" for r in run]
        i = j
    return out
```

- [ ] **Step 4: Bound the `## Defined here` block too**

Review of Task 1 found the one part of an answer the loop does not cover: the
definitions block before the loop is appended whole (30 short definitions
returned 1186 characters at every limit from 50 to 1000), and the early
return when no section matches ignores `limit` entirely. Add above `ask()`:

```python
def _defined_here(exact: list, room: int) -> str:
    """The definitions block, whole lines up to `room`, with a count of what
    did not fit. Empty when not even one definition fits."""
    head = "## Defined here\n"
    budget = room - 32  # the "… N more definitions" line, paid up front
    if budget <= len(head):
        return ""  # not even the head fits: nothing, not a head with a count
    kept, used, dropped = [head], len(head), 0
    for line in exact:
        if used + len(line) + 1 > budget:
            dropped += 1
            continue
        kept.append(line)
        used += len(line) + 1
    if dropped:
        kept.append(f"… {dropped} more definitions")
    return "\n".join(kept) if len(kept) > 1 else ""
```

In `ask()`, the early path `if not scored:` currently does
`return "## Defined here\n\n" + "\n".join(exact)` when `exact` is non-empty;
change it to `return _defined_here(exact, limit)` (fall through to the
"no match" text when that returns ""). In the main path replace

```python
    exact = _definitions_for(map_path, terms)
    if exact:
        out.append("## Defined here\n\n" + "\n".join(exact))
        room -= sum(len(x) for x in exact)
```

with

```python
    exact = _definitions_for(map_path, terms)
    if exact:
        block = _defined_here(exact, room)
        if block:
            out.append(block)
            room -= len(block) + 2
```

Add a check to the verification script. Read `_definitions_for` first to learn
which map lines it treats as definitions of a name (it scans the map for a
declared-name row shape); write a map with 30 such lines for the name
`invoice` plus one ordinary section that mentions `invoice`, then:

```python
def test_ask_defined_here_respects_limit(tmp_path):
    path = ...  # the map described above
    for limit in (0, 10, 30, 50, 200, 1000):
        out = mapper.ask(path, "invoice", limit=limit)
        assert len(out) <= limit, (limit, len(out))
    out = mapper.ask(path, "invoice", limit=4000)
    assert "## Defined here" in out and "more definitions" not in out
```

Run the script: this check FAILs before the change (1186 > 50) and PASSes after.

- [ ] **Step 5: Run the checks**

Run: the task's verification script, then `uv run --python 3.12 --with pytest --with numpy python -m pytest tests/ -q`
Expected: every check prints PASS; the existing suite still passes (8 passed).

- [ ] **Step 6: Commit**

```bash
git add src/where_are_we/mapper.py
git commit -m "ask: rows under one directory are printed under it once; Defined here is bounded"
```

---

### Task 3: `--max-lines` caps the brief per section (M3)

**Files:**
- Modify: `src/where_are_we/mapper.py` — the `if args.max_lines and text.count("\n") > args.max_lines:` block in `main()`, new `_cap_sections`
- Verify: `.superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-brief-cap.py` (new, not committed)

**Interfaces:**
- Produces: `_cap_sections(text: str, max_lines: int) -> str`. Every `## ` section keeps its head and its first rows up to an equal share of `max_lines`, then `… N more in framework_map.md`. Text already within the cap is returned unchanged.

- [ ] **Step 1: Write the failing checks**

```python
"""--max-lines keeps every section and cuts inside them."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from where_are_we import mapper  # noqa: E402


def _brief(sections, rows_each):
    lines = ["# Framework map (brief)", "", "intro line", ""]
    for s in range(sections):
        lines += [f"## Section {s}", ""]
        lines += [f"- row {s}.{r}" for r in range(rows_each)]
        lines += [""]
    return "\n".join(lines)


def test_cap_keeps_every_section_head():
    out = mapper._cap_sections(_brief(3, 50), 30)
    assert all(f"## Section {s}" in out for s in range(3))
    assert out.count("\n") <= 30 + 3  # a tail line per section


def test_cap_says_how_many_rows_it_dropped():
    out = mapper._cap_sections(_brief(3, 50), 30)
    for s in range(3):
        shown = sum(1 for l in out.splitlines() if l.startswith(f"- row {s}."))
        assert f"… {50 - shown} more in framework_map.md" in out


def test_cap_leaves_a_short_brief_alone():
    text = _brief(2, 3)
    assert mapper._cap_sections(text, 200) == text


def test_cap_forces_no_rows_when_the_cap_cannot_hold_them():
    out = mapper._cap_sections(_brief(6, 10), 12)
    assert all(f"## Section {s}" in out for s in range(6))
    assert not any(l.startswith("- row") for l in out.splitlines())
    assert out.count("\n") <= 4 + 3 * 6  # preamble, then head + tail + blank per section


def test_cap_bounds_the_preamble():
    lines = ["# Framework map (brief)", ""] + [f"intro {i}" for i in range(200)] + [""]
    lines += ["## Only section", ""] + [f"- row 0.{r}" for r in range(5)] + [""]
    out = mapper._cap_sections("\n".join(lines), 40)
    assert out.count("\n") <= 40
    assert "## Only section" in out and "- row 0.4" in out
```

The script is a plain program, not a pytest module: the same functions as above, with `tmp_path` replaced by `pathlib.Path(tempfile.mkdtemp())` created inside a `__main__` block that calls each function in turn and prints `PASS <name>` or `FAIL <name>: <exception>` — never stopping at the first failure — and exits 1 if any failed. Keep the function bodies exactly as written here so the report's output is readable against the plan.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --python 3.12 --with numpy python .superpowers/sdd/2026-09-03-ask-rows-and-brief-cap/verify-brief-cap.py`
Expected: every check FAILs with `AttributeError: module ... has no attribute '_cap_sections'`.

- [ ] **Step 3: Implement**

```python
def _cap_sections(text: str, max_lines: int) -> str:
    """The brief cut inside its sections rather than at a line number.

    `--max-lines 200` used to keep the first 200 lines and drop the rest, so
    the sections at the end — the overlaps, the dead phrases, the debts — were
    the ones that never reached the prompt. Now every section is present and
    none is complete past its share; the tail says where the rest is.
    """
    if max_lines <= 0 or text.count("\n") <= max_lines:
        return text
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not heads:
        return "\n".join(lines[:max_lines])
    # The preamble is the brief's own few lines; a long one is cut too, or it
    # alone could spend the cap (measured at review: a 200-line preamble under
    # --max-lines 10 came back 206 lines). Every head stays whatever the cap —
    # a section that is absent cannot be asked about — so a cap too small to
    # hold the heads is exceeded by the heads and their tails, and by nothing
    # else: no row is forced in.
    preamble = lines[:heads[0]][:max(4, max_lines // 4)]
    share = max(0, (max_lines - len(preamble) - 3 * len(heads)) // len(heads))
    out = list(preamble)
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = [l for l in lines[start + 1:end] if l.strip()]
        out.append(lines[start])
        out += body[:share]
        if len(body) > share:
            out.append(f"… {len(body) - share} more in framework_map.md")
        out.append("")
    return "\n".join(out)
```

Then in `main()` replace the `--max-lines` block:

```python
    if args.max_lines and text.count("\n") > args.max_lines:
        text = _cap_sections(text, args.max_lines)
```

- [ ] **Step 4: Run the tests**

Run: the task's verification script, then `uv run --python 3.12 --with pytest --with numpy python -m pytest tests/ -q`
Expected: every check prints PASS; the existing suite still passes (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/where_are_we/mapper.py
git commit -m "--max-lines caps the brief per section, every section present"
```

---

### Task 4: Version, changelog, README

**Files:**
- Modify: `pyproject.toml` (version), `src/where_are_we/__init__.py` (`__version__`), `CHANGELOG.md`, `README.md` (the `--ask` paragraph and the `--max-lines` mention)

- [ ] **Step 1: Bump to 0.12.0 in both places**

```bash
grep -n 'version' pyproject.toml src/where_are_we/__init__.py
```

Edit both to `0.12.0`.

- [ ] **Step 2: CHANGELOG entry at the top**

```markdown
## 0.12.0

Answers end on whole rows and say what they left out.

- `--ask` and the MCP `ask` no longer slice a section at a character count:
  rows are whole, and a section that did not fit ends with how many matching
  rows were dropped and how many rows did not match at all.
- In an answer, consecutive rows under one directory are printed under it
  once. Rendering only; the map on disk keeps full paths.
- `--max-lines` caps the brief per section — every section keeps its head and
  its first rows, then says how many more are in `framework_map.md` — instead
  of dropping whatever came after line N.
```

- [ ] **Step 3: README**

Where the README describes `--ask` ("That prints only the sections that mention those words"), change to: "That prints only the rows that mention those words, whole, and says how much of each section it left out." Where `--max-lines` is mentioned, say it caps per section.

- [ ] **Step 4: Full test run and commit**

```bash
uv run --python 3.12 --with pytest --with numpy python -m pytest tests/ -q
git add pyproject.toml src/where_are_we/__init__.py CHANGELOG.md README.md
git commit -m "0.12.0: whole rows in answers, per-section brief cap"
git log --oneline main..ask-rows
```

Expected: all tests pass; four commits on `ask-rows`. Do not push or release: the operator publishes.
