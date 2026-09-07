"""Finding files and reading them: the walk, its caches, the config and the
manifest.

Nothing here knows what a declaration or a section is. It answers "which files
are in this repository", "what does this one say" and "has it changed since the
last build", and the rest of the package is built on those answers.
"""

import hashlib
import json
import os
import re
import stat
import subprocess

from . import state
from .state import (TRUNCATED, _FILE_CACHE, _IGNORE_CACHE, _LINK_CACHE,
                    _TRACKED_CACHE, _WALK_CACHE)

# `CACHE_SCHEMA`, `HASH_COUNT`, `PARSE_COUNT`, `_HASH_CACHE`, `_PARSE_CACHE`
# and `__version__` are reached through `state` rather than imported by name:
# several of them are rebound, and a name imported by value would go on
# holding whatever it held at import time.


SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".runs"}


_PARSE_CACHE_FILE = ".wawe-cache.json"


def _drop_if_dead(tmp: str, stem_len: int) -> None:
    """Remove one staged temporary if the process that staged it is gone.

    A live builder's temporary is a file it is about to rename into place, so
    it is left exactly alone. A pid that has been reused belongs to some other
    live process, which costs one temporary that outlives its writer and is
    swept the next time that pid is free.
    """
    try:
        pid = int(tmp[stem_len + 1:-len(".tmp")])
    except ValueError:
        return
    if pid == os.getpid():
        return
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        try:
            os.remove(tmp)
        except OSError:
            pass
    except OSError:  # alive, and owned by somebody else
        pass


def _sweep_stale(path: str) -> None:
    """Remove temporaries a killed writer left beside `path`."""
    import glob

    for tmp in glob.glob(f"{glob.escape(path)}.*.tmp"):
        _drop_if_dead(tmp, len(path))


# Everything this package stages beside its final name in an output directory.
# Named here rather than discovered by pattern, so a sweep never removes a file
# that merely happens to end in `.<digits>.tmp`.
ARTEFACTS = ("framework_map.json", "framework_map.md", "framework_map_brief.md",
             "framework_map.html", "spec_map.json", "spec_map.md",
             _PARSE_CACHE_FILE, ".pointer-head",
             "semantic_index.npy", "semantic_index.json")


def sweep_out_dir(out_dir: str) -> None:
    """Remove every dead writer's temporary in `out_dir`, at the start of a build.

    `_stage_atomic` sweeps the one name it is about to write, which is enough
    for an artefact this build writes and no help at all for one it does not.
    A build killed while writing `framework_map.html` leaves that temporary
    behind for good if the next build is run without `--html`, and the same
    for `spec_map.*`, the semantic index, and a `.pointer-head` staged by a
    `--pointer` call that never came back. Sweeping the whole known set once
    per build is the only thing that clears those.
    """
    import glob

    if not os.path.isdir(out_dir):
        return
    for name in ARTEFACTS:
        stem = os.path.join(out_dir, name)
        for tmp in glob.glob(f"{glob.escape(stem)}.*.tmp"):
            _drop_if_dead(tmp, len(stem))


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


# Every kind `_cached` is asked for, and the two families whose kind carries
# the language or the extension it parsed. A record under any other kind was
# written by a release whose shape has since changed: `func_edges_2` held six
# tables where `func_edges_3` holds seven, and nothing reads one again. They
# are dropped when the cache is written, so an upgraded checkout stops
# carrying a table nothing can read. A CI step asserts this list is the list
# of kinds the source asks for.
CACHE_KINDS = frozenset((
    "call_graph", "complexity", "exports_py", "func_edges_3", "hooks",
    "module_doc", "public_api", "py_spans_2", "pytest_ast", "redactions",
    "step_texts", "symbols"))
CACHE_KIND_PREFIXES = ("spans:", "ts:")


def _kind_is_live(key: str) -> bool:
    """Whether a cache key's kind is one this release still computes."""
    kind = key.split("\x1e", 1)[0]
    return kind in CACHE_KINDS or kind.startswith(CACHE_KIND_PREFIXES)


