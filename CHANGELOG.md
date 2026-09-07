# Changelog

## 1.3.0

- `callees` (MCP), `--callees NAME`: what a function calls, the other
  direction of `callers`, from the two call graphs the map already holds.
- `impact` (MCP), `--impact NAME [--impact-depth N]`: every `file:func` that
  reaches a name within N hops, grouped by hop, cycles walked once, capped at
  200 entries.

## 1.2.0

Two ideas taken from Headroom (headroomlabs-ai/headroom), rebuilt for a map
that lives on disk.

- A cut answer carries a handle. Every tail line that says what was left
  out (`... 37 more matching rows`, `... 15 more definitions`, `... more
  sections match`, `find`'s "these are the 40 that rank highest") now ends
  with `(more:<kind>:<payload>)`, and a sixth tool, `more`, returns the next
  slice under the same whole-row, ceiling and tail rules, with its own
  handle when there is still more. `--more HANDLE` on the command line. A
  handle is a query, not a cursor: it is recomputed from the map on disk,
  carries the question percent-encoded so `pre-commit`, `page.click` and
  non-Latin words survive it whole, and answers `no such handle in this
  map` when the map has changed under it. A question longer than about
  forty percent of the budget cannot carry per-section handles; the note
  line still points at the section.
- `wawe-eval` measures what the budget loses, from the map itself: 100
  questions built from declared names, step words and heading words, each
  asked at no budget and at 350, 1500 and 12000 bytes; first-answer recall
  (macro), pooled recall, top-5 recall, rows over budget, and recall with
  handles after every `more` has been followed. At 1500 bytes and up, the
  MCP server's floor, recall with handles is 1.0 on every fixture; CI
  asserts it. `wawe-eval --agent` asks the same questions through the Claude
  API with the map tools and with grep, scores against `framework_map.json`,
  needs `ANTHROPIC_API_KEY` and the `eval-agent` extra, and is not run in CI.
- Six new golden cases with punctuated questions; 156 pinned answers.

## 1.1.3

- `--install-hook` installs as one unit. Every target is checked before
  anything is written, so a refused hook, rule file or settings file leaves
  nothing behind and the message names the cause; a rerun after the cause
  is fixed installs the rest. Until now `git` could stop after
  `post-checkout` and report `installed: post-checkout; ...`, which read as
  success while the map went stale on the first commit, and the cursor,
  gemini and codex pairs could leave their first file behind.
- A symlinked `mcp.json` or `settings.json` is refused as a symlink, not as
  "not valid JSON".

## 1.1.2

Three audits (concurrency, robustness, design) ran against 1.1.1; every
finding below was reproduced with a command before it was fixed and has a
live CI step that fails on the old code.

Maps that are never torn:

- Every artefact (`framework_map.{md,json}`, the brief, the HTML, the agent
  file, `spec_map.*`, `.wawe-cache.json`, `.pointer-head`, the semantic index)
  is written to a temporary and renamed into place; a reader never sees a
  zero-byte or half-written file, and a build killed mid-way leaves the
  previous map intact. Dead temporaries are swept at the next build.
- `build()` starts from nothing: module state is reset per build, so two
  repositories mapped in one process no longer share names, and `--watch`
  reports a constant `indexed` count on an unchanged tree.
- The fingerprint keeps sub-second mtimes and watches exactly the files the
  map indexes (an edited `.go` or `.rs` file no longer reads as "unchanged").
- `--force` reads nothing from the parse cache and rewrites it.
- `--watch` rebuilds whole every iteration, writes every artefact including
  `framework_map.md`, and survives an exception in one iteration.

Reads that are bounded:

- Every whole-file read goes through one bounded reader; a 198 MB source
  costs about 40 MB of memory instead of four copies of itself. A module
  larger than the parser cap is parsed on whole lines and named in
  `## This map is incomplete`.
- A symlink that resolves outside the repository is not read; a FIFO or
  device is skipped; a tree walk honours `WAWE_MAX_FILES` before any other
  pass, so `--repo /` terminates.
- Ignore rules never drop a path git tracks (`.gitignore` semantics), while
  `.wawe-ignore` always prunes.

Servers that stay up:

- MCP and LSP reply with a JSON-RPC error to malformed `params`,
  `arguments` or `limit` and keep serving; both exit quietly when stdout
  closes; a corrupt semantic index degrades to an answer without the tail;
  the embed cache uses WAL and degrades to "no cache".
- `file://` URIs are percent-encoded; `changed_since` reads git NUL
  separated so a path with a space or a rename comes back verbatim.

What goes into the map:

- Secrets are redacted by what a line says, not by six prefixes: PEM blocks
  as a whole, Stripe, OpenAI, Slack, GitHub, AWS, JWT and URL passwords by
  shape, and any value under a key naming a secret, password, token, key or
  credential. A commit sha, a Java path and a counter such as
  `max_tokens = 1000000` survive.
- `--html` escapes repository content.
- UTF-16 sources with a byte order mark are decoded and indexed; a binary
  that merely starts with one is not.

The command line:

- A missing map, an unwritable `--out`, `--agent-file` or `--init` target and
  a non-directory `--repo` say so in one line with a non-zero exit code.
- A narrow stdout encoding replaces characters instead of crashing.
- `--ask` answers from a spec map alone when that is all there is.

Hooks and the plugin:

- `--install-hook` refuses to write through a symlink and refuses cleanly
  when `HOME` is unset or unwritable.
- `--spec-source` keys are validated and quoted; a timed-out fetch kills its
  whole process group. `SPEC_ROOTS` cannot smuggle shell syntax.
- The plugin's SessionStart hook maps a repository that has no git, and
  `prefer-the-map.sh` no longer refuses a destructive `find`.
- `wawe-measure` skips a `tool_use` block without a usable name.

Layout (no map bytes change; import paths do):

- `where_are_we._mapper.cli` is now `where_are_we.cli`, with no stub at the
  old path. `where_are_we.mapper:main`, `python -m where_are_we.mapper`,
  running `mapper.py` by path, and `from where_are_we.mapper import main,
  init_manifest, install_hook, propose_docs` all keep working.
- `_definitions_for` lives in `where_are_we.ask` as `definitions_for`;
  `fingerprint` is the public name of `walk._fingerprint`. Both underscore
  names stay as aliases for one release.
- `from where_are_we.mapper import *` now exports the eleven shared-state
  names and `definitions_for`/`fingerprint`, and no longer exports `main`,
  `init_manifest`, `install_hook`, `propose_docs` (import those by name).
- `WAWE_NO_CACHE`, `WAWE_DEBUG_PARSES`, `WAWE_VOCAB`, `WAWE_ASK_LOG` and
  `WAWE_EMBED_CACHE` are read once at import; a process that sets one after
  importing keeps the value it started with.
- `extract.Ctx.code_files` is a tuple and `Ctx` is hashable; `Ctx.read` is
  the `extract.Read` protocol; a new extractor is registered in
  `extract.EXTRACTORS`.
- The import graph has no cycles and no deferred import that existed only
  to dodge one (`tests/golden/import_graph.py` proves it in CI). Extractors
  are registered in one list and assembled in one loop. `SCHEMA.md`
  documents every top-level key the map emits. Every environment variable
  the code reads is in one README table.
- CI: every negative assertion is an `if ...; exit 1` (a `! cmd` under
  `bash -e` never fails a step; 24 of them were inert).

## 1.1.1

- `--mcp`, `--ask`, `--pointer` and `--callers` started by a hook or the
  plugin (no `--repo`, the map under `<repo>/.wawe`) now resolve the
  repository from that directory, so a project's `.wawe.toml` `[synonyms]`
  reaches its MCP answers. Until now they fell back to `$AGENT_REPO` or
  `/work` and read another tree's config, or none.
- The Claude Code plugin's SessionStart hook passes `--repo`, so the pointer
  it hands the session names what changed since the last one; it also lists
  the fifth MCP tool, `callers`.
- The deb install check runs on Debian 13; Debian 12 carries Python 3.11,
  below the 3.12 floor.

## 1.1.0

- `wawe-measure` reads Claude Code's own transcripts and reports, per session,
  how many turns, searches, map calls and orientation turns it took, as a
  table or as `--json`.
- Every map answer is logged to `.wawe-ask.log` (`ask`, `find`, `defines`,
  `sections`, `callers`, from both the CLI and MCP); `wawe-measure --ask-log`
  summarises median, p95 and max tokens per answer.
- `--pointer` now names what changed since the last session: `changed_since`
  diffs the repository's git HEAD against the one recorded on the previous
  build.
- Unchanged files are no longer re-parsed on rebuild: a parse cache keyed by
  path, kind, mtime and size, bypassed with `WAWE_NO_CACHE=1`;
  `WAWE_JUNIT_DIRS` names where a project's JUnit history lives.
- Declarations for Rust, Kotlin, C# and Ruby, joining Python, TypeScript,
  JavaScript and Go; wired into the tree-sitter parse where installed, and
  the `## Defined here` section is now capped.
- The cross-file call graph covers TypeScript, JavaScript and Go, not only
  Python.
- `--callers NAME`, the MCP `callers` tool, and a `## Called by` block in
  `--ask`, answer who calls a name, cross-file only: a call from within the
  same file it is defined in is not counted.
- `--ask` expands synonyms and stems terms before matching; `.wawe.toml`'s
  `[synonyms]` table adds a project's own words to the built-in groups.
- `--install-hook` gained `cursor`, `codex` and `gemini`, each idempotent and
  each wiring its own MCP configuration.
- `--spec-source github|linear` reads tickets straight from GitHub issues or
  a Linear GraphQL query, instead of a custom `--spec-cmd` only.
- `--lsp` serves go-to-definition and workspace symbols from the map over the
  Language Server Protocol.
- A public demo page, built against FastAPI 0.115.0, under `docs/demo/`.
- A golden suite of 150 `ask` cases runs in CI (`tests/golden/check.py`),
  alongside a determinism check that two builds of the same tree produce
  byte-identical maps.
- No behaviour change; `mapper` is a package behind a facade.
- Python 3.12 or newer; 3.10 and 3.11 dropped.

## 1.0.0

The contract is fixed. What 0.12.3 does, 1.0.0 does, and every 1.x will:

- `framework_map.json` is schema `where-are-we/1`: sections may be added, a
  section that exists keeps its shape and meaning, a key is never renamed or
  removed (SCHEMA.md, "Stability").
- The CLI flags and the four MCP tools (`ask`, `find`, `defines`, `sections`)
  keep their names and meanings through 1.x; anything that must break bumps
  to 2.0.0.
- The pointer, the brief and the map files keep their names and places:
  `framework_map.md`, `framework_map_brief.md`, `framework_map.json`,
  `spec_map.md`, `spec_map.json` under `--out` (`.wawe/` for the plugin and the
  pre-commit hook).
- The README lists every feature with what it is measured to save, and says
  "not measured" where it is not.

No code changed between 0.12.3 and 1.0.0.

## 0.12.3

- `wawe-readmes` is a command: `--help`, `--repo` (default `$AGENT_REPO` or
  the current directory), `--write`. Until now it parsed no arguments - `--help`
  ran it, and with `AGENT_REPO` set it wrote READMEs into that tree without a
  word. The default is now to list what would be written; nothing is written
  without `--write`.

## 0.12.2

Plugin fixes from the first install through the marketplace.

- `.wawe/` ignores itself: the hook writes `.wawe/.gitignore` instead of
  editing the repository's `.gitignore`, and a repository without one stays
  clean in `git status` too.
- The pointer says what it is a map of - "this repository" unless the map has
  step modules and feature files - and its size counts the brief, so a code
  repository no longer reads "(0 KB) map of this suite".
- The `v1` tag the GitHub Action example pins to now exists and moves with
  each release; the pre-commit example pins the current version.

## 0.12.1

A code repository gets a real map, and Claude Code gets a plugin.

- `--ask`, `--sections`, `--pointer` and the MCP `sections` read the brief's
  sections as well as the map's. For a behave suite nothing changes; for a
  plain code repository the map file was a three-section skeleton and the
  seventy sections that matter - entry points, routes, data model, public
  surface - sat in `framework_map_brief.md` where no question reached them.
- The product under test is guessed from sibling directories only when the
  repository is a test suite (a steps directory or a feature file). A code
  repository mapped from a directory of other projects had indexed its
  neighbours as the product. `--product none` switches the guess off.

- A Claude Code plugin in `plugin/`: a SessionStart hook that builds the map
  and hands the session its pointer, the map's tools over MCP, five skills
  (`orient`, `ask`, `where-defined`, `spec-map`, `readmes`), and an opt-in
  strict mode (`WAWE_STRICT=1`) that refuses repository searches while a map
  exists. Install: `/plugin marketplace add ngavrish/where-are-we`.

## 0.12.0

Answers end on whole rows and say what they left out.

- `--ask` and the MCP `ask` no longer slice a section at a character count:
  rows are whole, and a section that did not fit ends with how many matching
  rows were dropped and how many rows did not match at all.
- In an answer, consecutive rows under one directory are printed under it
  once. Rendering only; the map on disk keeps full paths.
- `--max-lines` caps the brief per section — every section keeps its head and
  up to its share of rows (none, under a cap too small to hold them), then
  says how many more are in `framework_map.md` — instead of dropping
  whatever came after line N.
- Bold `**…**` lines in a section are structure, not rows: they are neither
  shown in an answer nor counted as rows that did not match; a
  `- **label**: value` row matches only if it mentions the words.
- Internal: answering moved to `where_are_we/ask.py`; `mapper.ask` is a re-export.

## 0.11.2

Packaging only. The rpm job's "attach to the release" step ran `gh` inside a
fedora container whose checkout git cannot discover, so it died on "not a git
repository". Every `gh release` call now names the repo with `-R`, needing no
local git; the deb job matches for symmetry.

## 0.11.1

Packaging only, no code change to the tool.

- The deb now ships every module. It packaged only `mapper`, `readmes` and
  `__init__`, but `__init__` imports `mapper` and `mapper` imports `specs`,
  `semantic` and `mcp`, so the deb smoke test died on a missing-module import
  on every release since these modules were added.
- The rpm "attach to the release" step marks the container checkout as a safe
  git directory, fixing "not a git repository" when `gh` runs as root in the
  fedora image.
- `__version__` catches up to the packaged version.

## 0.11.0

A vector never changes for the same text and model, yet every run rebuilt its
index from scratch: five and a half of the six minutes of a full five-corpus
build were recomputing vectors computed the run before.

- `WAWE_EMBED_CACHE` names a sqlite file (stdlib, one file, its own locking)
  where embeddings are cached across runs, keyed by model and text hash. Unset
  keeps the old behavior byte for byte.
- `build_index` creates its out_dir instead of crashing on `np.save`.
- Running `mapper.py` by path works again: the local imports added since 0.8
  (`readmes`, `semantic`, `mcp`) now carry the same try-relative-then-plain
  fallback the top of the file always had.

## 0.10.0

A product tree handed over as `--corpus` is code, and "which component renders
the values dropdown" is the question a UI session pays twenty Reads to answer
without it.

- The corpus walk takes doc AND source extensions, skips dependency and build
  directories, and caps file size so a bundle or lockfile cannot flood the
  index. Chunking by blank lines works on source the way it works on prose.
- The "Related by meaning" tail moved into a shared helper: the MCP `ask` now
  appends it too, not only the CLI `--ask` branch.

## 0.9.0

The keyword ask answers when the asker knows the words the map used; the
sessions that pay the most only know their own words.

- A local embedding index closes the gap: fastembed's ONNX models on CPU
  (bge-small for recall, a MiniLM cross-encoder for precision on top), the
  index two flat files beside the map - at thousands of chunks a numpy dot
  product IS the vector database. Built after every map write, skipped by
  content hash, absent without complaint when the `[semantic]` extra is not
  installed.
- `--corpus NAME=PATH` indexes external corpora (a rules directory, a runbook)
  into the same answers; `--ask` grows a "Related by meaning" tail
  deduplicated against the keyword hits.
- `--ask` takes every question at once instead of one call per turn, a batch
  shares one budget, and sections are ranked by BM25 rather than raw word
  counts.
- `cluster()` greedy-folds failure messages for triage prefilters.

## 0.8.0

Half of what an agent searches for is text, not a name. Watched over one run: a
hundred and sixty-six searches by hand, of which eighty-six were names — which
the declaration index answers — and seventy were phrases like `"second Portal
tab"` or a label `"A 15"`, which it could not answer at all.

- `find(phrase)` returns every line holding that text, with file and line. The
  walk already opens every file; keeping the lines turns a repository-wide grep
  into a lookup.
- The line index lives in `framework_map.json` and never in the Markdown, so it
  is read by the tool and cannot end up in a prompt: 1.7 MB of lines beside
  178 KB of map.

## 0.7.0

Asking the map through a shell puts the question and the whole answer into the
conversation, where they are re-read on every turn after — and the agent has to
remember what the command is called, which one of them did not: it spent a turn
on `which where-are-us where-are-we`.

- `--mcp` serves the same index over MCP on stdin/stdout: `ask`, `defines`,
  `sections`. The question is an argument, the answer is a tool result. Same
  regexes, same JSON, no model and no network — JSON-RPC on a pipe, written on
  the standard library like the rest of this.

## 0.6.0

The map indexed the language of the test suite and nothing else, and said so in
the worst possible way. Asked where a constant was defined — line 31 of the
product, plainly there — it answered that this was "a real absence rather than a
search that missed". The agent believed it, rephrased three times, and spent the
next forty turns grepping by hand. It was right to.

- Every name in every file, with the line it is declared on: a table of
  declaration shapes per language, and a general shape for the rest, applied to
  whatever the walk finds. On a real product: 2343 names from 137 files, where
  the previous version had none.
- The map records what it indexed, and a "not found" now says where it looked.
  A map that overstates its reach turns "I did not look" into "it is not there",
  and the reader stops looking too.

## 0.5.1

A limit that stops quietly produces a map that looks complete and is not, and an
absence in a silent map reads as a fact about the codebase.

- Both walks name what they left out, at the top of the map: the tracker walk
  already did, the file walk did not and silently stopped at 40000 files.
- `--spec-limit` is a flag rather than a constant, beside `--spec-depth`.

## 0.5.0

A codebase is not the only thing an agent gropes around in. The other is the
tracker, and it gropes there for the same reason: no map, so it asks, and asks
again. On one run of a real pipeline sixteen tickets were fetched over and over —
one agent pulled fourteen neighbours, the next pulled the same fourteen again,
three were fetched three times inside a single session — and every answer then
sat in a context for ever, paid for on every later turn.

- `--specs KEY[,KEY]` with `--spec-cmd 'your-fetcher {key}'` walks the tracker
  once, two hops out, into `spec_map.json` and `spec_map.md`. This tool learns
  nothing about any tracker: it is handed a command that turns a key into JSON.
- Links are read out of the whole document rather than out of a schema's link
  fields — a key mentioned in a comment is a link somebody made on purpose.
- `--ask` answers from both maps: a question about a piece of work is as likely
  to be about what was asked for as about where the code is.

## 0.4.1

- `--for author|coder`. The vocabulary is what a scenario is written in, so the
  author writing scenarios gets all of it (64k tokens here) and the coder
  changing what it runs against does not (30k) — that context is worth more to
  them as room to work than as fourteen hundred phrases.
- The vocabulary is no longer capped by default: whole-map arithmetic favours
  carrying it, since one turn spent grepping for a phrase re-reads the entire
  context twice.

## 0.4.0

- The brief carries the vocabulary, not a count of it. It used to say "this
  module declares 211 steps" and leave the 211 in a file beside it, so the
  agents writing scenarios spent a hundred and forty-nine turns grepping for
  words they were entitled to be handed. Now: behave phrases, cucumber glue in
  any language, Robot keywords, pytest fixtures and page-object methods, in one
  section, capped by WAWE_VOCAB (700 by default) with the rest in the full map.

## 0.3.1

- An hour to nine seconds. The "interesting line" sections matched with patterns
  shaped `.*(?:a|b|c).*`, which makes the engine try every position of every
  line of every file; a substring test gives the same answer. On the repository
  this was written for the map had been running for an hour and the run it was
  meant to help never started.

## 0.3.0

- Lock files (what is actually installed), the status codes each file returns,
  the services this code calls out to, Kubernetes probes, resources and
  replicas, the asset inventory, which schema belongs to which topic, where
  feature flags are branched on, assumptions about time and locale, the
  functions carrying the complexity, and blocks of code that appear more than
  once.

## 0.2.0

- Every remaining ecosystem: Elixir, Dart, Groovy, Clojure, Haskell, Lua, Perl,
  Julia, Objective-C, Solidity; Vue, Svelte, Angular, Storybook; dbt, Airflow,
  Spark, notebooks; AsyncAPI, JSON Schema, Avro, Thrift, SOAP, tRPC, Pact;
  CloudFormation, Pulumi, Bicep, Ansible, Chef, Puppet; Jenkins, CircleCI, Azure
  Pipelines, Travis, Buildkite, Drone; Gradle, Maven, Bazel, sbt, CMake, Rake;
  MongoDB, Elasticsearch, DynamoDB, Cassandra, ClickHouse, NATS, Pulsar, MQTT;
  Prometheus rules, Grafana dashboards, OpenTelemetry, OPA, flag platforms;
  JMeter, Locust, Artillery; test data factories.
- Indexes and constraints, generated code, declared types, environment per
  service, retries/timeouts/breakers/limits, transactions and idempotency,
  logging levels, contribution templates, license headers.
- `.wawe.toml` for defaults, `--also` to fold several repositories into one map,
  `--watch`, `--html`, `--only`, `--skip`, `--max-lines`, `--diff`.
- A parse cache that survives between runs, and redaction of anything shaped
  like a credential before it reaches a file.

## 0.1.0

First release.

- Indexes any codebase into `framework_map.{json,md}` and a brief for a prompt:
  languages, entry points, HTTP routes, data model, public surface, import and
  cross-file call graphs, queues, gRPC, schedules, Kubernetes, Terraform, cache
  keys, permissions, observability, error types, CLI, frontend, contracts
  (OpenAPI, GraphQL, migrations, mocks, flags, i18n), ADRs, coverage, hotspots,
  licenses, git history, blame owners, deprecations and documentation drift.
- Test suites across behave, pytest, jest, playwright, cypress, robot, JUnit,
  TestNG, Cucumber in Java, Kotlin, Scala, TypeScript, JavaScript and Ruby,
  rspec, go test, xUnit, NUnit, SpecFlow, PHPUnit, Behat, Rust, XCTest, karate,
  gauge, k6 — plus the suite's own state: overlapping phrases, unused steps,
  dead page-object methods, admitted debts, quarantine and past-run timings.
- `--init` writes a manifest a repository can correct; what it states wins.
- `--install-hook git|agent`, `--agent-file`, `--only`, `--skip`, `--max-lines`,
  `--diff`, `--force`, `.wawe-ignore`.
- Rebuilds only when the tree has moved; JSON contract versioned as
  `where-are-we/1` and documented in `SCHEMA.md`.
