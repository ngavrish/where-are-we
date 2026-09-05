"""Finding files and reading them: the walk, its caches, the config and the
manifest.

Nothing here knows what a declaration or a section is. It answers "which files
are in this repository", "what does this one say" and "has it changed since the
last build", and the rest of the package is built on those answers.
"""

import json
import os
import re

from . import state
from .state import TRUNCATED, _FILE_CACHE, _IGNORE_CACHE, _WALK_CACHE

# `CACHE_SCHEMA`, `PARSE_COUNT`, `_PARSE_CACHE` and `__version__` are reached
# through `state` rather than imported by name: three of them are rebound, and
# a name imported by value would go on holding whatever it held at import time.


SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".runs"}


_PARSE_CACHE_FILE = ".wawe-cache.json"


def _load_parse_cache(out_dir: str) -> None:
    """Every `(kind, path)` -> `{"mtime", "size", "value"}` entry a previous
    build persisted, if it was written by this schema and this version of
    the tool; otherwise the whole file is discarded rather than trusted
    entry by entry.

    Walking the tree is cheap; parsing every module is not, and a repository
    where three files changed does not need the other nine hundred re-parsed."""
    try:
        with open(os.path.join(out_dir, _PARSE_CACHE_FILE), encoding="utf-8") as fh:
            doc = json.load(fh)
        if (doc.get("schema") != state.CACHE_SCHEMA
                or doc.get("version") != state.__version__):
            state._PARSE_CACHE = {}
            return
        state._PARSE_CACHE = doc.get("entries") or {}
    except (OSError, ValueError):
        state._PARSE_CACHE = {}


def _save_parse_cache(out_dir: str) -> None:
    # Never creates out_dir: build() calls this whether or not its caller
    # is about to write a map into out_dir (a --docs preview, say, never
    # does), and a directory that does not exist for that reason should stay
    # that way rather than gain a cache file nothing else will ever read.
    if not os.path.isdir(out_dir):
        return
    try:
        # A file that moved or was deleted since the last build otherwise
        # keeps its stale entry forever: nothing else ever prunes one.
        live = {k: v for k, v in state._PARSE_CACHE.items()
                if os.path.exists(k.split("\x1e", 1)[-1])}
        doc = {"schema": state.CACHE_SCHEMA, "version": state.__version__,
               "entries": live}
        with open(os.path.join(out_dir, _PARSE_CACHE_FILE), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    except OSError:
        pass


def _cached(path: str, kind: str, compute):
    """Run `compute()` once per file per kind, and reuse the answer after that.

    Keyed by the path and the kind of thing being computed, so the same file
    can hold a cached step-phrase list and a cached call graph without one
    overwriting the other. The stored mtime and size are what say whether the
    file has actually changed since; a build that trusted only the path would
    hand back last month's answer for a file the sha changed underneath.
    That check has a blind spot: a file rewritten with the same byte count
    inside the same filesystem timestamp tick keeps its old mtime and size,
    and the stale value is served. Nothing here detects that; WAWE_NO_CACHE=1
    is the escape hatch for anyone who suspects it has happened.

    WAWE_NO_CACHE=1 makes this a plain call to `compute()`, for whoever wants
    to be certain the cache is not the reason an answer looks a certain way.
    """
    if os.environ.get("WAWE_NO_CACHE"):
        state.PARSE_COUNT += 1
        return compute()
    try:
        st = os.stat(path)
    except OSError:
        state.PARSE_COUNT += 1
        return compute()
    key = f"{kind}\x1e{path}"
    entry = state._PARSE_CACHE.get(key)
    if (entry is not None and entry.get("mtime") == st.st_mtime
            and entry.get("size") == st.st_size):
        return entry["value"]
    value = compute()
    state.PARSE_COUNT += 1
    state._PARSE_CACHE[key] = {"mtime": st.st_mtime, "size": st.st_size, "value": value}
    return value




def _config(repo: str) -> dict:
    """Defaults from `.wawe.toml`, so a project states its own invocation once.

    Read with tomllib where it exists and by hand where it does not: this tool
    has no dependencies and is not about to grow one for six keys.
    """
    path = os.path.join(repo, ".wawe.toml")
    if not os.path.exists(path):
        return {}
    try:
        body = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    try:
        import tomllib
        data = tomllib.loads(body)
        out = data.get("where-are-we") or data.get("tool", {}).get("where-are-we") or data
        # `[synonyms]` is its own top-level table, named once for the project
        # even when the rest of its config sits under `[where-are-we]` or
        # `[tool.where-are-we]`; folded in here so it is never lost to
        # whichever of those three branches `out` ended up as.
        if isinstance(data.get("synonyms"), dict) and "synonyms" not in out:
            out = {**out, "synonyms": data["synonyms"]}
        return out
    except Exception:  # noqa: BLE001 — python 3.10, or a file with a typo in it
        # No tomllib on 3.10, so `[table]` headers are tracked by hand. A key
        # under `[where-are-we]` or `[tool.where-are-we]` flattens to the top,
        # the same as tomllib's own branches above; a key under any other
        # table (`[synonyms]`) nests under that table's name instead, so
        # `.wawe.toml`'s `[synonyms]` reaches `_config` the same shape on
        # every supported Python. Arrays of strings are the only value shape
        # this needs; nothing here reads a nested table of its own.
        out: dict = {}
        table = None
        for line in body.splitlines():
            m_table = re.match(r'^\s*\[([\w.-]+)\]\s*$', line)
            if m_table:
                table = m_table.group(1)
                continue
            m2 = re.match(r'\s*([\w-]+)\s*=\s*(.+)', line)
            if not m2:
                continue
            key, raw = m2.group(1), m2.group(2).strip()
            if raw.startswith("["):
                value = [x.strip().strip('"\'') for x in raw.strip("[]").split(",") if x.strip()]
            else:
                value = raw.strip('"\'')
            if table in (None, "where-are-we", "tool.where-are-we"):
                out[key] = value
            else:
                out.setdefault(table, {})[key] = value
        return out


_SECRET_SHAPES = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
    r"|pypi-[A-Za-z0-9_-]{40,}|[A-Za-z0-9+/]{40,}={0,2})")