def _cache_path_in(out_dir: str, path: str) -> str:
    """One indexed file's path as the cache file writes it: relative to the
    directory the cache file itself is in.

    The cache holds one key per file per kind plus one hash entry per file,
    and an absolute path is most of every one of them: on this repository the
    same 272 paths were written 13 times over. Relative to `out_dir` rather
    than to the repository because `out_dir` is where the file being written
    is, so nothing has to be told a second root, and `--also` folds in as the
    `../` path that reaches the other checkout. A path on another Windows
    drive has no relative form and keeps its absolute one, which `_cache_path_out`
    passes straight back through.
    """
    try:
        return os.path.relpath(path, out_dir)
    except ValueError:  # a different drive on Windows
        return path


def _cache_path_out(out_dir: str, path: str) -> str:
    """The inverse of `_cache_path_in`: what the process works in, absolute."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(out_dir, path))


def _load_parse_cache(out_dir: str) -> None:
    """Every `(kind, path)` -> `{"sha", "value"}` entry and every
    `path -> {"mtime", "size", "ctime", "sha"}` hash a previous build
    persisted, if the file was written by this schema and this version of the
    tool; otherwise the whole file is discarded rather than trusted entry by
    entry.

    Walking the tree is cheap; parsing every module is not, and a repository
    where three files changed does not need the other nine hundred re-parsed.
    The hashes ride along in the same file because they answer the same
    question one step earlier: which files are worth looking at again.

    Paths on disk are relative to `out_dir` and absolute in memory, so the
    two spellings meet here and in `_save_parse_cache` and nowhere else.
    `empty` is the section holding the entries whose value is the empty list,
    which is a sha and nothing else; it is read back as the entry it stands
    for, so `_cached` sees one shape."""
    try:
        with open(os.path.join(out_dir, _PARSE_CACHE_FILE), encoding="utf-8") as fh:
            doc = json.load(fh)
        hashes = {_cache_path_out(out_dir, k): v
                  for k, v in (doc.get("hashes") or {}).items()}
        if (doc.get("schema") != state.CACHE_SCHEMA
                or doc.get("version") != state.__version__):
            # Only the parse entries go. What a kind stores is what a schema
            # bump changes; the sha256 of a file's bytes means the same thing
            # in every release, and the hashes this process took itself are
            # not on disk to be distrusted in the first place.
            state._PARSE_CACHE = {}
            state.HASHES_AT_LOAD = hashes
            return
        entries = {}
        for k, v in (doc.get("entries") or {}).items():
            kind, _, path = k.partition("\x1e")
            entries[f"{kind}\x1e{_cache_path_out(out_dir, path)}"] = v
        for k, sha in (doc.get("empty") or {}).items():
            kind, _, path = k.partition("\x1e")
            entries[f"{kind}\x1e{_cache_path_out(out_dir, path)}"] = \
                {"sha": sha, "value": []}
        state._PARSE_CACHE = entries
        state.HASHES_AT_LOAD = hashes
        # Under, not over: a hash this process took describes the file as it
        # is, and one read off disk describes it as it was when that file was
        # last saved. The command line hashes on its way to deciding whether
        # to build at all, and a load that replaced the dict threw those away
        # and had `build()` read every one of those files a second time.
        # Nothing can be served stale by keeping them, because `content_hash`
        # validates every entry against the file's current stat block anyway.
        state._HASH_CACHE = {**hashes, **state._HASH_CACHE}
    except (OSError, ValueError):
        state._PARSE_CACHE = {}
        state.HASHES_AT_LOAD = {}


def _save_parse_cache(out_dir: str) -> None:
    # Never creates out_dir: build() calls this whether or not its caller
    # is about to write a map into out_dir (a --docs preview, say, never
    # does), and a directory that does not exist for that reason should stay
    # that way rather than gain a cache file nothing else will ever read.
    if not os.path.isdir(out_dir):
        return
    try:
        # A file that moved or was deleted since the last build otherwise
        # keeps its stale entry forever, and so does a record under a kind
        # this release no longer computes: nothing else ever prunes either.
        live, empty = {}, {}
        for k, v in state._PARSE_CACHE.items():
            kind, _, path = k.partition("\x1e")
            if not os.path.exists(path) or not _kind_is_live(k):
                continue
            short = f"{kind}\x1e{_cache_path_in(out_dir, path)}"
            # An entry whose value is the empty list is a sha and a shape.
            # 246 of this repository's 272 redaction diffs are empty, and
            # writing each of them as `{"sha": ..., "value": []}` under an
            # absolute path cost four times what the sha alone costs.
            if v.get("value") == []:
                empty[short] = v.get("sha")
            else:
                live[short] = v
        hashes = {_cache_path_in(out_dir, k): v
                  for k, v in state._HASH_CACHE.items() if os.path.exists(k)}
        doc = {"schema": state.CACHE_SCHEMA, "version": state.__version__,
               "entries": live, "empty": empty, "hashes": hashes}
        # Atomically: a reader that lands mid-write used to see a prefix,
        # fail to parse it and throw the whole cache away, and re-parse a
        # tree nobody had touched.
        _write_atomic(os.path.join(out_dir, _PARSE_CACHE_FILE), json.dumps(doc))
    except OSError:
        pass


# How much of a file is read at a time while hashing it. A whole file in
# memory is what `_slurp` already refuses to do for the large ones, and a hash
# has no reason to hold more than the block it is folding in.
_HASH_CHUNK = 1024 * 1024


def content_hash(path: str) -> str | None:
    """The sha256 of a file's bytes, hex, or None for a file that cannot be
    read. Computed once per file per build, and once per change after that.

    The stat block is the pre-filter and the hash is the answer. If `path` has
    the mtime, size and ctime it had when its hash was last taken, that hash
    still describes it and nothing is read; otherwise the bytes are read in
    blocks and folded into a fresh digest. On a tree nobody touched that is
    one `stat` per file and no reads at all, which is the whole reason this is
    affordable enough to key the parse cache on.

    Read `state._HASH_CACHE` for why the ctime is in the pre-filter: without
    it, the one case content addressing exists to catch (a same-size rewrite
    with the timestamp put back) is the one case the pre-filter would skip.

    `--force` distrusts this cache the way it distrusts the parse cache, so
    that one command exists that recomputes a content root from the bytes
    rather than from a stat block. It costs one read per file and not two:
    a file this build has already hashed is not hashed again for the root.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    entry = state._HASH_CACHE.get(path)
    trusted = state.PARSE_CACHE_READS or path in state._HASHED_THIS_BUILD
    if (trusted and entry is not None and entry.get("mtime") == st.st_mtime_ns
            and entry.get("size") == st.st_size
            and entry.get("ctime") == st.st_ctime_ns):
        return entry.get("sha")
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                block = fh.read(_HASH_CHUNK)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    sha = digest.hexdigest()
    state.HASH_COUNT += 1
    state._HASHED_THIS_BUILD.add(path)
    state._HASH_CACHE[path] = {"mtime": st.st_mtime_ns, "size": st.st_size,
                               "ctime": st.st_ctime_ns, "sha": sha}
    return sha


