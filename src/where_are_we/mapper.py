"""A map of the test framework, built from the checkout, for agents to read
instead of rediscovering it.

Every implementer session used to open with the same half hour: grep for where
the steps live, which page object owns the portal, how the driver is built, what
`environment.py` does, which scripts run a scenario. Forty tool calls at roughly
a minute each, in every branch, every run — and the answers are identical for
all of them and derivable without a model.

So they are derived here, deterministically, in a second or two, at the start of
the run and against this run's own checkout (the suite changes; a map from
yesterday would be a lie). The result goes to the run directory as JSON and as a
short Markdown digest the agents are pointed at.
"""

import argparse
import ast
import json
import os
import re
import sys

# Imported both ways on purpose: this file is a package module and also a script
# somebody runs by path, and the second is how most people meet it.
try:
    from . import specs
except ImportError:  # run as a plain file, with no package around it
    import specs  # type: ignore[no-redef]

try:
    from .ask import ask, fit_lines, map_heads
except ImportError:  # run as a plain file, with no package around it
    from ask import ask, fit_lines, map_heads  # type: ignore[no-redef]

STEP_DECORATORS = {"step", "given", "when", "then"}

# Every name this walk has seen, and the file and line it was defined on.
# Filled as files are parsed, written into the map, and searched first by --ask:
# a question about a name is a question about where it is.
DEFINITIONS: dict[str, str] = {}

# What was actually indexed, so an answer of "not found" can say what it looked
# at. The first version said "this is a real absence rather than a search that
# missed" about a constant sitting on line 31 of the product — because the
# product's language was not indexed at all. A map that overstates its reach is
# worse than a small one: it turns "I did not look" into "it is not there", and
# the reader stops looking too.
INDEXED: dict[str, int] = {}

# How a declaration looks, per language. Names are what people ask about — a
# constant, a function, a class, a step, a scenario — and every one of them is a
# line in a file. Adding a language is a row here, not a new code path.
DECLARATIONS = {
    ".ts": (
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+)?(?:type|interface)\s+([A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+)?enum\s+([A-Za-z_$][\w$]*)",
    ),
    ".py": (
        r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)",
        r"^\s*class\s+([A-Za-z_][\w]*)",
        r"^([A-Z][A-Z0-9_]{2,})\s*=",
    ),
    ".feature": (
        r"^\s*(?:Scenario(?: Outline)?|Feature):\s*(.+?)\s*$",
    ),
}
for _alias in (".tsx", ".js", ".jsx", ".mjs", ".cjs"):
    DECLARATIONS[_alias] = DECLARATIONS[".ts"]
for _alias in (".pyi",):
    DECLARATIONS[_alias] = DECLARATIONS[".py"]

# Everything else. A file whose language nobody wrote a row for is still full of
# names somebody will ask about, and answering "not indexed" for it is the same
# failure one level down. These patterns are the shapes almost every language
# agrees on, applied to any text file: a declaration keyword, a name, and the
# line it is on. Cheap, occasionally over-broad, and never silent.
DECLARATIONS["*"] = (
    r"^\s*(?:public|private|protected|internal|static|final|abstract|open|"
    r"export|pub|declare)?\s*"
    r"(?:function|func|def|fun|class|struct|interface|trait|enum|type|record|"
    r"module|package|const|val|var|let)\s+([A-Za-z_$][\w$]*)",
    r"^([A-Z][A-Z0-9_]{2,})\s*[:=]",
    r"^\s*(?:CREATE|create)\s+(?:TABLE|VIEW|INDEX|FUNCTION|PROCEDURE)\s+"
    r"(?:IF NOT EXISTS\s+)?[`\"']?([A-Za-z_][\w.]*)",
)


# Every line of every file the walk read, so a phrase can be found without
# searching the repository again.
#
# A scenario author looking for the words "second Portal tab" or a label like
# "A 15" is asking about text, not about a name — half of one session's hundred
# and sixty-six searches were of that kind, and an index of declarations cannot
# answer them. The same walk already opens every file; keeping the lines costs
# one pass and turns a repository-wide grep into a lookup.
LINES: dict[str, list] = {}


def index_lines(path: str, body: str) -> None:
    """Keep this file's lines, for a phrase search that does not touch disk."""
    LINES[path] = body.splitlines()


# At most this many lines from any one file. A generated table that matches
# everything must not spend the whole answer on itself.
_PER_FILE_CAP = 6

# Lines that declare rather than mention: a definition is what "where is it"
# means. Python, JS/TS and behave decorators, which is what this map walks.
_DECLARES = re.compile(
    r"^\s*(?:@(?:given|when|then|step)\b|def\s|class\s|async\s+def\s"
    r"|(?:export\s+)?(?:const|let|var|function|class|interface|type)\s)",
    re.I)


def find_text(out_dir: str, phrase: str, limit: int = 40) -> str:
    """Every line holding this phrase, with its file and line number.

    Reads the lines the mapper kept. Case-insensitive, because nobody
    remembers the case of a label they saw once.
    """
    phrase = (phrase or "").strip()
    if len(phrase) < 2:
        return "give me something longer than a character to look for"
    try:
        with open(os.path.join(out_dir, "framework_map.json"), encoding="utf-8") as fh:
            doc = json.load(fh) or {}
    except (OSError, ValueError) as exc:
        return f"no map in {out_dir}: {exc}"
    lines = doc.get("lines") or {}
    if not lines:
        return ("this map has no line index — it was built by a version that did "
                "not keep one, or the walk found nothing")

    needle = phrase.lower()
    # Everything, then the best of it — not the first forty the directory
    # order happened to reach.
    #
    # This used to return the moment it had `limit` hits, walking files in the
    # order the map was built. On this repository's own map "forecast" holds
    # 8,249 lines, "reset" 2,975, "export" 1,116: an agent saw forty of them,
    # chosen by nothing, and was told to ask for something narrower. That is a
    # tenth of a percent of the answer selected at random, and it is why nearly
    # half of these calls were followed by opening a file by hand.
    #
    # Scanning all of it costs a pass over the line index — twelve megabytes,
    # tens of milliseconds — against a round trip through a model at a hundred
    # and fifty thousand tokens of context. There is no version of that trade
    # where stopping early wins.
    words = [w for w in re.split(r"[^A-Za-z0-9_]+", phrase) if len(w) > 1]
    whole = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(needle)
                       + r"(?![A-Za-z0-9_])")
    dead = set(doc.get("dead_files") or ())
    hits, scanned = [], 0
    for path, rows in lines.items():
        low_path = path.lower()
        # A path that carries the other words of the question is the file being
        # asked about; the same phrase in an unrelated module is a coincidence.
        path_bonus = sum(1 for w in words if w.lower() in low_path)
        for number, text in enumerate(rows, 1):
            scanned += 1
            low = text.lower()
            if needle not in low:
                continue
            score = 1.0 + 0.75 * path_bonus
            if whole.search(low):
                score += 2.0        # `reset`, not `resetForm`
            if phrase in text:
                score += 0.5        # the case they typed
            if _DECLARES.search(text):
                score += 2.5        # where it is defined beats where it is used
            if path in dead:
                score -= 2.0        # the map already thinks nobody imports this
            # A match in a long line is diluted: minified bundles and generated
            # tables match everything and mean nothing.
            score -= min(1.0, len(text) / 400.0)
            hits.append((score, path, number, text.strip()[:160]))
    if not hits:
        return (f"no line holds {phrase!r}. searched {len(lines)} files, "
                f"{scanned} lines")
    hits.sort(key=lambda h: -h[0])
    # No single file may take the whole answer. Forty hits from one generated
    # table is the same as no answer, and the second-best file is often the one
    # that was wanted.
    per_file, kept = {}, []
    for score, path, number, text in hits:
        if per_file.get(path, 0) >= _PER_FILE_CAP:
            continue
        per_file[path] = per_file.get(path, 0) + 1
        kept.append(f"- {path}:{number}: {text}")
        if len(kept) >= limit:
            break
    tail = ""
    if len(hits) > len(kept):
        tail = (f"\n… {len(hits)} lines hold it across {len(per_file)} files; "
                f"these are the {len(kept)} that rank highest")
    return "\n".join(kept) + tail


def index_declarations(path: str, label: str = "") -> None:
    """Record every name this file declares, with the line it is declared on.

    Called for the suite and for the product alike. Without it the map could say
    which module a step lived in and nothing at all about the code under test —
    so an agent asking where a constant was defined was told it did not exist,
    and spent forty turns grepping for something the map had never looked for.
    """
    ext = os.path.splitext(path)[1].lower()
    patterns = DECLARATIONS.get(ext) or DECLARATIONS["*"]
    try:
        if os.path.getsize(path) > 2 * 1024 * 1024:
            return  # a generated bundle is names nobody asks about, by the ton
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError:
        return
    if "\x00" in body[:2048]:
        return  # binary
    INDEXED[label or ext] = INDEXED.get(label or ext, 0) + 1
    index_lines(path, body)
    # Line by line, and the number is the loop counter.
    #
    # Computed from a match offset instead, it was wrong for one name in nine:
    # the offset counts characters in a string that has already had undecodable
    # bytes replaced, and a multi-line pattern can start a match on the line
    # before the name. Checked against the files afterwards, eleven of a hundred
    # and twenty pointed at a blank line — which is worse than not indexing at
    # all, because the reader opens the file, sees nothing, and stops trusting
    # the map.
    compiled = [re.compile(pattern) for pattern in patterns]
    for number, text in enumerate(body.splitlines(), 1):
        for pattern in compiled:
            found = pattern.match(text) or pattern.search(text)
            if not found:
                continue
            name = found.group(1).strip()
            if len(name) >= 2 and name in text:
                DEFINITIONS.setdefault(name, f"{path}:{number}")
            break
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".runs"}



_PARSE_CACHE_FILE = ".wawe-cache.json"
_PARSE_CACHE: dict = {}


def _load_parse_cache(out_dir: str) -> None:
    """Parsed step phrases, keyed by path and mtime, kept between runs.

    Walking the tree is cheap; parsing every module is not, and a repository
    where three files changed does not need the other nine hundred re-parsed."""
    global _PARSE_CACHE
    try:
        with open(os.path.join(out_dir, _PARSE_CACHE_FILE), encoding="utf-8") as fh:
            _PARSE_CACHE = json.load(fh)
    except (OSError, ValueError):
        _PARSE_CACHE = {}


def _save_parse_cache(out_dir: str) -> None:
    try:
        with open(os.path.join(out_dir, _PARSE_CACHE_FILE), "w", encoding="utf-8") as fh:
            json.dump(_PARSE_CACHE, fh)
    except OSError:
        pass


def _step_texts(path: str) -> list[str]:
    """The step phrases a steps module declares, from its decorators."""
    try:
        key = f"{path}:{int(os.path.getmtime(path))}"
    except OSError:
        key = ""
    if key and key in _PARSE_CACHE:
        return _PARSE_CACHE[key]
    out: list[str] = []
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except (OSError, SyntaxError):
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not dec.args:
                continue
            name = getattr(dec.func, "id", "") or getattr(dec.func, "attr", "")
            if name.lower() not in STEP_DECORATORS:
                continue
            arg = dec.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(arg.value)
                # Where it is, not only that it exists.
                #
                # An agent that has been told a phrase exists still has to find
                # it, and finds it the only way it can: grep. Watched over one
                # run, a scenario author ran forty searches by hand against
                # three questions to the map — because the map answered "this
                # step is in that module" and grep answers "line 214". Same
                # question, and only one of the two answers ends the search.
                DEFINITIONS.setdefault(arg.value, f"{path}:{node.lineno}")
                DEFINITIONS.setdefault(f"def {node.name}", f"{path}:{node.lineno}")
    if key:
        _PARSE_CACHE[key] = out
    return out




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
        return data.get("where-are-we") or data.get("tool", {}).get("where-are-we") or data
    except Exception:  # noqa: BLE001 — python 3.10, or a file with a typo in it
        out = {}
        for line in body.splitlines():
            m2 = re.match(r'\s*([\w-]+)\s*=\s*(.+)', line)
            if not m2:
                continue
            key, raw = m2.group(1), m2.group(2).strip()
            if raw.startswith("["):
                out[key] = [x.strip().strip('"\'') for x in raw.strip("[]").split(",") if x.strip()]
            else:
                out[key] = raw.strip('"\'')
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


_FILE_CACHE: dict[str, str] = {}
_WALK_CACHE: dict[tuple, list] = {}



_TS_PARSERS: dict = {}


def _tree_sitter(lang: str):
    """A real parser where one is installed, and None where it is not.

    Regexes get TypeScript exports and Go signatures right often enough to be
    useful and wrong often enough to be annoying: a commented-out export counts,
    a multi-line signature does not. tree-sitter fixes both, and is optional
    because a tool with no dependencies is a tool people run without thinking.

        pip install "where-are-we[precise]"
    """
    if lang in _TS_PARSERS:
        return _TS_PARSERS[lang]
    parser = None
    try:
        from tree_sitter_languages import get_parser  # type: ignore
        parser = get_parser(lang)
    except Exception:  # noqa: BLE001 — absent, or built for another platform
        parser = None
    _TS_PARSERS[lang] = parser
    return parser


def _ts_symbols(path: str, lang: str) -> list:
    """Top-level declarations, from a parse tree rather than a pattern."""
    parser = _tree_sitter(lang)
    if parser is None:
        return []
    try:
        tree = parser.parse(_slurp(path).encode())
    except Exception:  # noqa: BLE001
        return []
    wanted = {"function_declaration", "class_declaration", "method_definition",
              "interface_declaration", "type_alias_declaration", "enum_declaration",
              "lexical_declaration", "type_declaration", "func_declaration"}
    out = []

    def walk(node, exported=False):
        if node.type == "export_statement":
            exported = True
        if node.type in wanted:
            for child in node.children:
                if child.type in ("identifier", "type_identifier", "property_identifier"):
                    name = child.text.decode(errors="replace")
                    if exported or lang == "go":
                        out.append(name)
                    break
        for child in node.children:
            walk(child, exported)

    walk(tree.root_node)
    return sorted(set(out))[:40]



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


_IGNORE_CACHE: dict[str, list] = {}
MAX_FILES = int(os.getenv("WAWE_MAX_FILES", "40000"))

# What the walk had to leave out. A limit that stops quietly produces a map that
# looks complete and is not, and the reader has no way to tell — which is worse
# than a small map, because a small map that says so can be asked to grow. Named
# in the map itself, where whoever reads it is already looking.
TRUNCATED: list[str] = []


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


def _layer_line(paths: list, what: str) -> str:
    """One line describing a layer by what was actually found in this repo,
    rather than by the names one particular suite happens to use."""
    if not paths:
        return f"{what}: none found"
    dirs = sorted({os.path.dirname(p) or "." for p in paths})
    where = ", ".join(dirs[:3]) + (f" (+{len(dirs)-3} more)" if len(dirs) > 3 else "")
    return f"{what} — {len(paths)} files under {where}"


