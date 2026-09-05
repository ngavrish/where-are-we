# where-are-we: measurement, incrementality, languages, answers, integrations, split

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every "not measured" row of the README into a measured one, make rebuilds incremental, widen language coverage, make `ask` answer synonyms and "who calls X", wire the map into Cursor/Codex/Gemini, add native GitHub/Linear ticket sources and an LSP mode, split `mapper.py`, and ship a public demo.

**Architecture:** `src/where_are_we/` is a flat package: `mapper.py` (walk + extract + render + CLI, 4,500 lines), `ask.py` (answers over `framework_map.md`), `mcp.py` (stdio JSON-RPC over `ask`), `specs.py` (ticket map), `semantic.py`, `readmes.py`. New modules are added beside them (`measure.py`, `lsp.py`, `hooks.py`); the split of `mapper.py` into a package is the last task and changes no behaviour. Every task ends with tests in `tests/` run by `pytest tests -q` and a README row updated.

**Tech Stack:** Python 3.10+, stdlib only for the core; optional extras `precise` (tree-sitter) and `semantic` (fastembed). pytest. Git worktrees per task.

**Spec:** the improvement list in the conversation of 2026-09-05; the README section "Everything it does, and what it is measured to save" is the contract each task updates.

## Global Constraints

- `schema: where-are-we/1`: sections may be added to `framework_map.json`, never renamed or removed (SCHEMA.md). New sections are documented in SCHEMA.md in the same commit.
- The four MCP tools `ask`, `find`, `defines`, `sections` keep names and meaning. New tools may be added.
- CLI flags keep names and meaning. New flags may be added.
- Deterministic output: same tree, same map, byte for byte. `tests/test_golden.py` (Task 1) must pass on every commit after Task 1.
- No new required dependencies. `dependencies = []` stays.
- Every commit goes to `main` (worktree branches are merged into `main`, never pushed as PRs).
- Every task edits the README row(s) for its feature: the "Measured impact" column gets the number the task's test produced, or the "If not measured, how to" column names the command that now measures it.
- No em dashes in new prose (README, docstrings, CHANGELOG).
- Commit message trailer on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Qt2xWwtUxwkeWyJt5hHgi7
  ```

## Execution order

| Wave | Tasks (parallel within a wave, one worktree each) | Why this order |
|---|---|---|
| A | 1 golden, 2 measure, 3 ask-log, 6 languages, 7 ts/go call graph, 10 agent hooks, 11 spec sources, 12 lsp | Independent files or disjoint regions of `mapper.py` |
| B | 4 diff-in-pointer, 5 incremental, 8 callers, 9 synonyms, 14 demo | 8 needs 7; 9 needs 1 (golden regenerated on purpose); 5 touches the walk, keep it out of wave A's merges |
| C | 13 split, 15 README consolidation | Split last, guarded by 1 and the byte-identity test; README last |

---

### Task 1: Golden `ask` suite and map determinism in CI

**Files:**
- Create: `tests/golden/build_fixtures.py` (builds the fixture trees and maps into a directory)
- Create: `tests/golden/cases.txt` (one case per line: `<fixture>\t<words>\t<limit>`)
- Create: `tests/golden/expected/<fixture>--<slug>--<limit>.txt` (150 files, generated once, committed)
- Create: `tests/test_golden.py`
- Modify: `.github/workflows/ci.yml` (nothing: `pytest tests -q` already runs it)
- Modify: `README.md` row "Deterministic output"

**Interfaces:**
- Produces: `tests/golden/build_fixtures.build_all(root: str) -> dict[str, str]` mapping fixture name to its `--out` directory, and `tests/golden/regen.py` that rewrites `expected/` (used by Task 9 and Task 13 when a change is intended).

- [ ] **Step 1: Write the fixture builder**

Three fixtures, deterministic content (no timestamps, no random):
- `suite`: a behave suite: `features/checkout/pay.feature` (3 scenarios), `features/login.feature` (2), `steps/pay_steps.py` with 40 step functions `step_pay_<i>` each calling `page.click_<i>()`, `steps/login_steps.py` (5 steps), `pages/checkout.py` with class `CheckoutPage` and 40 methods `click_<i>`.
- `code`: a plain repository: `app/api.py` (FastAPI-style routes `/invoice`, `/invoice/{id}`, `/health`), `app/models.py` (two ORM classes `Invoice`, `Customer`), `app/billing.py` (`charge()`, `refund()`), `app/cli.py` (argparse with `send`, `retry`), `Makefile` with `test` and `lint`.
- `poly`: `a.ts` exporting `charge`, `b.ts` calling it, `main.go` with `func Serve()` and `func TestServe`, `migrations/V1__init.sql`.

Each is written under `<root>/<name>/repo`, mapped with `mapper.build` + `mapper.brief` written to `<root>/<name>/out/framework_map.md`, `framework_map_brief.md`, `framework_map.json` (mirror what `main()` writes: read `main()` in `mapper.py` for the three writes and reuse the same functions).

- [ ] **Step 2: Write `cases.txt`**

150 lines. Words: `invoice`, `invoice checkout`, `charge`, `click_7`, `login`, `Serve`, `nothing_here`, `pay step`, `health`, `migration`. Limits: 0, 10, 50, 100, 350, 1500, 12000. Product over the three fixtures, pruned to 150 by taking the first 150 lines of the cartesian product in the order fixtures × words × limits.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_golden.py
import os, sys, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden"))
from where_are_we import mapper
import build_fixtures

HERE = pathlib.Path(__file__).parent / "golden"

def _cases():
    for line in (HERE / "cases.txt").read_text().splitlines():
        fixture, words, limit = line.split("\t")
        yield fixture, words, int(limit)

def test_ask_matches_golden(tmp_path):
    outs = build_fixtures.build_all(str(tmp_path))
    missing = []
    for fixture, words, limit in _cases():
        got = mapper.ask(os.path.join(outs[fixture], "framework_map.md"), words, limit)
        slug = words.replace(" ", "_")
        path = HERE / "expected" / f"{fixture}--{slug}--{limit}.txt"
        if not path.exists():
            missing.append(path.name); continue
        assert got == path.read_text(), f"{path.name} differs; if intended run tests/golden/regen.py"
        assert len(got) <= max(limit, 0) or limit == 0, f"{path.name} exceeds its limit"
    assert not missing, missing

def test_map_is_deterministic(tmp_path):
    outs = build_fixtures.build_all(str(tmp_path / "one"))
    outs2 = build_fixtures.build_all(str(tmp_path / "two"))
    for name in outs:
        for fn in ("framework_map.md", "framework_map_brief.md"):
            a = open(os.path.join(outs[name], fn)).read().replace(str(tmp_path / "one"), "")
            b = open(os.path.join(outs2[name], fn)).read().replace(str(tmp_path / "two"), "")
            assert a == b, f"{name}/{fn} differs between two builds of one tree"
```