def content_pairs(repo: str) -> list:
    """Every indexed file under `repo` as `(path relative to repo, sha256)`,
    sorted by path. A file that cannot be read is left out rather than given
    an invented hash: it is not in the map either.

    The set is `_indexable`'s, which is the set the walk indexes and the set
    `fingerprint` stamps, so all three are answering about the same files.
    """
    pairs = []
    for full in _indexable(repo):
        sha = content_hash(full)
        if sha is None:
            continue
        pairs.append((os.path.relpath(full, repo).replace(os.sep, "/"), sha))
    pairs.sort()
    return pairs


def content_root(repo: str) -> str:
    """One sha256 over the sorted `(relative path, hash)` pairs: what the tree
    says, rather than when it last said it.

    `fingerprint` answers "has anything been written here since", from the
    commit and the newest mtime, and that is the cheap question. This answers
    "is the content the same", and it is the one an mtime cannot be made to
    answer: a rewrite that kept its length and had its timestamp put back
    moves this and not that. Both are kept, because the mtime is what makes
    the check cheap and this is what makes it true.

    Deterministic by construction: the pairs are sorted, and a path is written
    as it reads relative to the repository root with forward slashes on every
    platform. The encoding is unambiguous because of the NUL after the path: a
    filename may legally contain a newline, so the newline between records
    would not separate them on its own, while a NUL cannot appear in a path on
    any filesystem this runs on and never appears in a hex digest.
    """
    return _root_of(content_pairs(repo))


