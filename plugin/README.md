# where-are-we as a Claude Code plugin

The map of a repository, built before the first turn and asked instead of
grepped.

- **SessionStart hook** builds `.wawe/framework_map.md` (or rebuilds it after a
  commit) and puts the map's ~600-byte pointer into the session's context. The
  map itself stays on disk.
- **MCP server** `where-are-we` exposes the map as eleven tools: `ask`, `find`,
  `defines`, `at`, `context`, `rank`, `sections`, `callers`, `callees`,
  `impact`, and `more`, which takes the handle an answer printed where it was
  cut and returns the part that was left out. `defines` names every file that
  declares a name, with the line each declaration ends on, `at` takes the
  `file:line` a stack trace gives you and returns the whole definition around
  it, and `rank` says which definitions the repository is built around,
  personalised on the files you are editing when you name them. `callees` is
  the other direction of `callers`, and `impact` walks that graph back several
  hops at once: every `file:func` that reaches a name, grouped by how far away
  it is. `context` is those five answers about one name in a single call, each
  block on a fixed share of the budget with a handle for what it cut.
- **Skills**: `orient`, `ask`, `rank`, `where-defined`, `spec-map`, `readmes`.
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

One more the plugin does not turn on for you: `--ctags` writes `.wawe/tags`
beside the map, in the format vim, emacs, helix, kakoune and `readtags` have
always read, so an editor open on the same checkout jumps to a definition with
no language server running.

## Try it without installing

    claude --plugin-dir /path/to/where-are-we/plugin
