# Changelog

## 1.5.0

- Every home of a name, with the line it ends on. The map gains a key
  `spans`: `{name: [{file, start, end, kind}]}`, one row per declaration site,
  sorted by file then start. `definitions` is unchanged, so nothing reading it
  moves; what changes is that a name declared in two files no longer keeps
  whichever of them the walk reached first and says nothing about the other.
  The end line is `ast`'s own `end_lineno` for Python and a tree-sitter node's
  `end_point` where a grammar is installed; for a language the pattern table
  reads it is null and prints as `?`, because a pattern has seen the line a
  declaration starts on and nothing that says where it stops, and a guessed
  end is worse than none for anyone editing by anchor.
- `--defines NAME` and the MCP `defines` tool list every home:
  `charge: a.py:10-24 (function), b.py:88-91 (function)`. The flag is new; the
  tool answered with one home per name before, chosen by directory order.
- `--at FILE:LINE` and the MCP `at` tool return the whole definition enclosing
  a line, which is the move after every stack trace and was until now a read
  at a guessed offset. The innermost definition, whole lines, cut to the
  answer budget with a `more:at:` handle for the rest. A line no definition
  encloses is answered with `no definition encloses FILE:LINE` and the nearest
  declarations, rather than with the wrong function.
- Under the `precise` extra, `.ts`, `.tsx`, `.js`, `.jsx` and `.go` get real
  end lines too. The grammar is asked how far a declaration runs and nothing
  else: which names those files declare, and on which line, is the pattern
  table's answer either way, so `definitions` is the same map with the extra
  installed and without it.
- `--context NAME` and the MCP `context` tool answer in one call what five
  calls answered before: where the name is declared and how far each
  declaration runs, the rows of the map that mention it, who calls it, what it
  calls, and its blast radius one hop out. Nothing new is parsed and nothing
  new is stored; it is `defines`, `ask`, `callers`, `callees` and `impact`
  over the same map, so an agent that lands on a name pays one round trip
  rather than five. The budget is allocated in two passes: every block is
  given the smaller of what printing all of itself would cost and its floor
  share - 15 percent for the declarations, 35 for the map's rows, 15 for the
  callers, 15 for the callees, 20 for the impact - and what nobody claimed is
  handed on in that same order to the blocks still short. So when the five
  answers together fit the budget, every one of them is printed whole; and the
  same name at the same budget is always the same answer, since the needs come
  from the map and the order is fixed. Whole rows; a block that could not
  print all of itself ends in a tail carrying a `more:ctx:` handle that `more`
  resolves like any other, and a block that could not be given room for even
  that is left out rather than printed as a count nobody can follow.
- `wawe-eval --tool context` measures the new tool with the harness that
  measures `ask`: over 100 names of the suite fixture, recall with handles is
  1.0 at 1500 and at 12000 bytes, which the CI step `context returns in one
  call what five calls return` asserts.
- What the repository is built around, ranked. The map gains a key `rank`:
  the top 200 definitions as `{name, file, line, score}`, best first, from
  PageRank over the graph the map already describes. Files are the nodes; an
  edge runs from a file that uses a name to the file that declares it,
  weighted by the square root of how often it uses it; aider's four
  multipliers apply, x10 for a long snake, kebab or camel name and x0.1 for a
  leading underscore or a name more than five files declare. A hundred
  iterations of power iteration at damping 0.85, nodes walked in sorted
  order, scores rounded to nine digits before they are sorted and ties broken
  by path, so two builds of one tree and both supported Pythons write the
  same bytes. No dependency: the iteration is forty lines of arithmetic.
- `--rank [FILE,...]` and the MCP `rank` tool answer the same question with
  the walk personalised on the files you name, which is the one worth asking:
  what should I read given that I am editing these. `--ask WORDS` alongside
  it, or the tool's `words`, weighs the identifiers in the question ten
  times. `--limit N` says how many rows; with no files and no words the
  answer is the stored key, which is what the CI step compares.
- `--files a.py,b.py` on `--ask`, and `files` on the MCP `ask` tool: inside
  every section the rows naming one of those files come first and the rest
  follow with the tail they had. A directory prefix counts and stops at a
  separator, so `--files bill` is not `billing.py`; paths are read relative to
  the repository root; a row that names only a basename is resolved through
  the files the map indexed, so `--files billing/` reaches
  `refund.py:refund` in the call graph; and a path nothing indexed matches is
  named on stderr rather than silently answered as the whole repository.
  `--files -` reads a newline separated list on stdin, which is where
  `git diff --name-only` goes. Without it no answer moves: every golden
  expected file was recorded before this and none of them changed.
- A scoped answer's `more:` handle carries the scope, as one more
  percent-encoded field: `more:rows:<section>:<words>:<offset>:<files>`. The
  offset counts rows in the order the scoped answer printed, so a handle
  without it would slice the unscoped order at that number, skipping every row
  `--files` demoted past the cut and repeating every row it promoted. `more()`
  rebuilds the scope from the field and reorders the section before it
  continues, so following a scoped answer's handles reaches every row an
  unscoped answer holds. An unscoped answer carries no fifth field and its
  handles are character for character what they were.
