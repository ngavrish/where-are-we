"""What a file declares, and on which line: the name index the map is built on.

A question about a name is a question about a file and a line, so every file
the walk reads passes through here once. The regex table below is the portable
answer; tree-sitter is used instead wherever a grammar is installed.
"""

import ast
import json
import os
import re

from .state import DEFINITIONS, INDEXED, LINES
from .walk import _cached, _slurp


STEP_DECORATORS = {"step", "given", "when", "then"}


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
    ".rs": (
        r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait|type|const|static|mod)\s+([A-Za-z_]\w*)",
    ),
    ".kt": (
        r"^\s*(?:(?:public|private|internal|open|data|sealed|abstract|suspend|override|inline)\s+)*(?:fun|class|object|interface|val|var)\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)",
    ),
    ".cs": (
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|async|override|virtual|readonly)\s+)*(?:class|interface|struct|enum|record|delegate)\s+([A-Za-z_]\w*)",
        r"^\s*(?:(?:public|private|protected|internal|static|abstract|async|override|virtual)\s+)+[\w<>\[\],.?]+\s+([A-Za-z_]\w*)\s*\(",
    ),
    ".rb": (
        r"^\s*(?:def\s+(?:self\.)?|class\s+|module\s+)([A-Za-z_]\w*[?!=]?)",
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


# Extensions where a tree-sitter grammar can stand in for the regex table,
# keyed to the grammar name `_tree_sitter`/`_ts_symbols` expect. Only the four
# this task added: widening this to languages the regex table already gets
# right (Python, TypeScript) is a separate change, not this one.
TS_LANG_BY_EXT = {".rs": "rust", ".kt": "kotlin", ".cs": "c_sharp", ".rb": "ruby"}


def _regex_declared_names(body: str, ext: str) -> list:
    """(name, 1-based line) pairs `body` declares, by the patterns for `ext`.

    The matching rules `index_declarations` and `declarations_in` both need:
    the file-reading and bookkeeping around it differ (one fills the shared
    DEFINITIONS/LINES tables, the other returns a plain list), the pattern
    walk over the text does not. Also the fallback when no tree-sitter parser
    is installed, or the file's language has none: the CI path, and the one
    every regex in this table is written and checked against.
    """
    patterns = DECLARATIONS.get(ext) or DECLARATIONS["*"]
    compiled = [re.compile(pattern) for pattern in patterns]
    out = []
    # Line by line, and the number is the loop counter.
    #
    # Computed from a match offset instead, it was wrong for one name in nine:
    # the offset counts characters in a string that has already had undecodable
    # bytes replaced, and a multi-line pattern can start a match on the line
    # before the name. Checked against the files afterwards, eleven of a hundred
    # and twenty pointed at a blank line — which is worse than not indexing at
    # all, because the reader opens the file, sees nothing, and stops trusting
    # the map.
    for number, text in enumerate(body.splitlines(), 1):
        for pattern in compiled:
            found = pattern.match(text) or pattern.search(text)
            if not found:
                continue
            name = found.group(1).strip()
            if len(name) >= 2 and name in text:
                out.append((name, number))
            break
    return out


def _line_for_name(lines: list, name: str, regex_hits: list) -> int:
    """The 1-based line to credit `name` to.

    First choice is the line the regex table itself would have picked for
    this exact name, so a name tree-sitter and the regex both see keeps the
    same line either way. Failing that (tree-sitter found something the
    line-start regex missed, typically a multi-line signature), the first
    line that mentions the name as a whole word; failing even that, the top
    of the file rather than nothing.
    """
    for hit_name, line in regex_hits:
        if hit_name == name:
            return line
    whole_word = re.compile(r"\b" + re.escape(name) + r"\b")
    for number, text in enumerate(lines, 1):
        if whole_word.search(text):
            return number
    return 1


def _declared_names(body: str, ext: str, path: str = "") -> list:
    """(name, 1-based line) pairs `body` (the text of `path`) declares.

    A tree-sitter parse tree where one is installed for `ext`'s language,
    since it gets exported/visibility and multi-line signatures right where a
    line-start regex cannot; the regex table otherwise, which is also what
    supplies the line number in both cases (see `_line_for_name`). Absent the
    optional parser this is exactly `_regex_declared_names`, byte for byte:
    the CI path never installs `tree-sitter-languages`, so it never takes the
    branch below.

    The regex pass is routed through `_cached`, keyed on `path`, the same as
    every other real parse in this file. `_ts_symbols` below caches itself on
    the same key; this one cannot, since it only has a path when a caller
    handed it one, so an empty `path` here just means "always recompute,
    never persist" rather than a crash.
    """
    regex_hits = _cached(path, f"regex_declared:{ext}",
                         lambda: _regex_declared_names(body, ext))
    ts_lang = TS_LANG_BY_EXT.get(ext)
    if not ts_lang or not path:
        return regex_hits
    if _tree_sitter(ts_lang) is None:
        return regex_hits
    ts_names = _ts_symbols(path, ts_lang)
    if not ts_names:
        return regex_hits
    lines = body.splitlines()
    seen = set()
    out = []
    for name in ts_names:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, _line_for_name(lines, name, regex_hits)))
    return out


