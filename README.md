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
| One tree walk → `framework_map.md`, `framework_map_brief.md`, `framework_map.json` | Indexes layers, entry points, routes, data model, public surface, call graph, steps, scenarios, fixtures, CI, duplicates, dead code, every declared name with its line | Build: ~10 s on the 184-feature suite, offline, 0 tokens (README). 75 sections on this repository, 28 on the demo suite | — |
| Deterministic output | Same tree, same map, byte for byte | Not measured as a number; the golden check of 150 `ask` cases across the 0.12 refactor relied on it and held | `diff` two builds of one tree |
| `schema: where-are-we/1`, stable JSON contract (`SCHEMA.md`) | Sections may be added within a major; existing shapes keep | Not measurable; a promise | Consumers: any agent runner that reads the JSON (`find_text`, `_definitions_for`) |
| Fingerprint (`<commit>:<newest mtime>`) and `--force` | A build is skipped when the tree has not moved | Not measured | Time a no-op rebuild vs a forced one |
| `## This map is incomplete` | What a bound cut (file count, spec depth) is named at the top of the map | Not measured; a correctness feature: an answer of "absent" is never given past a bound | Count answers that say "indexed: …" per run |
| `.wawe.toml`, `.wawe-ignore`, `WAWE_MAX_FILES` | A project states its invocation and exclusions once | Not measured | — |
| `--product`, sibling guessing only for a suite, `--product none` | The application under test is indexed beside its suite; a plain code repository does not index its neighbours | Measured 2026-09-03 on this repository: before the fix the map held 231 files of three unrelated sibling repositories (3.1 MB JSON, `defines` answering with their paths); after, `indexed: suite 75`, 818 KB | — |
| `--also` | Fold other repositories into one map | Not measured | — |
| `--diff` | What changed since the map already in `--out` | Not measured | — |
| `--watch SECONDS` | Rebuild whenever the tree moves | Not measured | — |
| `--html` | The brief as a page | Not measured | — |
| `--init` → `.framework-map.json` manifest | A starter manifest the map reads `stated` facts from | Not measured | — |

### What an agent carries vs what it asks

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| The pointer (`--pointer`, `--agent-file`) | ~600–850 bytes in the prompt naming the map, its sections and how to ask; the map stays on disk | Map inlined: ≈ 64k tokens re-sent every turn, 27.4M tokens over one run, a quarter of that run; pointer: ≈ 212 tokens (300× less); a 5-hour allowance gone in 74 min vs the budget going to work (README, measured on one production run) | — |
| Orientation replaced by one `--ask` | The first turns of a session stop being `ls`/`find`/`grep` | ~40 orientation turns → 1 on the measured suite (README) | — |
| `--ask` / MCP `ask`: whole rows, ranked sections, honest tail | Only rows that mention the words, never a cut row, `limit` a strict ceiling, "… N more matching rows; M rows do not mention these words" | Before 0.12: an answer could exceed its limit 68× (3 KB head at limit 50) and cut a row mid-word; after: ≤ limit on every golden case (150), 5/5 fixture checks. `.wawe/.wawe-ask.log` records every answer; `wawe-measure --ask-log .wawe` prints median/p95/max tokens | — |
| Rows under one directory printed once | `- \`features/checkout/\`` then the files | Not measured | Bytes of an answer before/after on a 40-row directory |
| `## Defined here` (`defines`, `_definitions_for`) | A name → file:line, every declared name in every walked file | Not measured as turns saved; the README's claim is one question instead of `grep -rn` | Count `Grep` calls per session before/after (the run's call events) |
| Cross-file call graph (`call_graph_files`) | Function to callees defined in another file, Python by AST, now TypeScript, JavaScript and Go by pattern | Not measured | Count `Grep` calls spent chasing a callee across files before/after |
| `find` (MCP) | Where a phrase or string lives, with the line | Not measured | Same |
| `sections` (MCP), `--sections` | The headings, now map + brief (75 vs 3 before 0.12.1) | Measured 2026-09-03: a code repository's `--sections` went from 3 empty suite headings to 75 | — |
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
| `where-are-we --docs plan|write` | Drafts a README per directory that lacks one, from the map's facts, with a `TODO:` for the purpose only a human knows | Not measured | Count of directories without a README before/after |
| `wawe-readmes` | The same drafts as one command (both call `readmes.describe`; `--docs` is the map-aware wrapper): `--repo`, `--write`, `--help`; lists by default, writes only with `--write` | Fixed in 0.12.3: until then the entry point parsed no arguments and wrote into `$AGENT_REPO` unasked | — |