- `--rank` reads `--files` too, so the flag that means "the files I am working
  in" means it on both tools. `--limit` is refused below 1 rather than sliced
  from the end, which is what the MCP tool already did.
- The parse cache is keyed on content. An entry is now `(path, kind, sha256 of
  the file's bytes)` rather than `(path, kind, mtime, size)`, so a rewrite that
  kept its byte count and had its timestamp put back (rsync --times, cp -p,
  tar -p, a restore from a build cache, a `git checkout` of a line the same
  length) is re-parsed without `--force`. That was the one staleness hole the
  README named out loud, and it is closed.
- Hashing stays affordable because it is pre-filtered: a file whose mtime,
  size and inode change time are what they were when its hash was last taken
  is not read at all. A rebuild of a tree nobody touched hashes nothing and
  parses nothing, and `WAWE_DEBUG_PARSES=1` now prints `hashed N files` beside
  `parsed N files` so both halves of that claim can be checked. The inode
  change time is in the pre-filter because the mtime and the size alone are
  exactly the case content addressing exists to catch, and nothing in
  userland can put a ctime back.
- New map key `content_root`: one sha256 over the sorted `(path relative to
  the repository, hash)` pairs of every indexed file. `fingerprint` keeps its
  documented `<commit>:<newest mtime in nanoseconds>` format and its meaning;
  the root is the sibling that says what the tree holds rather than when it
  was last written to. A build is now skipped only when both agree.
- `--diff` names the files whose content moved before it names the map keys
  that moved with them.
- The parse cache schema is 3. A 1.4 cache is not read: `ts:<lang>` stored a
  list of names and now stores a list of `[name, start, end, kind]` rows, and
  an old entry read under the new code would index a character out of a
  string. Neither is a 1.5.0 cache written before the key changed shape, since
  an entry validated by hash has no hash in it.
- Upgrading does not add `spans` to a map that is already on disk. A build
  skips a tree that has not moved, so run `where-are-we --repo . --out ...
  --force` once after upgrading, or wait for the next commit. Until then
  `--defines` answers in the old `- \`name\` - file:line` shape from the old
  map, and `--at` says the map has no spans index and names the fix.

## 1.4.1

- Receivers the syntax settles. A call written `NAME.callee(...)` used to be
  placed by the callee's name alone, so every file with a `def add` was a
  candidate for `out.add(key)`. Three shapes of receiver are now read, none
  of them needing a type checker. A receiver that resolves to one indexed
  file which does not declare the name is a facade, and that file's own
  `from M import name` line is followed, three steps at most, to the file
  with the `def`: `mapper.build(...)` in `hooks.py` is `_mapper/build.py`'s
  `build`, not a choice between two files. A receiver the function itself
  bound to a builtin (a literal, a comprehension, an f-string, one of the
  builtin constructors, or `defaultdict`, `Counter`, `deque` and
  `OrderedDict` through an import from outside the tree) is not a
  first-party object, so `out = set()` followed by `out.add(key)` is
  `set.add` and no edge at all. A parameter's default counts as what the
  function bound and `None` does not, `*args` and `**kwargs` are a tuple and
  a dict, a name a nested function never binds is the one written around it,
  and `d.setdefault(k, set())` is a set whatever `d` is; a name the function
  also bound to something else, and a receiver that is not a name such as
  `d[k]`, keep the candidate list. And `self.name(...)` and `cls.name(...)`
  go to the class the method is in: declared there or by a base in the same
  file, the call is local and no cross-file edge; declared by exactly one
  base in another file, the edge names that file. A base is followed only
  where the file says where it came from, so `class D(Base)` with no import
  of `Base` and `class D(other.Base)` where nothing binds `other` keep the
  mark rather than matching a class name anywhere in the tree.
- A directory named after an imported module no longer speaks for it on its
  own. `_module_is_here` counts a directory whose last path part matches the
  module, at any depth, which made `tests/fixtures/logging/` enough for
  `logging.info(...)` to reach a first-party `info`. The directory now has to
  hold one of the callee's candidate homes. A vendored
  `requests/__init__.py` that declares `get` is a file and still answers for
  `requests.get(...)`.
- The numbers after those rules. On this repository the marks under the same
  60 keys go from 20 to 1, and the one that stays is `pool[kind].add(word)`,
  a call on a subscript. Mapping the previous release's own checkout with
  both releases, the marks under the same 60 keys go from 20 to 1 as well.
  `call_graph_stats` for this repository is now 0.2431 over 2308 Python
  sites, with 156 edges and 4 of them marked, against 145 and 36 before.
  Only the names something was actually called on are kept in the parse
  cache, so this costs `.wawe-cache.json` 241 KB against 159 KB and a full
  build of this tree 2.11s against 1.97s. The cache record these rules read
  is stored under its own kind, so upgrading re-parses the call graph rather
  than serving 1.4.0 answers from a warm cache.