Note on `limit == 0`: read `ask()` to see what it returns at 0 (the existing golden in the 0.12 plan used 0 as a case) and adjust the length assertion so it states the real contract.

- [ ] **Step 4: Run to verify it fails** (no expected files): `pytest tests/test_golden.py -q` → FAIL on `missing`.

- [ ] **Step 5: Write `tests/golden/regen.py`** that builds fixtures into a temp dir and writes every expected file. Run it. Inspect five files by eye: whole rows, tail line "… N more matching rows", no row cut mid-word.

- [ ] **Step 6: Run to verify it passes**: `pytest tests/test_golden.py -q` → 2 passed.

- [ ] **Step 7: README**: row "Deterministic output" → Measured impact: "`tests/test_golden.py`: two builds of three fixture trees are byte-identical on every CI run; 150 `ask` cases pinned". Commit: `test: golden ask suite and determinism check in CI`.

---

### Task 2: `wawe-measure`: turns and searches per session from agent transcripts

**Files:**
- Create: `src/where_are_we/measure.py`
- Create: `tests/test_measure.py`
- Modify: `pyproject.toml` (`[project.scripts] wawe-measure = "where_are_we.measure:main"`)
- Modify: `README.md` section "Not yet measured anywhere" → becomes "How to measure it on your own sessions"

**Interfaces:**
- Produces: `measure.summarise(paths: list[str]) -> list[dict]` one dict per session: `{"session": <basename>, "turns": int, "searches": int, "map_calls": int, "reads": int, "first_map_call_turn": int|None, "orientation_turns": int}`; `measure.main() -> int`.
- Definitions: a *turn* is one assistant message. A *search* is a `tool_use` named `Grep` or `Glob`, or `Bash` whose `input.command` starts with (after optional `cd … &&`) `grep`, `rg`, `find`, `ls`, `ag`, `ack`, `fd`, `tree`. A *map call* is a `tool_use` whose name contains `where-are-we` or `where_are_we`, or `Bash` whose command contains `where-are-we --`. *orientation_turns* is the index of the first turn that contains a non-search, non-read, non-map tool call (an Edit/Write/test run), i.e. how many turns went by before the agent did something other than look around.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_measure.py
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import measure

def _line(role, *uses):
    return json.dumps({"type": role, "message": {"role": role, "content": [
        {"type": "tool_use", "name": n, "input": i} for n, i in uses]}})

def test_counts_searches_map_calls_and_orientation(tmp_path):
    p = tmp_path / "s1.jsonl"
    p.write_text("\n".join([
        _line("assistant", ("Grep", {"pattern": "x"})),
        _line("assistant", ("Bash", {"command": "cd /r && grep -rn foo ."})),
        _line("assistant", ("mcp__plugin_where-are-we_where-are-we__ask", {"words": "foo"})),
        _line("assistant", ("Read", {"file_path": "/r/a.py"})),
        _line("assistant", ("Edit", {"file_path": "/r/a.py"})),
        _line("user", ),
        _line("assistant", ("Bash", {"command": "pytest -q"})),
    ]))
    s = measure.summarise([str(p)])[0]
    assert s["turns"] == 6
    assert s["searches"] == 2
    assert s["map_calls"] == 1
    assert s["reads"] == 1
    assert s["first_map_call_turn"] == 3
    assert s["orientation_turns"] == 4