def redact(value):
    """Never carry a credential into the map.

    The map is written into files that get committed and pasted into prompts, so
    anything that looks like a key is replaced by its shape. Paths to secrets are
    useful and kept; the secrets themselves are not."""
    if isinstance(value, str):
        return _SECRET_SHAPES.sub("[redacted]", value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


def _lines_matching(body: str, words: tuple, limit: int = 4) -> list:
    """Lines mentioning any of these words, without a regex.

    Every "interesting line" section used a pattern shaped `.*\b(?:a|b|c)\b.*`,
    which makes the engine try every position of every line of every file. The
    same answer comes out of a substring test, and a substring test is what the
    repository this was written for could actually afford: the map spent an hour
    on patterns before anyone saw a single requirement.
    """
    out = []
    for line in body.splitlines():
        low = line.lower()
        if any(w in low for w in words):
            out.append(line.strip()[:130])
            if len(out) >= limit:
                break
    return out



def _lines_matching(body, words, limit=4):
    """Lines mentioning any of these words, without a regex.

    Every "interesting line" section used a pattern shaped `.*(?:a|b|c).*`,
    which makes the engine try every position of every line of every file. A
    substring test gives the same answer at a fraction of the cost, and cost is
    the whole point: on a real repository the map spent an hour inside these
    patterns and the run never started.
    """
    out = []
    for line in body.splitlines():
        low = line.lower()
        if any(w in low for w in words):
            out.append(line.strip()[:130])
            if len(out) >= limit:
                break
    return out


def _slurp(path: str, limit: int = 400000) -> str:
    """Read a file once per run. The sections each used to walk and re-read the
    tree for themselves — a hundred sections over a hundred-thousand-file
    repository is a hundred passes over the same disk for the same bytes."""
    hit = _FILE_CACHE.get(path)
    if hit is not None:
        return hit
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read(limit)
    except OSError:
        body = ""
    if len(_FILE_CACHE) < 20000:
        _FILE_CACHE[path] = body
    return body


MAX_FILES = int(os.getenv("WAWE_MAX_FILES", "40000"))


def _ignores(root: str) -> list:
    """Patterns from `.wawe-ignore`, one per line, fnmatch against the relative
    path. A hundred-thousand-file monorepo does not want its build output read,
    and saying so once beats waiting for it every time."""
    if root in _IGNORE_CACHE:
        return _IGNORE_CACHE[root]
    pats = []
    for name in (".wawe-ignore", ".gitignore"):
        fp = os.path.join(root, name)
        if not os.path.exists(fp):
            continue
        try:
            for line in open(fp, encoding="utf-8", errors="replace"):
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line.rstrip("/"))
        except OSError:
            continue
        if name == ".wawe-ignore":
            break
    _IGNORE_CACHE[root] = pats
    return pats


def _ignored(rel: str, pats: list) -> bool:
    import fnmatch
    for p in pats:
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*") \
                or fnmatch.fnmatch(os.path.basename(rel), p):
            return True
    return False


