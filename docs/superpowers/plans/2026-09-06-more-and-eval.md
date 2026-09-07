# 1.2.0: retrieval handles and an answer-quality evaluation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. No `tests/test_*.py` files (a global hook forbids the model writing tests): every behaviour is proven by a live command in the report and a step in `.github/workflows/ci.yml`; the golden suite (`tests/golden/check.py`) stays byte-identical unless the change is explained in the commit message.

**Goal:** Two ideas taken from Headroom (headroomlabs-ai/headroom): (1) a cut answer carries a handle that fetches what was left out (their "cached content retrieval"); (2) a measured claim that the budgeted answer loses nothing the full answer had, plus an optional agent A/B on real questions.

**Architecture:** `ask.py` already knows every place it cuts: section tails ("… N more matching rows"), the definitions cap ("… N more definitions"), the sections note ("… more sections match"), and `find_text`'s hit cap. Each cut gets a deterministic handle computed from the map file, the query and the position, so a later process can recompute the same cut and return the remainder. A fifth read tool, `more`, resolves handles. `wawe-eval` reads the same map files and answers, needs no LLM for the deterministic half, and calls the Claude API only in `--agent` mode.

**Global constraints:** schema `where-are-we/1` unchanged; existing tools and flags keep names and meaning (additive only); stdlib only in the core (`anthropic` is an optional extra `eval-agent`); deterministic output; Python 3.12+; no em dashes in new prose; commit trailer as in common.md.

---

### Task 1: handles and the `more` tool

**Files:** `src/where_are_we/ask.py` (handles in `_section_answer`, `_defined_here`, `_more_note`; new `more(map_path, handle, limit)`), `src/where_are_we/_mapper/declare.py` (`find_text` tail gets a handle), `src/where_are_we/mcp.py` (`TOOLS` += `more`; dispatch; `log_answer`), `src/where_are_we/cli.py` (`--more HANDLE`), `plugin/skills/ask/SKILL.md`, `plugin/README.md`, `README.md` rows, `CHANGELOG.md` left to the controller.

**Handle format:** `more:<kind>:<payload>` where kind is `rows` (a section's unshown matching rows), `unmatched` (a section's rows that do not mention the words), `defs` (definitions beyond the cap), `sections` (matching sections not shown), `find` (hits beyond the limit). Payload is URL-safe and deterministic: for rows/unmatched `<section-slug>:<words-slug>:<offset>`; for defs `<words-slug>:<offset>`; for sections `<words-slug>:<rank-offset>`; for find `<phrase-slug>:<offset>`. Slugs are lowercase `[a-z0-9_-]` derived from the heading/words; the resolver recomputes the same ranking from the map on disk, so no state is stored. A handle for a map that has been rebuilt since may point elsewhere: `more` says so when the section is absent.

**Tail lines become:** `… 37 more matching rows (more:rows:steps-that-overlap:invoice:12)`; `… 210 rows in this section do not mention these words (more:unmatched:...:0)`; `… 15 more definitions (more:defs:invoice:40)`; `… more sections match; ask for something narrower, or more:sections:invoice:6`; `find`: `… 22 more hits (more:find:click_pay:40)`.

**`more(map_path, handle, limit=4000)`:** returns the next slice under the same whole-row, ceiling, tail rules, with its own follow-up handle when there is still more; an unknown or stale handle returns `no such handle in this map: <reason>`.

**Proofs (report + CI step "the more tool returns what an answer left out"):** on the suite fixture, `ask("invoice checkout", 350)` prints a rows handle; `more(handle)` returns rows none of which appear in the first answer and all of which appear in `ask("invoice checkout", 12000)`; chaining handles until none is left reconstructs exactly the 12000 answer's row set; a handle against a rebuilt map with the section removed returns the stale message; `--more` CLI and MCP `more` answer the same; `tools/list` shows six tools. Golden: the tail lines change in every case that has a tail, so regenerate once and state in the commit that only tail lines moved (diff the expected files with the handle text stripped: zero other changes).

