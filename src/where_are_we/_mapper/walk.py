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
from .state import (TRUNCATED, _FILE_CACHE, _IGNORE_CACHE, _LINK_CACHE,
                    _WALK_CACHE)

# `CACHE_SCHEMA`, `PARSE_COUNT`, `_PARSE_CACHE` and `__version__` are reached
# through `state` rather than imported by name: three of them are rebound, and
# a name imported by value would go on holding whatever it held at import time.


SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".runs"}


_PARSE_CACHE_FILE = ".wawe-cache.json"


def _sweep_stale(path: str) -> None:
    """Remove temporaries a killed writer left beside `path`.

    A build killed between writing its temporary and renaming it (the plugin's
    hook timeout does exactly that) leaves the file behind, and nothing else
    would ever remove it. Only temporaries whose process is gone are touched:
    a live builder's temporary is a file it is about to rename into place.
    """
    import glob

    for tmp in glob.glob(f"{glob.escape(path)}.*.tmp"):
        try:
            pid = int(tmp[len(path) + 1:-len(".tmp")])
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            try:
                os.remove(tmp)
            except OSError:
                pass
        except OSError:  # alive, and owned by somebody else
            continue


def _stage_atomic(path: str, text: str) -> str:
    """Write `text` beside `path` under a temporary name, and return that name.

    The temporary file carries the writing process's pid, so two builders on
    one output directory never share one, and it sits in the destination
    directory rather than in the system temp, so the `os.replace` that follows
    is a rename inside one filesystem, which is the only kind that is atomic.
    """
    _sweep_stale(path)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    return tmp


def _discard(tmps) -> None:
    """Remove staged temporaries after a write that did not finish."""
    for tmp in tmps:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _write_atomic(path: str, text: str) -> None:
    """Write a file so that nothing ever reads a half-written one.

    Every artefact this package writes is read by something else while it is
    being written: the MCP server answers from `framework_map.json` on every
    tool call, a git hook rebuilds the map while a session is asking it, two
    sessions start in one repository at once. `open(path, "w")` truncates the
    file at open and grows it over the write, so a reader inside that window
    gets zero bytes or a prefix and answers "not in the map", which is the one
    wrong answer that sends a reader back to grepping. A build killed in that
    window (the plugin's hook timeout does exactly this) leaves the truncated
    file on disk for good.

    Writing to a temporary and renaming it over the target removes both: a
    reader sees either the whole previous file or the whole new one, and a
    kill leaves the previous one untouched.
    """
    tmp = _stage_atomic(path, text)
    try:
        os.replace(tmp, path)
    except OSError:
        _discard([tmp])
        raise


def _write_atomic_group(pairs) -> None:
    """Several files replaced back to back, once all of them are complete.

    `_write_atomic` makes each file whole on its own; this makes a set of them
    consistent with each other. Every file is written to its temporary first,
    and only then are the renames done, one after another with no work in
    between, so the window in which a reader could see a mixture is a few
    renames wide rather than a whole serialisation wide, and a kill before the
    first rename leaves the entire previous set in place.

    `pairs` is `[(path, text), ...]` and the renames happen in that order.
    """
    staged = []
    try:
        for path, text in pairs:
            staged.append((_stage_atomic(path, text), path))
    except OSError:
        _discard([tmp for tmp, _ in staged])
        raise
    for i, (tmp, path) in enumerate(staged):
        try:
            os.replace(tmp, path)
        except OSError:
            _discard([t for t, _ in staged[i:]])
            raise


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
        # Atomically: a reader that lands mid-write used to see a prefix,
        # fail to parse it and throw the whole cache away, and re-parse a
        # tree nobody had touched.
        _write_atomic(os.path.join(out_dir, _PARSE_CACHE_FILE), json.dumps(doc))
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
    and the stale value is served. `--force` is the escape hatch: it sets
    `state.PARSE_CACHE_READS` False for that build, so nothing here is
    believed and every answer is computed again, and the cache is rewritten
    from what that build found.

    WAWE_NO_CACHE=1 goes further and makes this a plain call to `compute()`
    with nothing recorded at all, for whoever wants a build that leaves the
    cache exactly as it was.
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
    if state.PARSE_CACHE_READS:
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

    tomllib is stdlib on every supported Python, so this reads with it alone:
    this tool has no dependencies and is not about to grow one for six keys.
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
    except Exception:  # noqa: BLE001, a file with a typo in it
        return {}
    out = data.get("where-are-we") or data.get("tool", {}).get("where-are-we") or data
    # `[synonyms]` is its own top-level table, named once for the project
    # even when the rest of its config sits under `[where-are-we]` or
    # `[tool.where-are-we]`; folded in here so it is never lost to
    # whichever of those three branches `out` ended up as.
    if isinstance(data.get("synonyms"), dict) and "synonyms" not in out:
        out = {**out, "synonyms": data["synonyms"]}
    return out