def test_cli_prints_a_table_and_json(tmp_path, capsys):
    (tmp_path / "s.jsonl").write_text(_line("assistant", ("Glob", {"pattern": "*"})))
    assert measure.main(["--sessions", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "searches" in out and "s.jsonl" in out
    assert measure.main(["--sessions", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["searches"] == 1
```

- [ ] **Step 2: Run to verify it fails**: `pytest tests/test_measure.py -q` → ImportError.

- [ ] **Step 3: Implement `measure.py`**

`main(argv=None)`: `--sessions DIR` (default: every `~/.claude/projects/*/` directory), `--since YYYY-MM-DD` (file mtime), `--json`, `--ask-log PATH` (Task 3 fills this in; accept and ignore for now with a note). Table output: one row per session plus a `median` row. Lines that fail to parse are skipped and counted in a final "skipped N unparsable lines" note.

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Run it for real**: `wawe-measure --since 2026-09-01` on this machine. Put the median `searches` and `orientation_turns` for sessions with map calls vs without into the README section (the numbers as a table, dated, "on N sessions of one developer, not a controlled run").

- [ ] **Step 6: README**: replace "Not yet measured anywhere" with "How to measure it on your own sessions": the command, the definitions above, and the table from Step 5. Commit: `feat: wawe-measure counts turns, searches and map calls per session`.

---

### Task 3: Ask log: the size of every map answer

**Files:**
- Modify: `src/where_are_we/ask.py` (add `log_answer(out_dir, tool, words, answer, room)`)
- Modify: `src/where_are_we/mcp.py` (`serve`: call `log_answer` after each `ask`/`find`/`defines`/`sections` reply)
- Modify: `src/where_are_we/mapper.py` `main()` `--ask` branch (same call)
- Modify: `src/where_are_we/measure.py` (`--ask-log DIR` summarises `<DIR>/.wawe-ask.log`)
- Create: `tests/test_ask_log.py`
- Modify: `README.md` row "`--ask` / MCP `ask`" ("Per-answer token cost" column)

**Interfaces:**
- Produces: `ask.log_answer(out_dir: str, tool: str, words: str, answer: str, room: int) -> None`; appends one JSON line `{"ts": <iso, seconds>, "tool", "words", "chars": len(answer), "tokens": len(answer)//4, "room"}` to `<out_dir>/.wawe-ask.log`. Disabled when `WAWE_ASK_LOG=0`. Never raises (OSError swallowed). `measure.ask_log_summary(path) -> dict` with `n`, `median_tokens`, `p95_tokens`, `max_tokens`, `by_tool: {tool: n}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ask_log.py
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import ask, measure

def test_log_answer_appends_one_json_line(tmp_path):
    ask.log_answer(str(tmp_path), "ask", "invoice", "x" * 400, 12000)
    ask.log_answer(str(tmp_path), "find", "foo", "y" * 40, 40)
    lines = (tmp_path / ".wawe-ask.log").read_text().splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["tool"] == "ask" and row["chars"] == 400 and row["tokens"] == 100 and row["room"] == 12000

def test_log_is_off_when_env_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("WAWE_ASK_LOG", "0")
    ask.log_answer(str(tmp_path), "ask", "a", "b", 1)
    assert not (tmp_path / ".wawe-ask.log").exists()

def test_measure_summarises_the_log(tmp_path):
    for n in (100, 200, 300, 400):
        ask.log_answer(str(tmp_path), "ask", "w", "x" * (n * 4), 12000)
    s = measure.ask_log_summary(str(tmp_path / ".wawe-ask.log"))
    assert s["n"] == 4 and s["median_tokens"] == 250 and s["max_tokens"] == 400
    assert s["by_tool"] == {"ask": 4}
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Wire into `mcp.serve` and `main --ask`.** Test by piping a `tools/call` request to `where-are-we --out <fixture out> --mcp` in a subprocess and asserting the log line exists (add to `tests/test_ask_log.py` as `test_mcp_logs_every_answer`, build the `code` fixture from `tests/golden/build_fixtures.py` if Task 1 is merged, else a two-file tmp repo mapped with `mapper.build`).

- [ ] **Step 6: README** row: Measured impact gets "`.wawe/.wawe-ask.log` records every answer; `wawe-measure --ask-log .wawe` prints median/p95/max tokens". Commit: `feat: log the size of every map answer`.

---

### Task 4: What changed since the last session, in the pointer

**Files:**
- Modify: `src/where_are_we/mapper.py` `pointer()` and the `--pointer` branch of `main()`
- Create: `tests/test_pointer_diff.py`
- Modify: `README.md` row "`--diff`"

**Interfaces:**
- Produces: `mapper.changed_since(repo: str, out_dir: str) -> list[str]`: reads `<out_dir>/.pointer-head` (a commit hash written by the previous `--pointer` call), returns `git diff --name-only <that>..HEAD` plus `git status --porcelain` paths (deduplicated, sorted, relative), and then writes the current HEAD to `.pointer-head`. Empty list when no previous head, no git, or nothing changed. `pointer(map_path, brief_path="", changed: list[str] | None = None)` appends, when `changed` is non-empty:
  ```
  Since the last session N files changed: a.py, b/c.ts, … and M more. Ask the map about them before reading them whole.
  ```
  capped at 10 names, and the whole pointer stays under `POINTER_MAX`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pointer_diff.py
import os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import mapper

def _git(repo, *a):
    subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)

def test_changed_since_reports_commits_and_working_tree(tmp_path):
    repo, out = tmp_path / "r", tmp_path / "o"; repo.mkdir(); out.mkdir()
    _git(repo, "init", "-q"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("x=1\n"); _git(repo, "add", "."); _git(repo, "commit", "-qm", "one")
    assert mapper.changed_since(str(repo), str(out)) == []          # first call: nothing to compare to
    (repo / "b.py").write_text("y=2\n"); _git(repo, "add", "."); _git(repo, "commit", "-qm", "two")
    (repo / "c.py").write_text("z=3\n")                              # uncommitted
    assert mapper.changed_since(str(repo), str(out)) == ["b.py", "c.py"]

def test_pointer_names_changed_files_and_stays_small(tmp_path):
    (tmp_path / "framework_map.md").write_text("# map\n\n## Entry points\n- a\n")
    text = mapper.pointer(str(tmp_path / "framework_map.md"), changed=[f"f{i}.py" for i in range(14)])
    assert "14 files changed" in text and "f9.py" in text and "f10.py" not in text and "and 4 more" in text
    assert len(text.encode()) <= mapper.POINTER_MAX
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** In `main()`'s `--pointer` branch call `changed_since(repo, out_dir)` and pass it. - [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: README** row "`--diff`": Measured impact "the pointer names what moved since the last session (`tests/test_pointer_diff.py`)". Commit: `feat: the pointer says what changed since the last session`.

---

### Task 5: Incremental rebuild: unchanged files are not re-parsed

**Files:**
- Modify: `src/where_are_we/mapper.py` (`_PARSE_CACHE` use in `index_declarations`, `_ts_symbols`, `_step_texts`, and the `ast.parse` sites in `build()`: search for every `ast.parse(` and every `_ts_symbols(` call)
- Create: `tests/test_incremental.py`
- Modify: `README.md` row "Fingerprint … and `--force`"

**Interfaces:**
- Produces: a module counter `mapper.PARSE_COUNT: int` incremented on every real parse (every `ast.parse`, every tree-sitter parse, every `index_declarations` regex pass over a file's body). A helper `mapper._cached(path: str, kind: str, compute: Callable[[], Any]) -> Any` keyed by `(path, kind)` with value `{"mtime": float, "size": int, "value": ...}` stored in `_PARSE_CACHE` and persisted by the existing `_save_parse_cache`. `WAWE_NO_CACHE=1` bypasses it.
- Constraint: the map output is byte-identical with and without the cache (`test_golden.py::test_map_is_deterministic` extended to compare a cold build with a warm one).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_incremental.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import mapper

def _repo(tmp_path, n=30):
    r = tmp_path / "r"; (r / "steps").mkdir(parents=True); (r / "app").mkdir()
    for i in range(n):
        (r / "steps" / f"s{i}.py").write_text(f"from behave import step\n@step('thing {i}')\ndef f{i}(c):\n    c.page.go{i}()\n")
        (r / "app" / f"m{i}.py").write_text(f"def g{i}():\n    return {i}\n")
    return r

def test_second_build_of_an_unchanged_tree_parses_nothing(tmp_path, monkeypatch):
    r = _repo(tmp_path); out = tmp_path / "o"; out.mkdir()
    monkeypatch.setenv("RUN_DIR", str(out))
    mapper._load_parse_cache(str(out)); mapper.PARSE_COUNT = 0
    m1 = mapper.build(str(r)); mapper._save_parse_cache(str(out))
    cold = mapper.PARSE_COUNT; assert cold >= 60
    mapper._load_parse_cache(str(out)); mapper.PARSE_COUNT = 0
    m2 = mapper.build(str(r))
    assert mapper.PARSE_COUNT == 0
    assert json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True)

def test_one_changed_file_is_the_only_one_reparsed(tmp_path, monkeypatch):
    r = _repo(tmp_path); out = tmp_path / "o"; out.mkdir()
    monkeypatch.setenv("RUN_DIR", str(out))
    mapper._load_parse_cache(str(out)); mapper.build(str(r)); mapper._save_parse_cache(str(out))
    p = r / "app" / "m3.py"; p.write_text("def g3():\n    return 99\n"); os.utime(p, (1, 1))
    mapper._load_parse_cache(str(out)); mapper.PARSE_COUNT = 0
    mapper.build(str(r))
    assert 1 <= mapper.PARSE_COUNT <= 3   # the file may be parsed by more than one extractor
```

Read how `build()` learns `out_dir` (it may take it from `RUN_DIR` or from `main()`); if `build` has no way to reach the cache directory, add an optional `out_dir` keyword to `build` (default `os.getenv("RUN_DIR", ".")`) and use it in the test instead of the env.

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement `_cached` and route every parse through it.** Keep `_fingerprint` as is. - [ ] **Step 4: Run to verify it passes, then `pytest tests -q`** (golden must still pass).

- [ ] **Step 5: Measure**: `time where-are-we --repo . --out /tmp/m --force` twice (cold: `rm -rf /tmp/m` first). Put both wall times in the README row. Commit: `perf: unchanged files are not re-parsed between builds`.

---

### Task 6: Declarations for Rust, Kotlin, C#, Ruby (regex always, tree-sitter when present)

**Files:**
- Modify: `src/where_are_we/mapper.py` `_ts_symbols` (`wanted` per language), `index_declarations` (regex per extension), and wherever the language of a file is decided for `_ts_symbols` (find the callers of `_ts_symbols`)
- Create: `tests/test_languages.py`
- Modify: `README.md` row "One tree walk" (list the languages), `pyproject.toml` keywords

**Interfaces:**
- Produces: `mapper.declarations_in(path: str) -> list[tuple[str, int]]` (name, 1-based line) for `.rs`, `.kt`, `.cs`, `.rb` files via regex; `_ts_symbols(path, lang)` handles `lang in {"rust","kotlin","c_sharp","ruby"}` when the parser exists. The `## Defined here` section of the map gets these names like any other.
- Regexes (anchored at line start, leading whitespace allowed):
  - rust: `(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait|type|const|static|mod)\s+([A-Za-z_]\w*)`
  - kotlin: `(?:(?:public|private|internal|open|data|sealed|abstract|suspend|override|inline)\s+)*(?:fun|class|object|interface|val|var)\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)`
  - c#: `(?:(?:public|private|protected|internal|static|abstract|sealed|partial|async|override|virtual|readonly)\s+)*(?:class|interface|struct|enum|record|delegate)\s+([A-Za-z_]\w*)` and methods `(?:(?:public|private|protected|internal|static|abstract|async|override|virtual)\s+)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\(`
  - ruby: `(?:def\s+(?:self\.)?|class\s+|module\s+)([A-Za-z_]\w*[?!=]?)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_languages.py
import os, sys, textwrap, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import mapper

CASES = {
    "lib.rs": ("pub fn charge() {}\nstruct Invoice;\npub(crate) enum State { A }\ntrait Pay {}\n// fn commented() {}\n", ["charge", "Invoice", "State", "Pay"], ["commented"]),
    "Pay.kt": ("class Invoice(val id: Int)\nfun charge(): Unit = Unit\nobject Config\nsuspend fun refund() {}\n", ["Invoice", "charge", "Config", "refund"], []),
    "Pay.cs": ("public class Invoice {\n  public static void Charge() {}\n  private int Total() => 1;\n}\npublic interface IPay {}\n", ["Invoice", "Charge", "Total", "IPay"], []),
    "pay.rb": ("module Billing\n  class Invoice\n    def charge?\n    end\n    def self.refund\n    end\n  end\nend\n", ["Billing", "Invoice", "charge?", "refund"], []),
}

@pytest.mark.parametrize("fn", CASES)
def test_regex_declarations(tmp_path, fn):
    body, want, unwanted = CASES[fn]
    p = tmp_path / fn; p.write_text(body)
    names = [n for n, _ in mapper.declarations_in(str(p))]
    for w in want: assert w in names, (fn, names)
    for u in unwanted: assert u not in names

def test_declarations_reach_the_map(tmp_path):
    for fn, (body, _, _) in CASES.items():
        (tmp_path / fn).write_text(body)
    m = mapper.build(str(tmp_path))
    text = mapper.brief(m) + "\n" + mapper.digest(m)
    assert "charge" in text and "Invoice" in text
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run to verify it passes** (also `pip install ".[precise]"` locally if the wheel exists for this platform and run again).

- [ ] **Step 5: README** + `pyproject.toml` keywords `rust, kotlin, csharp, ruby`. Commit: `feat: declarations for Rust, Kotlin, C# and Ruby`.

---

### Task 7: Cross-file call graph for TypeScript/JavaScript and Go

**Files:**
- Modify: `src/where_are_we/mapper.py` around `func_calls` in `build()` (line ~2241): add a second pass for `.ts .tsx .js .jsx .go`
- Create: `tests/test_call_graph.py`
- Modify: `SCHEMA.md` row `call_graph_files` (say it now covers ts/js/go)
- Modify: `README.md` row "`## Defined here`" gets a sibling line for the call graph

**Interfaces:**
- Produces: entries in `call_graph_files` shaped exactly like the Python ones: key `<basename>:<func>`, value `["<callee> (<basename>)", …]` sorted, at most 8, only when the callee is *defined in another file of the same language group*. Definitions: ts/js `function NAME(`, `const NAME = (` / `= async (`, `export function NAME`, class methods `NAME(...) {` at two-space indent; go `func NAME(` and `func (r T) NAME(`. Calls: `\bNAME\s*\(` inside the function's body (body found by brace matching from the definition line; cap at 400 lines).
- Cap unchanged: 60 entries total, sorted by callee count desc; stable tie-break by key so output stays deterministic.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_call_graph.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import mapper

def test_ts_and_go_cross_file_calls(tmp_path):
    (tmp_path / "a.ts").write_text("export function charge(x: number) { return x }\n")
    (tmp_path / "b.ts").write_text("import { charge } from './a'\nexport async function pay() {\n  const r = charge(1)\n  return r\n}\nfunction local() { return pay() }\n")
    (tmp_path / "s.go").write_text("package m\nfunc Serve() {}\n")
    (tmp_path / "c.go").write_text("package m\nfunc Run() { Serve() }\n")
    g = mapper.build(str(tmp_path))["call_graph_files"]
    assert g["b.ts:pay"] == ["charge (a.ts)"]
    assert "b.ts:local" not in g            # pay is in the same file
    assert g["c.go:Run"] == ["Serve (s.go)"]

def test_python_entries_unchanged(tmp_path):
    (tmp_path / "x.py").write_text("def f():\n    return 1\n")
    (tmp_path / "y.py").write_text("from x import f\ndef g():\n    return f()\n")
    assert mapper.build(str(tmp_path))["call_graph_files"]["y.py:g"] == ["f (x.py)"]
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run to verify it passes, then `pytest tests -q`.** - [ ] **Step 5: SCHEMA.md, README.** Commit: `feat: cross-file call graph for TypeScript, JavaScript and Go`.

---

### Task 8: "Who calls X": `callers` tool, `--callers`, and a "Called by" block in `ask`

**Files:**
- Modify: `src/where_are_we/ask.py` (`callers(map_json_path, name) -> list[str]`, `_callers_block`)
- Modify: `src/where_are_we/mcp.py` (`TOOLS` += `callers`; `tools/call` branch)
- Modify: `src/where_are_we/mapper.py` `main()` (`--callers NAME`)
- Modify: `plugin/skills/where-defined/SKILL.md` (mention `callers`), `plugin/README.md`
- Create: `tests/test_callers.py`
- Modify: `README.md` (new row under "What an agent carries vs what it asks")

**Interfaces:**
- Consumes: `call_graph_files` (`{ "b.ts:pay": ["charge (a.ts)"] }`) and `call_graph` (`{ "pay_steps.py:step_pay_1": ["click_1"] }`) from `framework_map.json`.
- Produces: `ask.callers(map_json: str, name: str) -> list[str]` returning sorted `"<file>:<func>"` keys whose value list mentions `name` (matching `name (…)` in `call_graph_files`, or bare `name` in `call_graph`). Case-sensitive exact name, or `name` with a trailing `(` stripped. `ask.ask()` appends, when any term (case-sensitive) has callers and there is room:
  ```
  ## Called by `charge`
  - b.ts:pay
  ```
  MCP tool `callers` with input `{"name": string | [string]}` → text `"<name>: a, b, c"` per name or `"nothing in the map calls <name>"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_callers.py
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import ask

def _map(tmp_path):
    j = tmp_path / "framework_map.json"
    j.write_text(json.dumps({"schema": "where-are-we/1",
        "call_graph_files": {"b.ts:pay": ["charge (a.ts)"], "y.py:g": ["f (x.py)", "charge (a.ts)"]},
        "call_graph": {"pay_steps.py:step_pay_1": ["click_1", "charge"]}}))
    (tmp_path / "framework_map.md").write_text("# map\n\n## Defined here\n- `a.ts:1` charge\n")
    return j

def test_callers_from_both_graphs(tmp_path):
    j = _map(tmp_path)
    assert ask.callers(str(j), "charge") == ["b.ts:pay", "pay_steps.py:step_pay_1", "y.py:g"]
    assert ask.callers(str(j), "nothing") == []

def test_ask_appends_a_called_by_block(tmp_path):
    _map(tmp_path)
    out = ask.ask(str(tmp_path / "framework_map.md"), "charge", 12000)
    assert "## Called by `charge`" in out and "- b.ts:pay" in out
    assert "Called by" not in ask.ask(str(tmp_path / "framework_map.md"), "charge", 60)
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, then regenerate goldens if any changed** (`python tests/golden/regen.py`; `git diff --stat tests/golden/expected` must show only cases whose words are a callee in the fixture: `charge`, `click_7`). - [ ] **Step 5: MCP tool, CLI flag, skill docs, README.** Commit: `feat: callers tool and a Called-by block in ask`.

---

### Task 9: Synonyms and stemming in `ask`

**Files:**
- Modify: `src/where_are_we/ask.py` (`_expand(terms) -> list[str]`, used by `ask()` before `_rank` and `_split_rows`; `_stem(word)`)
- Modify: `src/where_are_we/mapper.py` `_config` (read `[synonyms]` from `.wawe.toml`) and pass it to `ask` via `WAWE_SYNONYMS` env JSON or a module setter `ask.set_synonyms(dict)` called in `main()`
- Create: `tests/test_synonyms.py`
- Regenerate: `tests/golden/expected/` (intended change; the commit explains which cases moved and why)
- Modify: `README.md` row "`--ask` / MCP `ask`" and the `.wawe.toml` row

**Interfaces:**
- Produces: `ask._stem(w: str) -> str`: lowercase; for `len(w) >= 5` strip one of `ies→y`, `ing`, `ed`, `es`, `s` (that order, first that applies and leaves ≥ 3 chars). `ask.SYNONYMS: dict[str, list[str]]` groups; a term expands to itself, its stem, and every member of any group containing it or its stem. Built-in groups (each a list, first entry the canonical): `["login","signin","sign_in","sign-in","auth","authenticate","authentication"]`, `["logout","signout","sign_out"]`, `["invoice","bill","billing"]`, `["payment","pay","charge","checkout"]`, `["user","account","customer","member"]`, `["config","configuration","settings","setup"]`, `["error","exception","failure","fault"]`, `["endpoint","route","handler","api"]`, `["test","spec","scenario","case"]`, `["db","database","table","model","schema"]`, `["delete","remove","destroy","drop"]`, `["create","add","insert","new"]`, `["update","edit","modify","patch","change"]`, `["fetch","get","load","read","retrieve"]`, `["queue","topic","subject","message","event"]`, `["deploy","release","ship","rollout"]`, `["cache","memo","memoize"]`, `["cron","schedule","job","task"]`, `["permission","role","scope","guard","acl"]`, `["secret","credential","token","key","password"]`. `.wawe.toml`:
  ```toml
  [synonyms]
  invoice = ["proforma", "receipt"]
  ```
  merges into the group containing `invoice` (or makes a new group).
- Ranking: an expanded term scores at 0.5 weight of the literal term in `_rank`; the tail line still counts "rows that do not mention these words" against the *expanded* set. The answer's first line says `(also matched: signin, auth)` when an expansion produced hits the literal did not.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synonyms.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import ask

def test_stem():
    assert ask._stem("invoices") == "invoice" and ask._stem("paying") == "pay"
    assert ask._stem("categories") == "category" and ask._stem("bus") == "bus"

def test_expand_uses_groups_and_stems():
    got = set(ask._expand(["logins"]))
    assert {"logins", "login", "signin", "auth"} <= got

def test_ask_finds_signin_when_asked_for_login(tmp_path):
    (tmp_path / "framework_map.md").write_text("# map\n\n## Steps\n- `steps/a.py:3` user signs in with signin()\n- `steps/b.py:9` cart total\n")
    out = ask.ask(str(tmp_path / "framework_map.md"), "login", 12000)
    assert "signin()" in out and "cart total" not in out
    assert "also matched: signin" in out

def test_user_synonyms_merge(tmp_path):
    ask.set_synonyms({"invoice": ["proforma"]})
    try:
        assert "proforma" in ask._expand(["invoice"])
    finally:
        ask.set_synonyms({})
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: `pytest tests -q`; regenerate goldens; review `git diff --stat tests/golden/expected`**: only cases for `invoice`, `charge`, `login`, `pay step`, `health`, `migration` may change; a change in `nothing_here` or `click_7` is a bug. - [ ] **Step 5: README.** Commit: `feat: ask expands synonyms and stems`.

---

### Task 10: `--install-hook cursor|codex|gemini`

**Files:**
- Create: `src/where_are_we/hooks.py` (move the body of `install_hook` here; `mapper.install_hook` becomes a one-line delegate so the public name stays)
- Modify: `src/where_are_we/mapper.py` `main()` `--install-hook` choices `["git","agent","claude","cursor","codex","gemini"]` (`agent` stays an alias of `claude`)
- Create: `tests/test_hooks.py`
- Modify: `README.md` row "`--install-hook`", `plugin/README.md` "other harnesses" paragraph

**Interfaces:**
- Produces: `hooks.install(repo, kind, product, out, agent_file, home: str | None = None) -> str` (`home` overrides `~` for tests). Per kind, all idempotent (second call returns "already installed …"), all merge into existing files without losing other keys:
  - `cursor`: `<repo>/.cursor/rules/where-are-we.mdc` = frontmatter `---\ndescription: the repository map\nalwaysApply: true\n---\n` + `pointer()` text (map at `<repo>/.wawe`); `<repo>/.cursor/mcp.json` → `mcpServers["where-are-we"] = {"command": "where-are-we", "args": ["--out", ".wawe", "--mcp"]}`.
  - `codex`: `<repo>/AGENTS.md` gets a block between `<!-- where-are-we:start -->` and `<!-- where-are-we:end -->` holding the pointer (block replaced if present); `<home>/.codex/config.toml` gets, if the text `[mcp_servers.where-are-we]` is absent, an appended section:
    ```toml
    [mcp_servers.where-are-we]
    command = "where-are-we"
    args = ["--out", ".wawe", "--mcp"]
    ```
  - `gemini`: `<repo>/GEMINI.md` same block as codex; `<repo>/.gemini/settings.json` → `mcpServers["where-are-we"]` as cursor.
  - Every kind first builds the map into `<repo>/.wawe` if `framework_map.md` is missing (call `build` + write, same as `main()` does), and writes `.wawe/.gitignore` with `*`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hooks.py
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import hooks

def _repo(tmp_path):
    r = tmp_path / "r"; r.mkdir(); (r / "a.py").write_text("def f():\n    pass\n"); return r

def test_cursor(tmp_path):
    r = _repo(tmp_path)
    (r / ".cursor").mkdir(); (r / ".cursor" / "mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}')
    msg = hooks.install(str(r), "cursor", "", "", "", home=str(tmp_path))
    assert "installed" in msg
    rule = (r / ".cursor" / "rules" / "where-are-we.mdc").read_text()
    assert rule.startswith("---\n") and "alwaysApply: true" in rule and "framework map" in rule.lower()
    conf = json.loads((r / ".cursor" / "mcp.json").read_text())
    assert conf["mcpServers"]["other"] == {"command": "x"}
    assert conf["mcpServers"]["where-are-we"]["args"] == ["--out", ".wawe", "--mcp"]
    assert (r / ".wawe" / "framework_map.md").exists() and (r / ".wawe" / ".gitignore").read_text() == "*\n"
    assert "already" in hooks.install(str(r), "cursor", "", "", "", home=str(tmp_path))

def test_codex(tmp_path):
    r = _repo(tmp_path); (r / "AGENTS.md").write_text("# Agents\n\nkeep me\n")
    hooks.install(str(r), "codex", "", "", "", home=str(tmp_path))
    text = (r / "AGENTS.md").read_text()
    assert "keep me" in text and "<!-- where-are-we:start -->" in text
    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.where-are-we]" in toml
    hooks.install(str(r), "codex", "", "", "", home=str(tmp_path))
    assert (r / "AGENTS.md").read_text().count("where-are-we:start") == 1
    assert (tmp_path / ".codex" / "config.toml").read_text().count("[mcp_servers.where-are-we]") == 1

def test_gemini(tmp_path):
    r = _repo(tmp_path)
    hooks.install(str(r), "gemini", "", "", "", home=str(tmp_path))
    assert "where-are-we:start" in (r / "GEMINI.md").read_text()
    assert "where-are-we" in json.loads((r / ".gemini" / "settings.json").read_text())["mcpServers"]

def test_claude_and_git_still_work(tmp_path):
    r = _repo(tmp_path)
    assert "installed" in hooks.install(str(r), "claude", "", "", "", home=str(tmp_path))
    assert "SessionStart" in json.dumps(json.load(open(tmp_path / ".claude" / "settings.json")))
    assert "does not exist" in hooks.install(str(r), "git", "", "", "", home=str(tmp_path))
```

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, then `pytest tests -q`.** - [ ] **Step 5: README and plugin/README.** Commit: `feat: install the map into Cursor, Codex and Gemini CLI`.

---

### Task 11: `--spec-source github|linear`

**Files:**
- Modify: `src/where_are_we/specs.py` (`command_for(source, repo) -> tuple[str, re.Pattern]`, `walk(..., key_re=KEY)`)
- Modify: `src/where_are_we/mapper.py` `main()` (`--spec-source` choices `["cmd","github","linear"]`, default `cmd`; with `github`/`linear` the `--spec-cmd` is filled in)
- Create: `tests/test_spec_sources.py`
- Modify: `README.md` row "`--specs`…", `plugin/skills/spec-map/SKILL.md`

**Interfaces:**
- Produces: `specs.command_for(source: str, repo: str) -> tuple[str, re.Pattern]`:
  - `github`: command `gh issue view {key} --repo <owner/name> --json number,title,body,state,labels,url,comments` where `<owner/name>` comes from `git -C <repo> remote get-url origin` (both `git@github.com:o/n.git` and `https://github.com/o/n` forms); the key pattern is `(?<![\w/])#(\d+)\b`; `{key}` is substituted with the digits only. The fetched JSON gets `"key": "#<number>"` added so `links_of` and `digest` work unchanged.
  - `linear`: command `curl -sS -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" https://api.linear.app/graphql -d @-` fed on stdin with the query `{"query":"{ issue(id: \"{key}\") { identifier title description state { name } url parent { identifier } children { nodes { identifier } } relations { nodes { relatedIssue { identifier } } } comments { nodes { body } } } }"}`; `fetch` gains an optional `stdin: str` parameter for this. Key pattern stays `KEY`. Missing `LINEAR_API_KEY` returns `{"key": k, "error": "LINEAR_API_KEY is not set"}` without calling out.
- `walk(command, roots, depth, limit, say=None, key_re=KEY, stdin=None)`: `links_of(ticket, key_re)`.

- [ ] **Step 1: Write the failing test** (a fake `gh` and `curl` on PATH):

```python
# tests/test_spec_sources.py
import json, os, stat, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import specs

def _fake(tmp_path, name, script):
    p = tmp_path / "bin" / name; p.parent.mkdir(exist_ok=True); p.write_text(script); p.chmod(0o755)

def test_github_source(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir()
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", "git@github.com:acme/shop.git"], check=True)
    _fake(tmp_path, "gh", '#!/bin/sh\necho "{\\"number\\": $2, \\"title\\": \\"t $2\\", \\"body\\": \\"see #7\\", \\"comments\\": []}"\n')
    monkeypatch.setenv("PATH", f"{tmp_path/'bin'}:{os.environ['PATH']}")
    cmd, key_re = specs.command_for("github", str(repo))
    assert "--repo acme/shop" in cmd
    spec = specs.walk(cmd, ["#12"], depth=1, key_re=key_re)
    assert set(spec["tickets"]) == {"#12", "#7"} and spec["links"]["#12"] == ["#7"]

def test_linear_source_without_key(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    cmd, key_re = specs.command_for("linear", ".")
    t = specs.fetch(cmd, "ENG-1", stdin=specs.linear_query("ENG-1"))
    assert t["error"].startswith("LINEAR_API_KEY")

def test_linear_source_with_fake_curl(tmp_path, monkeypatch):
    _fake(tmp_path, "curl", '#!/bin/sh\ncat >/dev/null\necho "{\\"data\\": {\\"issue\\": {\\"identifier\\": \\"ENG-1\\", \\"title\\": \\"x\\", \\"parent\\": {\\"identifier\\": \\"ENG-9\\"}}}}"\n')
    monkeypatch.setenv("PATH", f"{tmp_path/'bin'}:{os.environ['PATH']}"); monkeypatch.setenv("LINEAR_API_KEY", "k")
    cmd, key_re = specs.command_for("linear", ".")
    spec = specs.walk(cmd, ["ENG-1"], depth=1, key_re=key_re, stdin=specs.linear_query)
    assert "ENG-9" in spec["links"]["ENG-1"]
```

`stdin` in `walk` may be a string or a callable of the key; document it in the docstring.

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run, then `pytest tests -q`.** - [ ] **Step 5: README, skill doc.** Commit: `feat: --spec-source github|linear`.

---

### Task 12: `--lsp`: go-to-definition and workspace symbols from the map

**Files:**
- Create: `src/where_are_we/lsp.py`
- Modify: `src/where_are_we/mapper.py` `main()` (`--lsp` flag, like `--mcp`, calls `lsp.serve(out_dir, repo)`)
- Create: `tests/test_lsp.py`
- Create: `docs/examples/lsp.md` (VS Code `settings.json` snippet for a generic LSP client, Neovim `vim.lsp.start` snippet)
- Modify: `README.md` "Ways in" table (new row)

**Interfaces:**
- Produces: `lsp.serve(out_dir: str, repo: str) -> int`: JSON-RPC over stdio with `Content-Length` framing. Methods: `initialize` → `{"capabilities": {"definitionProvider": true, "workspaceSymbolProvider": true}, "serverInfo": {"name": "where-are-we"}}`; `initialized` (notification, ignored); `textDocument/definition` → the identifier under `position` in the document (read from disk via `textDocument.uri`, `file://`), looked up with `mapper._definitions_for(map_path, [name])`; each hit line has the shape `- \`path:line\` name` (read `_definitions_for` to confirm the format) → `[{"uri": "file://<repo>/<path>", "range": {"start": {"line": L-1, "character": 0}, "end": {"line": L-1, "character": 0}}}]`; `workspace/symbol` → every declared name containing `query` (case-insensitive) as `{"name", "kind": 12, "location": {...}}`, at most 100; `shutdown` → `null`; `exit` → return 0. Unknown methods with an id → error `-32601`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lsp.py
import json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import mapper

def _frame(obj):
    b = json.dumps(obj).encode(); return b"Content-Length: %d\r\n\r\n%s" % (len(b), b)

def _unframe(data):
    out = []
    while data:
        head, _, rest = data.partition(b"\r\n\r\n")
        n = int(head.split(b":")[1]); out.append(json.loads(rest[:n])); data = rest[n:]
    return out

def test_definition_and_symbols(tmp_path):
    repo, out = tmp_path / "r", tmp_path / "o"; repo.mkdir(); out.mkdir()
    (repo / "billing.py").write_text("def charge(x):\n    return x\n")
    (repo / "api.py").write_text("from billing import charge\n\ndef pay():\n    return charge(1)\n")
    m = mapper.build(str(repo))
    (out / "framework_map.md").write_text(mapper.digest(m)); (out / "framework_map_brief.md").write_text(mapper.brief(m))
    (out / "framework_map.json").write_text(json.dumps(m))
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition", "params": {
                "textDocument": {"uri": f"file://{repo}/api.py"}, "position": {"line": 3, "character": 13}}},
            {"jsonrpc": "2.0", "id": 3, "method": "workspace/symbol", "params": {"query": "cha"}},
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown"}, {"jsonrpc": "2.0", "method": "exit"}]
    p = subprocess.run([sys.executable, "-m", "where_are_we.mapper", "--out", str(out), "--repo", str(repo), "--lsp"],
                       input=b"".join(_frame(m) for m in msgs), capture_output=True, timeout=30,
                       env={**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "src")})
    replies = {r["id"]: r for r in _unframe(p.stdout) if "id" in r}
    assert replies[1]["result"]["capabilities"]["definitionProvider"] is True
    loc = replies[2]["result"][0]
    assert loc["uri"].endswith("/billing.py") and loc["range"]["start"]["line"] == 0
    assert [s["name"] for s in replies[3]["result"]] == ["charge"]
```

Check that `python -m where_are_we.mapper` works (needs `if __name__ == "__main__": sys.exit(main())`; add it if absent). If the map's "Defined here" is in the brief rather than the digest, write both files as `main()` does.

- [ ] **Step 2: Run to verify it fails.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run.** - [ ] **Step 5: docs/examples/lsp.md, README row.** Commit: `feat: --lsp serves definitions and symbols from the map`.

---

### Task 13: Split `mapper.py` into a package, behaviour byte-identical

**Files:**
- Create: `src/where_are_we/mapper/__init__.py` (facade: re-exports every public and underscore name the tests, `mcp.py`, `readmes.py`, `semantic.py`, `hooks.py`, `lsp.py`, the plugin scripts and `pyproject.toml` use: `build, brief, digest, for_audience, init_manifest, install_hook, main, pointer, ask, find_text, index_lines, index_declarations, meaning_tail, propose_docs, changed_since, declarations_in, POINTER_MAX, PARSE_COUNT, _cap_sections, _definitions_for, _load_parse_cache, _save_parse_cache, _config, _fingerprint, _walk, _slurp, redact` and anything else `grep -rn "mapper\.\w\+" src tests plugin` finds)
- Create: `src/where_are_we/mapper/walk.py` (`_ignores, _ignored, _walk, _slurp, _fingerprint, _manifest, _config, _product_roots, _looks_like_suite, SKIP_DIRS`, parse cache, `_cached`)
- Create: `src/where_are_we/mapper/declare.py` (`index_lines, index_declarations, declarations_in, _tree_sitter, _ts_symbols, _step_texts, find_text, _definitions_for`)
- Create: `src/where_are_we/mapper/extract/__init__.py` with `python.py, web.py, go.py, infra.py, contracts.py, tests.py, history.py`: the per-topic loops that today sit inline in `build()`, each a function `(ctx) -> dict` where `ctx` is a small dataclass `Ctx(repo, files, code_files, read: Callable[[str], str])`
- Create: `src/where_are_we/mapper/build.py` (`build()` calls the extractors in the same order as today and assembles the same dict)
- Create: `src/where_are_we/mapper/render.py` (`digest, brief, for_audience, _cap_sections, _as_dict, _as_list, pointer, changed_since, meaning_tail`)
- Create: `src/where_are_we/mapper/cli.py` (`main`, `init_manifest`, `propose_docs`, `install_hook` delegate)
- Delete: `src/where_are_we/mapper.py`
- Modify: `pyproject.toml` `where-are-we = "where_are_we.mapper:main"` keeps working through the facade; add `where-are-we = "where_are_we.mapper.cli:main"` only if the facade import proves circular
- Create: `tests/test_split_identity.py`

**Interfaces:**
- Consumes everything; produces nothing new. The proof is the identity test.

- [ ] **Step 1: Before touching anything, capture the reference**: `python tests/golden/regen.py` must be a no-op (`git status --porcelain tests/golden` empty); build the map of this repository and of the three fixtures into `.superpowers/split/before/` (`where-are-we --repo . --out .superpowers/split/before/self --force` and the fixtures via `build_fixtures.build_all`).

- [ ] **Step 2: Write the identity test**

```python
# tests/test_split_identity.py
"""The split of mapper.py changed no output. Kept after the split as the guard
for the next refactor: the map of the fixtures and of this repository is
byte-identical to what the previous layout produced (tests/golden/expected
holds the ask answers; this holds the maps)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden"))
from where_are_we import mapper
import build_fixtures

def test_fixture_maps_match_reference(tmp_path):
    outs = build_fixtures.build_all(str(tmp_path))
    ref = os.path.join(os.path.dirname(__file__), "golden", "maps")
    for name, out in outs.items():
        for fn in ("framework_map.md", "framework_map_brief.md"):
            got = open(os.path.join(out, fn)).read().replace(str(tmp_path), "<root>")
            want = open(os.path.join(ref, name, fn)).read()
            assert got == want, f"{name}/{fn}: run tests/golden/regen.py --maps if the change is intended"

def test_facade_exports_what_callers_use():
    for name in ("build", "brief", "digest", "main", "pointer", "ask", "find_text", "_definitions_for", "_cap_sections", "install_hook", "meaning_tail"):
        assert hasattr(mapper, name), name
```

Extend `regen.py` with `--maps` writing `tests/golden/maps/<fixture>/framework_map{,_brief}.md` with `<root>` substituted. Generate them **before** the split, commit them with the test (test passes on the old layout).

- [ ] **Step 3: Move code in six commits**, running `pytest tests -q` after each: (a) `walk.py`, (b) `declare.py`, (c) `render.py`, (d) `extract/*` + `build.py`, (e) `cli.py` + facade + delete `mapper.py`, (f) `hooks.py`/`lsp.py`/`mcp.py` imports tidied. Each commit `refactor: mapper/<part>`. No function body changes; only moves, imports and the `Ctx` plumbing.

- [ ] **Step 4: After the last commit**: `where-are-we --repo . --out .superpowers/split/after/self --force && diff -r .superpowers/split/before/self .superpowers/split/after/self` (ignore `framework_map.json`'s `fingerprint` and `repo`) → identical. `pip install .` in a fresh venv → `where-are-we --help`, `wawe-readmes --help`, `wawe-measure --help` all exit 0.

- [ ] **Step 5: CONTRIBUTING.md**: a paragraph "where things are" listing the seven modules and the rule "an extractor is one file, one topic, one `(ctx) -> dict`". Commit: `docs: layout after the split`.

---

### Task 14: Public demo: the brief of a well-known repository as a page

**Files:**
- Create: `docs/demo/build.sh` (clones `https://github.com/fastapi/fastapi` at tag `0.115.0` into the scratchpad, runs `where-are-we --repo <clone> --out <tmp> --html --force`, copies the html to `docs/demo/fastapi/index.html`, writes `docs/demo/fastapi/README.md` with the tag, the date and the command)
- Create: `docs/demo/fastapi/index.html` (generated, committed)
- Create: `docs/index.md` (one paragraph, links the demo and the README)
- Modify: `README.md` "Ways in" intro: one line "See it on a repository you know: [FastAPI 0.115.0 mapped](https://ngavrish.github.io/where-are-we/demo/fastapi/)"
- GitHub Pages: enable with `gh api -X POST repos/ngavrish/where-are-we/pages -f build_type=legacy -f source[branch]=main -f source[path]=/docs` (if it already exists, `-X PUT` with the same fields). Verify with `curl -sI https://ngavrish.github.io/where-are-we/demo/fastapi/ | head -1` after the push (may take a few minutes; poll up to 10 times, 60 s apart).

- [ ] **Step 1: Write `build.sh`, run it.** Read the html once: it must not contain absolute paths of this machine (`grep -c "/Users/" docs/demo/fastapi/index.html` → 0; if not, strip the clone prefix in `build.sh` with `sed`).
- [ ] **Step 2: Check size**: under 2 MB, else pass `--max-lines 40`.
- [ ] **Step 3: Commit `docs: FastAPI demo page`; enable Pages; push; verify the URL returns 200.** README line.

---

### Task 15: README consolidation

**Files:**
- Modify: `README.md`, `CHANGELOG.md` (`## 1.1.0` listing Tasks 2 to 12 and 14 in one line each; Task 13 as "no behaviour change; `mapper` is a package"), `pyproject.toml` version `1.1.0`, `plugin/.claude-plugin/plugin.json` version if present

- [ ] **Step 1**: Every row of "Everything it does, and what it is measured to save" is re-read. A row whose "Measured impact" is still "Not measured" and whose "how to" column is now a shipped command (`wawe-measure`, `.wawe-ask.log`, `tests/test_*`) gets the command named in the "how to" column. No row claims a number without a test or a dated run behind it.
- [ ] **Step 2**: `pytest tests -q` all green; `where-are-we --repo . --out /tmp/m --force` exits 0; `git status` clean. Commit: `release: 1.1.0`. Tag `v1.1.0`, push tag (the release workflow builds packages).

---

## Self-review

- Spec coverage: measurement (2, 3, 15), incremental (5), `--diff` for the agent (4), languages (6), call graph ts/go (7), callers (8), synonyms (9), golden in CI (1), Cursor/Codex/Gemini (10), GitHub/Linear (11), LSP (12), split (13), demo (14). The A/B production run itself is not a task: it costs a run's budget and is the user's to launch; Task 2 is the tool that reads its result.
- Placeholders: none; every step has its test or its command.
- Names used across tasks: `build_fixtures.build_all`, `regen.py [--maps]` (1, 8, 9, 13); `measure.summarise`, `measure.ask_log_summary`, `ask.log_answer` (2, 3); `mapper.changed_since`, `pointer(…, changed=)` (4, 13); `mapper.PARSE_COUNT`, `_cached` (5, 13); `declarations_in` (6, 13); `call_graph_files` shape (7, 8); `ask.callers`, `ask.set_synonyms`, `ask._expand`, `ask._stem` (8, 9); `hooks.install` (10, 13); `specs.command_for`, `specs.linear_query`, `walk(key_re=, stdin=)` (11); `lsp.serve` (12, 13).