### Ways in

| Feature | What it does | Measured impact | If not measured, how to |
|---|---|---|---|
| CLI `where-are-we` | Everything above | — | — |
| MCP server (`--mcp`): `ask`, `find`, `defines`, `sections` | The map as tools, stdio | On the measured production run: 194 map calls vs 68 repository searches (call events of that run) | — |
| LSP server (`--lsp`): `textDocument/definition`, `workspace/symbol` | The map as an editor's language server, `Content-Length` framed stdio | Not measured | - |
| Library: `build`, `brief`, `digest`, `init_manifest`, `main` | Python API | Not measured | — |
| GitHub Action (`ngavrish/where-are-we@v1`): inputs `repo`, `product`, `out`, `agent-file`, `comment`; outputs `brief`, `summary` | Map on CI, optional PR comment | Not measured | — |
| pre-commit hook | Rebuild on commit so a map is never stale | Not measured | — |
| `--install-hook git|agent` | `git`: post-checkout/merge/commit hooks that rebuild; `agent`: a SessionStart hook for an agent harness (distinct from `--agent-file`, which writes the brief into a file) | Not measured | — |
| Claude Code plugin (`/plugin marketplace add ngavrish/where-are-we`) | SessionStart builds `.wawe/` and hands the session the pointer; the four tools over MCP; skills `orient`, `ask`, `where-defined`, `spec-map`, `readmes`; `WAWE_STRICT=1` refuses repository searches. Installed from the marketplace the tools are named `mcp__plugin_where-are-we_where-are-we__{ask,find,defines,sections}`; under `--plugin-dir` the prefix differs, so prompts name the server `where-are-we`, not the prefix | Verified 2026-09-03 in a fresh repository: hook built the map, tools answered, pointer reached the context. Turns saved not measured | Sessions with vs without the plugin: `Grep`/`Glob`/`Bash grep` counts |
| Packages: PyPI wheel + sdist, deb (apt repo with key), rpm, Homebrew tap, GitHub release with SBOM (SPDX) and sigstore signatures | Install anywhere | — | — |

### Honesty features (not savings, guarantees)

| Feature | Guarantee |
|---|---|
| `no match for … indexed: product N files, suite M files` | An absence names what was searched; it is not a claim the thing does not exist |
| `## This map is incomplete` | Every bound that cut is written at the top |
| Whole rows, a ceiling, a tail | An answer never pretends to be complete: what was left out is counted |
| The map says what it maps | "a map of this repository" vs "of this suite and the product it tests", from the map's own counts (0.12.2) |

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

macOS, Debian, Ubuntu, Fedora, RHEL. Or `ghcr.io/ngavrish/where-are-we`. The
`[semantic]` extra adds fastembed (ONNX on CPU, no service, no database); without
it `--ask` still answers by keyword.

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
| `--ask "words"` | only the rows that mention those words, whole, ranked by section; says what it left out |
| `--ask "words"` (with `[semantic]`) | the keyword hits plus a "Related by meaning" tail from a local embedding index |
| `--corpus NAME=PATH` | fold an external corpus (a rules dir, a runbook) into the same semantic answers |
| `--no-semantic` | skip the embedding index even when fastembed is installed |
| `--mcp` | serve the map over MCP on stdin/stdout instead of answering once |
| `--sections` | the section headings |

`WAWE_EMBED_CACHE=<file>` caches the semantic index's embeddings in one sqlite
file keyed by model and text, so a rebuild does not recompute vectors it already
has. Unset keeps the old behaviour.

## What it reads

- **Code** — languages, entry points, make targets, npm scripts, container
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

## Keeping it honest

```bash
where-are-we --init                 # starter .framework-map.json
where-are-we --docs                 # list the docs the repo lacks (--docs write to create)
where-are-we --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --install-hook agent   # before the first turn of a session
where-are-we --diff                 # what changed since the last map
```

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
--install-hook git|agent     wire it into something that already runs
--watch SECONDS              rebuild whenever the tree moves
--html                       also write framework_map.html
--force                      rebuild even when nothing moved
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