- An effects manifest, so a command guard can tell this tool's reads from
  its writes. `src/where_are_we/effects.py` holds one table: every flag the
  command line parser knows against one of `read`, `writes-map-dir`,
  `writes-repo`, `writes-config` and `network`, in that order, and a
  command's class is the highest class any of its flags carries.
  `where-are-we --effects` prints the table, `--effects --json` prints
  `{"schema": "where-are-we-effects/1", "flags": ..., "order": ...}`, and the
  same JSON ships beside the code as `effects.json`. `--effects --
  <command line>` classifies one command line with this tool's own parser
  and runs nothing: `--out /tmp/m --ask x` is `writes-map-dir`,
  `--install-hook git` is `writes-config`, `--mcp` is `read`. Flags are
  resolved the way argparse resolves them, abbreviations and all, and the
  dispatch of `--effects` itself goes through the same resolution, so
  `--eff` cannot be classified as one thing and run as another. A line
  naming none of the flags that answer from an existing map builds one into
  `--out`, so its floor is `writes-map-dir` whatever else it says; `--specs`
  is one of the exceptions, since it writes `spec_map.*` and returns. The
  JSON carries a `notes` object as well, saying per class what it touches,
  so a guard reading the file is told what a `read` may still append to.
  The table cannot drift: a CI step fails when the parser knows a flag the
  table does not, when the table names one the parser does not, when a named
  flag's class is not the one documented, or when `effects.json` in the
  checkout differs from what the table prints or from the copy installed
  beside the code.
- `--dry-run` prints every path a command can write, `would write` when
  nothing is there and `would replace` when a file is, and exits without
  writing any of them. The hook paths come from `hooks.paths()`, the one
  computation the installers themselves use, so a preview names the files
  the real run touches. It covers every command line and not only the three
  that write into a repository: `--docs write` is previewed from a map built
  with no cache, `--specs` names `spec_map.json` and `spec_map.md` without
  running the tracker command, a line that only reads says `nothing to
  write: --ask only read` rather than answering and appending to the answer
  log, and `--install-hook claude` with `HOME` unset gives the refusal the
  real install gives instead of naming the home directory of whoever the
  passwd entry belongs to. A CI step lists the files of the tree and their
  hashes before and after a dry run of `--init`, `--agent-file`,
  `--install-hook git` and `--install-hook claude`, and then runs those
  commands for real to prove every path the preview named is a path the run
  creates.

## 1.4.0

- Honest edges. A cross-file call graph edge is written `charge (a.ts)` when
  one indexed file declares the callee, and `charge (a.ts|c.ts)?` when
  several do: the edge names every file that declares the name, sorted, and
  the question mark says the map is choosing between them rather than letting
  the reader take one file for a fact. Three calls that used to produce an
  edge no longer do or no longer guess: a plain call to a name the calling
  file declares itself is a local call and is left out of a cross-file
  graph; a call through a module this tree does not declare, which is what
  `ast.walk(...)` is, and what `from os import path` followed by
  `path.join(...)` is, is not in the tree at all and is left out too; and a
  call the caller's own `from MOD import name` (or
  `import { name } from "./mod"`) settles is written plain. `callers`,
  `callees` and `impact` match on the name alone, so a marked edge is found
  exactly as an unmarked one is, and print the mark as they find it. Every
  `impact` reply now ends its rules line with "an edge ending in ? names
  every file that declares the callee, because more than one does". Mapping
  the previous release's checkout with both releases, the marks under the
  same 60 keys go from 40 to 17, and `cli.py:main -> build (ask.py)?`, which
  pointed at the wrong `build`, is now `build (build.py)`. `--callers walk`
  on this repository's own map used to answer with eleven callers of
  `ast.walk` and `os.walk` and not one caller of a `walk` this tree
  declares.
- Numbers for the call graph, and for the tree it was read from. The build
  records `call_graph_stats` in `framework_map.json`: per language group
  (`python`, `ts_js`, `go`) how many callee names the walk looked at
  (`sites`), how many of those names some indexed file declares
  (`resolved`), how many several files declare (`ambiguous`), and then the
  graph itself, the cross-file edges written (`edges`) and how many carry the
  mark (`marked`). `resolution_rate` is `resolved / sites`, which says how
  first-party a tree's calls are: builtins, methods and standard library
  names are in its denominator and a same-file call is in its numerator, so
  it is a fact about the code rather than a score for the graph. On this
  repository it is 0.239 over 2230 Python sites, with 145 edges and 36 of
  them marked. `wawe-eval --map OUT --graph` prints all of it, and `--json`
  carries it. With the `precise` extra installed it parses the TypeScript,
  JavaScript and Go again with tree-sitter and prints the delta, which is
  where the pattern pass admits what it over-counted: on the poly fixture the
  regex sees 5 Go sites to tree-sitter's 2.

## 1.3.0

- `callees` (MCP), `--callees NAME`: what a function calls, the other
  direction of `callers`, from the two call graphs the map already holds.
- `impact` (MCP), `--impact NAME [--impact-depth N]`: every `file:func` that
  reaches a name within N hops, grouped by hop, cycles walked once, capped at
  200 entries. Every reply opens with the rules it was built under: hops are
  followed by name, only cross-file calls are in the graph, and the map keeps
  a bounded number of graph keys, so the radius is a floor.

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
