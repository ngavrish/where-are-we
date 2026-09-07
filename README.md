<div align="center">

# where are we

**Stop paying your agent to grep.**

[![PyPI](https://img.shields.io/pypi/v/where-are-we?style=flat-square&color=1a1a1a&labelColor=1a1a1a)](https://pypi.org/project/where-are-we/)
[![CI](https://img.shields.io/github/actions/workflow/status/ngavrish/where-are-we/ci.yml?style=flat-square&color=1a1a1a&labelColor=1a1a1a&label=ci)](https://github.com/ngavrish/where-are-we/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/MIT-1a1a1a?style=flat-square&labelColor=1a1a1a)](LICENSE)

</div>

One tree walk writes entry points, routes, data model, step signatures, and
every duplicate or dead test into `AGENTS.md` — or JSON for your own harness.
Your agent starts working at turn one, not turn 41.

## What you save

Measured on a real 184-feature `behave` suite and one production agent run:

| | Without the map | With the map |
|---|---|---|
| Orientation before real work | ~40 turns of `ls`/`find`/`grep` | 1 turn: one `--ask` |
| Repo context re-sent each turn | the map inlined, ≈ 64k tokens | a pointer, ≈ 212 tokens (**300× less**) |
| That context over one run | **27.4M tokens** — a quarter of the whole run | a few KB total |
| Budget it drained | a 5-hour allowance gone in **74 min** | the budget goes to work |
| Cost to build it | — | one tree walk: **10s**, offline, 0 tokens |

The map (121 KB) stays on disk to grep; a 616-byte pointer is what an agent
carries. You pay a ten-second tree walk once and stop paying for rediscovery on
every turn.

## What it does

One command turns a repository into a map an agent reads before it works: layers,
entry points, routes, data model, contracts, tests, and where every name is
defined. It reads the tree offline in seconds, and the same tree gives the same map every time.

Without it a session spends its first turns rediscovering the repo:

```console
# turn 1   ls; find . -name "*steps*"
# turn 7   grep -rn "def click_pay" .
# turn 19  cat conftest.py; cat tox.ini; cat Makefile
# turn 34  grep -rn "BASE_URL" .
# turn 41  first line of actual work
```

With the map, turn 1 is the work. Measured on a real suite: forty-odd orientation
turns become one `--ask`, and the agent reads an 849-byte pointer instead of
grepping a repository it has not seen.

```console
$ where-are-we --repo . --agent-file AGENTS.md --max-lines 200

framework map: 66 step modules, 1359 steps, 179 features, 1782 scenarios -> ./framework_map.md
```

`AGENTS.md` gets a pointer - 849 bytes, not the map:

```markdown
## The framework map

`framework_map.md` (123 KB) is a generated map of this suite and the product it
tests. It is on disk on purpose: read from it, do not carry it. Ask it before
grepping the repository — it already knows.

    where-are-we --ask "the words you need"

That prints only the rows that mention those words, whole, and says how much of each section it left out. `--sections` lists what
is in it.

It has these sections:

- Where things are
- What a step may call
- Steps that overlap (14 pairs) — check whether one already does what you need
- What past runs measured (slowest first)
- …
```

And the map answers questions instead of being read:

```console
$ where-are-we --ask "refund settled invoice"

## What past runs measured (slowest first)
- `billing/`
  - `refund.feature:88` Refund a settled invoice — ~252s, failed 3×
  - `credit_note.feature:12` Refund a settled invoice by credit note — ~40s
… 61 rows in this section do not mention these words

## Steps that overlap (14 pairs)
- 0.88: "the invoice is settled" (`billing_steps.py`) ≈ "an invoice has settled" (`api_steps.py`)
… 2 more matching rows; 11 rows in this section do not mention these words
```

An answer is whole rows, never a row cut in the middle, and it fits the limit it
was given (12,000 characters for the CLI and the MCP) rather than filling it.
Rows under one directory are printed under it once. Each section ends by saying
what it left out — how many matching rows did not fit, and how many rows did not
mention the words at all — so the reader knows whether to ask again with more
words or to open `framework_map.md`.

## As a Claude Code plugin

    /plugin marketplace add ngavrish/where-are-we
    /plugin install where-are-we@where-are-we

The plugin builds the map at session start, puts its pointer into the session's
context, serves the map's tools over MCP (`ask`, `find`, `defines`,
`sections`) and ships five skills. It needs `where-are-we` on PATH
(`pipx install where-are-we`). Details in [plugin/README.md](plugin/README.md).

## Everything it does, and what it is measured to save

Each row names what the tool does and what that is measured to save. Where a
number exists it is cited; where none exists the row says so and names the
measurement that would settle it. Numbers come from one real run unless said
otherwise: a 184-feature behave suite and one production agent run
(1,409 turns, $59.65), read from that run's event log. Estimates are marked
as estimates.

### The map itself

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| One tree walk → `framework_map.md`, `framework_map_brief.md`, `framework_map.json` | Indexes layers, entry points, routes, data model, public surface, call graph, steps, scenarios, fixtures, CI, duplicates, dead code, every declared name with its line. Declarations are indexed by dedicated regex for Python, TypeScript/JavaScript, Rust, Kotlin, C# and Ruby (a tree-sitter parse tree instead, for the languages it has a grammar for, where `pip install "where-are-we[precise]"` is present), and by a generic pattern for anything else | Build: ~10 s on the 184-feature suite, offline, 0 tokens (README). 75 sections on this repository, 28 on the demo suite | — |
| Deterministic output | Same tree, same map, byte for byte | `tests/golden/check.py` (CI step `golden`): two builds of three fixture trees are byte-identical on every CI run; 150 `ask` cases pinned | n/a |
| `schema: where-are-we/1`, stable JSON contract (`SCHEMA.md`) | Sections may be added within a major; existing shapes keep | Not measurable; a promise | Consumers: any agent runner that reads the JSON (`find_text`, `_definitions_for`) |
| Fingerprint (`<commit>:<newest mtime in nanoseconds>`) and `--force` | A build is skipped when the tree has not moved. The mtime keeps the precision the filesystem reports, so an edit inside the same second as the build before it is still seen, and it covers every file the map indexes rather than a fixed list of extensions, so an edit to a `.go`, `.rs`, `.kt`, `.cs`, `.rb`, `.java`, `.yaml`, `.tf` or `.proto` file is seen too | Not measured | CI steps `idempotent` (two builds of the same tree, the second prints `unchanged since it was built`), `an edit in the same second as the build is still seen`, and `the fingerprint watches exactly the files the map indexes` (five languages edited in turn, each one rebuilt) |
| Incremental rebuild: `_cached()` around every `ast.parse`, tree-sitter parse and declaration scan, keyed by path, kind, mtime and size (`--force` reads nothing from it and rewrites it; `WAWE_NO_CACHE=1` neither reads nor writes it) | A rebuild only re-parses the files that actually changed since the last build in the same `--out`. `--force` parses everything again, because mtime and size cannot tell a same-size rewrite that kept its timestamp from no change at all | Measured 2026-09-05 on this repository (366 files parsed): cold build 1.05 s, warm build 0.80 s, warm build after touching one module 0.84 s, `--force` 1.09 s. `WAWE_DEBUG_PARSES=1` printed `parsed 366 files` cold, `parsed 0 files` warm, `parsed 4 files` after touching one module, `parsed 366 files` under `--force`, and `parsed 0 files` again on the build after that `--force`. Map output identical with and without the cache (`tests/golden/check.py`, plus a `WAWE_NO_CACHE=1` build diffed byte for byte against a cached one, fingerprint excluded) | — |
| `## This map is incomplete` | What a bound cut (file count, spec depth) is named at the top of the map | Not measured; a correctness feature: an answer of "absent" is never given past a bound | Count answers that say "indexed: …" per run |
| Every artefact written to a temporary and renamed into place | Nothing ever reads a half-written map, and a build killed mid-write leaves the previous one whole. Covers `framework_map.{json,md,html}`, the brief, `spec_map.*`, `semantic_index.{npy,json}`, `.wawe-cache.json`, `.pointer-head`, and the two files written outside `--out`: the agent file and `.framework-map.json`. The start-of-build sweep of a dead writer's temporaries covers what lives in `--out`, which is everything but those last two: a build knows where its output directory is and does not know where a previous run was told to put an agent file | Measured 2026-09-05 on a 3,000-file repository: a reader polling sizes through a build saw 26 zero-byte hits on `framework_map.json` before and none in 4.2 million reads after; six readers calling `defines` and `ask` through a rebuild loop saw 4 unparseable JSON reads and 4 empty `defines` answers before and none after; SIGTERM at the first touch of the map files left a zero-byte JSON beside a stale `.md` before, and the previous three files byte for byte after | CI step `every artefact is replaced, never truncated in place` |
| Every file read is bounded | `_slurp` reads at most 400 KB for a scan and `_slurp_source` at most 2 MB for a parser, once per (path, limit) and cached, so a build costs the limit rather than the size of what it walks. A file a parser only saw part of is named in the map | Measured 2026-09-06: a 198 MB `.py` cost 785 MB of peak RSS and 3.97 s before, 39 MB and 0.19 s after; a 196 MB `.ts` cost 590 MB and now 29 MB; a `.py` and a `.ts` together cost 1171 MB and now 42 MB | CI steps `a very large file costs the read limit, not its size` and `a large module is parsed, not silently dropped` |
| An optional source that misbehaves does not end the build | `--runs-api`, `git log` and `git blame` are history the map is better with and fine without, so a tracker answering something that is not HTTP, or an author name the locale cannot decode, costs that section and not the run | Measured 2026-09-06: a socket answering `GARBAGE NOT HTTP` exited 1 with a `BadStatusLine` traceback and wrote no map before, and exits 0 with a map after; `LC_ALL=C` with the author `Renée Müller` exited 1 with `UnicodeDecodeError` before, and after writes `blame_owners {'a.py': ['Renée Müller (1)']}`, the name exact | CI step `an optional source that misbehaves does not end the build` |
| A symlink or a pipe in the tree is not read | A file whose link resolves outside the repository is skipped, so nothing outside it is copied into a map that gets committed and pasted into prompts, and anything that is not a regular file is skipped, so a FIFO does not block the build forever. A link that stays inside the repository is still followed, and the map says what it left out | Measured 2026-09-05: a `passwd.py` symlinked to `/etc/passwd` put the whole file into the map's line index before and is absent after; a FIFO named `x.py` hung the build past a 60 second bound with nothing written before, and after it finishes and indexes its sibling | CI steps `a symlink out of the repository is not read into the map` and `a pipe does not hang the build, and dead temporaries are swept` |
| `.wawe.toml`, `.wawe-ignore`, `WAWE_MAX_FILES`, `WAWE_JUNIT_DIRS` (os.pathsep separated; default: the repository's own `reports`, `test-results`, `junit`, `build/test-results`, plus `/runs`, never `/tmp`) | A project states its invocation, exclusions and where its JUnit history lives once. `.wawe.toml`'s `[synonyms]` table adds a project's own words to `--ask`'s built-in groups | Not measured | — |
| `--product`, sibling guessing only for a suite, `--product none` | The application under test is indexed beside its suite; a plain code repository does not index its neighbours | Measured 2026-09-03 on this repository: before the fix the map held 231 files of three unrelated sibling repositories (3.1 MB JSON, `defines` answering with their paths); after, `indexed: suite 75`, 818 KB | — |
| `--also` | Fold other repositories into one map | Not measured | — |
| `--diff` | What changed since the map already in `--out` | the pointer names what moved since the last session; CI step "pointer says what changed since the last session" proves it | — |
| `--watch SECONDS` | Rebuild whenever the tree moves: a full rebuild each time, writing every artefact a one-shot build writes, and an iteration that raises is printed and the loop carries on | Not measured | CI step `--watch rebuilds whole, writes every file, and survives a failure`: twenty files added while watching all reach the map, a deleted name leaves it, `framework_map.md` and `--html` are written, and replacing the output directory with a plain file prints `rebuild failed, still watching` without ending the watcher |
| `--html` | The brief as a page | Not measured | — |
| `--init` → `.framework-map.json` manifest | A starter manifest the map reads `stated` facts from | Not measured | — |

### What an agent carries vs what it asks

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| The pointer (`--pointer`, `--agent-file`) | ~600–850 bytes in the prompt naming the map, its sections and how to ask; the map stays on disk | Map inlined: ≈ 64k tokens re-sent every turn, 27.4M tokens over one run, a quarter of that run; pointer: ≈ 212 tokens (300× less); a 5-hour allowance gone in 74 min vs the budget going to work (README, measured on one production run) | — |
| Orientation replaced by one `--ask` | The first turns of a session stop being `ls`/`find`/`grep` | ~40 orientation turns → 1 on the measured suite (README) | — |
| `--ask` / MCP `ask`: whole rows, ranked sections, honest tail | Only rows that mention the words, never a cut row, `limit` a strict ceiling, "… N more matching rows (more:rows:...); M rows do not mention these words" - the tail names what was left out and carries the handle `more` fetches it with | Before 0.12: an answer could exceed its limit 68× (3 KB head at limit 50) and cut a row mid-word; after: ≤ limit on every golden case (150), 5/5 fixture checks. `.wawe/.wawe-ask.log` records every answer; `wawe-measure --ask-log .wawe` prints median/p95/max tokens | — |
| `more` (MCP), `--more HANDLE` | What an answer left out, by the handle it printed: a section's unshown rows, the rows in it that never matched, definitions past the block's cap, the sections that did not fit, `find`'s hits past its limit. Stateless: the handle names a section, the words and a position, and `more` recomputes the ranking from the map on disk, so a rebuilt map answers "no such handle in this map" rather than a slice of some other list | Measured 2026-09-07 on the `suite` golden fixture, question "invoice checkout": chasing the handles from `ask(..., 1500)` to exhaustion returns all 167 rows the unbudgeted answer holds, in 10 calls; from `ask(..., 12000)`, 167 in 1 call. At 350 characters, 166 of 167 - the missing row is 446 characters long and cannot fit in a 350-character answer, and `more` says so | — |
| `--ask` synonyms and stemming | "login" also searches "signin", "auth"; "invoices" also searches "invoice"; a synonym or a stem scores at half the weight of the literal word, so it never outranks an exact hit; the first line says `(also matched: signin, auth)` when an expansion found something the literal words did not; `.wawe.toml`'s `[synonyms]` table adds a project's own words to the built-in groups | Not measured | — |
| Rows under one directory printed once | `- \`features/checkout/\`` then the files | Not measured | Bytes of an answer before/after on a 40-row directory |
| `## Defined here` (`defines`, `_definitions_for`) | A name → file:line, every declared name in every walked file | Not measured as turns saved; the README's claim is one question instead of `grep -rn` | Count `Grep` calls per session before/after (the run's call events) |
| Cross-file call graph (`call_graph_files`) | Function to callees defined in another file, Python by AST, TypeScript, JavaScript and Go by pattern. An edge is `charge (a.ts)` where exactly one indexed file defines the callee and `charge (a.ts)?` where several do, since the file named is then whichever the walk reached first. `callers`, `callees` and `impact` match on the name alone and print the mark as they find it | Measured 2026-09-07 on this repository's own map: 40 of the edges under its 60 keys carry the mark, `cli.py:main -> build (ask.py)?` among them, which names the wrong `build` | Count `Grep` calls spent chasing a callee across files before/after |
| `wawe-eval --map OUT --graph`, `call_graph_stats` | How much of the call tree the walk resolved, per language group: callee names looked at, names placed in a file, names several files define, and the two fractions. `--json` carries it. With the `precise` extra it parses the TypeScript, JavaScript and Go again with tree-sitter and prints the delta | Measured 2026-09-07. suite fixture: python 85 sites, 40 resolved, rate 0.4706, 0 ambiguous. code fixture: python 7 sites, 0 resolved, rate 0.0. poly fixture: ts_js 3/3 and go 5/5, rate 1.0 each, and tree-sitter says 1 and 2 sites for the same code, so the pattern pass counted 5 things that were not calls. This repository: python 2185 sites, 517 resolved, rate 0.2366, 102 ambiguous (share 0.0467); ts_js 2/2; go 3 sites, 2 resolved, rate 0.6667 | - |
| `callers` (MCP), `--callers`, "Called by" in `ask` | Who calls a name, the other direction of the call graph: every `file:func` that mentions it, exact and case-sensitive | Not measured as turns saved; the claim is one lookup instead of grepping every file for a call site | Count `Grep` calls spent finding call sites before/after |
| `callees` (MCP), `--callees` | What a name calls, the other direction of `callers`: every callee with the file it is defined in, from the same two graphs, cross-file only | Not measured as turns saved; the claim is one lookup instead of reading the function to find out what it reaches | Count `Read` calls spent opening a function to list its calls before/after |
| `impact` (MCP), `--impact NAME [--impact-depth N]` | The blast radius of a name: every `file:func` that reaches it within N hops (1 to 6, 3 by default), grouped by hop and sorted inside each. A visited set walks a cycle once, and the keys defining the name itself are the change rather than its radius. The first line of every reply states the rules the answer was built under, unconditionally: hops are followed by name, so where several files define one name their callers are unioned; only cross-file calls are in the graph; and the map keeps at most 60 cross-file and 120 step graph keys, so on a large repository the radius is a floor. Where the key data shows the clash a `note:` names up to five of the keys and how many more. Capped at 200 `file:func` entries in the whole reply, note keys included, with a line naming how many are left and at which depth; no handle to fetch them, because the tool already takes a depth and narrowing is the reader's move. A depth outside 1 to 6 is refused: exit 2 on the command line, JSON-RPC -32602 on the tool | Not measured as turns saved; the claim is one lookup instead of running `callers` outward by hand, hop after hop | Count `callers` calls per session before/after |
| `find` (MCP) | Where a phrase or string lives, with the line | Not measured | Same |
| `sections` (MCP), `--sections` | The headings, now map + brief (75 vs 3 before 0.12.1) | Measured 2026-09-03: a code repository's `--sections` went from 3 empty suite headings to 75 | — |
| `wawe-eval` | Generates questions from the map, asks each at no budget to get the rows the map holds for it, and reports what a budgeted answer shows of those, three ways: macro (per question), pooled (all rows), and over the five rows that ranked highest, plus a count of the rows too long to print at that budget at all. With `more` in the build it also reports what the answer plus its handles reaches | Measured 2026-09-07 on the suite fixture, 100 questions, seed 0: first-answer recall 0.476 / 0.857 / 0.9999 at 350 / 1500 / 12000 bytes; pooled 0.105 / 0.305 / 0.999; top-5 0.725 / 1.000 / 1.000; 34 / 0 / 0 rows longer than the budget; mean answer 303 / 885 / 2051 bytes. Recall with handles, over the rows that fit, is asserted 1.0 by the CI step `wawe-eval: the budget loses no row the map holds`, which exits 1 on any such row a handle fails to return, from the release that adds `more` onwards | `--agent` compares the map tools against grep and read on the same questions; not run in CI |
| `--for author|coder`, `--only`, `--skip`, `--max-lines` | A brief tailored to who reads it; capped per section | Not measured in tokens; the per-section cap keeps every head (3×50 rows at 30 lines → every head present, before: the last sections dropped) | Token count of the brief per audience |

### The other map

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| `--specs`, `--spec-cmd`, `--spec-source`, `--spec-depth`, `--spec-limit` → `spec_map.md/json` | A ticket and its links two hops out, from any command that returns JSON, or from `--spec-source github\|linear` with no command to write | Not measured | Turns spent fetching tracker pages before/after |
| `ask` over both maps | One question, answers from code and spec | Not measured | — |

### Semantic answers (optional extra)

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| `pip install "where-are-we[semantic]"` — embedding index, "Related by meaning" tail | Keyword hits plus nearest paragraphs by meaning | Not measured for answer quality | An A/B of questions with and without the tail |
| `--corpus NAME=PATH` | External corpora (rules, runbooks) in the same index | Not measured | — |
| `WAWE_EMBED_CACHE` | Embeddings cached across builds in one sqlite file | Full five-corpus build: 6 min → about 30 s, five and a half minutes were recomputing unchanged vectors (CHANGELOG 0.11.0) | — |
| `WAWE_EMBED_MODEL`, `WAWE_RERANK_MODEL`, `--no-semantic` | Model choice; skip the index | Not measured | — |

### Docs the repository is missing

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| `where-are-we --docs plan|write` | Drafts a README per directory that lacks one, from the map's facts, with a `TODO:` for the purpose only a human knows | Not measured | `wawe-readmes --repo .` (or `--docs plan`) prints the count: "N README files would be written" |
| `wawe-readmes` | The same drafts as one command (both call `readmes.describe`; `--docs` is the map-aware wrapper): `--repo`, `--write`, `--help`; lists by default, writes only with `--write` | Fixed in 0.12.3: until then the entry point parsed no arguments and wrote into `$AGENT_REPO` unasked | — |

### Ways in

See it on a repository you know: [FastAPI 0.115.0 mapped](https://ngavrish.github.io/where-are-we/demo/fastapi/).

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| CLI `where-are-we` | Everything above | — | — |
| MCP server (`--mcp`): `ask`, `find`, `defines`, `sections` | The map as tools, stdio | On the measured production run: 194 map calls vs 68 repository searches (call events of that run) | — |
| LSP server (`--lsp`): `textDocument/definition`, `workspace/symbol` | The map as an editor's language server, `Content-Length` framed stdio | Not measured | - |
| Library: `build`, `brief`, `digest`, `init_manifest`, `main` | Python API | Not measured | — |
| GitHub Action (`ngavrish/where-are-we@v1`): inputs `repo`, `product`, `out`, `agent-file`, `comment`; outputs `brief`, `summary` | Map on CI, optional PR comment | Not measured | — |
| pre-commit hook | Rebuild on commit so a map is never stale | Not measured | — |
| `--install-hook git|claude|cursor|codex|gemini` | `git`: post-checkout/merge/commit hooks that rebuild; `claude` (`agent` is the same thing): a SessionStart hook for an agent harness (distinct from `--agent-file`, which writes the brief into a file); `cursor`: a Cursor rule at `.cursor/rules/where-are-we.mdc` plus `.cursor/mcp.json`; `codex`: an `AGENTS.md` block plus `~/.codex/config.toml`; `gemini`: a `GEMINI.md` block plus `.gemini/settings.json`. `cursor`, `codex` and `gemini` build the map into `.wawe` first if it is not already there; `git` and `claude` do not, since they already build into whatever `--out` was passed on their own first trigger, and a pre-build for them would be a second map in a different place. Each kind installs all of its files or none: every target is checked before the first write, and a refusal names the cause | Not measured | — |
| Claude Code plugin (`/plugin marketplace add ngavrish/where-are-we`) | SessionStart builds `.wawe/` and hands the session the pointer; the eight tools over MCP (`ask`, `find`, `defines`, `sections`, `callers`, `callees`, `impact`, `more`); skills `orient`, `ask`, `where-defined`, `spec-map`, `readmes`; `WAWE_STRICT=1` refuses repository searches. Installed from the marketplace the tools are named `mcp__plugin_where-are-we_where-are-we__{ask,find,defines,sections,callers,callees,impact,more}`; under `--plugin-dir` the prefix differs, so prompts name the server `where-are-we`, not the prefix | Verified 2026-09-03 in a fresh repository: hook built the map, tools answered, pointer reached the context. Turns saved not measured | Sessions with vs without the plugin: `Grep`/`Glob`/`Bash grep` counts |
| Packages: PyPI wheel + sdist, deb (apt repo with key), rpm, Homebrew tap, GitHub release with SBOM (SPDX) and sigstore signatures | Install anywhere | — | — |

### Honesty features (not savings, guarantees)

| Feature | Guarantee |
|---|---|
| `no match for … indexed: product N files, suite M files` | An absence names what was searched; it is not a claim the thing does not exist |
| `## This map is incomplete` | Every bound that cut is written at the top |
| Whole rows, a ceiling, a tail | An answer never pretends to be complete: what was left out is counted |
| The map says what it maps | "a map of this repository" vs "of this suite and the product it tests", from the map's own counts (0.12.2) |
| A map file is never torn | Every artefact is written to a temporary and renamed into place; a reader sees the previous map or the new one, never a half-written one, and a build killed mid-way leaves the previous map intact (CI step `every artefact is replaced, never truncated in place`) |
| The servers stay up | MCP and LSP answer malformed `params`, `arguments` or `limit` with a JSON-RPC error and keep serving; both exit quietly when stdout closes (CI steps `mcp malformed params...`, `lsp malformed params...`, `mcp and lsp exit 0 quietly when stdout closes early`) |
| `--html` escapes repository content | A docstring or a file name holding markup renders as text on the page (CI step `--html escapes repository content instead of interpolating it`) |
| `--install-hook` is one unit | Every target is checked before any is written; a refusal installs nothing and names its cause, a rerun finishes the job (CI step `install-hook git refuses a symlinked hook file`) |
| A source in UTF-16 is read | A file with a byte order mark is decoded, indexed and answerable; a binary that merely starts with one is not (CI step `a UTF-16 source file is decoded, indexed and answerable`) |
| An edge the map is guessing at says so | A cross-file callee two or more files define is written `charge (a.ts)?`; the file half is whichever the walk reached first, and the question mark is the map declining to pass a guess off as a lookup. Every `impact` reply states the rule (CI step `an edge whose callee two files define is marked, and matched without the mark`) |
| The graph says how much of the tree it resolved | `call_graph_stats` counts, per language, the callee names the walk looked at, the ones it could place in a file and the ones several files define, over the whole walk rather than the 60 keys that survive the cap. `wawe-eval --map OUT --graph` prints the rates, and with tree-sitter installed prints what a real parse makes of the same code beside them (CI step `wawe-eval --graph: the map says how much of its call tree it resolved`) |

### How to measure it on your own sessions

`wawe-measure` reads Claude Code's own transcripts (`~/.claude/projects/<project>/<session>.jsonl`)
and counts, per session, how many turns were spent looking around versus doing
something else:

```bash
pip install where-are-we
wawe-measure --since 2026-09-01           # table, one row per session, a median row
wawe-measure --since 2026-09-01 --json    # the same rows as JSON
wawe-measure --sessions /path/to/jsonls   # a directory of transcripts instead of ~/.claude/projects
```

Definitions:

- A *turn* is one assistant message.
- A *search* is a `Grep` or `Glob` tool call, or a `Bash` call whose command
  starts with (after an optional `cd ... &&`) `grep`, `rg`, `find`, `ls`,
  `ag`, `ack`, `fd` or `tree`.
- A *map call* is a tool call whose name contains `where-are-we` (the MCP
  tools) or a `Bash` call whose command contains `where-are-we --`.
- *orientation_turns* is how many turns went by before the agent did
  something other than look around (an edit, a write, a test run): the
  count of turns before the first turn with a non-search, non-read, non-map
  tool call.

Measured 2026-09-05, `wawe-measure --since 2026-09-01` against 30 sessions on
this machine (one developer, several projects, not a controlled run):

| | sessions | median searches | median orientation_turns |
|---|---|---|---|
| with a map call | 5 | 5 | 3 |
| without a map call | 25 | 1 | 2 |

Five sessions used the map at all in this window, and those five ran longer
and searched more, not less: this is one developer's mixed transcripts, not
a before/after comparison, and settling the "orientation replaced by one
--ask" claim above needs matched sessions on the same task, one with the map
and one without.

## Does the budget lose answers

Every answer `ask` gives is cut to a byte budget. `wawe-eval` measures what
that cut costs. It generates questions from the map itself (every declared
name, every step phrase's distinctive word, the longest word of every
section heading), asks each one at no budget at all to get the rows the map
holds for it, and then asks it again at each budget.

**First-answer recall is the share of the rows of the full answer that the
budgeted answer shows before any `more`, averaged over the questions.**

```bash
wawe-eval --map .wawe --questions 100 --budgets 350,1500,12000
```

Two averages are published, because they answer different questions and
neither is "the" recall:

- **first-answer recall** is the macro average: each question's recall is
  computed, then those are averaged, so a question with two rows counts as
  much as a question with three hundred. This is the number for "what does a
  typical question lose".
- **pooled recall** is the micro average: all rows shown over all rows there
  were, so the biggest questions dominate. This is the number for "what
  share of everything the map could have said was said".
- **top-5 recall** is rank aware: `ask` ranks what it shows, so this is the
  share of the *first five* rows of the full answer that survived the cut,
  averaged per question. It is the number for "was the answer at the top
  still there".
- **rows over budget** is not a recall at all. It counts reference rows
  longer than the whole budget, which nothing can print at that budget: not
  the first answer, and not `more`, which reports such a row rather than
  skipping it. On the suite fixture one 446 character row does this, and it
  turns up in 34 of the 100 questions at 350 bytes and in none at 1500.
  These rows count against first-answer recall, because a reader who asked
  for them did not get them; they are left out of the recall the exit code
  asserts, because that one is about rows a handle could have returned.

Measured 2026-09-07 on the three golden fixtures with `more` in the build,
100 questions per fixture (fewer where the map has fewer), seed 0, built
under the fixed root `/tmp/wawe-eval` the CI step uses:

| fixture | questions | budget | first-answer recall | pooled recall | top-5 recall | recall with handles | rows over budget | mean bytes |
|---|---|---|---|---|---|---|---|---|
| suite | 100 of 285 | 350 | 0.429 | 0.089 | 0.632 | 0.981 | 34 | 303 |
| suite | 100 of 285 | 1500 | 0.839 | 0.288 | 1.000 | 1.000 | 0 | 973 |
| suite | 100 of 285 | 12000 | 0.9996 | 0.997 | 1.000 | 1.000 | 0 | 2220 |
| code | 12 of 23 | 350 | 0.756 | 0.585 | 0.785 | 1.000 | 0 | 263 |
| code | 12 of 23 | 1500 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 413 |
| poly | 10 of 21 | 350 | 0.733 | 0.656 | 0.753 | 0.983 | 0 | 277 |
| poly | 10 of 21 | 1500 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 367 |

Read the suite row at 350 bytes together: a 303 byte answer holds under
half of what a typical question could have said and a tenth of every row
across all of them, and about two thirds of the five rows that ranked
highest. That is the shape of the cut. It is not a claim that nothing was
lost.

The claim that nothing is lost belongs to `more`, the tool that fetches what
a tail line says was left out. `recall_with_handles` counts the rows that
fit the budget after every `more:` handle in the answer has been followed,
and every handle in the replies after that. At 1500 bytes, the MCP server's
floor, and above, it is 1.000 on every fixture: the budget cuts the first
answer, the handles give all of it back. At 350 it is 0.98: an answer that
small cannot always hold a row and the handle that points at the rest, so
`wawe-eval` asserts 1.0 only from `--assert-from` (default 1500) and prints
the smaller budgets. The CI step `wawe-eval: the budget loses no row the map
holds` is that exit code.

### How much of the call tree the graph resolved

The cross-file call graph is built by name: a callee is placed in the file
the walk saw declare it. `call_graph_stats`, a top-level key of
`framework_map.json`, counts what that came to, per language group: `sites`
is the callee names the walk looked at, one per function per distinct name;
`resolved` is how many of them it could place in an indexed file at all; and
`ambiguous` is how many had more than one file to choose from, which are the
edges written with a trailing `?`. The counts are taken over the whole walk,
before `call_graph_files` is cut to its 60 keys, so the rate measures the
walk rather than the cap.

```bash
wawe-eval --map .wawe --graph          # a table
wawe-eval --map .wawe --graph --json   # the same numbers as JSON
```

Measured 2026-09-07, the three golden fixtures built under `/tmp/wawe-graph`
and this repository mapped with `--product none --no-semantic`:

| map | language | sites | resolved | ambiguous | resolution rate | ambiguous share |
|---|---|---|---|---|---|---|
| suite fixture | python | 85 | 40 | 0 | 0.4706 | 0.0 |
| code fixture | python | 7 | 0 | 0 | 0.0 | 0.0 |
| poly fixture | ts_js | 3 | 3 | 0 | 1.0 | 0.0 |
| poly fixture | go | 5 | 5 | 0 | 1.0 | 0.0 |
| where-are-we | python | 2185 | 517 | 102 | 0.2366 | 0.0467 |
| where-are-we | ts_js | 2 | 2 | 0 | 1.0 | 0.0 |
| where-are-we | go | 3 | 2 | 0 | 0.6667 | 0.0 |

The code fixture's 0.0 is the honest reading of a repository whose only
calls are into `argparse` and a decorator: nothing it calls is declared in
it, so the graph has no edges and says so. This repository's 0.2366 is what
a real Python tree looks like when most of what a function calls is a
standard library name or a method on an object, and its 102 ambiguous names
are the ones the `?` mark is for: `cli.py:main -> build (ask.py)?` names the
wrong `build`, and the map no longer pretends otherwise.

With `pip install "where-are-we[precise]"` the same numbers are computed
again for the TypeScript, JavaScript and Go from a tree-sitter parse and
printed beside the pattern pass:

```
regex vs tree-sitter, go: sites 5 vs 2 (-3), resolved 5 vs 2 (-3), rate 1.0 vs 1.0 (+0.0)
regex vs tree-sitter, ts_js: sites 3 vs 1 (-2), resolved 3 vs 1 (-2), rate 1.0 vs 1.0 (+0.0)
```

That is the poly fixture, and the gap is the pattern pass admitting what it
over-counted: its body scan starts at the signature line, so a function's
own name reads as a call, and `if (` reads as one too. Without the extra the
line says so and the run carries on.

`--agent` is the other half: the same questions asked through the Claude API
twice, once with the map tools and once with grep and read over the
repository, scored against answers taken from `framework_map.json`. It needs
`ANTHROPIC_API_KEY` and `pip install "where-are-we[eval-agent]"`, refuses
cleanly without them, costs money, and is not run in CI. How to read the
table and how to run the A/B: [`docs/examples/eval.md`](docs/examples/eval.md).

## Command line

A CLI is the tool. `pip install where-are-we` gives two commands:

- `where-are-we` — build the map and answer from it.
- `wawe-readmes` — offer a repo the docs it is missing.

```bash
where-are-we --repo . --agent-file AGENTS.md   # build the map, drop a pointer
where-are-we --ask "refund settled invoice"    # answer from an existing map
where-are-we --install-hook git                # rebuild on checkout/merge/commit
```

Every flag is under **All options** below; the map also answers over MCP
(`--mcp`) and as a library.

## Where is it defined

```console
$ where-are-we --ask "MAX_PERSISTED_FORECAST_RESULTS"

## Defined here

- `MAX_PERSISTED_FORECAST_RESULTS` — src/constants/forecastStorage.ts:31
```

Every name in every file the walk reaches, with its line — functions, classes,
constants, types, step phrases, scenario names. A question about a name is a
question about where it is, and an answer without the line sends the reader to
grep for it anyway.

When a name is not there, the answer says what was indexed rather than declaring
the absence real. A map that overstates its reach turns "I did not look" into
"it is not there".

## The other map: the specifications

A codebase is not the only thing an agent gropes around in. The other is the
tracker — the ticket, its parents, what it links to, what mentions it — and it
gropes there the same way and for the same reason: no map, so it asks, and asks
again.

Measured on one run of a real pipeline: sixteen tickets fetched over and over.
One agent pulled fourteen neighbours to understand the task; the next agent
pulled the same fourteen again, because a session cannot see another session's
memory. Three were fetched three times inside a single session, since finding an
answer already in a conversation costs more than asking for it fresh. Every
answer then sat in the context for ever, and every later turn paid to re-read it.

```console
$ where-are-we --specs APF-1934 --spec-cmd 'python3 fetch.py {key}'

  APF-1934 (1 so far)
  APF-1860 (2 so far)
  APF-2752 (3 so far)
spec map: 3 ticket(s) -> ./spec_map.md
```

This tool knows nothing about any tracker, which is the same contract as the rest
of it: you hand it a command that turns a ticket key into JSON, it walks the
links two hops out, and it writes `spec_map.json` and `spec_map.md`. Jira, Linear,
GitHub Issues, a text file — it never finds out.

Two trackers it does not need a command for: `--spec-source github` builds the
`gh issue view {key} --repo owner/name --json ...` call itself, reading
owner/name off the repository's `origin` remote; `--spec-source linear` builds
the GraphQL call over `curl` and needs `LINEAR_API_KEY` set. Either way
`--spec-cmd` is filled in rather than typed.

`--ask` answers from both maps, because a question about a piece of work is as
likely to be about what was asked for as about where the code is.

## What a map leaves out, it says

Both walks are bounded, because a repository and a tracker are both graphs and a
graph will hand over everything if asked. What the bound cut is named in the map
itself, at the top:

```markdown
## This map is incomplete

- the file walk stopped at 40000 files under /work — raise WAWE_MAX_FILES or add
  to .wawe-ignore; what is below that count is mapped and the rest is not
```

A limit that stops quietly produces a map that looks complete and is not, and the
reader has no way to tell — which is worse than a small map, because a small map
that says so can be asked to grow. An absence in a silent map reads as a fact
about the codebase.

| flag | bounds |
|---|---|
| `--spec-depth` | hops from the starting ticket (2) |
| `--spec-limit` | tickets fetched at most (60) |
| `WAWE_MAX_FILES` | files read from the repository (40000) |
| `.wawe-ignore` | paths never read at all |

## Why install it

- **The first forty turns stop repeating.** The answers never change between
  sessions and need no model to produce, so produce them once and commit them.
- **A step that exists stops being written twice.** Overlapping phrases, dead
  phrases and uncalled page-object methods are listed by name.
- **It reads a repo it has never seen.** Detection is by shape, not directory
  name: a page object is a class that owns selectors, wherever it lives.
- **It costs a tree walk.** 3s on a 6k-file repo, 2.5min on a 36k-file one,
  cold. Deterministic — same tree, same map, no API bill.

## Install

```bash
pip install where-are-we
pip install "where-are-we[semantic]"   # + local embeddings for a semantic --ask
brew tap ngavrish/tap && brew install where-are-we
curl -fsSL https://ngavrish.github.io/where-are-we/install.sh | sh
```

macOS, Debian 13, Ubuntu 24.04, Fedora, RHEL (any of them with Python 3.12 or newer). Or `ghcr.io/ngavrish/where-are-we`. The
`[semantic]` extra adds fastembed (ONNX on CPU, no service, no database); without
it `--ask` still answers by keyword.

Needs Python 3.12 or newer (stdlib only, no dependencies to install alongside
it); 3.10 and 3.11 are no longer supported.

## Output

| File | Contents |
|---|---|
| `framework_map_brief.md` | the digest for a prompt |
| `framework_map.md` | every step phrase, every scenario with its line number |
| `framework_map.json` | the same as data, under a versioned contract |

`--agent-file` writes a **pointer** into `AGENTS.md`, `CLAUDE.md` or
`.cursorrules` between markers. The rest of the file survives.

### Why a pointer and not the map

A prompt is re-sent in full on every turn — that is what a conversation is — so
anything put in one is paid for on every turn of the session, read or not.

Measured on a real run: the brief inlined whole was 253 KB, the agent carrying it
took 424 turns, and the map alone came to **27.4 million tokens re-sent** — a
quarter of everything that run consumed, and the reason a five-hour allowance
emptied in seventy-four minutes. Trimming it to an index still cost 6k a turn for
a document most turns never opened.

| in the prompt | per turn |
|---|---|
| the brief, inlined | 253 KB ≈ 64k tokens |
| an index of its sections | 27 KB ≈ 6k tokens |
| **a pointer** | **849 B ≈ 212 tokens** |

The sections are still named in the pointer, because an agent that cannot see
that a section exists goes back to grepping the repository — which is the thing
this was built to end. Naming them costs two hundred tokens; carrying them costs
sixty-four thousand, every turn.

| command | what it prints |
|---|---|
| `--pointer` | what belongs in a prompt: the path, the sections, how to ask |
| `--ask "words"` | only the rows that mention those words, their stems and their synonyms, whole, ranked by section; says what it left out and what a synonym matched |
| `--ask "words"` (with `[semantic]`) | the keyword hits plus a "Related by meaning" tail from a local embedding index |
| `--corpus NAME=PATH` | fold an external corpus (a rules dir, a runbook) into the same semantic answers |
| `--no-semantic` | skip the embedding index even when fastembed is installed |
| `--mcp` | serve the map over MCP on stdin/stdout instead of answering once |
| `--sections` | the section headings |

`WAWE_EMBED_CACHE=<file>` caches the semantic index's embeddings in one sqlite
file keyed by model and text, so a rebuild does not recompute vectors it already
has. Unset keeps the old behaviour.

## What it reads

- **Code** (UTF-8, or UTF-16/UTF-32 with a byte order mark) — languages, entry points, make targets, npm scripts, container
  commands, HTTP routes and status codes, data model, module public surface,
  call and package graphs, cycles, unimported files, complexity hotspots,
  duplicate blocks.
- **Runtime** — queues, topics, gRPC, cron, Kubernetes probes and resources,
  Terraform, Pulumi, Ansible, cache keys, permissions, metrics, spans, log
  fields, error types, retries, timeouts, breakers, rate limits, transactions,
  idempotency, outbound services, installed versions from lock files.
- **Contracts** — OpenAPI, GraphQL, migrations, mocks, feature flags and their
  branch points, locale keys, pinned images, secret paths (never values).
- **Decay** — deprecations, coverage, docs pointing at deleted files, git
  history and who touches what.
- **Tests** — layers, entry points, callable step signatures, hooks, locators,
  timeouts, fixtures, tag meanings, overlapping and unused step phrases, dead
  page-object methods, slow scenarios from past junit.

<details>
<summary><b>Supported stacks</b></summary>

**Test runners** — behave, pytest, jest, vitest, playwright, cypress, robot,
JUnit, TestNG, Cucumber (JVM/JS/Ruby), rspec, go test, xUnit, NUnit, SpecFlow,
PHPUnit, Behat, Rust, XCTest, ExUnit, Flutter, Spock, clojure.test, hspec,
busted, Foundry, karate, gauge, k6, gatling, JMeter, Locust, Espresso, Detox.

**Languages** — Python, TypeScript, JavaScript, Go, Java, Kotlin, Scala, Ruby,
Rust, C#, PHP, Swift, C, C++, Elixir, Erlang, Dart, Groovy, Clojure, Haskell,
Lua, Perl, R, Julia, Objective-C, F#, Solidity, Shell, SQL.

**Web** — Flask, FastAPI, Django, Express, Nest, Go net/http, chi, Spring,
Rails, React, Vue, Svelte, Angular, Storybook.

**Infrastructure** — Docker, Compose, Kubernetes, Helm, Terraform,
CloudFormation, Pulumi, Bicep, Ansible, Chef, Puppet, GitHub Actions, GitLab CI,
Jenkins, CircleCI, Azure Pipelines, Buildkite, Drone.

**Data** — PostgreSQL and friends, MongoDB, Elasticsearch, DynamoDB, Cassandra,
ClickHouse, Kafka, RabbitMQ, SQS, NATS, Pulsar, MQTT, dbt, Airflow, Spark,
notebooks.

</details>

## In a pipeline

```yaml
- uses: ngavrish/where-are-we@v1
  with:
    agent-file: AGENTS.md
    comment: "true"
```

```yaml
- repo: https://github.com/ngavrish/where-are-we
  rev: v1.0.0
  hooks: [{id: where-are-we}]
```

## Environment

Every variable the tool reads. A flag always wins over the variable it
defaults from.

| name | read in | what it does | default |
|---|---|---|---|
| `AGENT_REPO` | `_mapper/walk.py`, `cli.py`, `readmes.py` | the repository to index or answer about, when `--repo` is not given. `main()` also writes it back so the walk and the product guess see the resolved path | unset: `--out`'s parent when that is a `.wawe`, then `/work` if it exists, then the current directory |
| `RUN_DIR` | `cli.py`, `_mapper/build.py` | where the map files are written, when `--out` is not given | `.` |
| `PRODUCT_SRC` | `_mapper/walk.py`, `cli.py` | the product under test, colon or comma separated, when `--product` is not given. `none` switches the sibling guess off | unset: the siblings of a repository that looks like a test suite |
| `RULES_REPO` | `_mapper/build.py`, `cli.py` | a directory of agent rule files to fold into the map, when `--rules` is not given | `/rules` |
| `RUNS_API_READ` | `_mapper/build.py`, `cli.py` | base URL of a runs API whose recent verdicts go into the map, when `--runs-api` is not given | unset: no runs section |
| `SPEC_ROOTS` | `cli.py` | the ticket keys `--specs` walks from, comma separated | unset |
| `SPEC_FETCH_CMD` | `cli.py` | the command that fetches one ticket as JSON, when `--spec-cmd` is not given | unset: `--specs` refuses to run without one |
| `SPEC_SOURCE` | `cli.py` | which built-in tracker command to use (`jira`, `linear`, `github`, `cmd`), when `--spec-source` is not given | `cmd` |
| `WAWE_SPEC_DEPTH` | `specs.py` | how many link hops out from each root ticket the spec map walks | `2` |
| `WAWE_SPEC_LIMIT` | `specs.py` | the most tickets one spec map will fetch | `60` |
| `WAWE_MAX_FILES` | `_mapper/walk.py` | the most files one walk will visit before it stops and says so in the map | `40000` |
| `WAWE_NO_CACHE` | `_mapper/build.py`, `_mapper/walk.py` | set to anything: parse every file again and leave the parse cache exactly as it was. `--force` re-parses but rewrites the cache | unset: the cache is read and written |
| `WAWE_DEBUG_PARSES` | `_mapper/build.py` | set to anything: print the parse count per build to stderr, to see what an incremental rebuild actually re-read | unset: silent |
| `WAWE_JUNIT_DIRS` | `_mapper/build.py` | extra directories of JUnit XML to read past runs from, separated by the platform's path separator | unset: the repository's own reports directories |
| `WAWE_POINTER_MAX` | `_mapper/state.py` | the byte cap on the pointer, the block a SessionStart hook puts into context | `4000` |
| `WAWE_VOCAB` | `_mapper/render.py` | cap on how many vocabulary entries the brief prints, split across the groups | `0`, meaning no cap |
| `WAWE_ASK_LOG` | `ask.py` | set to `0` to stop appending a row per answer to `<out>/.wawe-ask.log` | unset: the log is written |
| `WAWE_EMBED_MODEL` | `semantic.py` | the embedding model the optional semantic index uses | `BAAI/bge-small-en-v1.5` |
| `WAWE_RERANK_MODEL` | `semantic.py` | the cross encoder that reranks semantic hits | `Xenova/ms-marco-MiniLM-L-6-v2` |
| `WAWE_EMBED_CACHE` | `semantic.py` | a directory to keep embeddings in between runs | unset: no cache |
| `WAWE_STRICT` | the Claude Code plugin, not `src/` | set to `1` and the plugin's PreToolUse hook refuses `Grep`, `Glob` and `Bash` searches over the repository, so the map is asked instead | unset: searches are allowed |
| `PYTHONIOENCODING` | the interpreter | a codec narrower than the map's text no longer fails: characters it cannot carry are replaced | unset: the locale's codec |
| `ANTHROPIC_API_KEY` | `eval.py`, read at import, used only by `wawe-eval --agent` | the Claude API key the agent A/B calls with; without it the command refuses and sends nothing | unset |

Each variable is read in one place, and named there. `WAWE_NO_CACHE`,
`WAWE_DEBUG_PARSES` and `WAWE_POINTER_MAX` are read once when
`_mapper/state.py` is imported (`NO_CACHE`, `DEBUG_PARSES`, `POINTER_MAX`),
`WAWE_MAX_FILES` when `_mapper/walk.py` is (`MAX_FILES`), `WAWE_VOCAB` when
`_mapper/render.py` is (`VOCAB_CAP`), `WAWE_ASK_LOG` when `ask.py` is
(`LOG_ANSWERS`), the three `WAWE_EMBED`/`WAWE_RERANK` ones when `semantic.py`
is, and the two `WAWE_SPEC` ones when `specs.py` is. So a process that sets one
of those after importing the package keeps the value it started with.

The rest are read per call. Five of them are the ones a flag writes back into
the environment for a later stage to pick up (`AGENT_REPO`, `PRODUCT_SRC`,
`RUN_DIR`, `RULES_REPO`, `RUNS_API_READ`). Three more are argparse defaults,
which `main()` evaluates when it builds the parser (`SPEC_ROOTS`,
`SPEC_FETCH_CMD`, `SPEC_SOURCE`). The last is `WAWE_JUNIT_DIRS`, which a caller
that builds several maps in one process sets per build.

## Keeping it honest

```bash
where-are-we --init                 # starter .framework-map.json
where-are-we --docs                 # list the docs the repo lacks (--docs write to create)
where-are-we --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --install-hook claude  # before the first turn of a session (agent = claude)
where-are-we --install-hook cursor  # a Cursor rule plus its MCP config
where-are-we --install-hook codex   # an AGENTS.md block plus ~/.codex/config.toml
where-are-we --install-hook gemini  # a GEMINI.md block plus .gemini/settings.json
where-are-we --diff                 # what changed since the last map
```

Every `--install-hook` kind installs as one unit: each target (the three git
hooks, a rule file and its MCP config, a markdown block and its settings
file) is checked before any of them is written. A target that is a symlink,
not valid JSON, or not writable stops the whole install with the cause
named and nothing changed; fix it and rerun, and the rest lands. Rerunning
on a finished install says "already installed" and touches nothing.

Autodetection gets the shape right and the vocabulary wrong, so a repo states
its own in `.framework-map.json` and what it states wins:

```json
{
  "name": "billing-e2e",
  "purpose": "End-to-end tests for the billing portal.",
  "layers": {"steps": "steps/*.py — steps own no selectors, they call page objects"},
  "product_src": ["../billing-web/src"],
  "conventions": ["After a fix, re-run only what failed."]
}
```

`.wawe.toml` holds CLI flags as defaults, `.wawe-ignore` keeps build output out,
existing files are never overwritten, and anything shaped like a credential is
redacted before it reaches a file. The commit and the newest file in the tree are
recorded with the map, so a re-run on an unchanged tree costs a stat walk.

### What is redacted

The map holds every indexed line of every indexed file, and the map gets
committed and pasted into prompts, so these rules replace a credential with
`[redacted]` before anything is written:

1. A whole PEM block, `-----BEGIN ... PRIVATE KEY-----` through
   `-----END ...-----`, header and body alike.
2. An issuer prefix at the start of a word: `AKIA...` (AWS), `ghp_`/`gho_`/
   `ghs_`/`ghu_`/`github_pat_` (GitHub), `xox?-...` (Slack), `sk_live_`/
   `sk_test_`/`rk_live_`/`rk_test_` (Stripe), `sk-`/`sk-proj-` (OpenAI),
   `pypi-` (PyPI), a JWT.
3. A base64 blob of forty characters or more that carries a `+` or ends in
   `=` padding.
4. The password inside a URL: `postgres://admin:pw@host/db` keeps the scheme,
   the user and the host and loses the password.
5. The value on a line whose left-hand side names a secret. The last segment
   of the key has to be `secret`, `password`, `passwd`, `token`, `api_key`,
   `private_key`, `credential`, `auth` or `authorization`, in an assignment, a
   dict or JSON key, a YAML key or an `export`. A quoted value and a bare value
   after `=` are replaced wherever they sit on the line, so a `.env` line
   inside a shell string counts too. A bare value after `:` is replaced only on
   a line shaped like YAML: the key starts the line, is not quoted, and nothing
   after the value turns the line back into code.

Key names are kept, and so are the quotes around a redacted literal, so a
question about where a password is set still gets the file, the line and the
syntax. What is not redacted, deliberately:

- Code on the right-hand side. No value rule admits a bracket, so
  `token = lexer.next_token()` and `PASSWORD = os.environ["PW"]` stay.
- A name that merely mentions a credential. The secret word has to be the last
  segment, so `token_count`, `max_token_count`, `auth_backend`, `secret_name`,
  `api_key_header`, `private_key_path` and `credential_kind` all stay.
- A number, a `True`/`False`/`None`, or a bare type name, whatever the key is
  called: `has_token = True` and the dataclass field `token: str = ""` stay.
- A commit sha, and a path. Rule 3 needs a `+` or an `=`, and a forty-character
  hex sha has neither. A slash is not a gate either, because
  `src/main/java/com/example/service/impl/CustomerServiceImpl` is a run of
  letters and slashes and nothing else.

`.wawe.toml`'s `[synonyms]` table adds a project's own words to `--ask`'s
built-in groups (login/signin/auth, invoice/bill/billing, and eighteen more):

```toml
[synonyms]
invoice = ["proforma", "receipt"]
```

merges into the group that already has `invoice`, or starts a new group when
none does. `--ask "invoice"` then also searches `proforma` and `receipt`.

<details>
<summary><b>All options</b></summary>

```
--repo PATH                  the repository to index
--product PATH,…             source roots of the application under test
--also PATH,…                other repositories to fold into the same map
--out DIR                    where the three files land
--agent-file FILE            also write the brief into AGENTS.md, CLAUDE.md, …
--docs [write]               offer the repository the documentation it lacks
--for author|coder           author gets the whole vocabulary; coder gets the rest
--only "routes,data model"   keep only these sections in the brief
--skip "coverage,history"    drop these
--max-lines N                cap the brief per section; the full map is untouched
--diff                       what changed since the map already in --out
--init                       write a starter .framework-map.json
--install-hook KIND          wire it into something that already runs:
                             git|claude|cursor|codex|gemini (agent = claude)
--watch SECONDS              rebuild whenever the tree moves
--html                       also write framework_map.html
--force                      rebuild even when nothing moved, reading
                             nothing from the parse cache
--quiet                      no summary line
```

</details>

## As an MCP server

```bash
where-are-we --mcp --out /path/to/the/map
```

Four tools — `ask`, `defines`, `find`, `sections` — over JSON-RPC on stdin and
stdout. `defines` answers where a name is declared; `find` answers where a phrase
appears, which is the other half of what a grep was for.
The same index answering the same questions; what changes is that the question is
an argument and the answer is a tool result, rather than a shell command and its
output sitting in the conversation to be re-read on every turn after.

It reads the JSON the mapper wrote, on the same machine, offline.

## As a library

```python
from where_are_we import build, brief

m = build("/path/to/repo")
open("AGENTS.md", "w").write(brief(m))
```

## Examples

Real output on a behave suite, a Go service and a React app —
[`docs/examples`](docs/examples/README.md). Generated by running the tool, not
by hand.

## Why it exists

Built inside an agentic QA pipeline where seven branches ran at once, each
opening with the same forty greps. Three runs died at their deadline with the
branches still reading. None of it was specific to that pipeline, agent, or
language.

## Contributing

Issues and PRs welcome — [CONTRIBUTING.md](CONTRIBUTING.md). A change keeps the
contract in [SCHEMA.md](SCHEMA.md) and comes with a case in `tests/` built from
a real directory.

<div align="center">

MIT

</div>