def _root_of(pairs) -> str:
    """The root digest of already-collected `(relative path, hash)` pairs.

    Split out from `content_root` for `build()`, which needs the pairs
    themselves as well (it reports which of them moved) and must arrive at the
    same digest the command line compares against, byte for byte, rather than
    at its own copy of this loop.
    """
    digest = hashlib.sha256()
    for rel, sha in pairs:
        digest.update(rel.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _cached(path: str, kind: str, compute):
    """Run `compute()` once per file per kind, and reuse the answer after that.

    Keyed by the path, the kind of thing being computed and the sha256 of the
    file's bytes. The path and the kind pick the entry out, so the same file
    can hold a cached step-phrase list and a cached call graph without one
    overwriting the other; the hash is what says the entry still describes the
    file. A build that trusted only the path would hand back last month's
    answer for a file that had been rewritten underneath it.

    The key used to be the path, the kind, the mtime and the size, and that
    had a blind spot: a file rewritten with the same byte count and its
    timestamp put back keeps both, and the stale value was served. `--force`
    was the only escape. The hash has no such spot, and `content_hash` keeps
    the mtime and size as its own pre-filter so that the tree nobody touched
    still costs one `stat` per file and no reads.

    `--force` still sets `state.PARSE_CACHE_READS` False for that build, so
    nothing here is believed and every answer is computed again, and the cache
    is rewritten from what that build found.

    WAWE_NO_CACHE=1 goes further and makes this a plain call to `compute()`
    with nothing recorded at all, for whoever wants a build that leaves the
    cache exactly as it was.
    """
    if state.NO_CACHE:
        state.PARSE_COUNT += 1
        return compute()
    sha = content_hash(path)
    if sha is None:
        state.PARSE_COUNT += 1
        return compute()
    key = f"{kind}\x1e{path}"
    if state.PARSE_CACHE_READS:
        entry = state._PARSE_CACHE.get(key)
        if entry is not None and entry.get("sha") == sha:
            return entry["value"]
    value = compute()
    state.PARSE_COUNT += 1
    state._PARSE_CACHE[key] = {"sha": sha, "value": value}
    return value




def _config(repo: str) -> dict:
    """Defaults from `.wawe.toml`, so a project states its own invocation once.

    tomllib is stdlib on every supported Python, so this reads with it alone:
    this tool has no dependencies and is not about to grow one for six keys.
    """
    path = os.path.join(repo, ".wawe.toml")
    if not os.path.exists(path):
        return {}
    # 64 KB: this file states six keys and a synonyms table. Anything past
    # that is not configuration, and an unbounded read of a path a repository
    # chooses the contents of is a hole whatever the file is called.
    body = _slurp(path, 64 * 1024)
    import tomllib
    try:
        data = tomllib.loads(body)
    except (tomllib.TOMLDecodeError, RecursionError):
        # A file with a typo in it, or one built to be parsed rather than
        # read: twenty thousand nested brackets are valid TOML syntax right up
        # to the point where the parser's own recursion runs out, and a
        # RecursionError out of a config read used to end the build. No
        # configuration is the answer to both.
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

# Values that are never a credential, whatever the key is. A bool, a None and
# a bare type name are what a flag and a dataclass field hold, and redacting
# them turned `has_token = True` into `has_token = [redacted]` and
# `token: str = ""` into `token: [redacted] = ""`.
#
# A number is not on this list. `DB_PASSWORD = 8675309`, `password =
# "12345678"` and `api_key: 1234567890123456` are all credentials, and a
# blanket "digits are safe" rule handed every one of them to the map. Numbers
# are decided in `_redact_bare` instead, where the key is in hand.
_NOT_A_SECRET = re.compile(
    r"(?:True|False|None|null|nil|true|false"
    r"|str|int|bool|float|bytes|list|dict|set|tuple|Any|object"
    r"|string|number|boolean|integer)\Z")

# An unquoted number under a key that also names a count is a count.
# `max_token = 4096` is a context window and `num_tokens = 10` is a quantity,
# even though both keys end in the word `token`.
#
# There is no ceiling on how big a count may be. There was one, of six digits,
# and it redacted `MAX_TOKENS = 1000000`, `max_tokens = 1048576` and
# `TIMEOUT_TOKEN = 2000000`, which are a context window, a buffer size and a
# millisecond timeout. The key is what decides this, not the magnitude: a key
# with no counter word in it has every number redacted whatever its length,
# and `DB_PASSWORD = 8675309` has none.
_COUNTER_WORD = re.compile(
    r"(?i)(?:^|[_.\-])(?:count|counts|index|idx|ttl|seconds|secs|size|limit"
    r"|max|maximum|min|minimum|len|length|num|number|total|timeout|retries"
    r"|retry|attempts|depth|width|height|port|version)(?:[_.\-]|$)")
# Underscores, hex and an exponent, because a count is written the way the
# language writes one: 1_048_576, 0x100000, 1e6.
_A_NUMBER = re.compile(
    r"[-+]?(?:0[xXbBoO][0-9A-Fa-f_]+"
    r"|[0-9][0-9_]*(?:\.[0-9_]+)?(?:[eE][-+]?[0-9]+)?)\Z")

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
    """A bare value, unless the key and the value together say it is a count.

    A bool, a None and a type name are never a credential. A number is one
    only sometimes: under a key that also names a count it is a count, of any
    size, and under a key that does not it is a value somebody chose.
    `max_token = 4096` and `MAX_TOKENS = 1000000` stay; `DB_PASSWORD =
    8675309` and `api_key: 1234567890123456` do not. A quoted number never
    reaches here, which is why `password = "12345678"` redacts: quoting a
    number is what a credential does and what a counter does not.
    """
    key, value = m.group(1), m.group(2)
    if _NOT_A_SECRET.match(value):
        return m.group(0)
    if _A_NUMBER.match(value) and _COUNTER_WORD.search(key):
        return m.group(0)
    return f"{key}[redacted]"


# The one place in the map where a list is a file: `lines[path]` is that
# file's lines, in order, and nothing else in the map is. Every other list is
# an aggregate that mixes files (`concurrency["notes"]` is one row per file,
# `duplicates` one row per pair), so carrying PEM state from one element to
# the next there is not "the rest of the key", it is somebody else's line.
_CONTIGUOUS_KEY = "lines"


def redact(value, contiguous: bool = False):
    """Never carry a credential into the map.

    The map is written into files that get committed and pasted into prompts,
    and every indexed line of every indexed file goes into it, so anything that
    looks like a key is replaced by its shape. Paths to secrets are useful and
    kept; the secrets themselves are not.

    The rules run in this order, because each one narrows what the next has to
    guess at: a whole PEM block, the issuer prefixes, a gated base64 blob, the
    credentials inside a URL, then a quoted and then a bare value on a line
    that names itself a secret.

    `contiguous` says the list being redacted is one file's consecutive lines,
    which is true only under `lines`. A PEM block spans several of them, so
    that list is swept with the state that says whether it is inside one.
    Every other list is an aggregate over files and gets no shared state:
    a header in one file's row used to blank the rows of every file after it.

    `lines` is passed through untouched when `state.LINES_REDACTED` says the
    build that produced the map redacted every line as it recorded it. It is
    the only key this pass can know is already done, it is by far the largest,
    and the pass over it is provably inert: on this repository's 36,000 lines
    it changed none of them. It cost 0.38 s of every build all the same. Every
    other key is swept whatever produced the map, and a map from a build that
    said `redact_lines=False`, or from no build at all, has its lines swept
    here as before, so nothing is written to disk unredacted.
    """
    if isinstance(value, str):
        out = _PEM_BLOCK.sub("[redacted]", value)
        # A header with no body after it in this string: a lone line lifted
        # into an aggregate, or a truncated file. Not a key on its own, but
        # the original rule replaced it and there is nothing in it to keep.
        out = _PEM_BEGIN.sub("[redacted]", out)
        out = _PEM_END.sub("[redacted]", out)
        out = _SECRET_SHAPES.sub("[redacted]", out)
        out = _B64_BLOB.sub("[redacted]", out)
        out = _SECRET_URL.sub(r"\1:[redacted]@", out)
        out = _SECRET_KEYED_QUOTED.sub(_redact_quoted, out)
        out = _SECRET_KEYED_BARE_EQ.sub(_redact_bare, out)
        return _SECRET_KEYED_BARE_COLON.sub(_redact_bare, out)
    if isinstance(value, list):
        return _redact_lines(value) if contiguous else [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: (v if k == _CONTIGUOUS_KEY and state.LINES_REDACTED
                    else redact(v, contiguous or k == _CONTIGUOUS_KEY))
                for k, v in value.items()}
    return value


def _redact_lines(items: list) -> list:
    """One file's lines, with a PEM block redacted as a block.

    Between a BEGIN line and its END line every element is replaced outright,
    header and footer included, because a private key has no line in it worth
    keeping. A block that never ends (a truncated file, a header quoted in
    prose) still suppresses the rest of that file, which is the safe way to be
    wrong about one file. Only ever called for a `lines[path]` list, so the
    rest of that file is all it can ever suppress."""
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


# What one extractor reads of one file by default. Named because two other
# modules have to know it: a declaration whose end line sits at this bound was
# not seen to end, it was cut off there.
SLURP_LIMIT = 400000


def _slurp(path: str, limit: int = SLURP_LIMIT) -> str:
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


# What a parser may be given. Not the same as `declare.py`'s 2 MB cap on the
# line-based index, and lower on purpose: an `ast` tree is far bigger than the
# source it came from, and how much bigger depends on how dense the source is,
# not on its size. A megabyte of one-line defs measures 30,277 statements and
# 179 MB of tree; two megabytes measures 356 MB. The line index has no such
# multiplier and keeps its 2 MB.
AST_LIMIT = 1024 * 1024


def _slurp_source(path: str, limit: int = AST_LIMIT) -> tuple[str, bool]:
    """A file's text for a parser, cut on a line boundary, and whether it was
    cut.

    `_slurp`'s plain byte cap is right for a regex scan over a body and wrong
    for a parser. A cut at an arbitrary byte lands mid-token as often as not,
    `ast.parse` raises `SyntaxError`, and every caller here treats that as
    "this file declares nothing": a 405 KB module lost even the names on its
    first line, and the map said nothing about it having happened.

    So the read goes to `AST_LIMIT`, the cut is moved back to the last newline
    so no line is half a line, and the file is named in `state.CUT_FILES`,
    which `build()` turns into a note in the map's own
    `## This map is incomplete` section. A bound that stops quietly produces a
    map that looks complete and is not.
    """
    body = _slurp(path, limit)
    try:
        cut = os.path.getsize(path) > limit
    except OSError:
        cut = False
    if not cut:
        return body, False
    nl = body.rfind("\n")
    if nl > 0:
        body = body[:nl + 1]
    if path not in state.CUT_FILES:
        state.CUT_FILES.append(path)
    return body, True


def _ignores(root: str) -> list:
    """Patterns from `.wawe-ignore`, one per line, fnmatch against the relative
    path. A hundred-thousand-file monorepo does not want its build output read,
    and saying so once beats waiting for it every time."""
    if root in _IGNORE_CACHE:
        return _IGNORE_CACHE[root]
    pats: list = []
    strict: list = []
    for name in (".wawe-ignore", ".gitignore"):
        fp = os.path.join(root, name)
        if not os.path.exists(fp):
            continue
        try:
            for line in open(fp, encoding="utf-8", errors="replace", newline=None):
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line.rstrip("/"))
        except OSError:
            continue
        if name == ".wawe-ignore":
            # Which file a pattern came from decides whether anything may
            # override it, so the answer is kept alongside the flat list under
            # a key no root can collide with. `.wawe-ignore` is this tool's
            # own file and says "do not read this", which is a different
            # statement from `.gitignore`'s "do not track this": a vendored
            # tree can be committed and still be something nobody wants in
            # the map. See `_indexable`.
            strict = list(pats)
            break
    _IGNORE_CACHE[root] = pats
    _IGNORE_CACHE[root + "\x00strict"] = strict
    return pats


