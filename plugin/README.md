# where-are-we as a Claude Code plugin

The map of a repository, built before the first turn and asked instead of
grepped.

- **SessionStart hook** builds `.wawe/framework_map.md` (or rebuilds it after a
  commit) and puts the map's ~600-byte pointer into the session's context. The
  map itself stays on disk.
- **MCP server** `where-are-we` exposes the map as eighteen tools: `affected`,
  `ask`, `at`, `callees`, `callers`, `context`, `dead`, `defines`, `find`,
  `hot`, `impact`, `more`, `path`, `range`, `rank`, `reaches`, `sections`,
  `unreached`, where `more` takes the handle an answer printed
  where it was cut and returns the part that was left out. `defines` names
  every file that declares a name, with the line each declaration ends on,
  `at` takes the `file:line` a stack trace gives you and returns the whole
  definition around it, and `rank` says which definitions the repository is
  built around, personalised on the files you are editing when you name them.
  `callees` is the other direction of `callers`, and `impact` walks that graph
  back several hops at once: every `file:func` that reaches a name, grouped by
  how far away it is. `context` is those five answers about one name in a
  single call, each block on a fixed share of the budget with a handle for
  what it cut. `affected` takes the files a change touched and answers which
  tests reach them: the scenarios, their feature files, the routes and page
  objects, and the files the graph holds no row for, so you know what the
  answer does not cover. A scenario is reached through a step phrase matched
  as a 40 character substring, a route through the file it is served from,
  and a changed feature file selects its own scenarios; `format="behave"`
  prints one `--name` per affected scenario rather than any tag or any file
  pattern, and two scenarios of one name are one argument that behave applies
  to both. A selection the tool reply can hold comes back whole; a
  larger one comes back as its count, its first selectors and the
  `--affected-out FILE` command line that writes all of it to a file, which is
  where a large selection belongs.
  `reaches` is that question from the other end: hand it one function or
  class and it names the scenarios, pytest cases and routes that reach it,
  grouped by feature file, with the chain of calls under the first scenario
  of each, and with no depth cap. A class is answered by what is declared
  inside it, because `spans` links a method to its class through nothing but
  a dotted name and the line it sits on; where neither is there the first
  line says the counts are a floor. `unreached` names the product functions
  and classes no test reaches at all, ranked, and its first line states how
  much of the call graph resolved, so the list is read as what it is rather
  than as a coverage report. It also prints the files it treated as suite,
  because the product split is only as good as the map's own heuristics, and
  a map with no step function and no test case says there is nothing to reach
  from and lists nothing.
  to both. A selection is never cut to a budget; on the command line
  `--affected-out FILE` writes it to a file and leaves stdout to the answer a
  person reads. `path` walks the same rows the other way, caller to callee,
  and prints the shortest chain from one name to another with the rule that
  placed each edge and the line the call is on; an ambiguous hop names every
  file that declares the callee, a cycle terminates, and where there is no
  chain the answer says how far the walk got. Only cross-file calls are in
  that graph, which every one of these answers says out loud. `range` hands
  an editor what it needs before an `Edit`: every home of a name as
  `file:start-end kind`, the text of the shortest, and the first line, the
  last, and the one after the last, each with the text of that line, so an
  insertion lands outside the definition rather than inside it. `dead` names
  the definitions no call row lands on, grouped by file, and it is a list of
  questions rather than a list of dead code: a call through an imported
  module and a call inside the declaring file leave no row, so on a library
  most rows are calls the map could not place, while on a suite, where a page
  object is called from step modules, it is sharp. Its first line leads with
  that and names the exclusions. `hot` multiplies the map's `rank` score by
  the commits its most-changed-files section counted and prints both numbers,
  so a reviewer can see which of the two put a row where it is; that section
  is the forty busiest files, so anything outside it counts 1, and an older
  map that can only count five commit lines a file prints `5+`.
- **Skills**: `orient`, `ask`, `rank`, `where-defined`, `spec-map`,
  `readmes`, and three for the graph answers: `what-to-rerun`
  (`affected`, `reaches`, `unreached`), `lines-to-edit` (`range`,
  `path`) and `what-to-look-at` (`hot`, `dead`).
- **Opt-in strict mode** (`WAWE_STRICT=1` in the environment): `Grep`, `Glob`
  and `grep`/`rg`/`ag`/`find`/`fd`/`ack` in Bash over a mapped repository are
  refused with the map's tools named instead - what a headless agent wants,
  and what an interactive session usually does not. A `find` that deletes or
  execs a mutating command (`-delete`, `-exec rm ...`) is left alone: it is
  changing the tree, not searching it, and the map has nothing to offer in
  its place.

## Install

The plugin needs the `where-are-we` command on PATH; it does not install it:

    pipx install where-are-we        # or: uv tool install where-are-we

Then, in Claude Code:

    /plugin marketplace add ngavrish/where-are-we
    /plugin install where-are-we@where-are-we

`.wawe/` ignores itself (the hook writes `.wawe/.gitignore`), so the repository's own `.gitignore` is never touched.

## Other harnesses

This plugin is Claude Code specific: the SessionStart hook and the skills only
exist there. For Cursor, Codex or Gemini CLI, skip the plugin and wire the
`where-are-we` command straight into that harness's own conventions:

    where-are-we --repo . --install-hook cursor   # .cursor/rules + .cursor/mcp.json
    where-are-we --repo . --install-hook codex    # AGENTS.md + ~/.codex/config.toml
    where-are-we --repo . --install-hook gemini   # GEMINI.md + .gemini/settings.json

Each writes a pointer where that CLI already looks and an MCP server entry, so
the map is read on the first turn and askable as a tool after that. Every kind
is idempotent and merges into whatever is already in those files. If any of
them - or `.git/hooks/*` for `--install-hook git` - is a symlink, the write is
refused and nothing is touched: the message names the path.

`where-are-we --effects` prints what every flag of the command does to the
disk (read, writes-map-dir, writes-repo, writes-config, network) for a guard
that checks a command before it runs, and `--dry-run` names every path a write
would touch without touching it.

Three more the plugin does not turn on for you. `--ctags` writes `.wawe/tags`
beside the map, in the format vim, emacs, helix, kakoune and `readtags` have
always read, so an editor open on the same checkout jumps to a definition with
no language server running. `--cost` says what each section of the map costs to
carry, heaviest first, for deciding what `--only`, `--skip` and `--max-lines`
should say. `--export FILE` packs the notice, the counts, the priced section
list and the brief into one file, for a PR comment or a paste, where there is
no `.wawe/` to read from.

## Try it without installing

    claude --plugin-dir /path/to/where-are-we/plugin