def _walk(root: str, want: str) -> list[str]:
    key = (root, want)
    if key in _WALK_CACHE:
        return _WALK_CACHE[key]
    hits = []
    base_repo = os.getenv("AGENT_REPO", root)
    pats = _ignores(base_repo)
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in {".git", ".venv", "node_modules", "__pycache__", ".runs"}]
        for f in files:
            if not f.endswith(want):
                continue
            full = os.path.join(base, f)
            rel = os.path.relpath(full, base_repo)
            if pats and _ignored(rel, pats):
                continue
            hits.append(full)
            if len(hits) >= MAX_FILES:
                note = (f"the file walk stopped at {MAX_FILES} files under "
                        f"{base_repo} — raise WAWE_MAX_FILES or add to "
                        f".wawe-ignore; what is below that count is mapped and "
                        f"the rest is not")
                if note not in TRUNCATED:
                    TRUNCATED.append(note)
                _WALK_CACHE[key] = sorted(hits)
                return _WALK_CACHE[key]
    _WALK_CACHE[key] = sorted(hits)
    return _WALK_CACHE[key]






def _fingerprint(repo: str) -> str:
    """What the map was built from: the commit, and the newest file in the tree.

    A map is only worth rebuilding when the thing it describes has moved. The
    commit catches every committed change; the newest mtime catches the working
    tree, which is where a run's own edits live."""
    head = ""
    try:
        import subprocess
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:  # noqa: BLE001 — a repository without git still gets a map
        pass
    newest = 0.0
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith((".py", ".feature", ".sh", ".ts", ".js", ".json", ".md")):
                continue
            try:
                newest = max(newest, os.path.getmtime(os.path.join(base, fn)))
            except OSError:
                continue
    return f"{head}:{int(newest)}"


def _manifest(repo: str) -> dict:
    """What the repository says about itself.

    Autodetection gets the shape of a suite right and its vocabulary wrong: it
    can see that a directory holds classes full of selectors, not that the team
    calls them portal_ui and treats them as the only place a selector may live.
    So a repository may state it, in `.framework-map.json` at its root or in a
    fenced ```framework-map block in its README, and whatever it states wins
    over what was guessed.

    Keys, all optional:
      name, purpose        - what this suite is, in one line each
      layers               - {layer: sentence} describing the local vocabulary
      product_src          - paths to the application under test
      conventions          - list of sentences a newcomer must know
      entry_points         - {command: what it runs}
      notes                - anything else worth carrying into every agent
    """
    path = os.path.join(repo, ".framework-map.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh) or {}
        except (OSError, ValueError):
            return {}
    for name in ("README.md", "readme.md", "docs/README.md"):
        fp = os.path.join(repo, name)
        if not os.path.exists(fp):
            continue
        try:
            body = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        m = re.search(r"```framework-map\s*(.+?)```", body, re.S)
        if m:
            try:
                return json.loads(m.group(1)) or {}
            except ValueError:
                return {}
    return {}


def _looks_like_suite(repo: str) -> bool:
    """Whether this repository is a test suite with a product elsewhere: a
    steps directory or a feature file within a few levels of the root."""
    root = os.path.abspath(repo)
    try:
        for cur, dirs, files in os.walk(root):
            depth = cur[len(root):].count(os.sep)
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", ".venv", "dist", "build")]
            if os.path.basename(cur) in ("steps", "step_defs", "step_definitions"):
                return True
            if any(f.endswith(".feature") for f in files):
                return True
            if depth >= 3:
                dirs[:] = []
    except OSError:
        return False
    return False


def _product_roots() -> list:
    """Where the product under test is checked out. Given by PRODUCT_SRC (colon
    or comma separated); otherwise the siblings of the test repo are tried, so a
    suite that sits next to its application still gets routes, storage keys and
    test ids without being told."""
    repo0 = os.getenv("AGENT_REPO", "/work")
    stated = (_manifest(repo0).get("product_src") or [])
    if isinstance(stated, str):
        stated = [stated]
    if stated:
        return [x for x in stated if x]
    raw = os.getenv("PRODUCT_SRC", "")
    if raw.strip().lower() in ("none", "-", "off"):
        return []
    if raw:
        return [x for x in re.split(r"[:,]", raw) if x]
    repo = os.getenv("AGENT_REPO", "/work")
    # Siblings are tried only for a repository that is a test suite. A plain
    # code repository mapped from a directory of other projects indexed its
    # neighbours as "the product" - 231 files of three unrelated repositories,
    # and `defines` answered with their paths. --product none switches the
    # guess off for a suite too.
    if not _looks_like_suite(repo):
        return []
    out = []
    for parent in (os.path.dirname(os.path.abspath(repo)), "/checkout"):
        if not os.path.isdir(parent):
            continue
        for name in sorted(os.listdir(parent))[:40]:
            cand = os.path.join(parent, name, "src")
            if os.path.isdir(cand):
                out.append(cand)
    return out[:6]