def _read_for_declarations(path: str):
    """This file's text, or None for anything too large or not text.

    Shared by `index_declarations` and `declarations_in` so the size cap and
    the binary sniff are one rule, not two that can drift apart.
    """
    try:
        if os.path.getsize(path) > 2 * 1024 * 1024:
            return None  # a generated bundle is names nobody asks about, by the ton
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError:
        return None
    if "\x00" in body[:2048]:
        return None  # binary
    return body


def declarations_in(path: str) -> list:
    """Every name `path` declares, with its 1-based line, as (name, line).

    What `index_declarations` finds for one file, without the side effects on
    DEFINITIONS/LINES/INDEXED: a caller that wants the names of a single file
    (a test, a future `--diff`) asks this instead of reading the shared maps
    and filtering them back down to one path.
    """
    ext = os.path.splitext(path)[1].lower()
    body = _read_for_declarations(path)
    if body is None:
        return []
    return _declared_names(body, ext, path)


def index_declarations(path: str, label: str = "") -> None:
    """Record every name this file declares, with the line it is declared on.

    Called for the suite and for the product alike. Without it the map could say
    which module a step lived in and nothing at all about the code under test —
    so an agent asking where a constant was defined was told it did not exist,
    and spent forty turns grepping for something the map had never looked for.
    """
    ext = os.path.splitext(path)[1].lower()
    body = _read_for_declarations(path)
    if body is None:
        return
    INDEXED[label or ext] = INDEXED.get(label or ext, 0) + 1
    index_lines(path, body)
    for name, number in _declared_names(body, ext, path):
        DEFINITIONS.setdefault(name, f"{path}:{number}")


def _step_texts(path: str) -> list[str]:
    """The step phrases a steps module declares, from its decorators."""
    def _parse():
        out: list[str] = []
        defs: list[tuple] = []
        try:
            tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
        except (OSError, SyntaxError):
            return {"texts": out, "defs": defs}
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
                    # An agent that has been told a phrase exists still has to
                    # find it, and finds it the only way it can: grep. Watched
                    # over one run, a scenario author ran forty searches by
                    # hand against three questions to the map, because the map
                    # answered "this step is in that module" and grep answers
                    # "line 214". Same question, and only one of the two
                    # answers ends the search.
                    defs.append((arg.value, f"{path}:{node.lineno}"))
                    defs.append((f"def {node.name}", f"{path}:{node.lineno}"))
        return {"texts": out, "defs": defs}

    result = _cached(path, "step_texts", _parse)
    for name, loc in result["defs"]:
        DEFINITIONS.setdefault(name, loc)
    return result["texts"]


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

    def _parse():
        try:
            tree = parser.parse(_slurp(path).encode())
        except Exception:  # noqa: BLE001
            return []
        wanted = {"function_declaration", "class_declaration", "method_definition",
                  "interface_declaration", "type_alias_declaration", "enum_declaration",
                  "lexical_declaration", "type_declaration", "func_declaration",
                  # rust
                  "function_item", "struct_item", "enum_item", "trait_item",
                  "const_item", "static_item", "mod_item", "type_item",
                  # kotlin (class_declaration also covers its "interface" spelling)
                  "object_declaration",
                  # c_sharp (class_declaration, interface_declaration and
                  # enum_declaration already listed above)
                  "struct_declaration", "record_declaration", "delegate_declaration",
                  "method_declaration",
                  # ruby
                  "method", "singleton_method", "class", "module"}
        # Languages with no export keyword: a top-level declaration is visible by
        # definition, so gating on `export_statement` here would just drop every
        # name in every file.
        no_export_keyword = {"go", "rust", "kotlin", "c_sharp", "ruby"}
        out = []

        def walk(node, exported=False):
            if node.type == "export_statement":
                exported = True
            if node.type in wanted:
                for child in node.children:
                    if child.type in ("identifier", "type_identifier",
                                       "property_identifier", "simple_identifier",
                                       "constant"):
                        name = child.text.decode(errors="replace")
                        if exported or lang in no_export_keyword:
                            out.append(name)
                        break
            for child in node.children:
                walk(child, exported)

        walk(tree.root_node)
        # No cap: the regex path this stands in for has none either, and a file
        # with more than a handful of declarations silently losing the ones past
        # some count is exactly the "indexed here, not there" gap this project
        # exists to close. Whatever bounds the reader sees are bounds `brief()`
        # applies once, in one place, when it renders the table for a prompt;
        # `framework_map.json` and `declarations_in` stay complete.
        return sorted(set(out))

    return _cached(path, f"ts:{lang}", _parse)