_ESCAPED_NOTE = ("something in this tree was not read: a symlink that resolves "
                 "outside the repository (a link that leaves the repository is "
                 "not part of it, and what is on the other end has no business "
                 "in a map that gets committed and pasted into prompts), or a "
                 "file that is not a regular file, such as a pipe or a device")


def _unreadable(path: str, real_root: str) -> bool:
    """Whether the walk should refuse to open `path` at all.

    Two reasons. A symlink whose target lives outside `real_root`, and
    anything that is not a regular file.

    `os.walk` is called without `followlinks` anywhere in this package, so a
    symlinked *directory* is never descended into and a link loop terminates.
    A symlinked *file* is still listed, and was still read: a `passwd.py`
    pointing at `/etc/passwd` put the whole of `/etc/passwd` into the map's
    line index, and a link to a file in a sibling checkout put that file's
    contents there. The path recorded stays inside the repository, which
    makes the leak harder to notice rather than easier.

    The second is the reason a FIFO named `x.py` was fatal: `os.walk` lists
    it like any other file, and `open()` on a FIFO with no writer blocks
    forever, so the build stopped at that file and never came back. There is
    no timeout to reach for and no partial answer to give; a pipe, a socket
    or a device is not source code, and the map is better off not knowing it
    is there. The same `lstat` answers both questions.

    The answer is remembered for the length of the build, because one build
    walks the same tree about a dozen times and an `lstat` per file per pass
    was measurable where one per file is not.
    """
    key = (real_root, path)
    hit = _LINK_CACHE.get(key)
    if hit is not None:
        return hit
    out = False
    try:
        st = os.lstat(path)
    except OSError:
        out = True
    else:
        if stat.S_ISLNK(st.st_mode):
            try:
                real = os.path.realpath(path)
                out = not (real == real_root
                           or real.startswith(real_root + os.sep))
                if not out:
                    out = not stat.S_ISREG(os.stat(path).st_mode)
            except OSError:
                out = True
        else:
            out = not stat.S_ISREG(st.st_mode)
    _LINK_CACHE[key] = out
    return out


