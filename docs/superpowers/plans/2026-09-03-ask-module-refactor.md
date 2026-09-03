# ask module refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `ask()` and its helpers out of mapper.py into `ask.py`, with one budget loop shared by the three places that fit whole lines into a budget, and no change in behaviour.

**Architecture:** New module `src/where_are_we/ask.py` owns answering a question over the map: `ask()`, `_rank`, `_definitions_for`'s consumer side, `_group_dirs`, `_defined_here`, `fit_lines`, the reserves. `mapper.py` keeps `_cap_sections` (it is about the brief, not answers) but uses `fit_lines`. `mapper.ask` stays importable as a re-export so the CLI, the MCP server and the README examples do not change.

**Tech Stack:** Python 3.10+, stdlib. Verification by golden output: the same questions over the same fixture maps give byte-identical answers before and after.

**Spec:** the SOLID audit in this session; the behaviour spec is `/Users/boberit/work/agentic-v-model/docs/superpowers/specs/2026-09-03-context-per-turn-design.md` (M1–M3), which must keep holding.

## Global Constraints

- No behaviour change: byte-identical output of `ask()` and `_cap_sections()` on the fixtures before and after. The golden files prove it.
- No file under tests/ is written or edited (operator's standing order, enforced by a hook). Checks live under `.superpowers/sdd/2026-09-03-ask-module-refactor/`.
- `mapper.ask`, `mapper._definitions_for`, `mapper.find_text`, `mapper.meaning_tail` keep their names and signatures; mcp.py imports nothing new.
- Work on branch `ask-module`; commit trailer lines:
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01CUuMM2MhtNrGyvDiy7VENv

---

### Task 1: Golden outputs before touching anything

**Files:**
- Create: `.superpowers/sdd/2026-09-03-ask-module-refactor/golden.py` (not committed)

- [ ] **Step 1: Write the golden script**

It builds three fixture maps in a temp dir (reuse the shapes from `docs/superpowers/plans/2026-09-03-ask-rows-and-brief-cap.md`: 40 `steps/pay_i.py` rows plus 5 `other` rows; a 3000-char head plus a 5000-char row plus a small row; `features/checkout/` rows; a `## Build systems` section with a bare `**Tools**` line and two `- **label**: value` rows; a map with 30 definition rows in the shape `_definitions_for` reads — read that function to get it), asks each with `mapper.ask(path, words, limit)` for `words` in ("invoice", "invoice checkout", "nothing") and `limit` in (0, 10, 30, 50, 100, 200, 350, 400, 1500, 4000, 12000), and also runs `mapper._cap_sections(text, n)` for three briefs (3×50 rows; 6×10 rows; 200-line preamble + 1 section) with n in (2, 10, 12, 30, 40, 200). Every result is written under `<out_dir>/<case>.txt`. Usage: `python golden.py <out_dir>`.

- [ ] **Step 2: Record the baseline**

Run: `uv run --python 3.12 --with numpy python .superpowers/sdd/2026-09-03-ask-module-refactor/golden.py .superpowers/sdd/2026-09-03-ask-module-refactor/before`
Expected: files written; `ls | wc -l` reported in the report.

---

### Task 2: `ask.py` with one `fit_lines`

**Files:**
- Create: `src/where_are_we/ask.py`
- Modify: `src/where_are_we/mapper.py` (remove `ask`, `_rank`, `_group_dirs`, `_ROW_PATH`, `_defined_here`, `_TAIL_RESERVE`; re-export `ask`; `_cap_sections` uses `fit_lines`)

**Interfaces:**
- `fit_lines(lines: list[str], budget: int, cost=len, sep: int = 1) -> tuple[list[str], int]` — whole lines in order while `used + cost(line) + sep <= budget`; returns kept and the count dropped. Best-fit, not a prefix (a line that does not fit is skipped and later ones may still fit), exactly as the three loops behave today.
- `RESERVE_TAIL = 96`, `RESERVE_DEFINED = 32` — the two reserves, named beside each other with one comment saying what each tail costs.
- `ask(map_path, words, limit=12000) -> str` — same contract.

- [ ] **Step 1: Create `ask.py`**

Move, verbatim in behaviour: `ask`, `_rank`, `_group_dirs` and `_ROW_PATH`, `_defined_here`, the reserves. `ask()` becomes a short pipeline of named steps, each a module function: `_blocks(text)` (split into head/body sections), `_definitions_block(map_path, terms, room)`, `_section_answer(head, body, terms, room) -> tuple[str, bool]` (the chunk and whether it was attempted, for `seen`), `_more_note(room)`. The row filter (bare `**` lines skipped; a row matches iff it mentions a term) lives in `_split_rows(body, terms) -> tuple[list[str], int]`. `_defined_here` and `_section_answer` both call `fit_lines`. Imports from mapper: `_definitions_for` (leave it in mapper.py, it reads the map's declared-name rows and is used by `find`/`defines` too).

- [ ] **Step 2: Wire mapper.py**

At the top of mapper.py, after its own imports, the same try-relative-then-plain import the file already uses for `readmes`, `semantic`, `mcp`: `from .ask import ask, fit_lines` with the plain fallback. Delete the moved definitions. `_cap_sections` keeps its share arithmetic and calls `fit_lines(body, share, cost=lambda _l: 1, sep=0)` for `body[:share]` — same result, one loop. `main()` and `mcp.py` call `mapper.ask` as before (re-exported).

- [ ] **Step 3: Golden check and the suite**

Run: `uv run --python 3.12 --with numpy python .superpowers/sdd/2026-09-03-ask-module-refactor/golden.py .superpowers/sdd/2026-09-03-ask-module-refactor/after && diff -r .superpowers/sdd/2026-09-03-ask-module-refactor/before .superpowers/sdd/2026-09-03-ask-module-refactor/after && echo IDENTICAL`
Expected: `IDENTICAL`. Then `uv run --python 3.12 --with pytest --with numpy python -m pytest tests/ -q` → 8 passed. Then `python3 -c "import ast; ast.parse(open('src/where_are_we/mcp.py').read())"` and a script-mode run `uv run --python 3.12 --with numpy python src/where_are_we/mapper.py --ask invoice --out <the temp dir of one fixture>` to prove the plain-import fallback works.

- [ ] **Step 4: Commit**

```bash
git add src/where_are_we/ask.py src/where_are_we/mapper.py
git commit -m "ask() moves to ask.py: one fit_lines for the three budget loops, no behaviour change"
```

---

### Task 3: CHANGELOG line

- [ ] Add under `## 0.12.0`: "- Internal: answering moved to `where_are_we/ask.py`; `mapper.ask` is a re-export." Run the suite once more; commit `git add CHANGELOG.md; git commit -m "CHANGELOG: ask.py"`.