# Issuer prefixes: a string in one of these shapes is a credential wherever it
# appears, whatever the line around it says. Each one is anchored on a prefix a
# vendor reserved, so a false positive would have to be a deliberate imitation.
#
# The lookbehind matters more than it looks. Without it `sk-` matched inside
# `docs/ask-the-map-and-not-the-tree.md` and `rk_live_` inside
# `work_live_configuration`, so a file name and an identifier came back as
# `docs/a[redacted].md` and `wo[redacted]`. A prefix only counts at the start
# of a word.
_SECRET_SHAPES = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:AKIA[0-9A-Z]{16}"                          # AWS access key id
    r"|ghp_[A-Za-z0-9]{20,}"                        # GitHub personal token
    r"|gh[opsu]_[A-Za-z0-9]{20,}"                   # the rest of the gh_ family
    r"|github_pat_[A-Za-z0-9_]{20,}"                # GitHub fine-grained token
    r"|xox[baprse]-[A-Za-z0-9-]{10,}"               # Slack
    r"|sk_(?:live|test)_[A-Za-z0-9]{10,}"           # Stripe
    r"|rk_(?:live|test)_[A-Za-z0-9]{10,}"           # Stripe restricted
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{20,}"             # OpenAI
    r"|pypi-[A-Za-z0-9_-]{40,}"                     # PyPI upload token
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+)?"  # JWT
    r")")

# A PEM block, header to footer, in one string. Redacting only the header (all
# this used to do) was worse than redacting nothing: the header is the line a
# reader would have recognised, and the base64 body stayed in the map and came
# back out of `find` verbatim. `lines` holds a file as a list of separate
# strings, so `redact` also runs a state machine over a list; this pattern is
# for a body that arrives whole, in a docstring or a snippet.
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL)

# A long base64 run, back after being dropped for destroying commit shas, but
# gated this time: the run has to carry a `+` or end in `=` padding. That is
# what a base64 blob has and what the two things this rule used to ruin do not.
#
# `/` is deliberately not a gate, whatever it looks like: a Java package path
# is a forty-character run of letters and slashes and nothing else, and
# `src/main/java/com/example/service/impl/CustomerServiceImpl` is exactly the
# string the old rule turned into `[redacted]`. That is why the inner run in
# the lookahead admits `/`: it is asking whether the blob has anything a path
# would not have, and a slash is not it.
_B64_BLOB = re.compile(
    r"(?<![A-Za-z0-9+/=])"
    r"(?=[A-Za-z0-9+/]{40})"
    r"(?![A-Za-z0-9/]+(?![A-Za-z0-9+/=]))"
    r"[A-Za-z0-9+/]{40,}={0,2}")

# A URL that carries its own credentials: postgres://user:pass@host/db. Only
# the password is replaced, because the scheme, the user and the host are the
# part of the line a reader is asking about. The host part must be followed by
# an `@` for this to fire, so `http://example.com:8080/x` is left alone.
_SECRET_URL = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s/:@\"\']+):[^\s/@\"\']+@")