def _tree(root: str):
    """`os.walk(root)` with the directories this project never reads pruned,
    files that link out of the tree or are not regular files dropped, and a
    bound on how much of a tree one pass will look at.

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

    What counts against the budget is what this walk looked at, and pruning a
    directory does not always mean not having looked at it. The count is taken
    after `SKIP_DIRS` and after a non-regular or escaping file is dropped, so
    those cost nothing, and before the caller has applied the repository's
    ignore rules, so a directory `_indexable` is about to prune still costs the
    one entry it took to see it. That is deliberate: a tree of a million
    ignored directories is still a million directories to walk past, and the
    budget exists to bound the walking. What pruning saves is descending them.

    `WAWE_MAX_FILES` raises it, which is what the note in the map says to do.
    """
    real_root = os.path.realpath(root)
    seen = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        kept = [f for f in files if not _unreadable(os.path.join(base, f), real_root)]
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


def _tracked(root: str) -> tuple:
    """What git already tracks under `root`: (files, directories holding one),
    as paths relative to `root`.

    git does not ignore a file it already tracks, and neither may this. A
    `.gitignore` line is a rule about what to start tracking, so a repository
    that has committed something its own ignore file names keeps it. This
    repository is one: it says `.wawe/` and commits three example maps under
    `docs/examples/*/.wawe/`, and pruning by ignore rules alone dropped all
    nine of them out of its own map.

    One `git ls-files` per root, cached for as long as the cache lives. That
    is once per build on the ordinary path and twice under `--force`, because
    the fingerprint walks before `build()` and `state.reset()` clears the
    cache between them. Two subprocesses on the run that was asked to trust
    nothing is the right side of that trade: the alternative is a cache that
    outlives the reset and hands a second repository the first one's answer.

    Empty for a root with no git, where "tracked" means nothing and the ignore
    rules stand on their own. Also empty when the only patterns in play came
    from `.wawe-ignore`, which nothing overrides, so git is not asked at all.
    """
    if root in _TRACKED_CACHE:
        return _TRACKED_CACHE[root]
    files: set = set()
    dirs: set = set()
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                             capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        out = b""
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        files.add(rel)
        parent = os.path.dirname(rel)
        while parent:
            if parent in dirs:
                break
            dirs.add(parent)
            parent = os.path.dirname(parent)
    _TRACKED_CACHE[root] = (frozenset(files), frozenset(dirs))
    return _TRACKED_CACHE[root]


