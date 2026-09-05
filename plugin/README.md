# where-are-we as a Claude Code plugin

The map of a repository, built before the first turn and asked instead of
grepped.

- **SessionStart hook** builds `.wawe/framework_map.md` (or rebuilds it after a
  commit) and puts the map's ~600-byte pointer into the session's context. The
  map itself stays on disk.
- **MCP server** `where-are-we` exposes the map as tools: `ask`, `find`,
  `defines`, `sections`, `callers`.
- **Skills**: `orient`, `ask`, `where-defined`, `spec-map`, `readmes`.
- **Opt-in strict mode** (`WAWE_STRICT=1` in the environment): `Grep`, `Glob`
  and `grep`/`rg`/`find` in Bash over a mapped repository are refused with the
  map's tools named instead - what a headless agent wants, and what an
  interactive session usually does not.

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
is idempotent and merges into whatever is already in those files.

## Try it without installing

    claude --plugin-dir /path/to/where-are-we/plugin