# A line whose left-hand side says the right-hand side is a credential: an
# assignment, a dict or JSON key, a YAML key, an `export`. This is the rule
# that covers every shape nobody has a prefix for, which was most of them:
# a password, a database DSN, an internal service token.
#
# The key is read as identifier segments and the secret word has to be the
# LAST one. Allowing trailing segments made this rule eat most of a codebase:
# `token_count = 3`, `max_token_count`, `auth_backend`, `secret_name`,
# `api_key_header`, `private_key_path` and `credential_kind` were all read as
# credentials. `token_count` is a count of tokens; `db_password` is a
# password. The segment after the word is what says which.
_KEY_SEG = r"[A-Za-z0-9]+"
_SECRET_WORD = (r"(?:secret|passw(?:or)?d|token|api[_-]?key|private[_-]?key"
                r"|credential|auth(?:orization)?)")
# `(?![A-Za-z0-9_.\-])` is the "last segment" test: `author` and `token_count`
# fail it, `client_secret"` and `db_password:` pass.
_SECRET_NAME = rf"(?:{_KEY_SEG}[_.\-])*{_SECRET_WORD}s?(?![A-Za-z0-9_.\-])"
_SECRET_KEY = rf"[\"']?{_SECRET_NAME}[\"']?"

# Values that are never a credential, whatever the key is called. A bare
# integer, a bool, a None and a bare type name are what a counter, a flag and
# a dataclass field hold, and redacting them turned `has_token = True` into
# `has_token = [redacted]` and `token: str = ""` into `token: [redacted] = ""`.
_NOT_A_SECRET = re.compile(
    r"(?:[-+]?[0-9]+(?:\.[0-9]+)?|True|False|None|null|nil|true|false"
    r"|str|int|bool|float|bytes|list|dict|set|tuple|Any|object"
    r"|string|number|boolean|integer)\Z")

# A bare value ends where the line, the enclosing literal or the enclosing
# call ends. An opening bracket is deliberately not a terminator, which is
# what keeps `PASSWORD = os.environ[NAME]` and `token = lexer.next_token()`
# in the map: they are code, and code is what the map is for. A backslash is
# not part of the value either, so `printf 'DB_PASSWORD=hunter2\n'` keeps its
# `\n`.
_BARE_VALUE = r"([^\s'\"(){}\[\],;\\]+(?=$|[\s,;'\"\\)}\]]))"

# No anchor before the key on purpose: without one, a .env line inside a shell
# string (`printf 'DB_PASSWORD=hunter2\n' > .env`) is caught as well as one
# that starts a line.
_SECRET_KEYED_QUOTED = re.compile(
    rf"(?i)({_SECRET_KEY}\s*[:=]\s*)"
    r"([\"'])((?:(?!\2)[^\n])*)(\2)")
# `=` says assignment wherever it sits.
_SECRET_KEYED_BARE_EQ = re.compile(
    rf"(?i)({_SECRET_KEY}[ \t]*=[ \t]*)" + _BARE_VALUE)
# `:` does not. A bare value after a colon is a secret only on a line shaped
# like YAML: the key starts the line and is not quoted, and nothing after the
# value turns the line back into code. `"auth": auth,` in a Python dict has a
# quoted key; `token: str = ""` in a dataclass has an `=` after it; neither is
# a YAML key with a password behind it.
_SECRET_KEYED_BARE_COLON = re.compile(
    rf"(?im)(^[ \t]*(?:-[ \t]+)?{_SECRET_NAME}[ \t]*:[ \t]*)"
    + _BARE_VALUE + r"(?![ \t]*=)")


def _redact_quoted(m):
    """Keep the quotes a quoted value came in: `PASSWORD = "[redacted]"`.

    Replacing the quotes too made the line stop being the syntax it was, and a
    reader looking at `PASSWORD = [redacted]` cannot tell whether the value was
    a literal or a name."""
    body = m.group(3)
    if not body or _NOT_A_SECRET.match(body):
        return m.group(0)
    return f"{m.group(1)}{m.group(2)}[redacted]{m.group(4)}"


