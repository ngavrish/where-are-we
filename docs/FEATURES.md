# Every feature, and what it is worth

Each row names what the tool does and what that is measured to save. Where a
number exists it is cited; where none exists the row says so and names the
measurement that would settle it. Numbers come from one real run unless said
otherwise: a 184-feature behave suite and one production agent run of the
dokimos pipeline (run `166fcf64`, 1,409 turns, $59.65), read from its ammit
events. Estimates are marked as estimates.

## The map itself

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| One tree walk → `framework_map.md`, `framework_map_brief.md`, `framework_map.json` | Indexes layers, entry points, routes, data model, public surface, call graph, steps, scenarios, fixtures, CI, duplicates, dead code, every declared name with its line | Build: ~10 s on the 184-feature suite, offline, 0 tokens (README). 75 sections on this repository, 28 on the demo suite | — |
| Deterministic output | Same tree, same map, byte for byte | Not measured as a number; the golden check of 150 `ask` cases across the 0.12 refactor relied on it and held | `diff` two builds of one tree |
| `schema: where-are-we/1`, stable JSON contract (`SCHEMA.md`) | Sections may be added within a major; existing shapes keep | Not measurable; a promise | Consumers: the dokimos runner's `map` MCP, `find_text`, `_definitions_for` |
| Fingerprint (`<commit>:<newest mtime>`) and `--force` | A build is skipped when the tree has not moved | Not measured | Time a no-op rebuild vs a forced one |
| `## This map is incomplete` | What a bound cut (file count, spec depth) is named at the top of the map | Not measured; a correctness feature: an answer of "absent" is never given past a bound | Count answers that say "indexed: …" per run |
| `.wawe.toml`, `.wawe-ignore`, `WAWE_MAX_FILES` | A project states its invocation and exclusions once | Not measured | — |
| `--product`, sibling guessing only for a suite, `--product none` | The application under test is indexed beside its suite; a plain code repository does not index its neighbours | Measured 2026-09-03 on this repository: before the fix the map held 231 files of three unrelated sibling repositories (3.1 MB JSON, `defines` answering with their paths); after, `indexed: suite 75`, 818 KB | — |
| `--also` | Fold other repositories into one map | Not measured | — |
| `--diff` | What changed since the map already in `--out` | Not measured | — |
| `--watch SECONDS` | Rebuild whenever the tree moves | Not measured | — |
| `--html` | The brief as a page | Not measured | — |
| `--init` → `.framework-map.json` manifest | A starter manifest the map reads `stated` facts from | Not measured | — |

## What an agent carries vs what it asks

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| The pointer (`--pointer`, `--agent-file`) | ~600–850 bytes in the prompt naming the map, its sections and how to ask; the map stays on disk | Map inlined: ≈ 64k tokens re-sent every turn, 27.4M tokens over one run, a quarter of that run; pointer: ≈ 212 tokens (300× less); a 5-hour allowance gone in 74 min vs the budget going to work (README, measured on one production run) | — |
| Orientation replaced by one `--ask` | The first turns of a session stop being `ls`/`find`/`grep` | ~40 orientation turns → 1 on the measured suite (README) | — |
| `--ask` / MCP `ask`: whole rows, ranked sections, honest tail | Only rows that mention the words, never a cut row, `limit` a strict ceiling, "… N more matching rows; M rows do not mention these words" | Before 0.12: an answer could exceed its limit 68× (3 KB head at limit 50) and cut a row mid-word; after: ≤ limit on every golden case (150), 5/5 fixture checks. Per-answer token cost not measured on a run | `compression` events of the dokimos runner will carry map-answer sizes on the next run |
| Rows under one directory printed once | `- \`features/checkout/\`` then the files | Not measured | Bytes of an answer before/after on a 40-row directory |
| `## Defined here` (`defines`, `_definitions_for`) | A name → file:line, every declared name in every walked file | Not measured as turns saved; the README's claim is one question instead of `grep -rn` | Count `Grep` calls per session before/after (ammit `calls`) |
| `find` (MCP) | Where a phrase or string lives, with the line | Not measured | Same |
| `sections` (MCP), `--sections` | The headings, now map + brief (75 vs 3 before 0.12.1) | Measured 2026-09-03: a code repository's `--sections` went from 3 empty suite headings to 75 | — |
| `--for author|coder`, `--only`, `--skip`, `--max-lines` | A brief tailored to who reads it; capped per section | Not measured in tokens; the per-section cap keeps every head (3×50 rows at 30 lines → every head present, before: the last sections dropped) | Token count of the brief per audience |
| Read dedup in the dokimos runner (`tool_compression`) | A re-read of an unchanged file is a one-line stub | Runner-side; markers proven per session via `compression` events from the next run | — |