def _indexable(root: str):
    """Every file under `root` that this map would index, as full paths.

    One definition of "the files this map covers", so that the walk that
    builds the map and the fingerprint that decides whether to rebuild it are
    asking about the same set. They used to disagree: the fingerprint looked
    at seven extensions and the walk at all of them, so editing a .go, .rs,
    .kt, .cs, .rb, .java, .yaml, .tf or .proto file moved the map's contents
    and not its fingerprint, and the next build printed "unchanged since it
    was built" over a map that no longer described the tree.

    An ignored directory is pruned rather than descended and filtered file by
    file. That is the same set of files by the patterns that name a path, and
    a smaller one by a pattern that names a bare directory at any depth, which
    is what such a pattern means in a .gitignore. It also stops an ignored
    directory spending the entry budget `_tree` counts.

    Nothing git already tracks is dropped by a `.gitignore` pattern, because
    git would not drop it either: see `_tracked`. A `.wawe-ignore` pattern
    prunes regardless, tracked or not, because that file is this tool being
    told what not to read rather than git being told what not to track. An
    ignored path that is untracked goes either way.
    """
    base_repo = os.getenv("AGENT_REPO", root)
    pats = _ignores(base_repo)
    # Only `.gitignore`'s patterns are overridable by what git tracks, and
    # only they need git asked at all.
    strict = _IGNORE_CACHE.get(base_repo + "\x00strict") or []
    overridable = bool(pats) and pats != strict
    keep_files, keep_dirs = (_tracked(base_repo) if overridable
                             else (frozenset(), frozenset()))

    def _blocked(rel: str, tracked: frozenset) -> bool:
        if not _ignored(rel, pats):
            return False
        # `.wawe-ignore` is the project saying "do not read this", and being
        # committed is no answer to that. A vendored tree is routinely both.
        if _ignored(rel, strict):
            return True
        return rel not in tracked

    for base, dirs, files in _tree(root):
        if pats:
            dirs[:] = [d for d in dirs
                       if not _blocked(os.path.relpath(os.path.join(base, d),
                                                       base_repo), keep_dirs)]
        for f in files:
            full = os.path.join(base, f)
            if pats and _blocked(os.path.relpath(full, base_repo), keep_files):
                continue
            yield full


