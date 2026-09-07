# 1.6.0: answers the graph already holds

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. No `tests/test_*.py` files (a global hook forbids the model writing tests): every behaviour is proven by a live command in the report and a step in `.github/workflows/ci.yml`; `tests/golden/expected/` stays byte-identical unless the commit names the moved lines; golden maps regenerate only when a key is added.

**Goal:** 1.5.0 put three tables in `framework_map.json` that nothing yet reads end to end: `xrefs` (every edge with a resolution), `spans` (every declaration with its range) and `rank`. Every tool below is a read over those tables plus the keys the map already had (`steps`, `features`, `scenarios`, `routes`, `call_graph`, `most_changed`/git churn section). No new extraction, no new schema key except where stated, no LLM.

**Architecture:** one new module `src/where_are_we/graph.py` (stdlib) loads `framework_map.json` once and exposes pure functions over it: `affected(map, files)`, `reaches(map, name)`, `unreached(map)`, `path(map, a, b)`, `symbol_range(map, name)`, `dead(map)`, `hot(map)`. `ask.py`'s budget/tail/handle rules apply to every answer (whole rows, ceiling, `more:` handle). `mcp.py` `TOOLS` gains one tool per function; `cli.py` one flag each; `effects.py` classes them `read` and adds them to `NO_MAP_BUILD`. The traversal walks `xrefs` `calls` rows upward (callee to caller) with a visited set; behave step functions are the rows whose subject file is a step module (the map's `step_modules` / `steps` keys name them); a scenario is reached when one of its steps' functions is reached.

**Global constraints:** stdlib only; deterministic (sorted traversal, ties by path then line); Python 3.12+; no em dashes or en dashes in new prose; CI negations as `if cmd; then exit 1; fi`; every MCP tool has a CLI flag with byte-identical output; `tools/list` count moves from 11 and every pin in ci.yml moves with it; comments say what is there; commit trailers `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01Qt2xWwtUxwkeWyJt5hHgi7`.

---

### Task 1: `affected FILES` (test selection)

`affected(map, files, depth=6)`: from every `xrefs` row whose subject file is in `files` (repo-relative prefixes, the `--files` matching rule from 1.5.0), walk callers upward; collect step functions reached; map them through `steps` to scenarios and through `features` to feature files; also collect routes (`routes` key) whose handler is reached and page objects reached. Output blocks: `scenarios` (feature file, scenario name, the step that reaches the change, hop count), `features`, `routes`, `page objects`, then `unreachable from the graph` naming files in `files` that have no `xrefs` row (so the caller knows the answer is partial). A `--changed` form reads `git diff --name-only <ref>` (default `HEAD`) so the pipeline passes nothing. `--affected-format behave` prints a `behave` include list (`-i` regex or `--tags` when scenarios carry a unique tag; pick what the map holds and say which), `--affected-format pytest` prints node ids from `pytest_cases`. MCP `affected(files=[...], depth)`, CLI `--affected FILE[,FILE]`, `--changed [REF]`.

Proofs (CI step "a change names the scenarios that reach it"): on the suite golden fixture, changing `pages/checkout.py` names every scenario whose steps call a `CheckoutPage` method and no scenario that does not (compute the expected set independently in the step from `steps`/`features`/`xrefs` with a different traversal order); a file no row names lands in `unreachable from the graph`; `--changed` against a fixture git repo with one modified file equals `--affected <that file>`; depth cap respected; MCP and CLI byte-identical; handles recover every row at 1500.

### Task 2: `reaches NAME` and `unreached`

`reaches(map, name)`: scenarios and routes that reach a product function or class, with the path (hop chain) for the first scenario per feature. `unreached(map)`: product definitions (files under the product roots, not the suite) with no upward path to any step function, grouped by file, ranked by `rank`; with a tail and handle; a first line stating the graph's resolution rate so a reader knows how much of "unreached" is unknown rather than untested. MCP `reaches(name)`, `unreached(limit)`, CLI `--reaches NAME`, `--unreached`.

Proofs (CI step "the graph says what the tests reach and what they do not"): on the suite fixture a function called from a step is reached by the scenarios that use that step; a function called from nowhere is in `unreached`; `reaches` of an unknown name says so; `unreached` on the `code` fixture (no suite) says there are no steps to reach from; byte-identical runs.

### Task 3: `path A B`

Shortest call path from A to B over `xrefs` `calls` rows (BFS, sorted neighbours), printed one hop per line with the resolution of each edge and the line of the call site; `no path from A to B within N hops` otherwise, with the nearest reached names. MCP `path(a, b, depth)`, CLI `--path A,B`.

Proofs (CI step "path shows one chain, with how each hop was resolved"): the three-hop fixture from 1.3.0 gives a -> b -> c -> d with resolutions; a cycle terminates; an ambiguous edge on the path prints its candidate list; MCP and CLI byte-identical.

### Task 4: `range NAME`

`symbol_range(map, name)`: every `spans` site as `file:start-end kind`, the text of the shortest one under the budget, and the exact line numbers an editor needs (start, end, the line after end) so an agent's `Edit` can anchor without reading the file. MCP `range(name)`, CLI `--range NAME`. No write path.

Proofs (CI step "range hands an editor the lines it needs"): a name with two homes prints both; the printed end is the last line of the definition (`sed -n` shows the next line is dedented or blank); `end` unknown prints `?` and says why.

### Task 5: `dead` and `hot`

`dead(map)`: definitions with no incoming `xrefs` row, no route, no step decorator, not `main`/`__init__`/test entry points (the exclusion list stated in the answer's first line), grouped by file; the existing "Page-object methods nothing calls" section becomes a rendering of this. `hot(map)`: definitions ranked by `rank` score times churn from the map's most-changed-files section (files with no churn row count as 1), top N with both numbers shown. MCP `dead(limit)`, `hot(limit)`, CLI `--dead`, `--hot`.

Proofs (CI step "dead and hot read the graph and the history"): a function called from nowhere is dead; one referenced only from a route is not; `hot` puts a file with ten commits above an equal-rank file with one; the page-object section is byte-identical to before (golden expected unchanged).

### Task 6: pipeline hook and release 1.6.0

In `agentic-v-model` (separate dispatch, the user's parallel session works there: `git pull --rebase` before commits): the tester phase asks `affected --changed <base>` before choosing what to run, and the card for the tester names it; `mapfresh` unchanged. Prove with a flow simulation that the phase's command list contains the selection and that a change to one page object yields a subset run. In where-are-we: README rows and a section "What to re-run after a change", plugin skills, CHANGELOG `## 1.6.0`, version bump, `wawe-eval` re-measured, `tools/list` 18 with every pin, all gates.