def build(repo: str) -> dict:
    steps: dict[str, list[str]] = {}
    for p in _walk(repo, ".py"):
        rel = os.path.relpath(p, repo)
        if "/steps/" not in "/" + rel:
            continue
        texts = _step_texts(p)
        if texts:
            steps[rel] = texts

    features: dict[str, dict] = {}
    for p in _walk(repo, ".feature"):
        rel = os.path.relpath(p, repo)
        try:
            body = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        scenarios = []
        for i, line in enumerate(body.splitlines(), 1):
            m = re.match(r"\s*Scenario(?: Outline)?:\s*(.+)$", line)
            if m:
                scenarios.append({"line": i, "name": m.group(1).strip()})
        features[rel] = {
            # With line numbers, because the scoped runner takes them and a
            # branch that has to grep the feature for a line number has learnt
            # nothing from having this map.
            "scenarios": scenarios,
            "tags": sorted(set(re.findall(r"@([\w.-]+)", body))),
        }

    # A page object is a class that owns selectors: found by shape, so this
    # works on a suite that calls the layer "pages", "po" or nothing at all.
    page_objects = []
    for p2 in _walk(repo, ".py"):
        rel = os.path.relpath(p2, repo)
        if "/steps/" in "/" + rel:
            continue
        try:
            src = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        looks_like_page = (
            os.path.basename(p2).lower().endswith(("page.py", "_page.py"))
            or "/pages/" in "/" + rel.lower() or "/page_objects/" in "/" + rel.lower()
            or "/portal_ui/" in "/" + rel.lower()
            or len(re.findall(r"(?:XPATH|SELECTOR|LOCATOR|CSS|data-testid|By\.)", src)) >= 3)
        if looks_like_page and "class " in src:
            page_objects.append(rel)
    page_objects = sorted(page_objects)
    drivers = [os.path.relpath(p, repo) for p in _walk(repo, ".py")
               if "driver" in os.path.basename(p).lower()]
    envs = [os.path.relpath(p, repo) for p in _walk(repo, "environment.py")]
    scripts = [os.path.relpath(p, repo) for p in _walk(repo, ".sh")
               if "/scripts/" in "/" + os.path.relpath(p, repo)]

    # The environment the suite reads, and where each name is set. Branches
    # grepped .envrc, environment.py and the shell for IFP_PORTAL_BASE_URL,
    # IFP_ENV_BRANCH and the ports before they could run anything at all.
    env_names: dict[str, list[str]] = {}
    for p in _walk(repo, ".envrc") + _walk(repo, "environment.py") + _walk(repo, ".sh"):
        rel = os.path.relpath(p, repo)
        try:
            body = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for name in set(re.findall(r"\b([A-Z][A-Z0-9]{1,}_[A-Z0-9_]{2,}|ENV|HEADLESS)\b", body)):
            env_names.setdefault(name, [])
            if rel not in env_names[name]:
                env_names[name].append(rel)

    # Module-level constants and public functions of the step modules: the other
    # thing branches grepped for, one module at a time.
    symbols: dict[str, dict] = {}
    for rel in steps:
        try:
            tree = ast.parse(open(os.path.join(repo, rel), encoding="utf-8",
                                  errors="replace").read())
        except (OSError, SyntaxError):
            continue
        consts, funcs = [], []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        consts.append(t.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("__"):
                    funcs.append(node.name)
        if consts or funcs:
            symbols[rel] = {"constants": sorted(consts), "functions": sorted(funcs)}

    def _public_api(rel: str) -> list[str]:
        """The surface a step is allowed to call, with signatures. Without it an
        agent either greps the class or invents a method that does not exist."""
        try:
            tree = ast.parse(open(os.path.join(repo, rel), encoding="utf-8",
                                  errors="replace").read())
        except (OSError, SyntaxError):
            return []
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and not sub.name.startswith("_"):
                        args = [a.arg for a in sub.args.args if a.arg != "self"]
                        out.append(f"{node.name}.{sub.name}({', '.join(args)})")
                        DEFINITIONS.setdefault(
                            f"{node.name}.{sub.name}",
                            f"{rel}:{sub.lineno}")
                DEFINITIONS.setdefault(f"class {node.name}", f"{rel}:{node.lineno}")
        return sorted(out)

    api = {rel: _public_api(rel) for rel in page_objects + drivers}
    api = {k: v for k, v in api.items() if v}

    # How a scenario is launched here, from the scripts' own usage headers.
    entry_points = {}
    for rel in scripts:
        try:
            head = open(os.path.join(repo, rel), encoding="utf-8",
                        errors="replace").read(2000)
        except OSError:
            continue
        usage = [ln.lstrip("# ").rstrip() for ln in head.splitlines()[:24]
                 if ln.startswith("#") and ("usage" in ln.lower() or ".sh " in ln)]
        if usage:
            entry_points[rel] = usage[:4]

    # The suite's own prose. Docs and module docstrings are the only place some
    # conventions are written down, and rediscovering a convention by reading
    # code is exactly the half hour this map exists to remove.
    docs = {}
    for rel in [os.path.relpath(p, repo) for p in _walk(repo, ".md")]:
        if "/docs/" not in "/" + rel and not rel.lower().startswith("readme"):
            continue
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8",
                        errors="replace").read()
        except OSError:
            continue
        docs[rel] = {"headings": re.findall(r"^#{1,3}\s+(.+)$", body, re.M)[:30],
                     "bytes": len(body)}

    module_docs = {}
    for rel in list(steps) + page_objects + drivers + envs:
        try:
            tree = ast.parse(open(os.path.join(repo, rel), encoding="utf-8",
                                  errors="replace").read())
            d = ast.get_docstring(tree)
        except (OSError, SyntaxError):
            continue
        if d:
            module_docs[rel] = d.strip().split("\n\n")[0][:400]

    # 1. Which step modules a feature's phrases resolve to, and which page
    #    objects those modules touch. The question every new step starts with.
    phrase_owner = {}
    for rel, texts in steps.items():
        for t in texts:
            phrase_owner.setdefault(re.sub(r"\{[^}]*\}", "", t).strip().lower(), rel)
    feature_links: dict[str, dict] = {}
    for rel in features:
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        mods = set()
        for line in body.splitlines():
            m = re.match(r"\s*(?:Given|When|Then|And|But)\s+(.+)$", line)
            if not m:
                continue
            phrase = re.sub(r'"[^"]*"', "", m.group(1)).strip().lower()
            for known, owner in phrase_owner.items():
                if known and known[:40] and known[:40] in phrase:
                    mods.add(owner)
                    break
        pages = set()
        for mod in mods:
            try:
                src = open(os.path.join(repo, mod), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for po in page_objects:
                name = os.path.basename(po)[:-3]
                if name != "__init__" and name in src:
                    pages.add(po)
        feature_links[rel] = {"step_modules": sorted(mods), "page_objects": sorted(pages)}

    # 2. Test data: what the suite reads that is not code.
    data_files = [os.path.relpath(p, repo) for p in
                  _walk(repo, ".json") + _walk(repo, ".csv") + _walk(repo, ".yaml")
                  if any(k in "/" + os.path.relpath(p, repo)
                         for k in ("/data/", "/fixtures/", "/testdata/", "/snapshots/"))]

    # 3. The selectors the suite drives, and the ones the product exposes.
    testids: dict[str, list[str]] = {"suite": [], "product": []}
    for po in page_objects + list(steps):
        try:
            src = open(os.path.join(repo, po), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        testids["suite"] += re.findall(r"data-testid=[\"\']([\w:.-]+)", src)
    for root in _product_roots():
        if not os.path.isdir(root):
            continue
        for p2 in _walk(root, ".tsx") + _walk(root, ".ts"):
            try:
                src = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            testids["product"] += re.findall(r"data-testid=[\"\'{]{1,2}([\w:.-]+)", src)
        break
    testids = {k: sorted(set(v))[:400] for k, v in testids.items()}

    # 4. Helpers outside steps and page objects: the shared toolbox.
    helpers = {}
    for p2 in _walk(repo, ".py"):
        rel = os.path.relpath(p2, repo)
        if "/steps/" in "/" + rel or "/portal_ui/" in "/" + rel or rel in steps:
            continue
        if not ("/Base/" in "/" + rel or "util" in rel.lower() or "helper" in rel.lower()
                or "client" in rel.lower() or "api" in rel.lower()):
            continue
        api2 = _public_api(rel)
        if api2:
            helpers[rel] = api2[:20]

    # 5. Reporting: where results and artefacts land.
    reporting = {}
    for rel in list(steps) + envs + scripts:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for kw in ("allure", "REPORT_PORTAL", "reportportal", "junit", "screenshot",
                   "video", "trace"):
            if kw.lower() in src.lower():
                reporting.setdefault(kw, [])
                if rel not in reporting[kw]:
                    reporting[kw].append(rel)
    reporting = {k: v[:4] for k, v in reporting.items()}

    # 6. behave hooks, by what they actually do.
    hooks = {}
    for rel in envs:
        try:
            tree = ast.parse(open(os.path.join(repo, rel), encoding="utf-8",
                                  errors="replace").read())
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith(("before_", "after_")):
                doc = (ast.get_docstring(node) or "").strip().split("\n")[0]
                calls = sorted({c.func.attr for c in ast.walk(node)
                                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
                hooks[f"{rel}:{node.name}"] = {"doc": doc[:200], "calls": calls[:12]}

    # 7. Quarantine and known flakiness, from the tags the suite already uses.
    quarantine = {}
    for rel, f in features.items():
        marked = [t for t in f["tags"]
                  if any(k in t.lower() for k in ("skip", "wip", "flaky", "quarantine",
                                                  "known", "broken", "disabled"))]
        if marked:
            quarantine[rel] = marked

    # 8. The product side a test asserts against: routes and storage keys.
    product = {"routes": [], "storage_keys": [], "api_paths": []}
    # Everything under the product roots, not the two extensions somebody
    # happened to need first. A name is a name whatever it is written in.
    for src_root in _product_roots():
        if not os.path.isdir(src_root):
            continue
        for p3 in _walk(src_root, ""):
            index_declarations(p3, "product")
        for p2 in _walk(src_root, ".tsx") + _walk(src_root, ".ts"):
            try:
                src = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            product["routes"] += re.findall(r"path=[\"\']([/][\w/:-]*)", src)
            product["storage_keys"] += re.findall(r"localStorage\.(?:get|set|remove)Item\(\s*[\"\'`]([\w.:-]+)", src)
            product["storage_keys"] += re.findall(r"[\"\'`]([a-z][\w-]{2,}-[\w.-]+)[\"\'`]", src)
            product["api_paths"] += re.findall(r"[\"\'`](/api/v\d[\w/{}-]*)", src)
            # What the product declares, and the line it declares it on.
            #
            # Only routes, storage keys and API paths were indexed here, so a
            # question about anything else in the product — a constant, a
            # function, a type — came back "nothing in the map mentions this",
            # which is worse than silence: it says the absence is real. Watched
            # on one run, an agent asked the map three times about a constant
            # that is on line 31 of a file two directories away, was told it did
            # not exist, and spent the next forty turns grepping. It was right
            # to.
            _rel = os.path.relpath(p2, src_root)
            for pattern in (
                r"^\s*export\s+(?:default\s+)?const\s+([A-Za-z_$][\w$]*)",
                r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
                r"^\s*export\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)",
                r"^\s*export\s+(?:type|interface)\s+([A-Za-z_$][\w$]*)",
                r"^\s*(?:export\s+)?enum\s+([A-Za-z_$][\w$]*)",
            ):
                for m2 in re.finditer(pattern, src, re.M):
                    line = src[:m2.start()].count("\n") + 1
                    DEFINITIONS.setdefault(m2.group(1), f"{p2}:{line}")
    product = {k: sorted(set(v))[:120] for k, v in product.items()}

    # Locators the page objects actually drive, and the timing constants that
    # decide how long anything waits. Both are grepped constantly and neither
    # can be guessed.
    locators: dict[str, list[str]] = {}
    timings: dict[str, list[str]] = {}
    for _p in _walk(repo, ""):
        index_declarations(_p, "suite")
    for rel in page_objects + list(steps) + drivers:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        loc = re.findall(r"^([A-Z_0-9]*(?:XPATH|SELECTOR|LOCATOR|CSS)[A-Z_0-9]*)\s*=\s*(.+)$",
                         src, re.M)
        if loc:
            locators[rel] = [f"{k} = {v.strip()[:90]}" for k, v in loc[:25]]
        tim = re.findall(r"^([A-Z_0-9]*(?:TIMEOUT|SETTLE|WAIT|RETRY|BUDGET|DEADLINE|POLL)[A-Z_0-9]*)\s*=\s*(.+)$",
                         src, re.M)
        if tim:
            timings[rel] = [f"{k} = {v.strip()[:60]}" for k, v in tim[:25]]

    # behave's own configuration: defaults nobody states out loud.
    behave_cfg = {}
    for name in ("behave.ini", "setup.cfg", "tox.ini", "pytest.ini", ".behaverc"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            try:
                behave_cfg[name] = open(fp, encoding="utf-8", errors="replace").read()[:2000]
            except OSError:
                continue

    # The suite's coverage document: ticket -> scenarios, maintained by hand and
    # the only place the traceability lives.
    coverage_docs = {}
    for p2 in _walk(repo, ".md"):
        rel = os.path.relpath(p2, repo)
        if "coverage" not in rel.lower():
            continue
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        coverage_docs[rel] = {
            "tickets": sorted(set(re.findall(r"\b(APF-\d+)\b", body)))[:120],
            "headings": re.findall(r"^#{1,3}\s+(.+)$", body, re.M)[:40],
        }

    # How the environment is brought up and proven ready.
    env_setup = {}
    for rel in scripts:
        base = os.path.basename(rel)
        if not any(k in base for k in ("preflight", "portal_rebuild", "start", "health",
                                       "reset_env", "watchdog")):
            continue
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        env_setup[rel] = {
            "flags": sorted(set(re.findall(r"--[a-z][a-z0-9-]+", src)))[:20],
            "urls": sorted(set(re.findall(r"https?://[\w.:%-]+", src)))[:12],
            "ports": sorted(set(re.findall(r":(\d{4,5})\b", src)))[:12],
        }

    # The backend a test can call directly, and the data it seeds.
    backend = {"endpoints": [], "tables": [], "seed_scripts": []}
    for rel in list(steps) + list(helpers if "helpers" in dir() else []):
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        backend["endpoints"] += re.findall(r"[\"\'`](/api/v\d[\w/{}.-]*)", src)
        backend["tables"] += re.findall(r"\bFROM\s+([a-z_][\w.]*)", src, re.I)
    backend["seed_scripts"] = [r for r in scripts
                               if any(k in os.path.basename(r)
                                      for k in ("seed", "fixture", "snapshot", "data"))][:12]
    backend = {k: (sorted(set(v))[:40] if isinstance(v, list) else v)
               for k, v in backend.items()}

    # The API-level suite, which is not the UI suite and has its own entry point.
    api_tests = [os.path.relpath(p2, repo) for p2 in _walk(repo, ".feature")
                 if "/api" in "/" + os.path.relpath(p2, repo).lower()][:40]

    # Repository conventions, from the tests repo itself.
    conventions = {}
    for name in ("CONTRIBUTING.md", "README.md", "AGENTS.md", "CLAUDE.md"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            try:
                conventions[name] = open(fp, encoding="utf-8", errors="replace").read()[:1500]
            except OSError:
                continue

    # What past runs measured: how long each scenario takes and how often it
    # failed. The suite writes junit on every scoped run, and nobody has ever
    # read it back — so every branch guesses at cost and stability instead of
    # knowing which scenario is a twenty-minute one.
    history: dict[str, dict] = {}
    for root in ("/runs", "/tmp"):
        if not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")][:200]
            for fn in files:
                if not fn.endswith(".xml"):
                    continue
                try:
                    body = open(os.path.join(base, fn), encoding="utf-8",
                                errors="replace").read(400000)
                except OSError:
                    continue
                for name, secs in re.findall(
                        r'<testcase[^>]*name="([^"]+)"[^>]*time="([\d.]+)"', body):
                    h = history.setdefault(name, {"runs": 0, "total_s": 0.0, "failed": 0})
                    h["runs"] += 1
                    h["total_s"] += float(secs)
                for name in re.findall(
                        r'<testcase[^>]*name="([^"]+)"[^>]*>\s*<(?:failure|error)', body):
                    history.setdefault(name, {"runs": 0, "total_s": 0.0, "failed": 0})
                    history[name]["failed"] += 1
    history = {k: {"runs": v["runs"], "avg_s": round(v["total_s"] / max(v["runs"], 1)),
                   "failed": v["failed"]}
               for k, v in sorted(history.items(),
                                  key=lambda kv: -kv[1]["total_s"])[:120]}

    # A README in a directory is that directory explaining itself, which beats
    # anything inferred from the files in it. Every one of them is carried.
    dir_readmes = {}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs
                   if d not in {".git", ".venv", "node_modules", "__pycache__", ".runs"}]
        for fn in files:
            if fn.lower() not in ("readme.md", "readme.rst", "readme.txt"):
                continue
            rel = os.path.relpath(os.path.join(base, fn), repo)
            try:
                body = open(os.path.join(base, fn), encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            first = next((ln.strip() for ln in body.splitlines()
                          if ln.strip() and not ln.startswith("#")), "")
            dir_readmes[os.path.dirname(rel) or "."] = {
                "path": rel,
                "summary": first[:300],
                "headings": re.findall(r"^#{1,3}\s+(.+)$", body, re.M)[:12],
            }

    # ---- the state of the suite itself, not just its shape ----------------
    # Duplicates: two modules declaring the same phrase, or phrases that differ
    # only by their placeholders and wording. This is why a branch writes a step
    # that already exists, three modules away.
    def _norm(t: str) -> str:
        t = re.sub(r"\{[^}]*\}", "{}", t.lower())
        t = re.sub(r"[\"\']", "", t)
        return re.sub(r"\s+", " ", t).strip()

    by_norm: dict[str, list] = {}
    for rel, texts in steps.items():
        for t in texts:
            by_norm.setdefault(_norm(t), []).append((rel, t))
    duplicates = {k: v for k, v in by_norm.items()
                  if len({r for r, _ in v}) > 1 or len(v) > 1}

    # Exact collisions are rare — behave refuses to start on an ambiguous step,
    # so the suite cannot hold two identical phrases. The costly duplicates are
    # the near ones: "select targeting value {x}" beside "choose the targeting
    # value {x}" in another module. Those are found by comparing word sets, and
    # they are the reason a branch writes a step that already exists.
    STOP = {"the", "a", "an", "is", "are", "to", "of", "in", "on", "for", "and", "{}"}

    def _tokens(t: str) -> frozenset:
        # Placeholders count: "…data" and "…data {summary}" ask for different
        # things, and calling them duplicates sends an agent to reuse a step
        # that checks less than the scenario needs. So the arity travels with
        # the word set rather than being normalised away.
        words = frozenset(w for w in re.findall(r"[a-z]+", _norm(t)) if w not in STOP)
        return words | {f"__args{t.count('{')}"}

    items = [(rel, t, _tokens(t)) for rel, texts in steps.items() for t in texts]
    items = [x for x in items if len(x[2]) >= 3]
    buckets: dict[str, list] = {}
    for rel, t, toks in items:
        for w in sorted(toks)[:3]:          # index by rarest-ish words, bounded work
            buckets.setdefault(w, []).append((rel, t, toks))
    near: list[dict] = []
    seen_pairs = set()
    for _, group in buckets.items():
        if len(group) > 400:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a[0] == b[0] and a[1] == b[1]:
                    continue
                key = tuple(sorted((a[1], b[1])))
                if key in seen_pairs:
                    continue
                inter = len(a[2] & b[2])
                union = len(a[2] | b[2])
                if union and inter / union >= 0.8:
                    seen_pairs.add(key)
                    if a[1] == b[1] and a[0] == b[0]:
                        continue
                    near.append({"a": a[1], "a_in": a[0], "b": b[1], "b_in": b[0],
                                 "similarity": round(inter / union, 2)})
    near_duplicates = sorted(near, key=lambda d: -d["similarity"])[:80]

    # Which helper or page-object method each step function actually calls: the
    # graph an agent otherwise rebuilds by reading a module top to bottom.
    call_graph: dict[str, list] = {}
    for rel in steps:
        try:
            tree = ast.parse(open(os.path.join(repo, rel), encoding="utf-8",
                                  errors="replace").read())
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = sorted({c.func.attr for c in ast.walk(node)
                            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
            if calls:
                call_graph[f"{os.path.basename(rel)}:{node.name}"] = calls[:12]
    call_graph = dict(list(call_graph.items())[:120])

    # What a finished run leaves behind, and where.
    artefacts = {}
    for rel in list(steps) + envs + scripts + drivers:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m2 in re.findall(r"[\"\']([\w./-]*(?:report|screenshot|junit|allure|video|trace|log)[\w./-]*)[\"\']",
                             src, re.I):
            if "/" in m2 or m2.endswith((".xml", ".json", ".html", ".png", ".log")):
                artefacts.setdefault(m2, [])
                if rel not in artefacts[m2]:
                    artefacts[m2].append(rel)
    artefacts = {k: v[:3] for k, v in list(artefacts.items())[:40]}

    # Unused: a phrase no feature ever says, and a public page-object method
    # nothing calls. Both are dead weight an agent reads and imitates.
    feature_text = ""
    for rel in features:
        try:
            feature_text += open(os.path.join(repo, rel), encoding="utf-8",
                                 errors="replace").read().lower()
        except OSError:
            continue
    unused_steps = {}
    for rel, texts in steps.items():
        dead = [t for t in texts
                if re.sub(r"\{[^}]*\}", "", t).strip().lower()[:35] not in feature_text]
        if dead:
            unused_steps[rel] = dead[:20]

    suite_src = feature_text
    for rel in list(steps) + page_objects + drivers:
        try:
            suite_src += open(os.path.join(repo, rel), encoding="utf-8",
                              errors="replace").read()
        except OSError:
            continue
    unused_api = {}
    for rel, methods in api.items():
        dead = [m for m in methods
                if suite_src.count("." + m.split(".", 1)[1].split("(")[0]) <= 1]
        if dead:
            unused_api[rel] = dead[:20]

    # Debts the suite already admits to.
    debts = {}
    for rel in list(steps) + page_objects + list(features) + drivers + envs:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        found = _lines_matching(src, ('@skip', '@wip', 'fixme', 'hack', 'todo', 'xxx'), 6)
        if found:
            debts[rel] = [x.strip()[:140] for x in found]

    # Who changed what, and which ticket brought which scenario.
    git_history, ticket_links = {}, {}
    try:
        import subprocess
        log = subprocess.run(
            ["git", "-C", repo, "log", "--since=90.days", "--name-only",
             "--pretty=format:%H|%an|%ad|%s", "--date=short"],
            capture_output=True, text=True, timeout=60).stdout
        cur = None
        for line in log.splitlines():
            if "|" in line and len(line.split("|")) >= 4:
                h, who, when, subj = line.split("|", 3)
                cur = {"who": who, "when": when, "subject": subj}
                for t in re.findall(r"\b([A-Z]{2,6}-\d+)\b", subj):
                    ticket_links.setdefault(t, {"subject": subj, "files": []})
                    cur["ticket"] = t
            elif line.strip() and cur:
                git_history.setdefault(line.strip(), []).append(
                    f"{cur['when']} {cur['who']}: {cur['subject'][:60]}")
                if cur.get("ticket"):
                    ticket_links[cur["ticket"]]["files"].append(line.strip())
    except Exception:  # noqa: BLE001 — a map without history is still a map
        pass
    git_history = {k: v[:5] for k, v in
                   sorted(git_history.items(), key=lambda kv: -len(kv[1]))[:40]}
    ticket_links = {k: {"subject": v["subject"], "files": sorted(set(v["files"]))[:8]}
                    for k, v in list(ticket_links.items())[:40]}

    # What the suite runs on, and how CI runs it.
    deps = {}
    for name in ("requirements.txt", "pyproject.toml", "uv.lock", "Pipfile", "package.json"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            try:
                body = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            deps[name] = sorted(set(re.findall(
                r"^\s*[\"\']?([A-Za-z][\w.-]+)[\"\']?\s*[=><~^]{1,2}\s*[\"\']?([\d][\w.+-]*)",
                body, re.M)))[:40]
    ci = {}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(base, repo)
        if not any(k in rel for k in (".github", ".gitlab", "ci", "pipelines")):
            continue
        for fn in files:
            if not fn.endswith((".yml", ".yaml")):
                continue
            try:
                body = open(os.path.join(base, fn), encoding="utf-8",
                            errors="replace").read()
            except OSError:
                continue
            ci[os.path.join(rel, fn)] = {
                "jobs": re.findall(r"^\s{0,4}([a-z][\w-]*):\s*$", body, re.M)[:12],
                "runs": re.findall(r"(?:behave|pytest|run_[\w]+\.sh)[^\n]{0,60}", body)[:6],
            }

    # Required environment, without values: what must be set for anything to run.
    required_env = sorted({n for n, files in env_names.items()
                           if any(f.endswith(".envrc") for f in files)})[:60]

    # How a test gets in: the login path, the tokens, whatever stands in for a
    # human at the SSO screen. A branch that has to work this out reads three
    # modules before its first click.
    helpers_paths = list((helpers or {}).keys())
    auth = {}
    for rel in list(steps) + envs + page_objects + drivers + helpers_paths:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = _lines_matching(src, ('auth', 'cognito', 'cookie', 'log_in', 'login', 'okta', 'session', 'sign_in', 'sso', 'token'), 4)
        if hits:
            auth[rel] = [h.strip()[:130] for h in hits]
    auth = dict(list(auth.items())[:12])

    # What must not run at the same time as something else. Shared fixtures,
    # singletons, ports, files and the scenarios that say so themselves.
    concurrency = {"shared_state": [], "serial_tags": [], "notes": []}
    for rel in list(steps) + envs + page_objects:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m2 in re.findall(r"^([A-Z_0-9]+)\s*=\s*(?:\{|\[|dict\(|list\()", src, re.M):
            concurrency["shared_state"].append(f"{os.path.basename(rel)}:{m2}")
        for m2 in _lines_matching(src, ('lock', 'mutex', 'not.thread.safe', 'serial', 'shared', 'singleton'), 2):
            concurrency["notes"].append(f"{os.path.basename(rel)}: {m2.strip()[:110]}")
    concurrency["serial_tags"] = sorted({t for f in features.values() for t in f["tags"]
                                         if any(k in t.lower() for k in
                                                ("serial", "isolated", "nonparallel", "single"))})
    concurrency = {k: (v[:20] if isinstance(v, list) else v) for k, v in concurrency.items()}

    # Failure signatures the suite already knows how to read.
    failure_signatures = {}
    for rel in list(steps) + page_objects + drivers + envs:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for msg in re.findall(r"(?:assert[^,\n]*,\s*|raise \w+\(\s*)f?[\"\']([^\"\']{25,140})",
                              src)[:6]:
            failure_signatures.setdefault(msg.strip(), []).append(os.path.basename(rel))
    failure_signatures = {k: sorted(set(v))[:3]
                          for k, v in list(failure_signatures.items())[:60]}

    # The values a test may safely use, taken from the data the suite ships.
    safe_data = {}
    for rel in data_files[:40]:
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read(20000)
        except OSError:
            continue
        ids = re.findall(r"[\"\'](?:id|productId|lineItemId|o1_?product)[\"\']\s*:\s*[\"\']?(\w{3,})",
                         body, re.I)[:20]
        if ids:
            safe_data[rel] = sorted(set(ids))[:20]
    for rel in list(features)[:60]:
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        nums = re.findall(r"\b(\d{4,7})\b", body)
        if nums:
            safe_data.setdefault("used in features", [])
            safe_data["used in features"] = sorted(set(safe_data["used in features"] + nums))[:40]

    # Which steps are slow, not just which scenarios: from the same junit the
    # history came from, matched back to the phrases that own the time.
    slow_steps = {}
    for name, meta in list(history.items())[:120]:
        for rel, texts in steps.items():
            for t in texts:
                key = re.sub(r"\{[^}]*\}", "", t).strip()[:30].lower()
                if key and key in name.lower():
                    cur = slow_steps.setdefault(t, {"avg_s": 0, "seen": 0,
                                                    "module": os.path.basename(rel)})
                    cur["avg_s"] = max(cur["avg_s"], meta["avg_s"])
                    cur["seen"] += 1
    slow_steps = dict(sorted(slow_steps.items(), key=lambda kv: -kv[1]["avg_s"])[:30])

    # What the tags mean, where anyone wrote it down.
    tag_meaning = {}
    for rel, meta in (docs or {}).items():
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for tag, sense in re.findall(r"[`@](\w[\w.-]{2,})[`]?\s*[—:-]\s*([^\n]{10,120})", body)[:40]:
            tag_meaning.setdefault(tag, sense.strip())

    # Locators the suite itself marks as fragile or dead.
    fragile = {}
    for rel, items in locators.items():
        flagged = [x for x in items
                   if re.search(r"(?:deprecated|fragile|flaky|legacy|fallback|old)", x, re.I)]
        if flagged:
            fragile[rel] = flagged[:8]

    # Which product component owns which test id.
    testid_owners = {}
    for root in _product_roots():
        if not os.path.isdir(root):
            continue
        for p2 in _walk(root, ".tsx"):
            try:
                src = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for tid in set(re.findall(r"data-testid=[\"\'{]{1,2}([\w:.-]+)", src)):
                testid_owners.setdefault(tid, os.path.basename(p2))
    testid_owners = dict(list(testid_owners.items())[:200])

    # The rules corpus the agents are held to, by name.
    rules_corpus = []
    for root in (os.getenv("RULES_REPO", "/rules"), os.path.join(repo, ".cursor", "rules")):
        if not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            rules_corpus += [os.path.splitext(f)[0] for f in files if f.endswith(".mdc")]
    rules_corpus = sorted(set(rules_corpus))[:200]

    # Interface strings the assertions depend on.
    ui_strings = []
    for root in _product_roots():
        if not os.path.isdir(root):
            continue
        for p2 in (_walk(root, ".tsx") + _walk(root, ".ts"))[:400]:
            try:
                src = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            ui_strings += re.findall(r">\s*([A-Z][A-Za-z ]{4,40})\s*<", src)
    ui_strings = sorted(set(ui_strings))[:150]

    # The infrastructure the suite talks to: compose files, service names, the
    # ports and health endpoints that decide whether anything can run at all.
    infra = {}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not re.match(r"(docker-)?compose.*\.ya?ml$|Dockerfile.*", fn):
                continue
            rel = os.path.relpath(os.path.join(base, fn), repo)
            try:
                body = open(os.path.join(base, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            infra[rel] = {
                "services": re.findall(r"^\s{2}([a-z][\w-]*):\s*$", body, re.M)[:20],
                "ports": sorted(set(re.findall(r"(\d{2,5}):(?:\d{2,5})", body)))[:15],
                "health": re.findall(r"(?:healthcheck|test:)\s*(.{0,80})", body)[:4],
            }
    for rel in scripts:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        health = re.findall(r"https?://[\w.:%-]*/(?:health|healthz|health_check|ping)[\w/]*", src)
        if health:
            infra.setdefault("health endpoints", {"services": [], "ports": [], "health": []})
            infra["health endpoints"]["health"] = sorted(set(
                infra["health endpoints"]["health"] + health))[:12]

    # Columns, not just table names: what a data test is allowed to assert on.
    schemas = {}
    for rel in list(steps) + [r for r in _walk(repo, ".sql")]:
        rel = os.path.relpath(rel, repo) if os.path.isabs(rel) else rel
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for tbl, cols in re.findall(r"SELECT\s+(.{5,300}?)\s+FROM\s+([a-z_][\w.]*)",
                                    src, re.I | re.S)[:20]:
            name = cols.strip()
            fields = [c.strip().split()[-1] for c in tbl.split(",")][:12]
            schemas.setdefault(name, set()).update(f for f in fields if re.match(r"^\w+$", f))
    schemas = {k: sorted(v)[:20] for k, v in list(schemas.items())[:25]}

    # Who owns what, where the repository says so.
    owners = {}
    for name in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            try:
                for line in open(fp, encoding="utf-8", errors="replace"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        owners[parts[0]] = parts[1:][:4]
            except OSError:
                pass

    # How the environments differ, from the branches the code takes on ENV.
    env_differences = {}
    for rel in list(steps) + envs + scripts:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = _lines_matching(src, ('dev', 'envs==s"\':uat', 'local', 'prod'), 4)
        if hits:
            env_differences[rel] = [h.strip()[:120] for h in hits]
    env_differences = dict(list(env_differences.items())[:15])

    # What past runs of this pipeline already found in this product.
    past_bugs = []
    try:
        import urllib.request as _u
        base_url = os.getenv("RUNS_API_READ", "")
        if base_url:
            with _u.urlopen(f"{base_url}/r/runs?limit=40", timeout=10) as resp:
                for row in json.loads(resp.read().decode() or "[]"):
                    if row.get("verdict"):
                        past_bugs.append({"run": row.get("id"), "ticket": row.get("ticket"),
                                          "verdict": row.get("verdict"),
                                          "summary": (row.get("summary") or "")[:160]})
    except Exception:  # noqa: BLE001 — the map is built with or without history
        pass
    past_bugs = past_bugs[:20]

    # Visual baselines a comparison could use.
    baselines = [os.path.relpath(p2, repo) for p2 in
                 _walk(repo, ".png") + _walk(repo, ".jpg")
                 if any(k in "/" + os.path.relpath(p2, repo).lower()
                        for k in ("baseline", "expected", "golden", "snapshot"))][:40]

    # How a feature file is written here, by example.
    feature_style = {}
    for rel in list(features)[:1]:
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        feature_style = {
            "sample": rel,
            "first_scenario": "\n".join(body.splitlines()[:40])[:1200],
            "uses_outlines": "Scenario Outline" in body,
            "example_headers": re.findall(r"^\s*\|(.+)\|\s*$", body, re.M)[:3],
        }

    # Not every suite is behave. A pytest suite keeps its cases in functions and
    # its shared setup in fixtures; a JS suite keeps them in describe/it blocks.
    # Both are indexed the same way, so this script is worth running on a
    # repository that has never heard of Gherkin.
    pytest_tests: dict[str, list] = {}
    fixtures: dict[str, list] = {}
    markers: list = []
    for p2 in _walk(repo, ".py"):
        rel = os.path.relpath(p2, repo)
        base = os.path.basename(p2)
        if not (base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"):
            continue
        try:
            tree = ast.parse(open(p2, encoding="utf-8", errors="replace").read())
        except (OSError, SyntaxError):
            continue
        cases, fixs = [], []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decs = []
            for d in node.decorator_list:
                f = d.func if isinstance(d, ast.Call) else d
                decs.append(getattr(f, "attr", "") or getattr(f, "id", ""))
            if node.name.startswith("test"):
                cases.append(node.name + (f" [{', '.join(decs)}]" if decs else ""))
                markers += [x for x in decs if x not in ("parametrize", "fixture")]
            elif "fixture" in decs:
                fixs.append(node.name)
        if cases:
            pytest_tests[rel] = cases[:30]
        if fixs:
            fixtures[rel] = fixs[:30]

    js_tests: dict[str, list] = {}
    for ext in (".spec.ts", ".spec.js", ".test.ts", ".test.js"):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            names = re.findall(r"(?:describe|it|test)\s*\(\s*[\"\'`]([^\"\'`]{3,80})", body)
            if names:
                js_tests[rel] = names[:25]

    test_config = {}
    for name in ("pytest.ini", "pyproject.toml", "playwright.config.ts",
                 "jest.config.js", "package.json"):
        fp = os.path.join(repo, name)
        if not os.path.exists(fp):
            continue
        try:
            body = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = [ln.strip() for ln in body.splitlines()
                if re.search(r"(?:testpaths|markers|addopts|testDir|testMatch|scripts|timeout)", ln)][:8]
        if hits:
            test_config[name] = hits

    # The rest of the runners a repository might use. Each one is read for the
    # same three things: where its cases live, what they are called, and what
    # its shared setup is — so this script is worth running before anyone has
    # said which framework the suite uses.
    other_suites: dict[str, dict] = {}

    cypress = {}
    for ext in (".cy.ts", ".cy.js", ".e2e.ts", ".e2e.js"):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            cypress[rel] = re.findall(r"(?:describe|it|context)\s*\(\s*[\"\'`]([^\"\'`]{3,80})",
                                      body)[:20]
    if cypress:
        other_suites["cypress"] = dict(list(cypress.items())[:30])

    robot = {}
    for p2 in _walk(repo, ".robot"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        cases = re.findall(r"^(\S.+)$", body.split("*** Test Cases ***")[-1], re.M)[:20] \
            if "*** Test Cases ***" in body else []
        kws = re.findall(r"^(\S.+)$", body.split("*** Keywords ***")[-1], re.M)[:20] \
            if "*** Keywords ***" in body else []
        robot[rel] = {"tests": [c.strip() for c in cases][:15],
                      "keywords": [k.strip() for k in kws][:15]}
    if robot:
        other_suites["robot"] = dict(list(robot.items())[:20])

    jvm = {}
    for ext in (".java", ".kt"):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            cases = re.findall(r"@(?:Test|ParameterizedTest)[^\n]*\n\s*(?:public\s+)?\w[\w<>\[\] ]*\s+(\w+)\s*\(",
                               body)
            glue = re.findall(r"@(?:Given|When|Then|And)\s*\(\s*[\"\']([^\"\']{5,90})", body)
            if cases or glue:
                jvm[rel] = {"tests": cases[:20], "step_glue": glue[:20]}

    # Cucumber outside Python: the glue is the same idea in every language —
    # a phrase bound to a function — and a .feature file does not say which
    # language implements it, so all of them are read.
    for ext in (".scala",):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            cases = re.findall(r'(?:test|it|should)\s*\(\s*[\"\']([^\"\']{3,90})', body)
            glue = re.findall(r'(?:Given|When|Then|And)\s*\(\s*[\"\']([^\"\']{5,90})', body)
            if cases or glue:
                jvm[rel] = {"tests": cases[:20], "step_glue": glue[:20]}
    if jvm:
        other_suites["jvm"] = dict(list(jvm.items())[:40])

    # cucumber-js and friends: step glue written in TypeScript or JavaScript.
    cucumber_js = {}
    for ext in (".ts", ".js", ".tsx", ".mjs"):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            if any(k in "/" + rel.lower() for k in ("node_modules", "/dist/", "/build/")):
                continue
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            glue = re.findall(
                r"\b(?:Given|When|Then|defineStep)\s*\(\s*(?:/([^/]{5,90})/|[\"\'`]([^\"\'`]{5,90}))",
                body)
            phrases = [a or b for a, b in glue]
            if phrases:
                cucumber_js[rel] = phrases[:25]
    if cucumber_js:
        other_suites["cucumber-js"] = dict(list(cucumber_js.items())[:40])

    go_tests = {}
    for p2 in _walk(repo, "_test.go"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        go_tests[rel] = re.findall(r"^func\s+(Test\w+|Benchmark\w+|Fuzz\w+)\s*\(", body, re.M)[:25]
    if go_tests:
        other_suites["go"] = dict(list(go_tests.items())[:30])

    rspec = {}
    for p2 in _walk(repo, "_spec.rb"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        rspec[rel] = re.findall(r"(?:describe|context|it)\s+[\"\']([^\"\']{3,80})", body)[:20]
    if rspec:
        other_suites["rspec"] = dict(list(rspec.items())[:30])

    # The remaining runners. Same three questions each: where the cases live,
    # what they are called, what binds a phrase to code.
    dotnet = {}
    for ext in (".cs",):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            cases = re.findall(r"\[(?:Fact|Theory|Test|TestMethod)\][\s\S]{0,200}?\b(\w+)\s*\(", body)[:20]
            glue = re.findall(r"\[(?:Given|When|Then)\(@?[\"\']([^\"\']{5,90})", body)[:20]
            if cases or glue:
                dotnet[rel] = {"tests": cases, "step_glue": glue}
    if dotnet:
        other_suites["dotnet"] = dict(list(dotnet.items())[:30])

    php = {}
    for p2 in _walk(repo, ".php"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        cases = re.findall(r"function\s+(test\w+)\s*\(", body)[:20]
        glue = re.findall(r"@(?:Given|When|Then)\s+(.{5,90})", body)[:20]
        if cases or glue:
            php[rel] = {"tests": cases, "step_glue": [g.strip() for g in glue]}
    if php:
        other_suites["php"] = dict(list(php.items())[:30])

    rust = {}
    for p2 in _walk(repo, ".rs"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        cases = re.findall(r"#\[(?:test|tokio::test)\]\s*(?:async\s+)?fn\s+(\w+)", body)[:20]
        if cases:
            rust[rel] = cases
    if rust:
        other_suites["rust"] = dict(list(rust.items())[:30])

    swift = {}
    for p2 in _walk(repo, ".swift"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        cases = re.findall(r"func\s+(test\w+)\s*\(", body)[:20]
        if cases:
            swift[rel] = cases
    if swift:
        other_suites["swift"] = dict(list(swift.items())[:30])

    ruby_cucumber = {}
    for p2 in _walk(repo, ".rb"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        glue = re.findall(r"^(?:Given|When|Then)\s*[(/]\s*[\"\'/]?([^\"\'/\n]{5,90})", body, re.M)[:20]
        if glue:
            ruby_cucumber[rel] = glue
    if ruby_cucumber:
        other_suites["cucumber-ruby"] = dict(list(ruby_cucumber.items())[:30])

    declarative = {}
    for ext, kind in ((".feature", "karate"), (".spec", "gauge"), (".yaml", "k6/gatling")):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            low = rel.lower()
            if kind == "karate" and "karate" not in low:
                continue
            if kind == "gauge" and "/specs/" not in "/" + low:
                continue
            if kind.startswith("k6") and not any(k in low for k in ("k6", "gatling", "perf", "load")):
                continue
            declarative.setdefault(kind, []).append(rel)
    for kind, files in declarative.items():
        other_suites[kind] = {f: [] for f in files[:20]}

    # Contracts, schemas and the machinery around them.
    contracts = {"openapi": [], "graphql": [], "migrations": [], "mocks": [],
                 "feature_flags": [], "i18n": [], "images": [], "secret_paths": []}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            rel = os.path.relpath(os.path.join(base, fn), repo)
            low = rel.lower()
            full = os.path.join(base, fn)
            if fn.endswith((".yaml", ".yml", ".json")) and any(
                    k in low for k in ("openapi", "swagger", "api-spec")):
                contracts["openapi"].append(rel)
            elif fn.endswith((".graphql", ".gql")):
                contracts["graphql"].append(rel)
            elif "/migrations/" in "/" + low or re.match(r"V\d+__|^\d{3,}_", fn):
                contracts["migrations"].append(rel)
            elif any(k in low for k in ("wiremock", "mockserver", "/mocks/", "msw", "handlers")):
                contracts["mocks"].append(rel)
            elif any(k in low for k in ("feature-flag", "featureflag", "flags.")):
                contracts["feature_flags"].append(rel)
            elif any(k in low for k in ("/locales/", "/i18n/", "messages_", "translation")):
                contracts["i18n"].append(rel)
            if fn.startswith("docker-compose") or fn == "Dockerfile":
                try:
                    body = open(full, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                contracts["images"] += re.findall(r"(?:image|FROM)\s*:?\s*([\w./-]+:[\w.-]+)", body)[:20]
    for rel in list(steps) + scripts + envs:
        try:
            src = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        contracts["secret_paths"] += re.findall(
            r"(?:vault|secretsmanager|ssm|aws_secret|SecretId)\W{1,4}([\w/.-]{4,60})", src, re.I)[:10]
    contracts = {k: sorted(set(v))[:30] for k, v in contracts.items()}

    # Contracts are worth reading, not just listing: an agent asserting on an
    # endpoint wants the endpoint, not the name of a file that mentions one.
    contract_details = {"endpoints": [], "graphql": [], "migration_tables": [],
                        "i18n_keys": [], "flags": []}
    for rel in contracts.get("openapi", []):
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if rel.endswith(".json"):
            try:
                doc = json.loads(body)
                for path_, ops in (doc.get("paths") or {}).items():
                    for method in ops:
                        contract_details["endpoints"].append(f"{method.upper()} {path_}")
            except ValueError:
                pass
        else:
            cur = None
            for line in body.splitlines():
                m2 = re.match(r"^\s{2}(/[\w/{}.-]+):\s*$", line)
                if m2:
                    cur = m2.group(1)
                elif cur and re.match(r"^\s{4}(get|post|put|patch|delete):", line):
                    contract_details["endpoints"].append(
                        f"{line.strip().rstrip(':').upper()} {cur}")
    for rel in contracts.get("graphql", []):
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        contract_details["graphql"] += re.findall(
            r"^\s*(?:type|input|enum|interface)\s+(\w+)", body, re.M)[:40]
    for rel in contracts.get("migrations", []):
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for tbl, cols in re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([\w.\"]+)\s*\(([^;]{0,600})",
                                    body, re.I):
            names = re.findall(r"^\s*[\"`]?(\w+)[\"`]?\s+\w", cols, re.M)[:15]
            contract_details["migration_tables"].append(f"{tbl.strip()}({', '.join(names)})")
    for rel in contracts.get("i18n", [])[:10]:
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read(60000)
        except OSError:
            continue
        contract_details["i18n_keys"] += re.findall(r'[\"\'](\w[\w.-]{2,40})[\"\']\s*:', body)[:40]
    for rel in contracts.get("feature_flags", [])[:10]:
        try:
            body = open(os.path.join(repo, rel), encoding="utf-8", errors="replace").read(40000)
        except OSError:
            continue
        contract_details["flags"] += re.findall(r'[\"\'](\w[\w._-]{2,50})[\"\']\s*[:=]', body)[:40]
    contract_details = {k: sorted(set(v))[:60] for k, v in contract_details.items()}

    # Which tags each CI job actually runs.
    ci_tags = {}
    for path, meta in (ci or {}).items():
        try:
            body = open(os.path.join(repo, path), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        tg2 = re.findall(r"--tags[= ]+([^\s\"\']+)", body)
        if tg2:
            ci_tags[path] = sorted(set(tg2))[:12]

    # ---- the codebase itself, test suite or not -------------------------
    # Everything above assumes the repository exists to test something. Most do
    # not. What follows is true of any codebase and is what a newcomer — or an
    # agent on its first turn — asks before anything else.
    LANG = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
            ".js": "JavaScript", ".jsx": "JavaScript", ".go": "Go",
            ".java": "Java", ".kt": "Kotlin", ".scala": "Scala", ".rb": "Ruby",
            ".rs": "Rust", ".cs": "C#", ".php": "PHP", ".swift": "Swift",
            ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".sh": "Shell",
            ".sql": "SQL", ".proto": "Protobuf", ".md": "Markdown"}
    languages: dict[str, int] = {}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            lang = LANG.get(os.path.splitext(fn)[1])
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
    languages = dict(sorted(languages.items(), key=lambda kv: -kv[1]))

    # Where execution starts, by every convention that says so.
    entry = {}
    for rel in ("main.py", "app.py", "manage.py", "__main__.py", "index.ts",
                "index.js", "src/index.ts", "src/main.ts", "main.go", "cmd",
                "Makefile", "package.json", "Cargo.toml", "go.mod", "Dockerfile"):
        fp = os.path.join(repo, rel)
        if not os.path.exists(fp):
            continue
        if rel == "package.json":
            try:
                pkg = json.load(open(fp, encoding="utf-8", errors="replace"))
                entry["package.json scripts"] = list((pkg.get("scripts") or {}).items())[:15]
            except (OSError, ValueError):
                pass
        elif rel == "Makefile":
            try:
                body = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                body = ""
            entry["make targets"] = re.findall(r"^([a-zA-Z][\w.-]*):(?!=)", body, re.M)[:20]
        elif rel == "Dockerfile":
            try:
                body = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                body = ""
            cmds = re.findall(r"^(?:CMD|ENTRYPOINT)\s+(.+)$", body, re.M)[:4]
            if cmds:
                entry["container starts with"] = cmds
        else:
            entry[rel] = ["present"]
    for p2 in _walk(repo, ".go"):
        rel = os.path.relpath(p2, repo)
        if os.path.basename(p2) == "main.go":
            entry.setdefault("go binaries", []).append(rel)
    entry = {k: v[:15] if isinstance(v, list) else v for k, v in entry.items()}

    # The public surface of the code itself: what other code may call.
    exports: dict[str, list] = {}
    for p2 in _walk(repo, ".py"):
        rel = os.path.relpath(p2, repo)
        if "/test" in "/" + rel or "/steps/" in "/" + rel:
            continue
        try:
            tree = ast.parse(open(p2, encoding="utf-8", errors="replace").read())
        except (OSError, SyntaxError):
            continue
        names = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and not n.name.startswith("_")]
        if names:
            exports[rel] = names[:20]
    for ext in (".ts", ".tsx", ".js"):
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            if any(k in "/" + rel for k in ("node_modules", "/dist/", ".spec.", ".test.")):
                continue
            try:
                body = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            names = re.findall(r"export\s+(?:default\s+)?(?:async\s+)?"
                               r"(?:function|class|const|interface|type)\s+(\w+)", body)
            if names:
                exports[rel] = names[:20]
    for p2 in _walk(repo, ".go"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        names = re.findall(r"^func\s+(?:\([^)]*\)\s*)?([A-Z]\w+)", body, re.M)
        names += re.findall(r"^type\s+([A-Z]\w+)", body, re.M)
        if names:
            exports[rel] = sorted(set(names))[:20]
    exports = dict(sorted(exports.items(), key=lambda kv: -len(kv[1]))[:60])

    # HTTP surface: the routes this codebase serves, in whatever framework.
    routes_served = []
    for p2 in _walk(repo, ".py") + _walk(repo, ".ts") + _walk(repo, ".js") \
            + _walk(repo, ".go") + _walk(repo, ".java") + _walk(repo, ".rb"):
        rel = os.path.relpath(p2, repo)
        if any(k in "/" + rel for k in ("node_modules", "/dist/")):
            continue
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m2 in re.findall(r"@(?:app|router|blueprint|bp)\.(get|post|put|patch|delete)\(\s*[\"\']([^\"\']+)",
                             body, re.I):
            routes_served.append(f"{m2[0].upper()} {m2[1]}  ({os.path.basename(rel)})")
        for m2 in re.findall(r"(?:app|router)\.(get|post|put|patch|delete)\(\s*[\"\'`]([^\"\'`]+)",
                             body):
            routes_served.append(f"{m2[0].upper()} {m2[1]}  ({os.path.basename(rel)})")
        for m2 in re.findall(r"(?:HandleFunc|Handle)\(\s*[\"\']([^\"\']+)", body):
            routes_served.append(f"{m2}  ({os.path.basename(rel)})")
        for m2 in re.findall(r"@(?:Get|Post|Put|Patch|Delete|RequestMapping)\w*\(\s*[\"\']([^\"\']+)",
                             body):
            routes_served.append(f"{m2}  ({os.path.basename(rel)})")
        for m2 in re.findall(r"^\s*(get|post|put|patch|delete)\s+[\"\']([^\"\']+)", body, re.M):
            routes_served.append(f"{m2[0].upper()} {m2[1]}  ({os.path.basename(rel)})")
    routes_served = sorted(set(routes_served))[:80]

    # The data model, in whatever ORM.
    models = {}
    for p2 in _walk(repo, ".py"):
        rel = os.path.relpath(p2, repo)
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for cls in re.findall(r"class\s+(\w+)\s*\((?:[\w.]*(?:Base|Model|Document)[\w.]*)\)", body):
            fields = re.findall(r"^\s{4}(\w+)\s*[:=]\s*(?:Column|models\.|Field|mapped_column)", body, re.M)
            models[f"{cls} ({os.path.basename(rel)})"] = sorted(set(fields))[:15]
    for p2 in _walk(repo, ".prisma"):
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for name, fields in re.findall(r"model\s+(\w+)\s*\{([^}]*)\}", body):
            models[f"{name} (prisma)"] = re.findall(r"^\s*(\w+)\s+\w", fields, re.M)[:15]
    models = dict(list(models.items())[:30])

    # How the top-level packages depend on each other.
    import_graph: dict[str, set] = {}
    tops = {d for d in os.listdir(repo)
            if os.path.isdir(os.path.join(repo, d)) and d not in SKIP_DIRS}
    for p2 in _walk(repo, ".py") + _walk(repo, ".ts") + _walk(repo, ".js"):
        rel = os.path.relpath(p2, repo)
        top = rel.split(os.sep)[0]
        if top not in tops:
            continue
        try:
            body = open(p2, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for mod in re.findall(r"(?:^from\s+([\w.]+)|^import\s+([\w.]+)|from\s+[\"\']([^\"\']+))",
                              body, re.M):
            name = (mod[0] or mod[1] or mod[2]).lstrip("./").split(".")[0].split("/")[0]
            if name in tops and name != top:
                import_graph.setdefault(top, set()).add(name)
    import_graph = {k: sorted(v)[:10] for k, v in sorted(import_graph.items())[:25]}

    # Monorepo layout, if this is one.
    workspaces = []
    pkg_json = os.path.join(repo, "package.json")
    if os.path.exists(pkg_json):
        try:
            pkg = json.load(open(pkg_json, encoding="utf-8", errors="replace"))
            ws = pkg.get("workspaces")
            workspaces = (ws.get("packages") if isinstance(ws, dict) else ws) or []
        except (OSError, ValueError):
            pass
    for name in ("pnpm-workspace.yaml", "lerna.json", "turbo.json", "go.work", "Cargo.toml"):
        if os.path.exists(os.path.join(repo, name)):
            workspaces.append(name)

    # ---- the rest of what a codebase is ---------------------------------
    def _read(rel: str, limit: int = 200000) -> str:
        return _slurp(os.path.join(repo, rel), limit)

    code_files = []
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            # Extensionless names count: a Jenkinsfile is the CI, a Rakefile is
            # the build, and neither ends in anything.
            if fn.endswith((".py", ".ts", ".tsx", ".js", ".go", ".java", ".kt",
                            ".rb", ".rs", ".cs", ".yaml", ".yml", ".tf", ".proto",
                            ".xml", ".json", ".md", ".sh", ".sql", ".ex", ".exs",
                            ".dart", ".sol", ".vue", ".svelte", ".rego", ".jmx",
                            ".bicep", ".pp", ".avsc", ".thrift", ".wsdl", ".ipynb")) \
                    or fn in ("Jenkinsfile", "Makefile", "Dockerfile", "Rakefile",
                              "BUILD", "BUILD.bazel", "WORKSPACE", "CMakeLists.txt",
                              "pom.xml", "build.sbt", "Gemfile", "Procfile"):
                code_files.append(os.path.relpath(os.path.join(base, fn), repo))

    messaging, grpc_services, schedules = {}, {}, {}
    k8s, iac, cache_keys = {}, {}, []
    permissions, observability, error_types = {}, {"metrics": [], "log_fields": [], "spans": []}, {}
    cli_commands, frontend = {}, {"components": [], "stores": [], "hooks": []}
    adrs, coverage, hotspots, dep_licenses = [], {}, [], {}

    for rel in code_files:
        body = _read(rel)
        if not body:
            continue
        base_name = os.path.basename(rel)
        low = rel.lower()

        topics = re.findall(r"(?:topic|queue|exchange|subject|channel)\W{1,4}[\"\']([\w.\-/]{3,60})[\"\']",
                            body, re.I)[:10]
        if topics:
            messaging.setdefault(rel, [])
            messaging[rel] = sorted(set(messaging[rel] + topics))[:12]

        if rel.endswith(".proto"):
            for svc, block in re.findall(r"service\s+(\w+)\s*\{([^}]*)\}", body):
                grpc_services[svc] = re.findall(r"rpc\s+(\w+)", block)[:20]

        cron = re.findall(r"[\"\']?((?:[\d*/,\-]+\s+){4}[\d*/,\-]+)[\"\']?", body)[:6]
        dag = re.findall(r"(?:DAG|schedule_interval|@daily|@hourly|CronJob|crontab)\W{0,4}([\w@*/ ,\-:]{3,40})",
                         body)[:6]
        if cron or dag:
            schedules[rel] = sorted(set(cron + dag))[:8]

        if rel.endswith((".yaml", ".yml")) and re.search(r"^kind:\s*\w+", body, re.M):
            kinds = re.findall(r"^kind:\s*(\w+)", body, re.M)
            names = re.findall(r"^\s{2}name:\s*([\w.-]+)", body, re.M)
            k8s[rel] = {"kinds": sorted(set(kinds))[:8], "names": sorted(set(names))[:8]}

        if rel.endswith(".tf"):
            iac[rel] = re.findall(r'^resource\s+"([\w.-]+)"\s+"([\w.-]+)"', body, re.M)[:15]

        cache_keys += re.findall(r"(?:redis|cache)\w*\.(?:get|set|setex|hset|expire)\(\s*[\"\'`f]{0,2}([\w:{}.\-]{3,50})",
                                 body, re.I)[:10]

        perms = re.findall(r"(?:@(?:requires?|has_perm|roles?|scope|authorize)\w*\(\s*[\"\']([^\"\']{2,40})"
                           r"|PERMISSION\w*\s*=\s*[\"\']([^\"\']{2,40}))", body)
        perms = [a or b for a, b in perms][:10]
        if perms:
            permissions[rel] = sorted(set(perms))[:12]

        observability["metrics"] += re.findall(r"(?:Counter|Gauge|Histogram|Summary|metrics?\.\w+)\(\s*[\"\']([\w.:_-]{3,60})",
                                               body)[:8]
        observability["spans"] += re.findall(r"(?:start_span|start_as_current_span|tracer\.\w+)\(\s*[\"\']([\w.:_-]{3,60})",
                                             body)[:8]
        observability["log_fields"] += re.findall(r"log\w*\.(?:info|warn|error|debug)\([^)]*?[\"\'](\w{3,30})[\"\']\s*:",
                                                  body)[:8]

        for exc in re.findall(r"class\s+(\w*(?:Error|Exception)\w*)\s*[\(:]", body)[:10]:
            error_types.setdefault(exc, os.path.basename(rel))

        cmds = re.findall(r"@(?:click|app|cli)\.command\(\s*(?:[\"\']([^\"\']+)[\"\'])?", body)[:10]
        cmds += re.findall(r"add_parser\(\s*[\"\']([^\"\']+)", body)[:10]
        cmds += re.findall(r"Use:\s*[\"\']([\w -]+)", body)[:10]
        cmds = [c for c in cmds if c]
        if cmds:
            cli_commands[rel] = sorted(set(cmds))[:12]

        if rel.endswith((".tsx", ".jsx")):
            comp = re.findall(r"(?:export\s+(?:default\s+)?(?:function|const)\s+)([A-Z]\w+)", body)[:10]
            frontend["components"] += [f"{c} ({base_name})" for c in comp]
        if re.search(r"create(?:Store|Slice)|configureStore|zustand|useReducer", body):
            frontend["stores"].append(rel)
        frontend["hooks"] += re.findall(r"export\s+(?:default\s+)?(?:function|const)\s+(use[A-Z]\w+)", body)[:10]

        if "/adr" in "/" + low or re.match(r"^\d{3,4}-", base_name):
            if rel.endswith(".md"):
                title = next((l.strip("# ").strip() for l in body.splitlines() if l.startswith("#")), base_name)
                adrs.append(f"{rel} — {title[:90]}")

        if base_name in ("coverage.xml", "lcov.info", "coverage-summary.json"):
            pct = re.findall(r'line-rate="([\d.]+)"|"pct"\s*:\s*([\d.]+)|LF:(\d+)', body)[:3]
            coverage[rel] = [next(x for x in t if x) for t in pct] if pct else ["present"]

        if base_name in ("package.json", "requirements.txt", "go.mod", "Cargo.toml", "pom.xml"):
            dep_licenses[rel] = re.findall(r"[\"\']?license[\"\']?\s*[:=]\s*[\"\']?([\w.\-+ ]{2,30})",
                                           body, re.I)[:8]

    for rel in code_files:
        try:
            size = os.path.getsize(os.path.join(repo, rel))
        except OSError:
            continue
        if rel.endswith((".py", ".ts", ".tsx", ".js", ".go", ".java", ".rb", ".cs")):
            hotspots.append((rel, size))
    hotspots = [f"{r} ({s // 1024} KB)" for r, s in
                sorted(hotspots, key=lambda kv: -kv[1])[:20]]

    observability = {k: sorted(set(v))[:30] for k, v in observability.items()}
    cache_keys = sorted(set(cache_keys))[:30]
    frontend = {k: (sorted(set(v))[:30] if isinstance(v, list) else v)
                for k, v in frontend.items()}

    # Function-level call graph across files: who calls what, beyond imports.
    func_calls: dict[str, list] = {}
    defined_at: dict[str, str] = {}
    for rel in code_files:
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(_read(rel))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined_at.setdefault(node.name, rel)
    for rel in code_files:
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(_read(rel))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            targets = set()
            for c in ast.walk(node):
                if isinstance(c, ast.Call):
                    name = getattr(c.func, "id", "") or getattr(c.func, "attr", "")
                    home = defined_at.get(name)
                    if home and home != rel:
                        targets.add(f"{name} ({os.path.basename(home)})")
            if targets:
                func_calls[f"{os.path.basename(rel)}:{node.name}"] = sorted(targets)[:8]
    func_calls = dict(sorted(func_calls.items(), key=lambda kv: -len(kv[1]))[:60])

    # Data flow: which handler touches which table, by co-occurrence in a file.
    data_flow = {}
    for rel in code_files:
        body = _read(rel)
        if not body:
            continue
        eps = re.findall(r"[\"\'`](/[\w/{}.:-]{2,60})[\"\'`]", body)[:20]
        tbls = re.findall(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([a-z_][\w.]{2,40})", body, re.I)[:20]
        if eps and tbls:
            data_flow[rel] = {"paths": sorted(set(eps))[:8], "tables": sorted(set(tbls))[:8]}
    data_flow = dict(list(data_flow.items())[:25])

    # Who owns a file, by who last touched it most.
    blame_owners = {}
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", repo, "log", "--since=365.days", "--name-only",
             "--pretty=format:%an"], capture_output=True, text=True, timeout=90).stdout
        who = None
        counts: dict[str, dict] = {}
        for line in out.splitlines():
            if not line.strip():
                continue
            if "/" not in line and "." not in line.split()[-1][-6:]:
                who = line.strip()
            elif who:
                counts.setdefault(line.strip(), {})
                counts[line.strip()][who] = counts[line.strip()].get(who, 0) + 1
        for f, people in list(counts.items()):
            top = sorted(people.items(), key=lambda kv: -kv[1])[:2]
            if top:
                blame_owners[f] = [f"{n} ({c})" for n, c in top]
    except Exception:  # noqa: BLE001
        pass
    blame_owners = dict(sorted(blame_owners.items(),
                               key=lambda kv: -len(kv[1]))[:40])

    # Coverage per file, where a report survives.
    coverage_by_file = {}
    for rel in code_files:
        if os.path.basename(rel) not in ("coverage.xml", "lcov.info", "coverage-summary.json"):
            continue
        body = _read(rel, 400000)
        for fn2, rate in re.findall(r'filename="([^"]+)"[^>]*line-rate="([\d.]+)"', body)[:200]:
            coverage_by_file[fn2] = f"{float(rate) * 100:.0f}%"
        for fn2, hit, found in re.findall(r"SF:(.+)\nFNF:\d+\nFNH:\d+\n(?:.*\n)*?LH:(\d+)\nLF:(\d+)",
                                          body)[:200]:
            if int(found):
                coverage_by_file[fn2] = f"{int(hit) * 100 // int(found)}%"
    coverage_by_file = dict(list(coverage_by_file.items())[:60])

    # Deprecations and API versions the code announces.
    deprecations = {}
    api_versions = set()
    for rel in code_files:
        body = _read(rel)
        if not body:
            continue
        dep = _lines_matching(body, ('@deprecated', 'deprecated', 'deprecationwarning'), 4)
        if dep:
            deprecations[rel] = [d.strip()[:120] for d in dep]
        api_versions.update(re.findall(r"/(v\d+(?:\.\d+)?)/", body)[:10])
    deprecations = dict(list(deprecations.items())[:20])

    # Documentation that talks about things the code no longer has.
    doc_drift = []
    known = set(defined_at) | {os.path.basename(x) for x in code_files}
    for rel in code_files:
        if not rel.endswith(".md"):
            continue
        body = _read(rel, 100000)
        for ref in set(re.findall(r"`([\w./-]{4,60}\.(?:py|ts|js|go|sh))`", body)):
            if not os.path.exists(os.path.join(repo, ref)) and os.path.basename(ref) not in known:
                doc_drift.append(f"{rel} → {ref}")
    doc_drift = sorted(set(doc_drift))[:25]

    # ---- everything else a repository might be written in ---------------
    # Each ecosystem is asked the same questions the rest were: where the cases
    # live, what is declared, what binds a name to code. Regexes, because the
    # alternative is a parser per language and a dependency per parser.
    ext_langs = {".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang",
                 ".dart": "Dart", ".groovy": "Groovy", ".clj": "Clojure",
                 ".hs": "Haskell", ".lua": "Lua", ".pl": "Perl", ".r": "R",
                 ".jl": "Julia", ".m": "Objective-C", ".fs": "F#",
                 ".vb": "VB.NET", ".sol": "Solidity", ".vue": "Vue",
                 ".svelte": "Svelte", ".ipynb": "Notebook"}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            lang = ext_langs.get(os.path.splitext(fn)[1])
            if lang:
                languages[lang] = languages.get(lang, 0) + 1

    more_suites: dict[str, dict] = {}

    def _collect(ext: str, pattern: str, label: str, group: int = 1) -> None:
        found = {}
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            body = _slurp(p2)
            hits = [h if isinstance(h, str) else h[group - 1]
                    for h in re.findall(pattern, body)][:20]
            if hits:
                found[rel] = sorted(set(hits))[:20]
        if found:
            more_suites[label] = dict(list(found.items())[:25])

    _collect(".exs", r"\btest\s+[\"\']([^\"\']{3,80})", "exunit")
    _collect(".dart", r"\b(?:test|testWidgets)\(\s*[\"\']([^\"\']{3,80})", "flutter")
    _collect(".groovy", r"\bvoid\s+[\"\']?([\w ]{3,60})[\"\']?\s*\(\)\s*\{", "spock")
    _collect(".clj", r"\(deftest\s+([\w-]{3,60})", "clojure.test")
    _collect(".hs", r"\b(?:it|describe)\s+[\"\']([^\"\']{3,80})", "hspec")
    _collect(".lua", r"\b(?:it|describe)\s*\(\s*[\"\']([^\"\']{3,80})", "busted")
    _collect(".pl", r"\b(?:ok|is|subtest)\s*\(?\s*[\"\']([^\"\']{3,80})", "perl-test")
    _collect(".sol", r"\bfunction\s+(test\w+)\s*\(", "foundry")
    _collect(".jl", r"@testset\s+[\"\']([^\"\']{3,80})", "julia")
    _collect(".m", r"^-\s*\(void\)\s*(test\w+)", "xcunit-objc")
    _collect(".java", r"@(?:Test|RunWith\(AndroidJUnit4)[^\n]*\n\s*public\s+void\s+(\w+)",
             "espresso")
    _collect(".js", r"\b(?:element|device)\.\w+\([^)]*\).*?\b(?:it|describe)\(\s*[\"\']([^\"\']{3,60})",
             "detox")

    # Frontend beyond React.
    for ext, label in ((".vue", "vue"), (".svelte", "svelte")):
        comps = {}
        for p2 in _walk(repo, ext):
            rel = os.path.relpath(p2, repo)
            body = _slurp(p2)
            comps[rel] = re.findall(r"(?:export\s+default\s*\{|<script[^>]*>)", body)[:1] and \
                [os.path.splitext(os.path.basename(rel))[0]] or []
        comps = {k: v for k, v in comps.items() if v}
        if comps:
            frontend.setdefault("components", [])
            frontend["components"] += [f"{v[0]} ({label})" for v in comps.values()][:40]
    angular = {}
    for p2 in _walk(repo, ".ts"):
        rel = os.path.relpath(p2, repo)
        body = _slurp(p2)
        decs = re.findall(r"@(Component|Injectable|NgModule|Directive)\(", body)
        if decs:
            angular[rel] = sorted(set(decs))
    if angular:
        frontend["angular"] = [f"{os.path.basename(k)}: {', '.join(v)}"
                               for k, v in list(angular.items())[:20]]
    stories = [os.path.relpath(p2, repo) for ext in (".stories.tsx", ".stories.ts", ".stories.js")
               for p2 in _walk(repo, ext)][:30]
    if stories:
        frontend["storybook"] = stories

    # Data engineering.
    data_stack = {"dbt_models": [], "airflow_dags": {}, "spark_jobs": [], "notebooks": []}
    for p2 in _walk(repo, ".sql"):
        rel = os.path.relpath(p2, repo)
        if "/models/" in "/" + rel or "dbt" in rel.lower():
            data_stack["dbt_models"].append(rel)
    for p2 in _walk(repo, ".py"):
        rel = os.path.relpath(p2, repo)
        body = _slurp(p2)
        if "DAG(" in body or "@dag" in body:
            tasks = re.findall(r"(?:task_id\s*=\s*[\"\']([\w.-]+)|@task\s*\n\s*def\s+(\w+))", body)
            data_stack["airflow_dags"][rel] = sorted({a or b for a, b in tasks})[:15]
        if re.search(r"SparkSession|spark\.read|pyspark", body):
            data_stack["spark_jobs"].append(rel)
    data_stack["notebooks"] = [os.path.relpath(p2, repo) for p2 in _walk(repo, ".ipynb")][:25]
    data_stack = {k: (v[:25] if isinstance(v, list) else dict(list(v.items())[:15]))
                  for k, v in data_stack.items()}

    # Contracts beyond OpenAPI.
    for rel in code_files:
        low = rel.lower()
        if low.endswith((".avsc", ".avro")):
            contracts.setdefault("avro", []).append(rel)
        elif low.endswith(".thrift"):
            contracts.setdefault("thrift", []).append(rel)
        elif low.endswith(".wsdl") or low.endswith(".xsd"):
            contracts.setdefault("soap", []).append(rel)
        elif "asyncapi" in low:
            contracts.setdefault("asyncapi", []).append(rel)
        elif "pact" in low and low.endswith(".json"):
            contracts.setdefault("pact", []).append(rel)
        elif low.endswith(".schema.json") or "json-schema" in low:
            contracts.setdefault("json_schema", []).append(rel)
        elif "trpc" in low:
            contracts.setdefault("trpc", []).append(rel)
    contracts = {k: sorted(set(v))[:25] for k, v in contracts.items()}

    # Infrastructure beyond Terraform.
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        low = rel.lower()
        if low.endswith((".yaml", ".yml")) and re.search(r"AWSTemplateFormatVersion|Resources:", body):
            iac.setdefault(rel, []).extend(
                [("cloudformation", x) for x in re.findall(r"^\s{2,4}(\w+):\s*$", body, re.M)[:10]])
        elif "pulumi" in low or re.search(r"\bpulumi\b", body[:2000], re.I):
            iac.setdefault(rel, []).append(("pulumi", os.path.basename(rel)))
        elif low.endswith(".bicep"):
            iac.setdefault(rel, []).extend(
                [("bicep", x) for x in re.findall(r"^resource\s+(\w+)", body, re.M)[:10]])
        elif re.search(r"^\s*-\s*(?:hosts|name):", body, re.M) and low.endswith((".yml", ".yaml")) \
                and re.search(r"\btasks:|\bansible", body, re.I):
            iac.setdefault(rel, []).extend(
                [("ansible", x) for x in re.findall(r"^\s*-\s*name:\s*(.+)$", body, re.M)[:10]])
        elif low.endswith(".rb") and ("/recipes/" in "/" + low or "cookbook" in low):
            iac.setdefault(rel, []).append(("chef", os.path.basename(rel)))
        elif low.endswith(".pp"):
            iac.setdefault(rel, []).append(("puppet", os.path.basename(rel)))
    iac = {k: v[:12] for k, v in list(iac.items())[:25]}

    # CI beyond GitHub and GitLab.
    for rel in code_files:
        base_name = os.path.basename(rel)
        body = _slurp(os.path.join(repo, rel))
        if base_name == "Jenkinsfile":
            ci[rel] = {"jobs": re.findall(r"stage\s*\(\s*[\"\']([^\"\']+)", body)[:12],
                       "runs": re.findall(r"sh\s+[\"\']([^\"\']{3,60})", body)[:6]}
        elif "circleci" in rel.lower() and base_name.endswith((".yml", ".yaml")):
            ci[rel] = {"jobs": re.findall(r"^\s{2}([\w-]+):\s*$", body, re.M)[:12],
                       "runs": re.findall(r"command:\s*(.{3,60})", body)[:6]}
        elif base_name in ("azure-pipelines.yml", ".travis.yml", "bitbucket-pipelines.yml") \
                or "buildkite" in rel.lower() or "drone" in rel.lower():
            ci[rel] = {"jobs": re.findall(r"^\s*-?\s*(?:job|label|name):\s*(.+)$", body, re.M)[:12],
                       "runs": re.findall(r"^\s*-?\s*(?:script|command):\s*(.+)$", body, re.M)[:6]}
    ci = dict(list(ci.items())[:15])

    # Build systems and their module graphs.
    build_systems = {}
    for rel in code_files:
        base_name = os.path.basename(rel)
        body = _slurp(os.path.join(repo, rel))
        if base_name in ("build.gradle", "build.gradle.kts", "settings.gradle",
                         "settings.gradle.kts"):
            build_systems.setdefault("gradle", []).append(
                f"{rel}: " + ", ".join(re.findall(r"include\s*[\('\"]+([\w:.-]+)", body)[:10]))
        elif base_name == "pom.xml":
            build_systems.setdefault("maven", []).append(
                f"{rel}: " + ", ".join(re.findall(r"<module>([^<]+)</module>", body)[:10]))
        elif base_name in ("BUILD", "BUILD.bazel", "WORKSPACE"):
            build_systems.setdefault("bazel", []).append(rel)
        elif base_name == "build.sbt":
            build_systems.setdefault("sbt", []).append(rel)
        elif base_name == "CMakeLists.txt":
            build_systems.setdefault("cmake", []).append(
                f"{rel}: " + ", ".join(re.findall(r"add_(?:executable|library)\(\s*(\w+)", body)[:8]))
        elif base_name == "Rakefile":
            build_systems.setdefault("rake", []).append(
                f"{rel}: " + ", ".join(re.findall(r"task\s+:?(\w+)", body)[:10]))
    build_systems = {k: v[:15] for k, v in build_systems.items()}

    # Datastores and brokers beyond SQL and Kafka.
    stores = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        for kw, pat in (("mongodb", r"(?:db|database)\.(\w{3,40})\.(?:find|insert|update|aggregate)"),
                        ("elasticsearch", r"(?:index|indices)\W{1,4}[\"\']([\w.-]{3,40})[\"\']"),
                        ("dynamodb", r"TableName\W{1,4}[\"\']([\w.-]{3,40})[\"\']"),
                        ("cassandra", r"(?:KEYSPACE|keyspace)\W{1,4}[\"\']?([\w.-]{3,40})"),
                        ("clickhouse", r"clickhouse[^\n]{0,40}?[\"\']([\w.-]{3,40})[\"\']"),
                        ("nats", r"(?:nats|subject)\.(?:publish|subscribe)\(\s*[\"\']([\w.>*-]{3,40})"),
                        ("pulsar", r"(?:persistent|non-persistent)://([\w./-]{3,60})"),
                        ("mqtt", r"(?:publish|subscribe)\(\s*[\"\']([\w/+#-]{3,40})")):
            hits = re.findall(pat, body)[:8]
            if hits:
                stores.setdefault(kw, set()).update(hits)
    stores = {k: sorted(v)[:20] for k, v in stores.items()}

    # Observability configuration and policy.
    obs_config = {}
    for rel in code_files:
        low = rel.lower()
        body = _slurp(os.path.join(repo, rel))
        if low.endswith((".yml", ".yaml")) and re.search(r"^groups:|alert:", body, re.M):
            obs_config.setdefault("prometheus_rules", []).append(
                f"{rel}: " + ", ".join(re.findall(r"alert:\s*(\w+)", body)[:8]))
        elif low.endswith(".json") and '"panels"' in body[:4000]:
            obs_config.setdefault("grafana_dashboards", []).append(rel)
        elif "otel" in low or "opentelemetry" in low:
            obs_config.setdefault("otel", []).append(rel)
        elif low.endswith(".rego"):
            obs_config.setdefault("opa_policies", []).append(
                f"{rel}: " + ", ".join(re.findall(r"^(\w+)\s*(?:\[|:=|=)", body, re.M)[:8]))
        elif "launchdarkly" in low or "unleash" in low:
            obs_config.setdefault("flag_platform", []).append(rel)
    obs_config = {k: v[:15] for k, v in obs_config.items()}

    # Load and contract testing, and the factories that make test data.
    perf_suites, factories = {}, {}
    for rel in code_files:
        low = rel.lower()
        body = _slurp(os.path.join(repo, rel))
        if low.endswith(".jmx"):
            perf_suites.setdefault("jmeter", []).append(rel)
        elif re.search(r"from\s+locust|class\s+\w+\(HttpUser\)", body):
            perf_suites.setdefault("locust", []).append(rel)
        elif "artillery" in low and low.endswith((".yml", ".yaml")):
            perf_suites.setdefault("artillery", []).append(rel)
        if re.search(r"factory_boy|class\s+\w+Factory\(|FactoryBot\.define", body):
            factories[rel] = re.findall(r"class\s+(\w+Factory)|factory\s+:(\w+)", body)[:10]
    perf_suites = {k: v[:12] for k, v in perf_suites.items()}
    factories = {k: [a or b for a, b in v] for k, v in list(factories.items())[:20]}

    # Indexes and constraints: a table is not its columns alone, and a test that
    # asserts uniqueness wants to know where uniqueness is declared.
    db_constraints: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        found = re.findall(
            r"(?:CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?([\w.]+)"
            r"|CONSTRAINT\s+([\w.]+)|(?:PRIMARY|FOREIGN)\s+KEY\s*\(([^)]{1,60})\)"
            r"|UNIQUE\s*\(([^)]{1,60})\))", body, re.I)[:20]
        names = [next(x for x in t if x) for t in found]
        if names:
            db_constraints[rel] = sorted(set(names))[:15]
    db_constraints = dict(list(db_constraints.items())[:20])

    # Generated code, and what it was generated from: editing the artefact is a
    # mistake the map can prevent.
    generated = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel), 4000)
        m3 = re.search(r"(?:Code generated by|@generated|AUTO-?GENERATED|DO NOT EDIT)"
                       r"[^\n]{0,90}", body, re.I)
        if m3:
            generated[rel] = m3.group(0).strip()[:110]
    generated = dict(list(generated.items())[:40])

    # The type surface: interfaces, protocols, enums and dataclasses.
    types_declared: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        names = re.findall(r"export\s+(?:type|interface|enum)\s+(\w+)", body)
        names += re.findall(r"class\s+(\w+)\s*\((?:\w*Protocol|\w*Enum|BaseModel)\)", body)
        names += re.findall(r"@dataclass[\s\S]{0,40}?class\s+(\w+)", body)
        names += re.findall(r"^type\s+(\w+)\s+(?:struct|interface)", body, re.M)
        if names:
            types_declared[rel] = sorted(set(names))[:20]
    types_declared = dict(sorted(types_declared.items(), key=lambda kv: -len(kv[1]))[:40])

    # Environment by service, not one flat list: a compose file says which
    # variables each service is handed.
    env_by_service = {}
    for rel, meta in (infra or {}).items():
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        current, bucket = None, {}
        for line in body.splitlines():
            m4 = re.match(r"^\s{2}([a-z][\w-]*):\s*$", line)
            if m4:
                current = m4.group(1)
                continue
            if current:
                v = re.match(r"^\s{4,8}([A-Z][A-Z0-9_]{2,}):", line)
                if v:
                    bucket.setdefault(current, []).append(v.group(1))
        for svc, names in bucket.items():
            env_by_service[f"{os.path.basename(rel)}:{svc}"] = sorted(set(names))[:20]
    env_by_service = dict(list(env_by_service.items())[:25])

    # Client policies: retries, timeouts, circuit breakers, rate limits — the
    # behaviour a flaky test is usually arguing with.
    client_policies: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = _lines_matching(body, ('backoff', 'breaker', 'circuitw', 'connect_timeout', 'max_retries', 'rate_limit', 'ratelimiter', 'read_timeout"\n            r"', 'retries', 'throttlw', 'timeout'), 5)
        if hits:
            client_policies[rel] = [h.strip()[:110] for h in hits]
    client_policies = dict(list(client_policies.items())[:25])

    # Transaction boundaries and idempotency, where the code marks them.
    transactions: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = _lines_matching(body, ('@transactional', 'atomic', 'begin', 'commit', 'idempotencw', 'idempotency-key', 'rollback', 'transaction"\n                          r"'), 4)
        if hits:
            transactions[rel] = [h.strip()[:110] for h in hits]
    transactions = dict(list(transactions.items())[:20])

    # Logging configuration: levels and handlers, from config rather than code.
    logging_config = {}
    for rel in code_files:
        low = rel.lower()
        if not any(k in low for k in ("logging", "log4j", "logback", "serilog", "nlog")):
            continue
        body = _slurp(os.path.join(repo, rel))
        levels = re.findall(r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|TRACE)\b", body)[:12]
        if levels:
            logging_config[rel] = sorted(set(levels))

    # The repository's own conventions, from the templates it makes people fill in.
    templates = {}
    for name in (".github/PULL_REQUEST_TEMPLATE.md", ".github/pull_request_template.md",
                 ".gitlab/merge_request_templates", ".github/ISSUE_TEMPLATE"):
        fp = os.path.join(repo, name)
        if os.path.isfile(fp):
            body = _slurp(fp, 4000)
            templates[name] = re.findall(r"^#{1,3}\s+(.+)$|^-\s*\[ \]\s*(.+)$", body, re.M)[:12]
            templates[name] = [a or b for a, b in templates[name]]
        elif os.path.isdir(fp):
            templates[name] = sorted(os.listdir(fp))[:10]

    # License headers, where files carry them.
    license_headers: dict[str, int] = {}
    for rel in code_files[:4000]:
        head = _slurp(os.path.join(repo, rel), 600)
        m5 = re.search(r"(?:SPDX-License-Identifier:\s*([\w.+-]+)"
                       r"|Licensed under the ([\w ]{3,40}) License"
                       r"|Copyright \(c\) [\d-]+ ([\w .,-]{3,40}))", head)
        if m5:
            key = next(x for x in m5.groups() if x).strip()
            license_headers[key] = license_headers.get(key, 0) + 1
    license_headers = dict(sorted(license_headers.items(), key=lambda kv: -kv[1])[:10])

    # Lock files: what is actually installed, as opposed to what a manifest
    # would accept.
    locked = {}
    for name in ("poetry.lock", "uv.lock", "yarn.lock", "pnpm-lock.yaml",
                 "package-lock.json", "go.sum", "Cargo.lock", "composer.lock",
                 "Gemfile.lock"):
        fp = os.path.join(repo, name)
        if not os.path.exists(fp):
            continue
        body = _slurp(fp, 300000)
        pins = re.findall(r'name\s*=\s*"([\w.-]+)"\s*\nversion\s*=\s*"([\w.+-]+)"', body)
        pins += re.findall(r'^\s{4}"?([\w@/.-]+)"?:\s*\n\s+version\s+"([\w.+-]+)"', body, re.M)
        pins += re.findall(r'^([\w./-]+)\s+v([\w.+-]+)', body, re.M)
        locked[name] = [f"{a}=={b}" for a, b in pins[:60]] or [f"{body.count(chr(10))} lines"]
    locked = {k: v[:40] for k, v in locked.items()}

    # Which status codes a route can answer with.
    status_codes: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        codes = re.findall(r"(?:status_code\s*=\s*|status\(|WriteHeader\(|HttpStatus\.|"
                           r"res\.status\(|abort\()\s*(\d{3})", body)[:20]
        codes += re.findall(r"\b(?:return|raise)[^\n]{0,40}?\b(\d{3})\b[^\n]{0,20}(?:Error|Response)",
                            body)[:10]
        codes = [c for c in codes if c.startswith(("2", "3", "4", "5"))]
        if codes:
            status_codes[rel] = sorted(set(codes))[:12]
    status_codes = dict(sorted(status_codes.items(), key=lambda kv: -len(kv[1]))[:25])

    # Calls out to other services: the URLs of things this codebase does not own.
    outbound = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        urls = re.findall(r"[\"\'`](https?://(?!localhost|127\.0\.0\.1)[\w.:%-]+)(?:/[\w./{}-]*)?[\"\'`]",
                          body)[:12]
        hosts = re.findall(r"(?:host|HOST|BASE_URL|_URL)\W{1,4}[\"\']([\w.-]+\.[a-z]{2,})", body)[:8]
        both = sorted(set(urls + hosts))
        if both:
            outbound[rel] = both[:10]
    outbound = dict(sorted(outbound.items(), key=lambda kv: -len(kv[1]))[:25])

    # Kubernetes beyond kinds: what keeps a pod alive and what it is allowed.
    k8s_runtime = {}
    for rel in (k8s or {}):
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        k8s_runtime[rel] = {
            "probes": re.findall(r"(livenessProbe|readinessProbe|startupProbe)", body)[:6],
            "resources": re.findall(r"(?:cpu|memory):\s*[\"\']?([\w.]+)", body)[:8],
            "replicas": re.findall(r"replicas:\s*(\d+)", body)[:4],
            "images": re.findall(r"image:\s*([\w./:-]+)", body)[:6],
        }
    k8s_runtime = {k: v for k, v in list(k8s_runtime.items())[:15] if any(v.values())}

    # Assets: what ships that is not code.
    assets: dict[str, int] = {}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
                       ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".mp3",
                       ".pdf", ".onnx", ".pt", ".pkl", ".h5", ".parquet"):
                assets[ext] = assets.get(ext, 0) + 1
    assets = dict(sorted(assets.items(), key=lambda kv: -kv[1])[:15])

    # Which schema belongs to which topic, where the code says both in one place.
    topic_schemas = {}
    for rel, topics in (messaging or {}).items():
        body = _slurp(os.path.join(repo, rel))
        schemas = re.findall(r"[\"\']([\w./-]+\.(?:avsc|json|proto))[\"\']", body)[:6]
        if schemas and topics:
            topic_schemas[rel] = {"topics": topics[:6], "schemas": sorted(set(schemas))[:6]}
    topic_schemas = dict(list(topic_schemas.items())[:15])

    # Where a flag is actually branched on, not merely defined.
    flag_uses: dict[str, list] = {}
    known_flags = set((contract_details or {}).get("flags") or [])
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = re.findall(r"(?:is_enabled|isEnabled|feature_?flag|variation|getFlag|flags?\.)"
                          r"\W{0,4}[\"\']([\w._-]{3,50})[\"\']", body)[:10]
        hits += [f for f in known_flags if f in body][:5]
        if hits:
            flag_uses[rel] = sorted(set(hits))[:10]
    flag_uses = dict(list(flag_uses.items())[:20])

    # Assumptions about time: a suite that ignores them fails at midnight.
    time_assumptions: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = _lines_matching(body, ('america/w', 'dayjs.tz', 'europe/w"\n                          r"', 'locale.', 'pytz', 'strftime', 'timezone', 'tolocalew', 'tzinfo', 'utc', 'zoneinfo'), 4)
        if hits:
            time_assumptions[rel] = [h.strip()[:110] for h in hits]
    time_assumptions = dict(list(time_assumptions.items())[:20])

    # Size and shape of functions: where the complexity actually sits.
    complexity = []
    for rel in code_files:
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(_slurp(os.path.join(repo, rel)))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            branches = sum(isinstance(x, (ast.If, ast.For, ast.While, ast.Try,
                                          ast.BoolOp, ast.ExceptHandler))
                           for x in ast.walk(node))
            length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno
            if branches >= 8 or length >= 80:
                complexity.append(f"{os.path.basename(rel)}:{node.name} "
                                  f"({length} lines, {branches} branches)")
    complexity = sorted(complexity, key=lambda x: -int(re.search(r"\((\d+) lines", x).group(1)))[:25]

    # Blocks of code that appear more than once, by their shape.
    clones: dict[str, list] = {}
    seen_blocks: dict[str, list] = {}
    for rel in code_files:
        if not rel.endswith((".py", ".ts", ".js", ".go", ".java")):
            continue
        lines_ = [l.strip() for l in _slurp(os.path.join(repo, rel)).splitlines()
                  if l.strip() and not l.strip().startswith(("#", "//", "*"))]
        for i in range(0, max(0, len(lines_) - 8), 4):
            block = "\n".join(lines_[i:i + 8])
            if len(block) < 120:
                continue
            key = str(hash(block))
            seen_blocks.setdefault(key, []).append(f"{rel}:{i}")
    for key, places in seen_blocks.items():
        if len(places) > 1:
            clones[places[0]] = places[1:6]
    clones = dict(list(clones.items())[:20])

    # Lines, not just files: a hundred shell scripts and a hundred thousand lines
    # of TypeScript are not the same repository.
    loc: dict[str, int] = {}
    comments: dict[str, int] = {}
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            lang = LANG.get(os.path.splitext(fn)[1]) or ext_langs.get(os.path.splitext(fn)[1])
            if not lang:
                continue
            body = _slurp(os.path.join(base, fn), 300000)
            lines_ = body.splitlines()
            loc[lang] = loc.get(lang, 0) + len(lines_)
            comments[lang] = comments.get(lang, 0) + sum(
                1 for l in lines_ if l.strip().startswith(("#", "//", "/*", "*", "--")))
    loc = dict(sorted(loc.items(), key=lambda kv: -kv[1])[:15])

    # Files nothing imports: candidates for deletion, and a warning against
    # imitating them.
    referenced = set()
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        for name in re.findall(r"(?:from|import|require\(|include)\s*[\"\']?([\w./-]+)", body):
            referenced.add(os.path.basename(name).split(".")[0])
    dead_files = []
    for rel in code_files:
        if not rel.endswith((".py", ".ts", ".js", ".go")):
            continue
        stem = os.path.splitext(os.path.basename(rel))[0]
        if stem in ("__init__", "main", "index", "conftest", "setup"):
            continue
        if stem not in referenced and "test" not in rel.lower():
            dead_files.append(rel)
    dead_files = sorted(dead_files)[:40]

    # Cycles between top-level packages: the thing that makes a refactor hurt.
    cycles = []
    for a, deps in (import_graph or {}).items():
        for b in deps:
            if a in (import_graph.get(b) or []) and f"{b} ↔ {a}" not in cycles:
                cycles.append(f"{a} ↔ {b}")
    cycles = cycles[:20]

    # Which third-party services the code actually talks to.
    sdks: dict[str, list] = {}
    SDK_HINTS = {
        "aws": r"\bboto3|aws-sdk|AWS\.|amazonaws", "gcp": r"google\.cloud|googleapis",
        "azure": r"azure\.\w+|Azure\.", "stripe": r"\bstripe\b",
        "twilio": r"\btwilio\b", "sendgrid": r"\bsendgrid\b",
        "datadog": r"\bdatadog|ddtrace", "sentry": r"\bsentry\b",
        "segment": r"\bsegment\b|analytics\.track", "slack": r"slack_sdk|slack-sdk|hooks\.slack",
        "github": r"PyGithub|@octokit|api\.github\.com", "jira": r"\bjira\b",
        "openai": r"\bopenai\b", "anthropic": r"\banthropic\b",
        "kubernetes": r"kubernetes\.client|client-go", "redis": r"\bredis\b",
        "postgres": r"psycopg|pgx|node-postgres", "snowflake": r"\bsnowflake\b",
        "databricks": r"\bdatabricks\b", "salesforce": r"\bsalesforce|simple_salesforce",
    }
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel), 60000)
        if not body:
            continue
        for name, pat in SDK_HINTS.items():
            if re.search(pat, body, re.I):
                sdks.setdefault(name, []).append(os.path.basename(rel))
    sdks = {k: sorted(set(v))[:8] for k, v in sorted(sdks.items(), key=lambda kv: -len(kv[1]))[:20]}

    # The tools that police this repository, and what they enforce.
    quality_tools = {}
    for name in ("ruff.toml", ".ruff.toml", "setup.cfg", ".flake8", ".eslintrc",
                 ".eslintrc.json", ".eslintrc.js", "eslint.config.js", ".prettierrc",
                 ".editorconfig", ".pre-commit-config.yaml", "mypy.ini", ".golangci.yml",
                 "rubocop.yml", ".rubocop.yml", "pyproject.toml"):
        fp = os.path.join(repo, name)
        if not os.path.exists(fp):
            continue
        body = _slurp(fp, 20000)
        rules = re.findall(r"^\s*(?:select|extend-select|rules?|plugins?|repos?|"
                           r"enable|linters)\s*[:=]\s*(.{0,120})", body, re.M)[:6]
        hooks = re.findall(r"^\s*-\s*id:\s*([\w.-]+)", body, re.M)[:12]
        if rules or hooks:
            quality_tools[name] = [x.strip() for x in (rules + hooks)][:12]
    if os.path.isdir(os.path.join(repo, ".husky")):
        quality_tools[".husky"] = sorted(os.listdir(os.path.join(repo, ".husky")))[:8]

    # Release history: the tags and what the changelog says about them.
    releases = []
    try:
        import subprocess
        out = subprocess.run(["git", "-C", repo, "for-each-ref", "--sort=-creatordate",
                              "--format=%(refname:short) %(creatordate:short)",
                              "refs/tags", "--count=25"],
                             capture_output=True, text=True, timeout=30).stdout
        releases = [l.strip() for l in out.splitlines() if l.strip()][:25]
    except Exception:  # noqa: BLE001
        pass
    changelog_entries = []
    for name in ("CHANGELOG.md", "CHANGES.md", "HISTORY.md"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            changelog_entries = re.findall(r"^#{1,3}\s*\[?v?([\d.]+)\]?\s*(?:-|—|\()?\s*([\d-]{0,10})",
                                           _slurp(fp, 60000), re.M)[:20]
            break

    # The documentation site, where there is one.
    docs_site = {}
    for name in ("mkdocs.yml", "docusaurus.config.js", "docusaurus.config.ts",
                 "sphinx/conf.py", "docs/conf.py", "book.toml"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            body = _slurp(fp, 20000)
            docs_site[name] = re.findall(r"^\s*-\s*([\w /.-]+):\s*[\w/.-]+\.md|title:\s*(.+)",
                                         body, re.M)[:15]
            docs_site[name] = [a or b for a, b in docs_site[name]][:15]

    # Environment parity: what CI sets that the example file never mentions.
    ci_env, example_env = set(), set()
    for path, _meta in (ci or {}).items():
        body = _slurp(os.path.join(repo, path))
        ci_env.update(re.findall(r"^\s*([A-Z][A-Z0-9_]{2,}):\s", body, re.M))
        ci_env.update(re.findall(r"secrets\.([A-Z][A-Z0-9_]{2,})", body))
    for name in (".env.example", ".env.sample", ".env.template", "tests/.envrc", ".envrc"):
        fp = os.path.join(repo, name)
        if os.path.exists(fp):
            example_env.update(re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})=",
                                          _slurp(fp), re.M))
    env_parity = {"in_ci_only": sorted(ci_env - example_env)[:30],
                  "in_example_only": sorted(example_env - ci_env)[:30]}

    # How much of this is tests.
    test_files = [r for r in code_files
                  if "test" in r.lower() or "spec" in r.lower() or r.endswith(".feature")]
    ratio = {"code_files": len(code_files), "test_files": len(test_files),
             "share": f"{len(test_files) * 100 // max(len(code_files), 1)}%"}

    # Which binary serves which routes, where a repository has more than one.
    binaries_routes = {}
    for rel in code_files:
        if os.path.basename(rel) not in ("main.go", "main.py", "app.py", "index.ts"):
            continue
        pkg_dir = os.path.dirname(rel)
        mine = [r for r in (routes_served or []) if pkg_dir and pkg_dir.split(os.sep)[-1] in r]
        binaries_routes[rel] = mine[:12] or ["(routes not attributable by directory)"]
    binaries_routes = dict(list(binaries_routes.items())[:10])

    tags: dict[str, int] = {}
    for f in features.values():
        for t in f["tags"]:
            tags[t] = tags.get(t, 0) + 1

    stated = _manifest(repo)

    return {
        "schema": "where-are-we/1",
        "repo": repo,
        "stated": stated,
        "layers": {
            "features": _layer_line(sorted(features), "Gherkin features"),
            "steps": _layer_line(sorted(steps), "step definitions the features bind to"),
            "page_objects": _layer_line(page_objects, "classes that own selectors and page actions"),
            "driver": _layer_line(drivers, "browser/session driver: waits, screenshots"),
            "environment": _layer_line(envs, "hooks and per-scenario setup"),
        },
        "public_api": api,
        # name -> file:line, for everything this walk defined. A question about a
        # name is a question about where it is, and an answer without the line
        # sends the reader to grep for it anyway.
        "definitions": dict(sorted(DEFINITIONS.items())),
        # What was looked at, so "not found" can say where it looked.
        "indexed": dict(sorted(INDEXED.items())),
        # And the lines themselves, so a phrase search is a lookup. Kept out of
        # the Markdown digest on purpose: this is for the tool to read, not for
        # anything to carry in a prompt.
        "lines": LINES,
        "feature_links": feature_links,
        "data_files": data_files,
        "testids": testids,
        "helpers": helpers,
        "reporting": reporting,
        "hooks": hooks,
        "quarantine": quarantine,
        "product": product,
        "locators": locators,
        "timings": timings,
        "behave_config": behave_cfg,
        "coverage_docs": coverage_docs,
        "env_setup": env_setup,
        "backend": backend,
        "api_tests": api_tests,
        "conventions": conventions,
        "scenario_history": history,
        "dir_readmes": dir_readmes,
        "duplicates": duplicates,
        "near_duplicates": near_duplicates,
        "call_graph": call_graph,
        "artefacts": artefacts,
        "unused_steps": unused_steps,
        "unused_api": unused_api,
        "debts": debts,
        "git_history": git_history,
        "ticket_links": ticket_links,
        "dependencies": deps,
        "ci": ci,
        "required_env": required_env,
        "auth": auth,
        "concurrency": concurrency,
        "failure_signatures": failure_signatures,
        "safe_data": safe_data,
        "slow_steps": slow_steps,
        "tag_meaning": tag_meaning,
        "fragile_locators": fragile,
        "testid_owners": testid_owners,
        "rules_corpus": rules_corpus,
        "ui_strings": ui_strings,
        "infrastructure": infra,
        "schemas": schemas,
        "owners": owners,
        "env_differences": env_differences,
        "past_runs": past_bugs,
        "visual_baselines": baselines,
        "feature_style": feature_style,
        "pytest_tests": pytest_tests,
        "fixtures": fixtures,
        "markers": sorted(set(markers))[:30],
        "js_tests": js_tests,
        "test_config": test_config,
        "other_suites": other_suites,
        "contracts": contracts,
        "contract_details": contract_details,
        "languages": languages,
        "entry": entry,
        "exports": exports,
        "routes_served": routes_served,
        "models": models,
        "import_graph": import_graph,
        "workspaces": workspaces,
        "messaging": messaging,
        "grpc": grpc_services,
        "schedules": schedules,
        "kubernetes": k8s,
        "iac": iac,
        "cache_keys": cache_keys,
        "permissions": permissions,
        "observability": observability,
        "error_types": error_types,
        "cli_commands": cli_commands,
        "frontend": frontend,
        "adrs": adrs,
        "coverage_reports": coverage,
        "hotspots": hotspots,
        "dependency_licenses": dep_licenses,
        "call_graph_files": func_calls,
        "data_flow": data_flow,
        "blame_owners": blame_owners,
        "coverage_by_file": coverage_by_file,
        "deprecations": deprecations,
        "api_versions": sorted(api_versions)[:10],
        "doc_drift": doc_drift,
        "more_suites": more_suites,
        "data_stack": data_stack,
        "build_systems": build_systems,
        "stores": stores,
        "obs_config": obs_config,
        "perf_suites": perf_suites,
        "factories": factories,
        "db_constraints": db_constraints,
        "generated": generated,
        "types_declared": types_declared,
        "env_by_service": env_by_service,
        "client_policies": client_policies,
        "transactions": transactions,
        "logging_config": logging_config,
        "templates": templates,
        "license_headers": license_headers,
        "locked": locked,
        "status_codes": status_codes,
        "outbound": outbound,
        "k8s_runtime": k8s_runtime,
        "assets": assets,
        "topic_schemas": topic_schemas,
        "flag_uses": flag_uses,
        "time_assumptions": time_assumptions,
        "complexity": complexity,
        "clones": clones,
        "loc": loc,
        "comment_lines": comments,
        "dead_files": dead_files,
        "cycles": cycles,
        "sdks": sdks,
        "quality_tools": quality_tools,
        "releases": releases,
        "changelog_entries": changelog_entries,
        "docs_site": docs_site,
        "env_parity": env_parity,
        "test_ratio": ratio,
        "binaries_routes": binaries_routes,
        "ci_tags": ci_tags,
        "entry_points": entry_points,
        "docs": docs,
        "module_docs": module_docs,
        "tags": dict(sorted(tags.items(), key=lambda kv: -kv[1])[:60]),
        "environment": {k: sorted(v) for k, v in sorted(env_names.items())},
        # Anything the repository stated about itself replaces the guess.
        **({"layers": {**{
            "features": _layer_line(sorted(features), "Gherkin features"),
            "steps": _layer_line(sorted(steps), "step definitions the features bind to"),
            "page_objects": _layer_line(page_objects, "classes that own selectors and page actions"),
            "driver": _layer_line(drivers, "browser/session driver: waits, screenshots"),
            "environment": _layer_line(envs, "hooks and per-scenario setup"),
        }, **stated["layers"]}} if isinstance(stated.get("layers"), dict) else {}),
        "symbols": symbols,
        "steps": steps,
        "features": features,
        "page_objects": page_objects,
        "drivers": drivers,
        "behave_environment_files": envs,
        "scripts": scripts,
        "counts": {
            "step_modules": len(steps),
            "steps": sum(len(v) for v in steps.values()),
            "features": len(features),
            "scenarios": sum(len(v["scenarios"]) for v in features.values()),
        },
    }


def digest(m: dict) -> str:
    """The Markdown an agent reads instead of grepping. Paths and phrases only —
    anything longer would be re-read on every turn for no gain."""
    c = m["counts"]
    lines = [
        "# Framework map",
        "",
        f"Built from `{m['repo']}` at the start of this run: "
        f"{c['step_modules']} step modules, {c['steps']} step phrases, "
        f"{c['features']} feature files, {c['scenarios']} scenarios.",
        "",
    ]
    if TRUNCATED:
        # Said at the top, not buried: a reader who does not know the map is
        # partial will treat an absence as a fact about the codebase.
        lines += ["## This map is incomplete", ""]
        lines += [f"- {note}" for note in TRUNCATED]
        lines += [""]
    lines += ["## Where things are"]
    for label, key in (("Page objects", "page_objects"), ("Drivers", "drivers"),
                       ("behave environment", "behave_environment_files"), ("Scripts", "scripts")):
        if m[key]:
            lines.append(f"- **{label}**: " + ", ".join(f"`{p}`" for p in m[key][:8]))
    lines += ["", "## Step modules and what they declare", ""]
    for path, texts in sorted(m["steps"].items()):
        lines.append(f"### `{path}` — {len(texts)} steps")
        for t in texts:
            lines.append(f"- {t}")
        lines.append("")
    lines += ["## Feature files", ""]
    for path, f in sorted(m["features"].items()):
        lines.append(f"- `{path}` — {len(f['scenarios'])} scenarios"
                     + (f", tags: {' '.join('@'+t for t in f['tags'][:10])}" if f["tags"] else ""))
    return "\n".join(lines) + "\n"


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


# What each audience is here for.
#
# `--for author` used to mean "everything, plus the vocabulary", which made the
# author brief twice the size of the coder one — 253 KB against 120 KB on a real
# suite — and most of that extra was the product's internals: its data model, its
# queues, its cache keys, its indexes. Somebody writing a scenario does not
# choose their words by reading a table definition.
#
# So each audience keeps what it works with. Matched on a heading's opening
# words, because the headings carry counts and names; a heading nobody claimed
# goes to both, which is the safe way to be wrong.
_PRODUCT_SIDE = (
    "data model", "tables and the columns", "which code touches which table",
    "indexes and constraints", "datastores and brokers", "queues, topics",
    "cache keys", "permissions and roles", "error types", "http routes",
    "http surface", "scheduled work", "api versions", "deprecations",
    "generated code", "types declared", "public surface of the code",
    "how the top-level packages", "how the packages depend", "monorepo layout",
    "who calls whom", "largest files", "lines of code", "assets",
    "logging configuration", "retries, timeouts, breakers",
    "architecture decisions", "code owners", "dependencies",
    "contracts, schemas and mocks", "what those contracts actually say",
    "documentation pointing at", "who has been touching what",
    "most-changed files", "recent tickets and the files",
)
_TEST_SIDE = (
    "what you can already write with", "steps that overlap", "what a step may call",
    "what each step calls", "step modules", "feature files", "biggest feature files",
    "which feature is served", "how a feature file is written", "how a scenario is run",
    "how a test authenticates", "tags in use", "tags each ci job", "what the tags mean",
    "markers in use", "fixtures", "test data", "test ids", "which component owns which test id",
    "locator constants", "locators marked fragile", "page-object methods nothing calls",
    "shared helpers outside steps", "interface strings", "failure messages this suite",
    "visual baselines", "quarantined", "slow steps", "what past runs measured",
    "what earlier runs of this pipeline", "coverage documents", "behave configuration",
    "behave hooks", "pytest cases", "javascript/typescript tests", "other test suites",
    "what cannot run beside", "what a run leaves behind", "reporting and artefacts",
    "admitted debts", "the suite's own documentation", "how this suite is built",
    "api-level features",
)


def for_audience(text: str, audience: str) -> str:
    """Drop the half of the brief this reader does not work with.

    Neither list is exhaustive on purpose: a section nobody claimed is kept for
    both, so a new section shows up rather than vanishing silently.
    """
    if audience not in ("author", "coder"):
        return text
    drop = _PRODUCT_SIDE if audience == "author" else _TEST_SIDE
    kept, dropping = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:].strip().lower()
            dropping = any(head.startswith(x) for x in drop)
        elif line.startswith("# "):
            dropping = False
        if not dropping:
            kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _cap_sections(text: str, max_lines: int) -> str:
    """The brief cut inside its sections rather than at a line number.

    `--max-lines 200` used to keep the first 200 lines and drop the rest, so
    the sections at the end — the overlaps, the dead phrases, the debts — were
    the ones that never reached the prompt. Now every section is present and
    none is complete past its share; the tail says where the rest is.
    """
    if max_lines <= 0 or text.count("\n") <= max_lines:
        return text
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    if not heads:
        return "\n".join(lines[:max_lines])
    # The preamble is the brief's own few lines; a long one is cut too, or it
    # alone could spend the cap (measured at review: a 200-line preamble under
    # --max-lines 10 came back 206 lines). Every head stays whatever the cap —
    # a section that is absent cannot be asked about — so a cap too small to
    # hold the heads is exceeded by the heads and their tails, and by nothing
    # else: no row is forced in.
    preamble = lines[:heads[0]][:max(4, max_lines // 4)]
    share = max(0, (max_lines - len(preamble) - 3 * len(heads)) // len(heads))
    out = list(preamble)
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        body = [l for l in lines[start + 1:end] if l.strip()]
        out.append(lines[start])
        kept, dropped = fit_lines(body, share, cost=lambda _l: 1, sep=0)
        out += kept
        if dropped:
            out.append(f"… {dropped} more in framework_map.md")
        out.append("")
    return "\n".join(out)


def brief(m: dict) -> str:
    """The few thousand characters that go in the prompt: where things are, and
    which module owns which area. The step phrases themselves stay in the big
    file, which is one grep away — an agent that needs a phrase greps for it
    instead of carrying 1400 of them through every turn."""
    c = m["counts"]
    lines = [
        "# Framework map (brief)",
        "",
        f"{c['step_modules']} step modules / {c['steps']} step phrases, "
        f"{c['features']} feature files / {c['scenarios']} scenarios. "
        "Full map with every step phrase: `framework_map.md` in this run's "
        "directory — grep that file instead of grepping the repository.",
        "",
    ]
    if TRUNCATED:
        lines += ["## This map is incomplete", ""]
        lines += [f"- {note}" for note in TRUNCATED]
        lines += [""]
    st = _as_dict(m.get("stated"))
    if st:
        lines += ["## What this repository says it is", ""]
        if st.get("name"):
            lines.append(f"- **{st['name']}**" + (f" — {st.get('purpose','')}" if st.get("purpose") else ""))
        for c in (st.get("conventions") or [])[:12]:
            lines.append(f"- {c}")
        for cmd, what in (st.get("entry_points") or {}).items():
            lines.append(f"- `{cmd}` — {what}")
        if st.get("notes"):
            lines.append(f"- {st['notes']}")
        lines.append("")
    lg = _as_dict(m.get("languages"))
    if lg:
        lines += ["## What this codebase is made of", "",
                  ", ".join(f"{k} ({n})" for k, n in list(lg.items())[:10]), ""]
    en = _as_dict(m.get("entry"))
    if en:
        lines += ["## Where it starts", ""]
        for k, v in list(en.items())[:10]:
            if k == "package.json scripts":
                lines.append("- npm scripts: " + ", ".join(f"`{a}` → {b[:40]}" for a, b in v[:8]))
            elif isinstance(v, list):
                lines.append(f"- {k}: " + ", ".join(str(x)[:60] for x in v[:8]))
        lines.append("")
    ws = _as_list(m.get("workspaces"))
    if ws:
        lines += ["## Monorepo layout", "", ", ".join(f"`{x}`" for x in ws[:12]), ""]
    rs = _as_list(m.get("routes_served"))
    if rs:
        lines += [f"## HTTP routes this codebase serves ({len(rs)})", ""]
        for r in rs[:30]:
            lines.append(f"- {r}")
        lines.append("")
    md2 = _as_dict(m.get("models"))
    if md2:
        lines += ["## Data model", ""]
        for name, fields in list(md2.items())[:15]:
            lines.append(f"- `{name}`: " + ", ".join(fields[:12]))
        lines.append("")
    ex = _as_dict(m.get("exports"))
    if ex:
        lines += ["## Public surface of the code", ""]
        for rel, names in list(ex.items())[:20]:
            lines.append(f"- `{rel}`: " + ", ".join(names[:10]))
        lines.append("")
    ig = _as_dict(m.get("import_graph"))
    if ig:
        lines += ["## How the top-level packages depend on each other", ""]
        for top, deps in ig.items():
            lines.append(f"- `{top}` → " + ", ".join(deps))
        lines.append("")
    def _sect(title: str, rows: list) -> None:
        if rows:
            lines.extend(["## " + title, ""] + rows + [""])

    ms = _as_dict(m.get("messaging"))
    _sect("Queues, topics and subjects",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:10]) for k, v in list(ms.items())[:12]])
    gr = _as_dict(m.get("grpc"))
    _sect("gRPC services", [f"- `{k}`: " + ", ".join(v[:12]) for k, v in list(gr.items())[:12]])
    sch = _as_dict(m.get("schedules"))
    _sect("Scheduled work",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:6]) for k, v in list(sch.items())[:12]])
    kb = _as_dict(m.get("kubernetes"))
    _sect("Kubernetes and Helm",
          [f"- `{k}` — {', '.join(v['kinds'][:6])}: {', '.join(v['names'][:6])}"
           for k, v in list(kb.items())[:12]])
    ic = _as_dict(m.get("iac"))
    _sect("Infrastructure as code",
          [f"- `{k}`: " + ", ".join(f"{a}.{b}" for a, b in v[:10]) for k, v in list(ic.items())[:10]])
    ck = _as_list(m.get("cache_keys"))
    _sect("Cache keys", ["- " + ", ".join(f"`{x}`" for x in ck[:25])] if ck else [])
    pm = _as_dict(m.get("permissions"))
    _sect("Permissions and roles",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:10]) for k, v in list(pm.items())[:12]])
    ob = _as_dict(m.get("observability"))
    _sect("Observability", [f"- {k}: " + ", ".join(v[:15]) for k, v in ob.items() if v])
    et = _as_dict(m.get("error_types"))
    _sect("Error types", ["- " + ", ".join(f"`{k}` ({v})" for k, v in list(et.items())[:20])] if et else [])
    cc = _as_dict(m.get("cli_commands"))
    _sect("Command line",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:12]) for k, v in list(cc.items())[:10]])
    fe = _as_dict(m.get("frontend"))
    _sect("Frontend", [f"- {k}: " + ", ".join(str(x) for x in v[:15]) for k, v in fe.items() if v])
    ad = _as_list(m.get("adrs"))
    _sect("Architecture decisions", [f"- {x}" for x in ad[:15]])
    cov = _as_dict(m.get("coverage_reports"))
    _sect("Coverage reports", [f"- `{k}`: " + ", ".join(v) for k, v in list(cov.items())[:6]])
    hp = _as_list(m.get("hotspots"))
    _sect("Largest files", ["- " + ", ".join(hp[:12])] if hp else [])
    dl = _as_dict(m.get("dependency_licenses"))
    _sect("Declared licenses", [f"- `{k}`: " + ", ".join(v[:6]) for k, v in list(dl.items())[:6] if v])

    fc = _as_dict(m.get("call_graph_files"))
    _sect("Who calls whom, across files",
          [f"- `{k}` → " + ", ".join(v[:6]) for k, v in list(fc.items())[:20]])
    df = _as_dict(m.get("data_flow"))
    _sect("Which code touches which table",
          [f"- `{os.path.basename(k)}`: {', '.join(v['paths'][:4])} ↔ {', '.join(v['tables'][:5])}"
           for k, v in list(df.items())[:15]])
    bo = _as_dict(m.get("blame_owners"))
    _sect("Who has been touching what (last year)",
          [f"- `{k}` — {', '.join(v)}" for k, v in list(bo.items())[:15]])
    cbf = _as_dict(m.get("coverage_by_file"))
    _sect("Coverage by file",
          [f"- `{k}` — {v}" for k, v in list(cbf.items())[:20]])
    dep2 = _as_dict(m.get("deprecations"))
    _sect("Deprecations",
          [f"- `{os.path.basename(k)}`: " + " | ".join(v[:2]) for k, v in list(dep2.items())[:12]])
    av = _as_list(m.get("api_versions"))
    _sect("API versions in use", ["- " + ", ".join(av)] if av else [])
    dd = _as_list(m.get("doc_drift"))
    _sect("Documentation pointing at things that are not there",
          [f"- {x}" for x in dd[:15]])

    mss = _as_dict(m.get("more_suites"))
    _sect("More test suites",
          [f"- **{k}** — {len(v)} files: " + ", ".join(os.path.basename(x) for x in list(v)[:4])
           for k, v in mss.items()])
    ds = _as_dict(m.get("data_stack"))
    _sect("Data engineering",
          ([f"- dbt models: {len(ds['dbt_models'])}"] if ds.get("dbt_models") else [])
          + ([f"- Airflow: " + ", ".join(f"`{os.path.basename(k)}` ({len(v)} tasks)"
                                        for k, v in list(ds["airflow_dags"].items())[:6])]
             if ds.get("airflow_dags") else [])
          + ([f"- Spark jobs: {len(ds['spark_jobs'])}"] if ds.get("spark_jobs") else [])
          + ([f"- notebooks: {len(ds['notebooks'])}"] if ds.get("notebooks") else []))
    bs = _as_dict(m.get("build_systems"))
    _sect("Build systems", [f"- **{k}**: " + "; ".join(v[:4]) for k, v in bs.items()])
    st = _as_dict(m.get("stores"))
    _sect("Datastores and brokers", [f"- {k}: " + ", ".join(v[:12]) for k, v in st.items()])
    oc = _as_dict(m.get("obs_config"))
    _sect("Observability and policy configuration",
          [f"- {k}: " + ", ".join(str(x)[:70] for x in v[:5]) for k, v in oc.items()])
    ps = _as_dict(m.get("perf_suites"))
    _sect("Load testing", [f"- {k}: " + ", ".join(os.path.basename(x) for x in v[:8])
                           for k, v in ps.items()])
    fac = _as_dict(m.get("factories"))
    _sect("Test data factories",
          [f"- `{os.path.basename(k)}`: " + ", ".join(x for x in v[:8] if x)
           for k, v in list(fac.items())[:10]])

    dbc = _as_dict(m.get("db_constraints"))
    _sect("Indexes and constraints",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:10]) for k, v in list(dbc.items())[:12]])
    gen = _as_dict(m.get("generated"))
    _sect("Generated code — do not edit by hand",
          [f"- `{k}` — {v}" for k, v in list(gen.items())[:15]])
    td = _as_dict(m.get("types_declared"))
    _sect("Types declared",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:12]) for k, v in list(td.items())[:15]])
    ebs = _as_dict(m.get("env_by_service"))
    _sect("Environment by service",
          [f"- `{k}`: " + ", ".join(v[:12]) for k, v in list(ebs.items())[:15]])
    cp = _as_dict(m.get("client_policies"))
    _sect("Retries, timeouts, breakers and limits",
          [f"- `{os.path.basename(k)}`: " + " | ".join(v[:2]) for k, v in list(cp.items())[:12]])
    tx = _as_dict(m.get("transactions"))
    _sect("Transactions and idempotency",
          [f"- `{os.path.basename(k)}`: " + " | ".join(v[:2]) for k, v in list(tx.items())[:10]])
    lc = _as_dict(m.get("logging_config"))
    _sect("Logging configuration", [f"- `{k}`: " + ", ".join(v) for k, v in list(lc.items())[:8]])
    tpl = _as_dict(m.get("templates"))
    _sect("What the repository asks contributors for",
          [f"- `{k}`: " + ", ".join(str(x)[:60] for x in v[:8]) for k, v in tpl.items() if v])
    lh = _as_dict(m.get("license_headers"))
    _sect("License headers", ["- " + ", ".join(f"{k} ({n})" for k, n in lh.items())] if lh else [])

    lk = _as_dict(m.get("locked"))
    _sect("What is actually installed",
          [f"- `{k}`: " + ", ".join(v[:12]) for k, v in lk.items()])
    scd = _as_dict(m.get("status_codes"))
    _sect("Status codes the code returns",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:10]) for k, v in list(scd.items())[:12]])
    ob = _as_dict(m.get("outbound"))
    _sect("Services this code calls",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:6]) for k, v in list(ob.items())[:12]])
    kr = _as_dict(m.get("k8s_runtime"))
    _sect("How pods are kept alive",
          [f"- `{os.path.basename(k)}` — probes: {', '.join(v['probes'][:3]) or 'none'}"
           f" · resources: {', '.join(v['resources'][:4]) or 'unset'}"
           f" · replicas: {', '.join(v['replicas'][:2]) or '—'}"
           for k, v in list(kr.items())[:10]])
    ast_ = _as_dict(m.get("assets"))
    _sect("Assets", ["- " + ", ".join(f"{k} ({n})" for k, n in ast_.items())] if ast_ else [])
    ts2 = _as_dict(m.get("topic_schemas"))
    _sect("Which schema belongs to which topic",
          [f"- `{os.path.basename(k)}`: {', '.join(v['topics'][:4])} ↔ {', '.join(v['schemas'][:4])}"
           for k, v in list(ts2.items())[:10]])
    fu = _as_dict(m.get("flag_uses"))
    _sect("Where flags are branched on",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:8]) for k, v in list(fu.items())[:12]])
    ta = _as_dict(m.get("time_assumptions"))
    _sect("Assumptions about time and locale",
          [f"- `{os.path.basename(k)}`: " + " | ".join(v[:2]) for k, v in list(ta.items())[:10]])
    cx = _as_list(m.get("complexity"))
    _sect("The functions that carry the complexity", [f"- {x}" for x in cx[:15]])
    cl = _as_dict(m.get("clones"))
    _sect("Blocks that appear more than once",
          [f"- `{k}` ≈ " + ", ".join(v[:3]) for k, v in list(cl.items())[:12]])

    lo = _as_dict(m.get("loc"))
    _sect("Lines of code", ["- " + ", ".join(f"{k}: {v:,}" for k, v in list(lo.items())[:10])] if lo else [])
    tr = _as_dict(m.get("test_ratio"))
    _sect("How much of this is tests",
          [f"- {tr.get('test_files')} test files of {tr.get('code_files')} ({tr.get('share')})"] if tr else [])
    dfl = _as_list(m.get("dead_files"))
    _sect("Files nothing imports", ["- " + ", ".join(f"`{x}`" for x in dfl[:20])] if dfl else [])
    cy = _as_list(m.get("cycles"))
    _sect("Circular dependencies", [f"- {x}" for x in cy[:12]])
    sd = _as_dict(m.get("sdks"))
    _sect("Third-party services this code talks to",
          [f"- **{k}** — {', '.join(v[:5])}" for k, v in list(sd.items())[:15]])
    qt = _as_dict(m.get("quality_tools"))
    _sect("What polices this repository",
          [f"- `{k}`: " + ", ".join(str(x)[:50] for x in v[:8]) for k, v in list(qt.items())[:10]])
    rl = _as_list(m.get("releases"))
    _sect("Releases", ["- " + ", ".join(rl[:12])] if rl else [])
    ce = _as_list(m.get("changelog_entries"))
    _sect("Changelog",
          ["- " + ", ".join(f"{a}{' (' + b + ')' if b else ''}" for a, b in ce[:12])] if ce else [])
    dsi = _as_dict(m.get("docs_site"))
    _sect("Documentation site",
          [f"- `{k}`: " + ", ".join(str(x)[:40] for x in v[:8]) for k, v in dsi.items()])
    ep = _as_dict(m.get("env_parity"))
    _sect("Environment parity",
          ([f"- set in CI only: " + ", ".join(ep["in_ci_only"][:15])] if ep.get("in_ci_only") else [])
          + ([f"- in the example only: " + ", ".join(ep["in_example_only"][:15])]
             if ep.get("in_example_only") else []))
    br = _as_dict(m.get("binaries_routes"))
    _sect("Which binary serves what",
          [f"- `{k}`: " + ", ".join(v[:6]) for k, v in list(br.items())[:8]])

    lines += ["## How this suite is built", ""]
    for k, v in (_as_dict(m.get("layers"))).items():
        lines.append(f"- **{k}** — {v}")
    lines.append("")
    for label, key in (("Page objects", "page_objects"), ("Drivers", "drivers"),
                       ("behave environment", "behave_environment_files"), ("Scripts", "scripts")):
        if m[key]:
            lines.append(f"- **{label}**: " + ", ".join(f"`{p}`" for p in m[key][:6]))
    ep = _as_dict(m.get("entry_points"))
    if ep:
        lines += ["", "## How a scenario is run", ""]
        for path, usage in list(ep.items())[:5]:
            lines.append(f"- `{path}`: " + "; ".join(usage))
    api = _as_dict(m.get("public_api"))
    if api:
        lines += ["", "## What a step may call", ""]
        for path, methods in api.items():
            lines.append(f"- `{path}`: " + ", ".join(methods[:16])
                         + (f" … +{len(methods)-16} more in the full map" if len(methods) > 16 else ""))
    md = _as_dict(m.get("module_docs"))
    if md:
        lines += ["", "## What each module says it is for", ""]
        for path, doc in list(md.items())[:20]:
            lines.append(f"- `{path}` — {doc.splitlines()[0][:180]}")
    dc = _as_dict(m.get("docs"))
    if dc:
        lines += ["", "## The suite's own documentation", ""]
        for path, meta in list(dc.items())[:12]:
            lines.append(f"- `{path}` — " + ", ".join(meta["headings"][:6]))
    fl = _as_dict(m.get("feature_links"))
    if fl:
        lines += ["", "## Which feature is served by which modules", ""]
        for path, link in sorted(fl.items(), key=lambda kv: -len(kv[1]["step_modules"]))[:20]:
            if not link["step_modules"]:
                continue
            lines.append(f"- `{os.path.basename(path)}` → steps: "
                         + ", ".join(os.path.basename(x) for x in link["step_modules"][:6])
                         + (" · pages: " + ", ".join(os.path.basename(x) for x in link["page_objects"][:4])
                            if link["page_objects"] else ""))
    hl = _as_dict(m.get("helpers"))
    if hl:
        lines += ["", "## Shared helpers outside steps and page objects", ""]
        for path, methods in list(hl.items())[:12]:
            lines.append(f"- `{path}`: " + ", ".join(methods[:10]))
    hk = _as_dict(m.get("hooks"))
    if hk:
        lines += ["", "## behave hooks and what they do", ""]
        for name, meta in list(hk.items())[:12]:
            lines.append(f"- `{name}` — {meta['doc'] or 'no docstring'}"
                         + (f" · calls: {', '.join(meta['calls'][:8])}" if meta["calls"] else ""))
    pr = _as_dict(m.get("product"))
    if any(pr.values()):
        lines += ["", "## The product under test", ""]
        if pr.get("routes"):
            lines.append("- routes: " + ", ".join(pr["routes"][:20]))
        if pr.get("storage_keys"):
            lines.append("- localStorage keys: " + ", ".join(pr["storage_keys"][:20]))
        if pr.get("api_paths"):
            lines.append("- API: " + ", ".join(pr["api_paths"][:20]))
    ti = _as_dict(m.get("testids"))
    if ti.get("product") or ti.get("suite"):
        lines += ["", "## Test ids", ""]
        if ti.get("product"):
            lines.append(f"- product exposes {len(ti['product'])}: "
                         + ", ".join(ti["product"][:25]) + " … (full list in the full map)")
        if ti.get("suite"):
            lines.append(f"- suite drives {len(ti['suite'])}: " + ", ".join(ti["suite"][:15]))
    df = _as_list(m.get("data_files"))
    if df:
        lines += ["", "## Test data and fixtures", "",
                  ", ".join(f"`{x}`" for x in df[:20])
                  + (f" … +{len(df)-20}" if len(df) > 20 else "")]
    rp = _as_dict(m.get("reporting"))
    if rp:
        lines += ["", "## Reporting and artefacts", ""]
        for kw, files in rp.items():
            lines.append(f"- {kw}: " + ", ".join(f"`{os.path.basename(f)}`" for f in files))
    qz = _as_dict(m.get("quarantine"))
    if qz:
        lines += ["", "## Quarantined / known-unstable", ""]
        for path, marks in list(qz.items())[:15]:
            lines.append(f"- `{os.path.basename(path)}` — " + ", ".join("@"+x for x in marks[:6]))
    lc = _as_dict(m.get("locators"))
    if lc:
        lines += ["", "## Locator constants", ""]
        for path, items in list(lc.items())[:8]:
            lines.append(f"- `{os.path.basename(path)}`: " + "; ".join(items[:8]))
    tm = _as_dict(m.get("timings"))
    if tm:
        lines += ["", "## Timeouts, waits and budgets", ""]
        for path, items in list(tm.items())[:10]:
            lines.append(f"- `{os.path.basename(path)}`: " + "; ".join(items[:10]))
    bc = _as_dict(m.get("behave_config"))
    if bc:
        lines += ["", "## behave configuration", ""]
        for name, body in bc.items():
            first = " · ".join(l.strip() for l in body.splitlines() if l.strip())[:300]
            lines.append(f"- `{name}`: {first}")
    cd = _as_dict(m.get("coverage_docs"))
    if cd:
        lines += ["", "## Coverage documents (ticket → scenarios)", ""]
        for path, meta in list(cd.items())[:6]:
            lines.append(f"- `{path}` — {len(meta['tickets'])} tickets: "
                         + ", ".join(meta["tickets"][:12]))
    es = _as_dict(m.get("env_setup"))
    if es:
        lines += ["", "## Bringing the environment up", ""]
        for path, meta in list(es.items())[:8]:
            lines.append(f"- `{os.path.basename(path)}` — flags: "
                         + ", ".join(meta["flags"][:8])
                         + (" · ports: " + ", ".join(meta["ports"][:6]) if meta["ports"] else ""))
    bk = _as_dict(m.get("backend"))
    if any(bk.values()):
        lines += ["", "## Backend the tests touch", ""]
        if bk.get("endpoints"):
            lines.append("- endpoints: " + ", ".join(bk["endpoints"][:20]))
        if bk.get("tables"):
            lines.append("- tables queried: " + ", ".join(bk["tables"][:20]))
        if bk.get("seed_scripts"):
            lines.append("- seeding: " + ", ".join(f"`{os.path.basename(x)}`" for x in bk["seed_scripts"][:8]))
    at = _as_list(m.get("api_tests"))
    if at:
        lines += ["", "## API-level features (not UI)", "",
                  ", ".join(f"`{os.path.basename(x)}`" for x in at[:20])]
    cv = _as_dict(m.get("conventions"))
    if cv:
        lines += ["", "## Repository conventions", ""]
        for name, body in cv.items():
            head = " · ".join(l.strip("# ").strip() for l in body.splitlines()
                              if l.startswith("#"))[:240]
            lines.append(f"- `{name}`: {head}")
    hs = _as_dict(m.get("scenario_history"))
    if hs:
        lines += ["", "## What past runs measured (slowest first)", ""]
        for name, meta in list(hs.items())[:20]:
            lines.append(f"- {name[:90]} — ~{meta['avg_s']}s"
                         + (f", failed {meta['failed']}×" if meta["failed"] else ""))
    dr = _as_dict(m.get("dir_readmes"))
    if dr:
        lines += ["", "## What each directory says it is", ""]
        for d, meta in sorted(dr.items())[:40]:
            lines.append(f"- `{d}` — {meta['summary'] or ', '.join(meta['headings'][:4])}")
    nd = _as_list(m.get("near_duplicates"))
    if nd:
        lines += ["", f"## Steps that overlap ({len(nd)} pairs) — check whether one already does what you need", ""]
        for d in nd[:20]:
            lines.append(f"- {d['similarity']}: \"{d['a'][:60]}\" (`{os.path.basename(d['a_in'])}`)"
                         f" ≈ \"{d['b'][:60]}\" (`{os.path.basename(d['b_in'])}`)")
    cg = _as_dict(m.get("call_graph"))
    if cg:
        lines += ["", "## What each step calls", ""]
        for name, calls in list(cg.items())[:25]:
            lines.append(f"- `{name}` → " + ", ".join(calls[:8]))
    af = _as_dict(m.get("artefacts"))
    if af:
        lines += ["", "## What a run leaves behind", "",
                  ", ".join(f"`{k}`" for k in list(af)[:25])]
    dup = _as_dict(m.get("duplicates"))
    if dup:
        lines += ["", f"## Duplicate step phrases ({len(dup)} collisions) — reuse, do not re-declare", ""]
        for norm, owners in list(dup.items())[:20]:
            where = ", ".join(f"`{os.path.basename(r)}`" for r, _ in owners[:4])
            lines.append(f"- \"{norm[:80]}\" — {where}")
    us = _as_dict(m.get("unused_steps"))
    if us:
        total = sum(len(v) for v in us.values())
        lines += ["", f"## Step phrases no feature uses ({total}) — dead weight, do not imitate", ""]
        for rel, dead in list(us.items())[:10]:
            lines.append(f"- `{os.path.basename(rel)}`: " + "; ".join(x[:60] for x in dead[:4]))
    ua = _as_dict(m.get("unused_api"))
    if ua:
        lines += ["", "## Page-object methods nothing calls", ""]
        for rel, dead in list(ua.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + ", ".join(dead[:8]))
    db = _as_dict(m.get("debts"))
    if db:
        lines += ["", f"## Admitted debts (TODO/FIXME/skip) in {len(db)} files", ""]
        for rel, items in list(db.items())[:12]:
            lines.append(f"- `{os.path.basename(rel)}`: " + " | ".join(items[:2]))
    gh = _as_dict(m.get("git_history"))
    if gh:
        lines += ["", "## Most-changed files, last 90 days", ""]
        for rel, entries in list(gh.items())[:12]:
            lines.append(f"- `{rel}` — {len(entries)} commits, latest: {entries[0][:80]}")
    tl = _as_dict(m.get("ticket_links"))
    if tl:
        lines += ["", "## Recent tickets and the files they touched", ""]
        for t, meta in list(tl.items())[:12]:
            lines.append(f"- {t}: {meta['subject'][:60]} → "
                         + ", ".join(os.path.basename(f) for f in meta["files"][:4]))
    dp = _as_dict(m.get("dependencies"))
    if dp:
        lines += ["", "## Dependencies", ""]
        for name, pins in dp.items():
            lines.append(f"- `{name}`: " + ", ".join(f"{a}={b}" for a, b in pins[:14]))
    ci = _as_dict(m.get("ci"))
    if ci:
        lines += ["", "## CI", ""]
        for path, meta in list(ci.items())[:6]:
            lines.append(f"- `{path}` — jobs: {', '.join(meta['jobs'][:8])}"
                         + (f" · runs: {meta['runs'][0][:60]}" if meta["runs"] else ""))
    re_env = _as_list(m.get("required_env"))
    if re_env:
        lines += ["", "## Environment that must be set (from .envrc)", "",
                  ", ".join(f"`{x}`" for x in re_env[:40])]
    au = _as_dict(m.get("auth"))
    if au:
        lines += ["", "## How a test authenticates", ""]
        for rel, hits in list(au.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + " | ".join(h[:90] for h in hits[:2]))
    cc = _as_dict(m.get("concurrency"))
    if any(cc.values()):
        lines += ["", "## What cannot run beside something else", ""]
        if cc.get("serial_tags"):
            lines.append("- tags demanding isolation: " + ", ".join("@"+t for t in cc["serial_tags"]))
        if cc.get("shared_state"):
            lines.append("- module-level shared state: " + ", ".join(cc["shared_state"][:12]))
        for n in (cc.get("notes") or [])[:5]:
            lines.append(f"- {n}")
    fs = _as_dict(m.get("failure_signatures"))
    if fs:
        lines += ["", "## Failure messages this suite can produce", ""]
        for msg, where in list(fs.items())[:15]:
            lines.append(f"- \"{msg[:100]}\" — {', '.join(where[:2])}")
    sd = _as_dict(m.get("safe_data"))
    if sd:
        lines += ["", "## Test data the suite already uses", ""]
        for rel, ids in list(sd.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + ", ".join(ids[:15]))
    ss = _as_dict(m.get("slow_steps"))
    if ss:
        lines += ["", "## Slow steps (from past runs)", ""]
        for phrase, meta in list(ss.items())[:12]:
            lines.append(f"- {phrase[:70]} — up to {meta['avg_s']}s (`{meta['module']}`)")
    tmn = _as_dict(m.get("tag_meaning"))
    if tmn:
        lines += ["", "## What the tags mean, where it is written down", ""]
        for tag, sense in list(tmn.items())[:15]:
            lines.append(f"- `@{tag}` — {sense[:110]}")
    fr = _as_dict(m.get("fragile_locators"))
    if fr:
        lines += ["", "## Locators marked fragile, legacy or fallback", ""]
        for rel, items in list(fr.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + "; ".join(x[:80] for x in items[:4]))
    to = _as_dict(m.get("testid_owners"))
    if to:
        lines += ["", f"## Which component owns which test id ({len(to)})", ""]
        for tid, owner in list(to.items())[:25]:
            lines.append(f"- `{tid}` — {owner}")
    rc = _as_list(m.get("rules_corpus"))
    if rc:
        lines += ["", f"## The rules this work is held to ({len(rc)})", "",
                  ", ".join(rc[:60]) + (" …" if len(rc) > 60 else "")]
    us2 = _as_list(m.get("ui_strings"))
    if us2:
        lines += ["", "## Interface strings assertions can match", "",
                  ", ".join(f"\"{x}\"" for x in us2[:40])]
    inf = _as_dict(m.get("infrastructure"))
    if inf:
        lines += ["", "## Infrastructure the suite talks to", ""]
        for rel, meta in list(inf.items())[:8]:
            lines.append(f"- `{rel}` — services: {', '.join(meta['services'][:8])}"
                         + (f" · ports: {', '.join(meta['ports'][:8])}" if meta["ports"] else "")
                         + (f" · health: {meta['health'][0][:60]}" if meta["health"] else ""))
    sc = _as_dict(m.get("schemas"))
    # Defensive because a section is data, not a promise: an older map, a
    # hand-edited one, or a future shape should degrade to "not shown" rather
    # than take the whole brief down with it. The smoke test that installs the
    # deb and maps this repository is what found this one.
    if not isinstance(sc, dict):
        sc = {}
    if sc:
        lines += ["", "## Tables and the columns tests read", ""]
        for tbl, cols in list(sc.items())[:12]:
            lines.append(f"- `{tbl}`: " + ", ".join(cols[:12]))
    ow = _as_dict(m.get("owners"))
    if ow:
        lines += ["", "## Code owners", ""]
        for path, who in list(ow.items())[:12]:
            lines.append(f"- `{path}` — {', '.join(who)}")
    ed = _as_dict(m.get("env_differences"))
    if ed:
        lines += ["", "## Where the environments differ", ""]
        for rel, hits in list(ed.items())[:10]:
            lines.append(f"- `{os.path.basename(rel)}`: " + " | ".join(h[:80] for h in hits[:2]))
    pr2 = _as_list(m.get("past_runs"))
    if pr2:
        lines += ["", "## What earlier runs of this pipeline concluded", ""]
        for r in pr2[:10]:
            lines.append(f"- run {r['run']} {r['ticket']}: {r['verdict']} — {r['summary'][:100]}")
    vb = _as_list(m.get("visual_baselines"))
    if vb:
        lines += ["", "## Visual baselines", "", ", ".join(f"`{x}`" for x in vb[:15])]
    fst = _as_dict(m.get("feature_style"))
    if fst.get("sample"):
        lines += ["", "## How a feature file is written here", "",
                  f"Sample: `{fst['sample']}`"
                  + (", uses Scenario Outline" if fst.get("uses_outlines") else ""),
                  "", "```gherkin", fst.get("first_scenario", "")[:900], "```"]
    pt = _as_dict(m.get("pytest_tests"))
    if pt:
        lines += ["", f"## pytest cases ({sum(len(v) for v in pt.values())})", ""]
        for rel, cases in list(pt.items())[:15]:
            lines.append(f"- `{rel}`: " + ", ".join(cases[:8]))
    fx = _as_dict(m.get("fixtures"))
    if fx:
        lines += ["", "## Fixtures", ""]
        for rel, fs2 in list(fx.items())[:12]:
            lines.append(f"- `{rel}`: " + ", ".join(fs2[:12]))
    mk = _as_list(m.get("markers"))
    if mk:
        lines += ["", "## Markers in use", "", ", ".join(mk[:25])]
    jt = _as_dict(m.get("js_tests"))
    if jt:
        lines += ["", f"## JavaScript/TypeScript tests ({len(jt)} files)", ""]
        for rel, names in list(jt.items())[:12]:
            lines.append(f"- `{rel}`: " + "; ".join(n[:60] for n in names[:5]))
    tc = _as_dict(m.get("test_config"))
    if tc:
        lines += ["", "## Test configuration", ""]
        for name, hits in tc.items():
            lines.append(f"- `{name}`: " + " · ".join(h[:80] for h in hits[:4]))
    os2 = _as_dict(m.get("other_suites"))
    if os2:
        lines += ["", "## Other test suites in this repository", ""]
        for kind, files in os2.items():
            n = len(files)
            sample = list(files.items())[:3]
            desc = "; ".join(
                f"`{os.path.basename(f)}`: " + (
                    ", ".join(v[:3]) if isinstance(v, list)
                    else ", ".join((v.get("tests") or v.get("keywords") or [])[:3]))
                for f, v in sample)
            lines.append(f"- **{kind}** — {n} files. {desc}")
    ct = _as_dict(m.get("contracts"))
    if any(ct.values()):
        lines += ["", "## Contracts, schemas and mocks", ""]
        for k, v in ct.items():
            if v:
                lines.append(f"- **{k}**: " + ", ".join(f"`{x}`" for x in v[:10])
                             + (f" … +{len(v)-10}" if len(v) > 10 else ""))
    cdet = _as_dict(m.get("contract_details"))
    if any(cdet.values()):
        lines += ["", "## What those contracts actually say", ""]
        if cdet.get("endpoints"):
            lines.append("- endpoints: " + ", ".join(cdet["endpoints"][:25]))
        if cdet.get("graphql"):
            lines.append("- GraphQL types: " + ", ".join(cdet["graphql"][:25]))
        if cdet.get("migration_tables"):
            lines.append("- tables created by migrations: " + "; ".join(cdet["migration_tables"][:10]))
        if cdet.get("i18n_keys"):
            lines.append(f"- {len(cdet['i18n_keys'])} i18n keys, e.g. " + ", ".join(cdet["i18n_keys"][:12]))
        if cdet.get("flags"):
            lines.append("- feature flags: " + ", ".join(cdet["flags"][:15]))
    ctg = _as_dict(m.get("ci_tags"))
    if ctg:
        lines += ["", "## Tags each CI job runs", ""]
        for path, tg2 in list(ctg.items())[:8]:
            lines.append(f"- `{path}`: " + ", ".join(tg2))
    tg = _as_dict(m.get("tags"))
    if tg:
        lines += ["", "## Tags in use", "",
                  ", ".join(f"@{t} ({n})" for t, n in list(tg.items())[:30])]
    env = _as_dict(m.get("environment"))
    if env:
        lines += ["", "## Environment the suite reads (name — where it is set)", ""]
        for name, files in list(env.items())[:40]:
            lines.append(f"- `{name}` — " + ", ".join(f"`{f}`" for f in files[:3]))
    # The vocabulary a test author already has, whatever the framework calls it:
    # behave phrases, cucumber glue in any language, Robot keywords, pytest
    # fixtures, the page objects' public methods. The brief used to say "this
    # module declares 211 steps" and leave the 211 in a file beside it — so the
    # agents writing scenarios spent a hundred and forty-nine turns grepping for
    # a vocabulary they were entitled to be handed. An author needs the words,
    # not the word count.
    vocab: dict[str, list] = {}
    phrases = sorted({t for texts in (m.get("steps") or {}).values() for t in texts})
    if phrases:
        vocab["step phrases"] = phrases
    for kind, files in (m.get("other_suites") or {}).items():
        glue, cases = [], []
        for entry in files.values():
            if isinstance(entry, dict):
                glue += entry.get("step_glue") or entry.get("keywords") or []
                cases += entry.get("tests") or []
            elif isinstance(entry, list):
                cases += entry
        if glue:
            vocab[f"{kind} glue"] = sorted(set(glue))
        elif cases:
            vocab[f"{kind} cases"] = sorted(set(cases))
    fixtures = sorted({f for fs in (m.get("fixtures") or {}).values() for f in fs})
    if fixtures:
        vocab["pytest fixtures"] = fixtures
    api_methods = sorted({x for v in (m.get("public_api") or {}).values() for x in v})
    if api_methods:
        vocab["page object methods"] = api_methods

    if vocab:
        # No cap by default. The arithmetic is not close: the whole vocabulary is
        # about forty thousand tokens, read from cache on every turn after the
        # first, while a single turn spent grepping for a phrase re-reads the
        # entire context to ask the question and again to receive the answer.
        # Truncating this to save context is saving the cheap thing.
        cap = int(os.getenv("WAWE_VOCAB", "0")) or 10 ** 9
        total = sum(len(v) for v in vocab.values())
        lines += ["", f"## What you can already write with ({total})", "",
                  "The vocabulary this suite already has. Write from these; adding a "
                  "new one is a last resort, and the overlaps above say which ones "
                  "already say the same thing.", ""]
        share = max(1, cap // max(len(vocab), 1))
        for name, items in vocab.items():
            lines.append(f"**{name}** ({len(items)})")
            lines += [f"- {x}" for x in items[:share]]
            if len(items) > share:
                lines.append(f"- … {len(items) - share} more in framework_map.md")

            lines.append("")

    lines += ["", "## Step modules, largest first", ""]
    for path, texts in sorted(m["steps"].items(), key=lambda kv: -len(kv[1]))[:40]:
        sym = (_as_dict(m.get("symbols"))).get(path, {})
        extra = ""
        if sym.get("constants"):
            extra += " · consts: " + ", ".join(sym["constants"][:6])
        lines.append(f"- `{path}` — {len(texts)} steps{extra}")
    feats = sorted(m["features"].items(), key=lambda kv: -len(kv[1]["scenarios"]))[:12]
    if feats:
        lines += ["", "## Biggest feature files (scenario line numbers are in the full map)", ""]
        for path, f in feats:
            lines.append(f"- `{path}` — {len(f['scenarios'])} scenarios")
    return "\n".join(lines) + "\n"


def init_manifest(repo: str, m: dict) -> str:
    """Write a starter `.framework-map.json` from what was detected.

    The manifest is where a repository states what autodetection cannot know —
    its own vocabulary and its own rules — so it has to exist before anyone can
    fill it in. This writes the skeleton with the detected layers already in
    place and the sentences left for a human; it never overwrites one that is
    already there."""
    path = os.path.join(repo, ".framework-map.json")
    if os.path.exists(path):
        return f"{path} exists, left alone"
    skeleton = {
        "name": os.path.basename(os.path.abspath(repo)),
        "purpose": "TODO: one sentence on what this suite tests.",
        "layers": dict(_as_dict(m.get("layers"))),
        "product_src": _product_roots(),
        "entry_points": {k: "TODO: what this runs"
                         for k in list((_as_dict(m.get("entry_points"))).keys())[:6]},
        "conventions": ["TODO: the rules a newcomer must not break."],
        "notes": "",
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(skeleton, fh, indent=2, ensure_ascii=False)
    return f"wrote {path}"




def propose_docs(repo: str, m: dict, apply: bool = False) -> list:
    """Offer the repository the documentation it is missing.

    A map handed to an agent is a good turn; a repository that explains itself
    is a better one, because the explanation survives the run and a person can
    correct it. So: a README in every content directory that has none, a
    manifest stating the vocabulary autodetection had to guess, an agent file
    carrying the brief, and an architecture page assembled from what was found.

    Nothing is invented — every line comes from the tree — and nothing is
    overwritten. Without `apply` this only says what it would write, because a
    tool that edits a repository it was asked to read is a tool nobody runs
    twice.
    """
    try:
        from . import readmes as _readmes
    except ImportError:  # run as a plain file, with no package around it
        import readmes as _readmes  # type: ignore[no-redef]

    planned = []

    for base, dirs, _files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        target = os.path.join(base, "README.md")
        if os.path.exists(target):
            continue
        text = _readmes.describe(base)
        if not text:
            continue
        planned.append((os.path.relpath(target, repo), text,
                        "explains what this directory holds"))

    manifest = os.path.join(repo, ".framework-map.json")
    if not os.path.exists(manifest):
        planned.append((".framework-map.json",
                        json.dumps({
                            "name": os.path.basename(os.path.abspath(repo)),
                            "purpose": "TODO: one sentence on what this repository is.",
                            "layers": dict(m.get("layers") or {}),
                            "product_src": _product_roots(),
                            "conventions": ["TODO: the rules a newcomer must not break."],
                        }, indent=2, ensure_ascii=False) + "\n",
                        "lets this repository state its own vocabulary, which then "
                        "wins over anything guessed"))

    agent_file = os.path.join(repo, "AGENTS.md")
    if not os.path.exists(agent_file):
        # A pointer, not the brief. Whatever goes in this file goes in the
        # prompt of every session in this repository, on every turn of it.
        planned.append(("AGENTS.md",
                        "<!-- where-are-we:start -->\n"
                        + pointer(os.path.join(os.getenv("RUN_DIR", "."),
                                               "framework_map.md"))
                        + "<!-- where-are-we:end -->\n",
                        "a pointer to the map, where every agent harness already "
                        "looks — the map itself stays on disk"))

    arch = os.path.join(repo, "docs", "ARCHITECTURE.md")
    if not os.path.exists(arch):
        parts = ["# Architecture", "",
                 "Assembled from the tree by `where-are-we`. Correct it freely: "
                 "the sections below are derived, the sentences are yours.", ""]
        if m.get("languages"):
            parts += ["## Made of", "",
                      ", ".join(f"{k} ({v})" for k, v in list(m["languages"].items())[:10]), ""]
        if m.get("layers"):
            parts += ["## Layers", ""] + [f"- **{k}** — {v}" for k, v in m["layers"].items()] + [""]
        if m.get("entry"):
            parts += ["## Entry points", ""] + \
                [f"- {k}: {', '.join(str(x)[:60] for x in v[:6])}"
                 for k, v in list(m["entry"].items())[:8]] + [""]
        if m.get("routes_served"):
            parts += ["## HTTP surface", ""] + [f"- {r}" for r in m["routes_served"][:30]] + [""]
        if m.get("models"):
            parts += ["## Data model", ""] + \
                [f"- `{k}`: {', '.join(v[:10])}" for k, v in list(m["models"].items())[:15]] + [""]
        if m.get("import_graph"):
            parts += ["## How the packages depend on each other", ""] + \
                [f"- `{k}` → {', '.join(v)}" for k, v in m["import_graph"].items()] + [""]
        planned.append(("docs/ARCHITECTURE.md", "\n".join(parts),
                        "one page a person can read before touching anything"))

    if apply:
        for rel, text, _why in planned:
            path = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    return planned


def install_hook(repo: str, kind: str, product: str, out: str, agent_file: str) -> str:
    """Wire the map into something that already runs, so nobody has to remember it.

    git: post-checkout, post-merge and post-commit — the three moments the tree
    becomes something other than what the map describes. The command is the
    cheap one: it exits immediately when the repository has not moved.

    agent: a SessionStart hook for Claude Code, and the same command works as a
    task in any other harness — it writes the brief into the agent file, so the
    first turn of a session already knows where it is.
    """
    cmd = ["where-are-we", "--repo", repo]
    if product:
        cmd += ["--product", product]
    if out:
        cmd += ["--out", out]
    if agent_file:
        cmd += ["--agent-file", agent_file]
    line = " ".join(cmd) + " --quiet || true"

    if kind == "git":
        hooks = os.path.join(repo, ".git", "hooks")
        if not os.path.isdir(hooks):
            return f"{hooks} does not exist — is {repo} a git repository?"
        written = []
        for name in ("post-checkout", "post-merge", "post-commit"):
            path = os.path.join(hooks, name)
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

    settings = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(settings, encoding="utf-8") as fh:
            conf = json.load(fh)
    except (OSError, ValueError):
        conf = {}
    entries = conf.setdefault("hooks", {}).setdefault("SessionStart", [])
    if any("where-are-we" in h.get("command", "")
           for e in entries for h in e.get("hooks", [])):
        return "already installed in ~/.claude/settings.json"
    entries.append({"hooks": [{"type": "command", "command": line}]})
    os.makedirs(os.path.dirname(settings), exist_ok=True)
    with open(settings, "w", encoding="utf-8") as fh:
        json.dump(conf, fh, indent=2)
    return f"installed in {settings} (SessionStart)"


# What may go in a prompt, in bytes. Not a preference: a prompt is re-sent in
# full on every turn of a session, so anything put there is paid for on every
# turn whether it is read or not. Measured on one real run — the brief inlined
# whole, 253 KB, one agent taking 424 turns — the map alone came to 27.4 million
# tokens re-sent, a quarter of everything that run consumed, and it emptied a
# five-hour allowance in seventy-four minutes.
#
# So this project answers a prompt with a pointer and keeps the map on disk. The
# number is small on purpose: it is a signpost, and a signpost the size of the
# town is a town.
POINTER_MAX = int(os.getenv("WAWE_POINTER_MAX", "4000"))


def pointer(map_path: str, brief_path: str = "") -> str:
    """What goes in a prompt: where the map is, what is in it, how to ask it.

    The map is generated so nobody searches the repository blind. Putting the map
    itself in the prompt fixes the blindness and creates a worse bill, because
    the prompt is charged per turn and the map is read on a few of them. The
    sections are named because an agent that cannot see that a section exists
    goes back to grepping the repository — which is the thing this was built to
    end.
    """
    try:
        heads = [h[3:].strip() for h in map_heads(map_path)]
        size = os.path.getsize(map_path) // 1024
    except OSError as exc:
        return f"(no framework map: {exc})"

    lines = [
        f"## The framework map",
        "",
        f"`{map_path}` ({size} KB) is a generated map of this suite and the "
        "product it tests. It is on disk on purpose: read from it, do not carry "
        "it. Ask it before grepping the repository — it already knows.",
        "",
        f"    where-are-we --out {os.path.dirname(map_path) or '.'} --ask \"the words you need\"",
        "",
        "That prints only the rows that mention those words, whole, and says how much "
        "of each section it left out. "
        f"`--sections` lists what is in it. `grep` on `{map_path}` works too; "
        "reading the whole file does not — it lands in every message after it.",
        "",
        "It has these sections:",
        "",
    ]
    for h in heads:
        line = f"- {h}"
        if sum(len(x) + 1 for x in lines) + len(line) > POINTER_MAX:
            lines.append(f"- … and {len(heads) - (len(lines) - 8)} more; "
                         "`--sections` lists them all")
            break
        lines.append(line)
    if brief_path:
        lines += ["", f"A shorter brief of the same thing is `{brief_path}`."]
    return "\n".join(lines) + "\n"


def _definitions_for(map_path: str, terms: list[str]) -> list[str]:
    """Exact places, from the map's own index of what was defined where.

    Answered before any prose, because this is the question actually being
    asked. A scenario author looking for `def ad_product_shows` wants a file and
    a line; told which module it lives in, they grep the module. Over one run
    that was forty hand searches against three questions to the map.
    """
    path = os.path.join(os.path.dirname(map_path) or ".", "framework_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            defs = (json.load(fh) or {}).get("definitions") or {}
    except (OSError, ValueError):
        return []
    hits = []
    for name, where in defs.items():
        low = name.lower()
        if all(t in low for t in terms) or any(t == low for t in terms):
            hits.append(f"- `{name}` — {where}")
    return sorted(hits)[:40]


def meaning_tail(out_dir: str, words: str, already: str, k: int = 4,
                 room: int = 5000) -> str:
    """The 'Related by meaning' section, deduplicated against an answer
    already built by keywords. Empty string when there is no index, no
    library, or nothing new to add - the keyword answer stands alone."""
    try:
        from . import semantic as _sem
    except ImportError:  # run as a plain file, with no package around it
        import semantic as _sem  # type: ignore[no-redef]
    hits = _sem.search(out_dir, words, k=k + 2)
    kept = [h for h in hits if h["title"] not in already][:k]
    if not kept:
        return ""
    out = "\n\n## Related by meaning\n"
    for h in kept:
        piece = (f"\n**{h['title']}** ({h['source']})\n"
                 + h["text"][:1200] + "\n")
        if len(out) + len(piece) > room:
            break
        out += piece
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="framework_map",
        description="Index a test framework into a map an agent can read: layers, "
                    "entry points, public API, steps, features, fixtures, env, CI, "
                    "duplicates, dead code and the product under test.",
        epilog="Examples:\n"
               "  framework_map.py --repo ~/work/my-suite --out /tmp/map\n"
               "  framework_map.py --repo . --product ../my-app/src --out .\n"
               "  framework_map.py --repo . --init      # write a starter .framework-map.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.getenv("AGENT_REPO", "/work"),
                    help="the test repository to index (default: $AGENT_REPO or /work)")
    ap.add_argument("--out", default=os.getenv("RUN_DIR", "."),
                    help="where to write framework_map.{json,md} and the brief "
                         "(default: $RUN_DIR or the current directory)")
    ap.add_argument("--product", default=os.getenv("PRODUCT_SRC", ""),
                    help="source roots of the application under test, comma separated; "
                         "without it, a test suite tries its sibling directories; a plain code repository does not; 'none' switches the guess off")
    ap.add_argument("--rules", default=os.getenv("RULES_REPO", ""),
                    help="a corpus of rules to list by name")
    ap.add_argument("--runs-api", default=os.getenv("RUNS_API_READ", ""),
                    help="read endpoint of a runs database, to carry what earlier runs concluded")
    ap.add_argument("--init", action="store_true",
                    help="write a starter .framework-map.json into the repository and exit")
    ap.add_argument("--agent-file", default="",
                    help="also write the brief into a file an agent reads on its own: "
                         "AGENTS.md, CLAUDE.md, .cursorrules, .github/copilot-instructions.md — "
                         "the map is written between markers, so anything else in the file survives")
    ap.add_argument("--install-hook", choices=["git", "agent"], default="",
                    help="wire the map into something that already runs: git "
                         "hooks (post-checkout, post-merge, post-commit), or a "
                         "SessionStart hook for an agent harness")
    ap.add_argument("--for", dest="audience", default="",
                    choices=["author", "coder"],
                    help="who the brief is for: author writes scenarios and needs the "
                         "vocabulary in full; coder edits the code behind them and needs "
                         "the layers, the public API and the overlaps, not fourteen "
                         "hundred phrases in its context window")
    ap.add_argument("--only", default="",
                    help="comma separated section titles (substring match) to keep "
                         "in the brief — everything else is left in the full map")
    ap.add_argument("--skip", default="",
                    help="comma separated section titles to drop from the brief")
    ap.add_argument("--max-lines", type=int, default=0,
                    help="cap the brief at this many lines; the map itself is untouched")
    ap.add_argument("--diff", action="store_true",
                    help="print what changed since the map already in --out, and exit")
    ap.add_argument("--also", default="",
                    help="other repositories to fold into the same map, comma separated")
    ap.add_argument("--docs", nargs="?", const="plan", choices=["plan", "write"],
                    help="offer the repository the documentation it lacks — a README in "
                         "every content directory, a manifest, an agent file and an "
                         "architecture page. Without an argument it only says what it "
                         "would write; 'write' creates them, and never overwrites")
    ap.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                    help="rebuild whenever the tree moves, checking every SECONDS")
    ap.add_argument("--html", action="store_true",
                    help="also write framework_map.html — the brief, readable in a browser")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when the existing map still matches the "
                         "repository (by default a map is built when it is missing "
                         "or the repository has moved, and skipped otherwise)")
    ap.add_argument("--quiet", action="store_true", help="no summary line")
    ap.add_argument("--ask", default="", metavar="WORDS",
                    help="answer from an existing map instead of building one: "
                         "print the rows that mention these words, whole, with a "
                         "count of what was left out, and nothing else. Reads "
                         "framework_map.md under --out.")
    ap.add_argument("--specs", default=os.getenv("SPEC_ROOTS", ""),
                    help="ticket keys to map, comma separated: the tracker walked "
                         "once into spec_map.{json,md} so no session has to ask it "
                         "again")
    ap.add_argument("--spec-cmd", default=os.getenv("SPEC_FETCH_CMD", ""),
                    help="how to fetch one ticket as JSON; {key} is substituted. "
                         "This tool knows no tracker — the caller supplies the "
                         "source, as with everything else here")
    ap.add_argument("--spec-depth", type=int, default=0,
                    help="how many hops from the roots to follow (default 2)")
    ap.add_argument("--spec-limit", type=int, default=0,
                    help="how many tickets to fetch at most (default 60). A "
                         "tracker is a graph and a graph will happily hand over a "
                         "thousand; whatever is left out is named in the map")
    ap.add_argument("--mcp", action="store_true",
                    help="serve the map over MCP on stdin/stdout instead of "
                         "answering once and exiting. Same index, same answers — "
                         "asked as a tool call rather than through a shell, so "
                         "the question and its answer do not land in the "
                         "conversation and get re-read on every turn after")
    ap.add_argument("--pointer", action="store_true",
                    help="print what belongs in a prompt: where the map is, what "
                         "sections it has, and how to ask it — never the map itself")
    ap.add_argument("--sections", action="store_true",
                    help="list the section headings of an existing map and exit")
    ap.add_argument("--corpus", action="append", default=[], metavar="NAME=PATH",
                    help="an extra corpus for the semantic index: a markdown "
                         "file or a directory of md/mdc/txt (a rules corpus, a "
                         "runbook). Repeatable. Indexed beside the map when the "
                         "optional [semantic] extra is installed; ignored, "
                         "loudly, when it is not")
    ap.add_argument("--no-semantic", action="store_true",
                    help="skip building the semantic index even when fastembed "
                         "is available")
    args = ap.parse_args()

    # Answering from a map that already exists needs none of what follows: no
    # repository walk, no product roots, no config. It is a read.
    if args.mcp:
        try:
            from . import mcp as _mcp
        except ImportError:  # run as a plain file, with no package around it
            import mcp as _mcp  # type: ignore[no-redef]
        return _mcp.serve(os.path.abspath(args.out))

    if args.specs:
        if not args.spec_cmd:
            print("--specs needs --spec-cmd: this tool does not know your tracker",
                  file=sys.stderr)
            return 2
        out_dir = os.path.abspath(args.out)
        os.makedirs(out_dir, exist_ok=True)
        roots = [k.strip() for k in args.specs.split(",") if k.strip()]
        say = None if args.quiet else (lambda line: print(line, flush=True))
        spec = specs.walk(args.spec_cmd, roots,
                          depth=args.spec_depth or specs.DEFAULT_DEPTH,
                          limit=args.spec_limit or specs.DEFAULT_LIMIT, say=say)
        with open(os.path.join(out_dir, "spec_map.json"), "w", encoding="utf-8") as fh:
            json.dump(spec, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(out_dir, "spec_map.md"), "w", encoding="utf-8") as fh:
            fh.write(specs.digest(spec))
        if not args.quiet:
            print(f"spec map: {len(spec['tickets'])} ticket(s) -> "
                  f"{os.path.join(out_dir, 'spec_map.md')}")
        return 0

    if args.sections or args.ask or args.pointer:
        out_dir = os.path.abspath(args.out)
        map_path = os.path.join(out_dir, "framework_map.md")
        # Both maps answer, because a question about this work is as likely to be
        # about what was asked for as about where the code is.
        spec_path = os.path.join(out_dir, "spec_map.md")
        if args.pointer:
            print(pointer(map_path), end="")
            return 0
        if args.sections:
            try:
                print("\n".join(map_heads(map_path)))
            except OSError as exc:
                print(f"no map at {map_path}: {exc}", file=sys.stderr)
                return 1
            return 0
        answer = ask(map_path, args.ask)
        if os.path.exists(spec_path):
            answer += "\n\n" + ask(spec_path, args.ask)
        answer += meaning_tail(out_dir, args.ask, answer)
        print(answer)
        return 0

    # The rest of the module reads these through the environment, which is also
    # how the pipeline passes them; the flags simply set them first, so the
    # script is usable by hand on any repository without knowing that.
    os.environ["AGENT_REPO"] = repo = os.path.abspath(args.repo)
    # A project states its own invocation once, in .wawe.toml; the flags win.
    conf = _config(repo)
    if not args.product and conf.get("product"):
        args.product = ",".join(conf["product"]) if isinstance(conf["product"], list) \
            else conf["product"]
    if args.out in (".", os.getenv("RUN_DIR", ".")) and conf.get("out"):
        args.out = conf["out"]
    if not args.agent_file and conf.get("agent_file"):
        args.agent_file = conf["agent_file"]
    if not args.only and conf.get("only"):
        args.only = ",".join(conf["only"]) if isinstance(conf["only"], list) else conf["only"]
    if not args.skip and conf.get("skip"):
        args.skip = ",".join(conf["skip"]) if isinstance(conf["skip"], list) else conf["skip"]
    if not args.max_lines and conf.get("max_lines"):
        args.max_lines = int(conf["max_lines"])
    if args.product:
        os.environ["PRODUCT_SRC"] = args.product
    if args.rules:
        os.environ["RULES_REPO"] = args.rules
    if args.runs_api:
        os.environ["RUNS_API_READ"] = args.runs_api
    out_dir = args.out

    if not os.path.isdir(repo):
        print(f"framework_map: {repo} is not a directory", file=sys.stderr)
        return 2

    # Build when there is no map, or when the repository has moved since the one
    # that is there was built. Otherwise the map on disk is the map that would
    # be built, and a second walk of the tree buys nothing.
    if args.docs:
        m2 = build(repo)
        planned = propose_docs(repo, m2, apply=(args.docs == "write"))
        if not planned:
            print("nothing to add: every directory already explains itself")
            return 0
        verb = "wrote" if args.docs == "write" else "would write"
        for rel, text, why in planned:
            print(f"{verb} {rel} ({len(text.splitlines())} lines) — {why}")
        if args.docs != "write":
            print(f"\n{len(planned)} files. Run with --docs write to create them; "
                  "existing files are never touched.")
        return 0

    if args.watch:
        import time as _t
        last = ""
        print(f"watching {repo}, every {args.watch}s — Ctrl-C to stop")
        while True:
            now_fp = _fingerprint(repo)
            if now_fp != last:
                last = now_fp
                m2 = build(repo)
                m2["fingerprint"] = now_fp
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, "framework_map.json"), "w",
                          encoding="utf-8") as fh:
                    json.dump(redact(m2), fh, indent=2)
                with open(os.path.join(out_dir, "framework_map_brief.md"), "w",
                          encoding="utf-8") as fh:
                    fh.write(brief(m2))
                c2 = m2["counts"]
                print(f"rebuilt: {c2['steps']} steps, {c2['scenarios']} scenarios")
            _t.sleep(args.watch)

    if args.install_hook:
        print(install_hook(repo, args.install_hook, args.product, args.out,
                           args.agent_file))
        return 0

    stamp_now = _fingerprint(repo)
    existing = os.path.join(out_dir, "framework_map.json")
    if not args.force and not args.init and os.path.exists(existing):
        try:
            with open(existing, encoding="utf-8") as fh:
                prev = json.load(fh)
        except (OSError, ValueError):
            prev = {}
        if prev.get("fingerprint") == stamp_now:
            if not args.quiet:
                c = (prev.get("counts") or {})
                print(f"framework map: unchanged since it was built "
                      f"({c.get('steps', 0)} steps, {c.get('scenarios', 0)} scenarios) "
                      f"-> {out_dir}/framework_map.md")
            return 0

    if args.diff:
        try:
            with open(existing, encoding="utf-8") as fh:
                prev = json.load(fh)
        except (OSError, ValueError):
            print("no previous map in " + out_dir)
            return 1
        now = build(repo)
        changed = []
        for key in sorted((set(prev) | set(now)) - {"fingerprint", "repo"}):
            a, b = prev.get(key), now.get(key)
            if a == b:
                continue
            if isinstance(a, dict) and isinstance(b, dict):
                added = sorted(set(b) - set(a))[:8]
                gone = sorted(set(a) - set(b))[:8]
                bits = []
                if added:
                    bits.append("+ " + ", ".join(str(x) for x in added))
                if gone:
                    bits.append("- " + ", ".join(str(x) for x in gone))
                changed.append(f"{key}: " + ("; ".join(bits) if bits else "contents changed"))
            elif isinstance(a, list) and isinstance(b, list):
                changed.append(f"{key}: {len(a)} → {len(b)}")
            else:
                changed.append(f"{key}: {str(a)[:40]} → {str(b)[:40]}")
        print("\n".join(changed[:60]) or "nothing changed")
        return 0

    # More than one repository, one map: a service and its client, or a monorepo
    # split across checkouts, are one system to whoever has to work on them.
    repos = [repo] + [os.path.abspath(x) for x in
                      (args.also.split(",") if args.also else []) if x]
    m = build(repo)
    if len(repos) > 1:
        m["also"] = {}
        for extra in repos[1:]:
            if not os.path.isdir(extra):
                continue
            os.environ["AGENT_REPO"] = extra
            _WALK_CACHE.clear()
            _IGNORE_CACHE.clear()
            m["also"][os.path.basename(extra)] = build(extra)
        os.environ["AGENT_REPO"] = repo
        # The name index is a copy taken when the first root finished; the line
        # index is the live dict. So a second root's lines were searchable and
        # its names were not, and a question about a name defined in it came
        # back "nothing in the map defines this" — the one answer that sends a
        # reader off to grep with confidence.
        m["definitions"] = dict(sorted(DEFINITIONS.items()))
        m["indexed"] = dict(sorted(INDEXED.items()))
    m = redact(m)
    m["fingerprint"] = stamp_now
    if args.init:
        print(init_manifest(repo, m))
        return 0
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "framework_map.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2)
    with open(os.path.join(out_dir, "framework_map.md"), "w", encoding="utf-8") as fh:
        fh.write(digest(m))
    text = for_audience(brief(m), args.audience)

    if args.only or args.skip:
        keep = [x.strip().lower() for x in args.only.split(",") if x.strip()]
        drop = [x.strip().lower() for x in args.skip.split(",") if x.strip()]
        out_lines, current_ok = [], True
        for line in text.splitlines():
            if line.startswith("## "):
                title = line[3:].lower()
                current_ok = (not keep or any(k in title for k in keep)) \
                    and not any(d in title for d in drop)
            elif line.startswith("# "):
                current_ok = True
            if current_ok:
                out_lines.append(line)
        text = "\n".join(out_lines) + "\n"
    if args.max_lines and text.count("\n") > args.max_lines:
        text = _cap_sections(text, args.max_lines)
    with open(os.path.join(out_dir, "framework_map_brief.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    if args.html:
        # Deliberately one file with no assets: it gets opened from a terminal,
        # not served.
        body_html = []
        for line in text.splitlines():
            if line.startswith("## "):
                body_html.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("# "):
                body_html.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("- "):
                body_html.append(f"<li>{line[2:]}</li>")
            elif line.strip():
                body_html.append(f"<p>{line}</p>")
        html = ("<!doctype html><meta charset=utf-8><title>where are we</title>"
                "<style>body{max-width:60rem;margin:3rem auto;padding:0 1rem;"
                "font:15px/1.6 ui-sans-serif,system-ui,sans-serif;color:#111}"
                "h1{font-size:1.7rem}h2{font-size:1.05rem;margin-top:2.2rem;"
                "border-bottom:1px solid #ddd;padding-bottom:.3rem}"
                "li{margin:.15rem 0}code{background:#f4f4f4;padding:0 .2em;border-radius:3px}"
                "@media(prefers-color-scheme:dark){body{background:#111;color:#eee}"
                "h2{border-color:#333}code{background:#222}}</style>"
                + "\n".join(body_html))
        with open(os.path.join(out_dir, "framework_map.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
    if args.agent_file:
        # Between markers, because these files are shared: whatever a human or
        # another tool put there is not this tool's to delete.
        start, end = "<!-- where-are-we:start -->", "<!-- where-are-we:end -->"
        block = f"{start}\n{text}{end}\n"
        try:
            with open(args.agent_file, encoding="utf-8") as fh:
                cur = fh.read()
        except OSError:
            cur = ""
        if start in cur and end in cur:
            cur = re.sub(re.escape(start) + r".*?" + re.escape(end), block.rstrip("\n"),
                         cur, flags=re.S)
        else:
            cur = (cur.rstrip() + "\n\n" if cur.strip() else "") + block
        os.makedirs(os.path.dirname(os.path.abspath(args.agent_file)), exist_ok=True)
        with open(args.agent_file, "w", encoding="utf-8") as fh:
            fh.write(cur)

    # The semantic index, built from the map just written plus whatever
    # corpora the caller named. Free when nothing changed (content hash),
    # absent without complaint when the [semantic] extra is not installed -
    # the keyword ask stands alone then, exactly as it always did.
    sem_line = ""
    if not args.no_semantic:
        try:
            from . import semantic as _sem
        except ImportError:  # run as a plain file, with no package around it
            import semantic as _sem  # type: ignore[no-redef]
        corpora = [("map", os.path.join(out_dir, "framework_map.md"))]
        spec_md = os.path.join(out_dir, "spec_map.md")
        if os.path.exists(spec_md):
            corpora.append(("specs", spec_md))
        for spec in args.corpus:
            name, _eq, path = spec.partition("=")
            if not _eq:
                name, path = os.path.basename(spec.rstrip("/")), spec
            corpora.append((name, path))
        sem_line = _sem.build_index(out_dir, corpora)

    c = m["counts"]
    if args.quiet:
        return 0
    print(f"framework map: {c['step_modules']} step modules, {c['steps']} steps, "
          f"{c['features']} features, {c['scenarios']} scenarios "
          f"-> {out_dir}/framework_map.md")
    if sem_line:
        print(sem_line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