### Task 2: `wawe-eval`

**Files:** `src/where_are_we/eval.py`, `pyproject.toml` (`wawe-eval` script; optional extra `eval-agent = ["anthropic>=0.40"]`), `docs/examples/eval.md`, `README.md` (a "Does the budget lose answers" section with the measured number), CI step.

**Deterministic half (`wawe-eval --map <out_dir> [--questions N] [--budgets 350,1500,12000]`):** generate N questions from the map itself (every declared name, every step phrase's distinctive word, every section heading's key noun; sample deterministically with a seed) and for each compute the reference row set: the rows `ask(words, 10**9)` returns. For each budget, the budgeted answer plus its `more` chain until exhaustion must reproduce the same row set (recall 1.0 with handles) and report recall without handles (what the first answer alone holds). Output: a table per budget: questions, mean first-answer recall, recall with handles, mean bytes; `--json`. Exit 1 if recall-with-handles < 1.0 for any question (that would be a bug in `more`).

**Agent half (`wawe-eval --agent --repo <path> --out <out_dir> --questions N --model claude-sonnet-5`):** N questions with known answers derived from `framework_map.json` (where is X defined; who calls Y; which scenarios are tagged Z; which file serves route R), asked two ways through the Anthropic Messages API with tool use: (a) tools = the five map tools (MCP replies simulated in-process by calling `ask.py`/`declare.py`); (b) tools = `grep`/`read` over the repository (bounded to the repo, read-only). Score each answer against the known one (exact file:line or name match), record tokens in/out and tool calls, print a table and write `eval-agent.json`. Requires `ANTHROPIC_API_KEY`; refuses cleanly without it. Not run in CI.

**Proofs:** CI step runs `wawe-eval --map <fixture out> --questions 100 --budgets 350,1500` and asserts recall-with-handles 1.0 and prints the first-answer recall; the README number comes from that run (dated). The agent mode is proven once locally by the implementer on the `code` fixture with N=5 if a key is present in the environment; if not, the report says so and shows the refusal message.

### Task 3: release 1.2.0
CHANGELOG, versions, README rows, Python 3.12/3.13 CI green, tag.

### Task 4 (1.3.0): `callees` and `impact`

Two tools CodeGraph has and the map already holds the data for. Both read `framework_map.json`'s `call_graph_files` (`"<file>:<func>": ["<callee> (<file>)", ...]`, cross-file, Python + TS/JS + Go) and `call_graph` (`"<steps file>:<func>": ["<callee>", ...]`, behave steps), the same two graphs `callers` reads.

- `callees(map_json, name)`: every callee of the functions named `name` (exact, case-sensitive, `(` stripped), as `"<callee> (<file>)"` strings sorted; from both graphs. MCP tool `callees` (`name`: string or list), CLI `--callees NAME`.
- `impact(map_json, name, depth=3)`: transitive callers (the blast radius): every `<file>:<func>` that reaches `name` through the caller graph within `depth` hops, grouped by hop distance, each hop sorted; cycles handled; the total capped at 200 entries with a tail line and a `more`-style note (`… N more at depth d`); a cross-file-only caveat in the reply's first line. MCP tool `impact` (`name`, optional `depth` 1..6), CLI `--impact NAME [--impact-depth N]`.
- `ask()`: no new blocks (the tools answer directly; the answer budget is already spent).
- Both logged via `log_answer`; both in `TOOLS` with schemas like `callers`; plugin skill and README updated (eight tools); SCHEMA.md unchanged (no new keys).
- Proofs: on the poly fixture (b.ts:pay calls charge (a.ts); c.go:Run calls Serve (s.go)) and a hand-made three-hop Python fixture (a calls b calls c calls d, plus a cycle d calls b): `callees b` = c; `impact d` = depth 1: c, depth 2: b, depth 3: a, and the cycle does not loop; depth cap respected; `impact` of a name nobody calls says so; MCP and CLI byte-identical; `tools/list` = 8; a CI step "callees and impact walk the graph the map holds"; golden byte-identical (no ask change).