def _walk(root: str, want: str) -> list[str]:
    key = (root, want)
    if key in _WALK_CACHE:
        return _WALK_CACHE[key]
    hits = []
    base_repo = os.getenv("AGENT_REPO", root)
    for full in _indexable(root):
        if not os.path.basename(full).endswith(want):
            continue
        hits.append(full)
        if len(hits) >= MAX_FILES:
            note = (f"the file walk stopped at {MAX_FILES} files under "
                    f"{base_repo}: raise WAWE_MAX_FILES or add to "
                    f".wawe-ignore; what is below that count is mapped and "
                    f"the rest is not")
            if note not in TRUNCATED:
                TRUNCATED.append(note)
            _WALK_CACHE[key] = sorted(hits)
            return _WALK_CACHE[key]
    _WALK_CACHE[key] = sorted(hits)
    return _WALK_CACHE[key]






def fingerprint(repo: str) -> str:
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

    The files considered are exactly `_indexable`'s, which is exactly what the
    walk indexes. This used to be its own list of seven extensions, and a
    repository whose code is none of them had a fingerprint that could not
    move: editing a .go, .rs, .kt, .cs, .rb, .java, .yaml, .tf or .proto file
    changed what the map should say and not what the fingerprint said, so the
    next build reported "unchanged since it was built" and served the old
    answer until some .py or .md file happened to change.

    Going through `_indexable` also means `_tree`'s bound and pruning and the
    repository's `.wawe-ignore`/`.gitignore` patterns apply here. This runs
    before anything else, so while it was unbounded `--repo /`, one keystroke
    away from `--repo .`, never returned at all and the file cap that does
    exist never got a chance to apply.
    """
    head = ""
    try:
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        # No git on the machine, no repository here, or a call that outlived
        # its timeout. A tree still gets a map; it is stamped with its newest
        # file alone.
        pass
    newest = 0
    for full in _indexable(repo):
        try:
            newest = max(newest, os.stat(full).st_mtime_ns)
        except OSError:
            continue
    return f"{head}:{newest}"


# The name this was called for its first eight releases, kept so a caller
# that already imported it does not break. Deprecated: use `fingerprint`.
_fingerprint = fingerprint


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
        # 1 MB, and the block this looks for belongs near the top of a
        # README. A README longer than that has other problems.
        body = _slurp(fp, 1024 * 1024)
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