## The other map

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| `--specs`, `--spec-cmd`, `--spec-depth`, `--spec-limit` → `spec_map.md/json` | A ticket and its links two hops out, from any command that returns JSON | Not measured | Turns spent fetching tracker pages before/after |
| `ask` over both maps | One question, answers from code and spec | Not measured | — |

## Semantic answers (optional extra)

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| `pip install "where-are-we[semantic]"` — embedding index, "Related by meaning" tail | Keyword hits plus nearest paragraphs by meaning | Not measured for answer quality | An A/B of questions with and without the tail |
| `--corpus NAME=PATH` | External corpora (rules, runbooks) in the same index | Not measured | — |
| `WAWE_EMBED_CACHE` | Embeddings cached across builds in one sqlite file | Full five-corpus build: 6 min → about 30 s, five and a half minutes were recomputing unchanged vectors (CHANGELOG 0.11.0) | — |
| `WAWE_EMBED_MODEL`, `WAWE_RERANK_MODEL`, `--no-semantic` | Model choice; skip the index | Not measured | — |

## Docs the repository is missing

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| `where-are-we --docs plan|write` | Drafts a README per directory that lacks one, from the map's facts, with a `TODO:` for the purpose only a human knows | Not measured | Count of directories without a README before/after |
| `wawe-readmes` | The same as a command | **Defect, 2026-09-04:** the entry point parses no arguments — `--help` runs it, and it writes into `$AGENT_REPO` (default `/work`) without asking. Fix before 1.0.0 | — |

## Ways in

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| CLI `where-are-we` | Everything above | — | — |
| MCP server (`--mcp`): `ask`, `find`, `defines`, `sections` | The map as tools, stdio | In the dokimos run: 194 map calls vs 68 repository searches per run (ammit `calls`, run 166fcf64) | — |
| Library: `build`, `brief`, `digest`, `init_manifest`, `main` | Python API | Not measured | — |
| GitHub Action (`ngavrish/where-are-we@v1`): inputs `repo`, `product`, `out`, `agent-file`, `comment`; outputs `brief`, `summary` | Map on CI, optional PR comment | Not measured | — |
| pre-commit hook | Rebuild on commit so a map is never stale | Not measured | — |
| `--install-hook git|agent` | Git hook, or the agent-file pointer | Not measured | — |
| Claude Code plugin (`/plugin marketplace add ngavrish/where-are-we`) | SessionStart builds `.wawe/` and hands the session the pointer; the four tools over MCP; skills `orient`, `ask`, `where-defined`, `spec-map`, `readmes`; `WAWE_STRICT=1` refuses repository searches | Verified 2026-09-03 in a fresh repository: hook built the map, tools answered, pointer reached the context. Turns saved not measured | Sessions with vs without the plugin: `Grep`/`Glob`/`Bash grep` counts |
| Packages: PyPI wheel + sdist, deb (apt repo with key), rpm, Homebrew tap, GitHub release with SBOM (SPDX) and sigstore signatures | Install anywhere | — | — |

## Honesty features (not savings, guarantees)

| Feature | Guarantee |
|---|---|
| `no match for … indexed: product N files, suite M files` | An absence names what was searched; it is not a claim the thing does not exist |
| `## This map is incomplete` | Every bound that cut is written at the top |
| Whole rows, a ceiling, a tail | An answer never pretends to be complete: what was left out is counted |
| The map says what it maps | "a map of this repository" vs "of this suite and the product it tests", from the map's own counts (0.12.2) |

## Not yet measured anywhere

The dokimos runner's next run after redeploy will add: sizes of map answers
in context (`compression` events), searches per session with the map tools
present (`calls`), and the turn count per role — the three numbers that turn
the "not measured" rows above into measured ones.
