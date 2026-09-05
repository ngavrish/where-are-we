"""Wire the map into something that already runs, so nobody has to remember it.

git: post-checkout, post-merge and post-commit -- the three moments the tree
becomes something other than what the map describes. The command is the
cheap one: it exits immediately when the repository has not moved.

claude (alias agent): a SessionStart hook for Claude Code, and the same
command works as a task in any other harness -- it writes the brief into the
agent file, so the first turn of a session already knows where it is.

cursor, codex, gemini: those CLIs read their own conventions rather than a
SessionStart hook, so each gets a pointer written where it already looks
(a Cursor rule, an AGENTS.md/GEMINI.md block) plus an MCP server entry, so
the map is both read on the first turn and askable as a tool after that.
"""
import json
import os
import re

_BLOCK_START = "<!-- where-are-we:start -->"
_BLOCK_END = "<!-- where-are-we:end -->"
_MCP_ARGS = ["--repo", ".", "--out", ".wawe", "--mcp"]


def _ensure_map(repo: str) -> None:
    """Build the map into <repo>/.wawe if it is not there yet, same three
    files main() writes, and keep .wawe out of the repository's own history --
    an agent harness reads it, nobody commits it."""
    from . import mapper

    wawe_dir = os.path.join(repo, ".wawe")
    map_md = os.path.join(wawe_dir, "framework_map.md")
    if not os.path.exists(map_md):
        # Created before the build: build() saves its parse cache into
        # out_dir itself, and only into a directory that already exists.
        os.makedirs(wawe_dir, exist_ok=True)
        m = mapper.redact(mapper.build(repo, out_dir=wawe_dir))
        m["fingerprint"] = mapper._fingerprint(repo)
        with open(os.path.join(wawe_dir, "framework_map.json"), "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=2)
        with open(map_md, "w", encoding="utf-8") as fh:
            fh.write(mapper.digest(m))
        with open(os.path.join(wawe_dir, "framework_map_brief.md"), "w", encoding="utf-8") as fh:
            fh.write(mapper.brief(m))
    else:
        os.makedirs(wawe_dir, exist_ok=True)
    with open(os.path.join(wawe_dir, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write("*\n")


def _merge_block(path: str, block_body: str) -> bool:
    """Replace the where-are-we block between markers, or append one.

    Whatever else is in the file -- a human's prose, another tool's block --
    stays. Returns whether the file's content actually changed, so a caller
    can tell "installed" from "already installed".
    """
    block = f"{_BLOCK_START}\n{block_body}{_BLOCK_END}\n"
    try:
        with open(path, encoding="utf-8") as fh:
            cur = fh.read()
    except OSError:
        cur = ""
    if _BLOCK_START in cur and _BLOCK_END in cur:
        new = re.sub(re.escape(_BLOCK_START) + r".*?" + re.escape(_BLOCK_END),
                     block.rstrip("\n"), cur, flags=re.S)
    else:
        new = (cur.rstrip() + "\n\n" if cur.strip() else "") + block
    if new == cur:
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def _load_json_conf(path: str, key: str) -> tuple[dict | None, str]:
    """Read a JSON config file this hook merges a `key` section into, or say
    why it can't be merged into.

    A missing file is the normal first run, not an error: it becomes {}. A
    file that exists but does not parse, or whose `key` is present and not
    an object, is left exactly as it is -- guessing what a broken file meant
    and overwriting it would lose whatever put it in that shape.
    """
    if not os.path.exists(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8") as fh:
            conf = json.load(fh)
    except (OSError, ValueError):
        return None, f"{path} is not valid JSON; fix it or move it aside, nothing was written"
    if not isinstance(conf, dict) or not isinstance(conf.get(key, {}), dict):
        return None, f"{path} is not valid JSON; fix it or move it aside, nothing was written"
    return conf, ""


def _mcp_entry_changed(conf: dict) -> bool:
    entry = {"command": "where-are-we", "args": list(_MCP_ARGS)}
    return conf.get("mcpServers", {}).get("where-are-we") != entry


def _write_mcp_conf(path: str, conf: dict) -> None:
    """Add the where-are-we server to a Cursor/Gemini style mcpServers file,
    leaving any server already configured there untouched."""
    conf.setdefault("mcpServers", {})["where-are-we"] = {
        "command": "where-are-we", "args": list(_MCP_ARGS)}
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(conf, fh, indent=2)


def _install_git(repo: str, product: str, out: str, agent_file: str) -> str:
    cmd = ["where-are-we", "--repo", repo]
    if product:
        cmd += ["--product", product]
    if out:
        cmd += ["--out", out]
    if agent_file:
        cmd += ["--agent-file", agent_file]
    line = " ".join(cmd) + " --quiet || true"

    hooks_dir = os.path.join(repo, ".git", "hooks")
    if not os.path.isdir(hooks_dir):
        return f"{hooks_dir} does not exist -- is {repo} a git repository?"
    written = []
    for name in ("post-checkout", "post-merge", "post-commit"):
        path = os.path.join(hooks_dir, name)
        body = ""
        if os.path.exists(path):
            try:
                body = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                body = ""
            if "where-are-we" in body:
                continue
        if not body.strip():
            body = "#!/bin/sh\n"
        body = body.rstrip("\n") + f"\n\n# keep the map in step with the tree\n{line}\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        written.append(name)
    return "installed: " + ", ".join(written) if written else "already installed"


def _install_claude(repo: str, product: str, out: str, agent_file: str, home: str) -> str:
    cmd = ["where-are-we", "--repo", repo]
    if product:
        cmd += ["--product", product]
    if out:
        cmd += ["--out", out]
    if agent_file:
        cmd += ["--agent-file", agent_file]
    line = " ".join(cmd) + " --quiet || true"

    settings = os.path.join(home, ".claude", "settings.json")
    conf, error = _load_json_conf(settings, "hooks")
    if error:
        return error
    entries = conf.setdefault("hooks", {}).setdefault("SessionStart", [])
    if any("where-are-we" in h.get("command", "")
           for e in entries for h in e.get("hooks", [])):
        return f"already installed in {settings}"
    entries.append({"hooks": [{"type": "command", "command": line}]})
    os.makedirs(os.path.dirname(settings), exist_ok=True)
    with open(settings, "w", encoding="utf-8") as fh:
        json.dump(conf, fh, indent=2)
    return f"installed in {settings} (SessionStart)"


def _install_cursor(repo: str) -> str:
    from . import mapper

    rule_path = os.path.join(repo, ".cursor", "rules", "where-are-we.mdc")
    mcp_path = os.path.join(repo, ".cursor", "mcp.json")
    map_path = os.path.join(repo, ".wawe", "framework_map.md")

    conf, error = _load_json_conf(mcp_path, "mcpServers")
    if error:
        return error

    content = ("---\n"
               "description: the repository map\n"
               "alwaysApply: true\n"
               "---\n"
               + mapper.pointer(map_path))
    try:
        with open(rule_path, encoding="utf-8") as fh:
            cur = fh.read()
    except OSError:
        cur = None
    changed_rule = cur != content
    changed_mcp = _mcp_entry_changed(conf)

    if changed_rule:
        os.makedirs(os.path.dirname(rule_path), exist_ok=True)
        with open(rule_path, "w", encoding="utf-8") as fh:
            fh.write(content)
    if changed_mcp:
        _write_mcp_conf(mcp_path, conf)

    if changed_rule or changed_mcp:
        return f"installed: {rule_path}, {mcp_path}"
    return f"already installed in {rule_path} and {mcp_path}"


def _install_codex(repo: str, home: str) -> str:
    from . import mapper

    agents_path = os.path.join(repo, "AGENTS.md")
    map_path = os.path.join(repo, ".wawe", "framework_map.md")
    changed_agents = _merge_block(agents_path, mapper.pointer(map_path))

    toml_path = os.path.join(home, ".codex", "config.toml")
    try:
        with open(toml_path, encoding="utf-8") as fh:
            cur = fh.read()
    except OSError:
        cur = ""
    changed_toml = "[mcp_servers.where-are-we]" not in cur
    if changed_toml:
        section = ('[mcp_servers.where-are-we]\n'
                   'command = "where-are-we"\n'
                   'args = ["--repo", ".", "--out", ".wawe", "--mcp"]\n')
        new = (cur.rstrip("\n") + "\n\n" if cur.strip() else "") + section
        os.makedirs(os.path.dirname(toml_path), exist_ok=True)
        with open(toml_path, "w", encoding="utf-8") as fh:
            fh.write(new)

    if changed_agents or changed_toml:
        return f"installed: {agents_path}, {toml_path}"
    return f"already installed in {agents_path} and {toml_path}"


def _install_gemini(repo: str) -> str:
    from . import mapper

    md_path = os.path.join(repo, "GEMINI.md")
    settings_path = os.path.join(repo, ".gemini", "settings.json")
    map_path = os.path.join(repo, ".wawe", "framework_map.md")

    conf, error = _load_json_conf(settings_path, "mcpServers")
    if error:
        return error

    changed_md = _merge_block(md_path, mapper.pointer(map_path))
    changed_settings = _mcp_entry_changed(conf)
    if changed_settings:
        _write_mcp_conf(settings_path, conf)

    if changed_md or changed_settings:
        return f"installed: {md_path}, {settings_path}"
    return f"already installed in {md_path} and {settings_path}"


def install(repo: str, kind: str, product: str, out: str, agent_file: str,
            home: str | None = None) -> str:
    """Wire the map into something that already runs. See the module
    docstring for what each kind does; `home` overrides `~` so tests never
    touch a real home directory. Only cursor, codex and gemini pre-build the
    map into .wawe: git and claude already build into whatever --out the
    caller passed on their own first trigger, so a pre-build for them would
    be a second map in a different place."""
    if kind == "agent":
        kind = "claude"
    home = home or os.path.expanduser("~")

    if kind == "git":
        return _install_git(repo, product, out, agent_file)
    if kind == "claude":
        return _install_claude(repo, product, out, agent_file, home)
    if kind in ("cursor", "codex", "gemini"):
        _ensure_map(repo)
        if kind == "cursor":
            return _install_cursor(repo)
        if kind == "codex":
            return _install_codex(repo, home)
        return _install_gemini(repo)
    raise ValueError(f"unknown --install-hook kind: {kind}")