def _redact_bare(m):
    """A bare value, unless it is a number, a bool, a None or a type name."""
    if _NOT_A_SECRET.match(m.group(2)):
        return m.group(0)
    return f"{m.group(1)}[redacted]"


def redact(value):
    """Never carry a credential into the map.

    The map is written into files that get committed and pasted into prompts,
    and every indexed line of every indexed file goes into it, so anything that
    looks like a key is replaced by its shape. Paths to secrets are useful and
    kept; the secrets themselves are not.

    The rules run in this order, because each one narrows what the next has to
    guess at: a whole PEM block, the issuer prefixes, a gated base64 blob, the
    credentials inside a URL, then a quoted and then a bare value on a line
    that names itself a secret.

    A list is not just each element redacted on its own. `lines` holds a file
    as one string per line, and a PEM block spans several of them, so a list
    is swept with the state that says whether it is inside one."""
    if isinstance(value, str):
        out = _PEM_BLOCK.sub("[redacted]", value)
        out = _SECRET_SHAPES.sub("[redacted]", out)
        out = _B64_BLOB.sub("[redacted]", out)
        out = _SECRET_URL.sub(r"\1:[redacted]@", out)
        out = _SECRET_KEYED_QUOTED.sub(_redact_quoted, out)
        out = _SECRET_KEYED_BARE_EQ.sub(_redact_bare, out)
        return _SECRET_KEYED_BARE_COLON.sub(_redact_bare, out)
    if isinstance(value, list):
        return _redact_lines(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


def _redact_lines(items: list) -> list:
    """Every element redacted, and a PEM block redacted as a block.

    Between a BEGIN line and its END line every element is replaced outright,
    header and footer included, because a private key has no line in it worth
    keeping. A block that never ends (a truncated file, a header quoted in
    prose) still suppresses the rest of the list, which is the safe way to be
    wrong."""
    out, in_pem = [], False
    for item in items:
        if isinstance(item, str):
            if in_pem:
                out.append("[redacted]")
                if _PEM_END.search(item):
                    in_pem = False
                continue
            if _PEM_BEGIN.search(item) and not _PEM_END.search(item):
                in_pem = True
                out.append("[redacted]")
                continue
            out.append(redact(item))
        else:
            out.append(redact(item))
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
    """Read a file once per run, up to `limit` bytes. The sections each used to
    walk and re-read the tree for themselves, and a hundred sections over a
    hundred-thousand-file repository is a hundred passes over the same disk for
    the same bytes.

    The key is the path and the limit together, not the path alone. Callers ask
    for different amounts of the same file (`build`'s own `_read` takes 200,000,
    most extractors declare 400,000), and a cache keyed on the path handed the
    first caller's prefix to every later one: which bytes an extractor saw was
    decided by whoever reached the file first, and for a file outside
    `code_files` that was `os.walk` order. Keyed on both, every caller gets the
    prefix it asked for, and a large file still costs the limit rather than its
    size, because the read is bounded here and not after the fact.
    """
    key = (path, limit)
    hit = _FILE_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read(limit)
    except OSError:
        body = ""
    if len(_FILE_CACHE) < 20000:
        _FILE_CACHE[key] = body
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


_ESCAPED_NOTE = ("a symlink in this tree resolves outside the repository and was "
                 "not read: a link that leaves the repository is not part of it, "
                 "and what is on the other end has no business in a map that gets "
                 "committed and pasted into prompts")


def _leaves_tree(path: str, real_root: str) -> bool:
    """Whether `path` is a symlink whose target lives outside `real_root`.

    `os.walk` is called without `followlinks` anywhere in this package, so a
    symlinked *directory* is never descended into and a link loop terminates.
    A symlinked *file* is still listed, and was still read: a `passwd.py`
    pointing at `/etc/passwd` put the whole of `/etc/passwd` into the map's
    line index, and a link to a file in a sibling checkout put that file's
    contents there. The path recorded stays inside the repository, which
    makes the leak harder to notice rather than easier.

    Only links are resolved, and the answer is remembered for the length of
    the build, because one build walks the same tree about a dozen times and
    the `lstat` per file per pass was measurable where one per file is not.
    """
    key = (real_root, path)
    hit = _LINK_CACHE.get(key)
    if hit is not None:
        return hit
    out = False
    if os.path.islink(path):
        try:
            real = os.path.realpath(path)
        except OSError:
            out = True
        else:
            out = not (real == real_root or real.startswith(real_root + os.sep))
    _LINK_CACHE[key] = out
    return out


def _tree(root: str):
    """`os.walk(root)` with the directories this project never reads pruned,
    files that link out of the tree dropped, and a bound on how much of a
    tree one pass will look at.

    Yields the same `(base, dirs, files)` triples in the same order, so a
    caller reads exactly as it did before. What it adds is the `SKIP_DIRS`
    pruning that every caller was repeating by hand, and a stop.

    The stop counts entries examined, not files kept. A cap on files kept
    bounds nothing on a tree that is mostly directories: `--repo /` is one
    keystroke away from `--repo .`, and a walk of `/` on the machine this was
    measured on passed 380,000 directories in thirty seconds having matched
    5,500 files, so a cap of forty thousand hits would have let it run for
    hours. Counting entries stops it in a fraction of a second and leaves
    every tree smaller than the cap walked exactly as it was before.

    `WAWE_MAX_FILES` raises it, which is what the note in the map says to do.
    """
    real_root = os.path.realpath(root)
    seen = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        kept = [f for f in files if not _leaves_tree(os.path.join(base, f), real_root)]
        if len(kept) != len(files) and _ESCAPED_NOTE not in TRUNCATED:
            TRUNCATED.append(_ESCAPED_NOTE)
        files = kept
        seen += len(dirs) + len(files)
        yield base, dirs, files
        if seen >= MAX_FILES:
            note = (f"a tree walk stopped after {MAX_FILES} entries under "
                    f"{root}: raise WAWE_MAX_FILES or add to .wawe-ignore; "
                    f"what was reached is mapped and the rest is not")
            if note not in TRUNCATED:
                TRUNCATED.append(note)
            return


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
    for base, dirs, files in _tree(root):
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
    tree, which is where a run's own edits live.

    The mtime is kept to the nanosecond the filesystem reports. It used to be
    truncated to a whole second, which left a one-second window in which an
    edit was invisible: a build at T.1 recorded T, a file saved at T.9 was still
    T, and the next build compared equal and printed "unchanged since it was
    built" over a map that no longer described the tree. Nothing recovered from
    that until some other file changed. A session's own edits land inside the
    same second as the build that follows them all the time.

    The walk goes through `_tree`, so it is bounded and pruned the same way
    every other pass over the repository is, and it honours the repository's
    `.wawe-ignore`/`.gitignore` patterns. It runs before anything else, so
    while it was unbounded `--repo /` - one keystroke away from `--repo .` -
    never returned at all, and the file cap that does exist never got a
    chance to apply.
    """
    head = ""
    try:
        import subprocess
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:  # noqa: BLE001 — a repository without git still gets a map
        pass
    pats = _ignores(repo)
    newest = 0
    for base, dirs, files in _tree(repo):
        if pats:
            dirs[:] = [d for d in dirs
                       if not _ignored(os.path.relpath(os.path.join(base, d), repo), pats)]
        for fn in files:
            if not fn.endswith((".py", ".feature", ".sh", ".ts", ".js", ".json", ".md")):
                continue
            full = os.path.join(base, fn)
            if pats and _ignored(os.path.relpath(full, repo), pats):
                continue
            try:
                newest = max(newest, os.stat(full).st_mtime_ns)
            except OSError:
                continue
    return f"{head}:{newest}"


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
