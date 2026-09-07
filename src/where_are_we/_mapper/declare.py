"""What a file declares, and on which line: the name index the map is built on.

A question about a name is a question about a file and a line, so every file
the walk reads passes through here once. The regex table below is the portable
answer; tree-sitter is used instead wherever a grammar is installed.
"""

import ast
import codecs
import json
import os
import re

from .state import DEFINITIONS, INDEXED, LINES, SPANS
from .walk import SLURP_LIMIT, _cached, _slurp

try:
    from ..ask import _encode
except ImportError:  # run as a plain file, with no package around it
    from ask import _encode  # type: ignore[no-redef]


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


def find_text(out_dir: str, phrase: str, limit: int = 40,
              offset: int = 0, room: int = 0) -> str:
    """Every line holding this phrase, with its file and line number.

    Reads the lines the mapper kept. Case-insensitive, because nobody
    remembers the case of a label they saw once.

    `offset` skips that many of the ranked hits before printing, which is how
    `more:find:` continues an answer this cut short. The ranking and the
    per-file cap below are recomputed from the map on disk both times, so the
    hit at a given offset is the same hit on both calls as long as the map is.

    `room`, when given, is a ceiling in characters as well as `limit`'s ceiling
    in hits, and the block comes back no longer than it. `more()` passes it:
    what a handle fetches lands in the conversation exactly like the answer
    that printed it, and forty hits of a hundred and sixty characters is 1,892
    characters against a caller that asked for 1,500.
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
    # The per-file cap and the ranking above make one fixed list of hits,
    # ranked and thinned the same way on every call over the same map. That
    # list, not this answer, is what an offset counts into: `taken` is how far
    # into it we are when the limit stops us, and a `more:find:` handle
    # carries that number so the next call starts on the next hit.
    per_file, capped = {}, []
    for score, path, number, text in hits:
        if per_file.get(path, 0) >= _PER_FILE_CAP:
            continue
        per_file[path] = per_file.get(path, 0) + 1
        capped.append(f"- {path}:{number}: {text}")
    if offset >= len(capped):
        return (f"no such handle in this map: {len(capped)} lines hold "
                f"{phrase!r} once no one file may take the whole answer, "
                f"and this handle asks for number {offset + 1}")
    def block(n: int, form: int = 0) -> str:
        """`n` hits from `offset`, with the line that says what is left.

        `form` is what that line gives up as the room runs out: 0 is the
        sentence with the handle, 1 is the handle with a count in front of it,
        2 is the sentence with no handle at all. Same ladder as a section's
        tail and the "more sections match" note: the handle is the last thing
        to go, because it is the only part a reader can act on.
        """
        kept = capped[offset:offset + n]
        reached = offset + len(kept)
        if len(hits) <= reached:
            return "\n".join(kept)
        # Only when there is a next hit to hand over: the rest may all have
        # been the per-file cap's doing, and those are not reachable by asking
        # again, so a handle promising them would be a lie.
        handle = (f"more:find:{_encode(phrase)}:{reached}"
                  if reached < len(capped) else "")
        if form == 1 and handle:
            return "\n".join(kept) + f"\n… {len(hits) - reached} more ({handle})"
        shown = (f"these are the {len(kept)} that rank highest" if not offset
                 else f"these are {len(kept)} of them, from number {offset + 1}")
        suffix = f" ({handle})" if form == 0 and handle else ""
        return ("\n".join(kept)
                + f"\n… {len(hits)} lines hold it across {len(per_file)} files; "
                + shown + suffix)

    if not room:
        return block(limit)
    # Whole hits, from the front, while the finished block fits. A prefix and
    # not a best fit, because `capped` is already the ranking: taking a later,
    # shorter hit over the one in front of it would print the sixth-best line
    # and call it the fifth.
    most = min(limit, len(capped) - offset)
    for form in (0, 1, 2):
        for n in range(most, 0, -1):
            out = block(n, form)
            if len(out) <= room:
                return out
    return (f"no such handle in this map: hit {offset + 1} of {len(capped)} "
            f"and the line saying what is left do not fit in {room} "
            f"characters together")


# Extensions where a tree-sitter grammar can stand in for the regex table,
# keyed to the grammar name `_tree_sitter`/`_ts_symbols` expect. Only the four
# this task added: widening this to languages the regex table already gets
# right (Python, TypeScript) is a separate change, not this one.
TS_LANG_BY_EXT = {".rs": "rust", ".kt": "kotlin", ".cs": "c_sharp", ".rb": "ruby"}

# Extensions a grammar can supply an end line for, without standing in for the
# pattern table that finds the names. `eval.py` already loads these five for
# `--graph`, so the parser is there and `spans` was reporting `?` for the
# languages most of this tool's readers write in. Which names are declared,
# and on which line, does not move: only the end does, and only where the
# `precise` extra is installed. Widening `TS_LANG_BY_EXT` itself would change
# `definitions` for these languages between one install and another, which is
# a separate change and not this one.
TS_END_BY_EXT = {".ts": "typescript", ".tsx": "tsx", ".js": "javascript",
                 ".jsx": "javascript", ".mjs": "javascript",
                 ".cjs": "javascript", ".go": "go"}


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


def _line_for_name(lines: list, name: str, start: int, end: int = 0) -> int:
    """The 1-based line to credit a declaration spanning `start` to `end` to.

    A parse tree says where a declaration begins, which is not always where
    its name is written: tree-sitter-c-sharp hangs an attribute list under the
    declaration node, so `[Test]` on the line above is where `public void
    Charge()` starts, and a multi-line signature puts the name a line or two
    in. So the credited line is the first line of the declaration that holds
    the name as a whole word, and the declaration's own first line when none
    of them does, which is a start with no name in it rather than nothing.

    Bounded by the declaration, not by the file. Searching the whole file was
    what the first version did, and it credited a name to the first line that
    happened to mention it, which for a name declared twice was the first
    declaration both times.
    """
    whole_word = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name)
                            + r"(?![A-Za-z0-9_])")
    last = max(start, end or start)
    for number in range(start, min(last, len(lines)) + 1):
        if number >= 1 and whole_word.search(lines[number - 1]):
            return number
    return start


def _declared_names(body: str, ext: str, path: str = "") -> list:
    """(name, 1-based line) pairs `body` (the text of `path`) declares.

    The first two fields of `_declared_spans`, which is the one pass over a
    file this module makes: names, start lines, end lines and kinds are found
    together, cached together, and read apart here. They used to be two
    passes with two cache entries, and the second stored the first's answer
    again under another key.
    """
    return [(name, start) for name, start, _end, _kind
            in _spans_of(body, ext, path)]


# What word introduced a declaration, and what that makes it. The closed set of
# kinds is the values on the right; SCHEMA.md lists them beside the `spans` row.
#
# `static` is deliberately absent. It introduces a declaration in Rust and is
# only a modifier in C#, so taking it as the kind made `public static void
# Charge()` a constant. A word that means two things in two languages is worth
# less here than the fallbacks below, which read the shape of the line.
_KIND_BY_WORD = {
    "class": "class", "object": "class", "record": "class",
    "interface": "interface", "trait": "trait", "struct": "struct",
    "enum": "enum", "type": "type", "typedef": "type",
    "def": "function", "fn": "function", "func": "function",
    "function": "function", "fun": "function", "method": "function",
    "mod": "module", "module": "module", "namespace": "module",
    "package": "module",
    "const": "constant", "val": "constant",
    "let": "variable", "var": "variable",
    "scenario": "scenario", "feature": "feature",
}
_WORDS = re.compile(r"[A-Za-z_]+")
_CONSTANT_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def _kind_of(text: str, name: str) -> str:
    """What kind of thing this line declares, from the words before the name.

    The declaring keyword is the last word before the name, not the first word
    on the line that happens to be a keyword: every pattern in the table above
    puts the modifiers in front of it. Reading the whole line instead made
    `def check(type)` a type and `class Foo(type)` a type as well.

    Then two fallbacks, for the languages that name the kind after the name or
    not at all: a name immediately followed by an argument list is a function
    (`public static void Charge()`), and a name in screaming case is a
    constant. `name` is what is left, and is honest: something is declared
    here and the pattern that found it did not say what.
    """
    where = text.find(name)
    for word in reversed(_WORDS.findall(text[:where] if where > 0 else "")):
        kind = _KIND_BY_WORD.get(word.lower())
        if kind:
            return kind
    if where >= 0 and text[where + len(name):].lstrip().startswith("("):
        return "function"
    return "constant" if _CONSTANT_NAME.match(name) else "name"


def _py_spans(path: str) -> dict:
    """`{"<name>\\x1e<line>": [end line, kind]}` for a Python file, from `ast`.

    `end_lineno` is stdlib and exact, which no line-start regex can be: it is
    the last line of the whole definition, decorators, nested bodies and all.
    Keyed by the line the name is declared on, because that is the line the
    regex table credits it to, so a declaration both of them see is one span
    rather than two.

    Module-level screaming-case assignments only, matching the `.py` row of
    the table above: a constant assigned inside a function is not what that
    pattern finds, and a span for a name `definitions` does not hold would be
    a home for a name nothing else in the map mentions.

    A file over `AST_LIMIT` is handed to the parser as a prefix, so the last
    thing in that prefix is a declaration this parse cannot see the end of:
    it ends where the cut is, not where the file says. Every declaration
    reaching the deepest line the tree holds gets no end at all in that case.
    A wrong end is worse than none, and this is the one place the parser can
    produce one.
    """
    def _compute():
        # Imported here rather than at the top of the file: `build` imports
        # this module, so a module-level import back would be circular.
        try:
            from .build import _parse_source
            from .walk import _slurp_source
        except ImportError:  # run as a plain file, with no package around it
            from build import _parse_source  # type: ignore[no-redef]
            from walk import _slurp_source  # type: ignore[no-redef]
        out: dict = {}
        tree = _parse_source(path)
        if tree is None:
            return out
        _text, was_cut = _slurp_source(path)
        deepest = 0
        for node in ast.walk(tree):
            deepest = max(deepest, getattr(node, "end_lineno", 0) or 0)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[f"{node.name}\x1e{node.lineno}"] = [node.end_lineno, "function"]
            elif isinstance(node, ast.ClassDef):
                out[f"{node.name}\x1e{node.lineno}"] = [node.end_lineno, "class"]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for target in targets:
                    if (isinstance(target, ast.Name) and target.col_offset == 0
                            and _CONSTANT_NAME.match(target.id)):
                        out[f"{target.id}\x1e{target.lineno}"] = [node.end_lineno,
                                                                  "constant"]
        if was_cut:
            for key, row in out.items():
                if row[0] >= deepest:
                    out[key] = [None, row[1]]
        return out

    return _cached(path, "py_spans", _compute)


def _declared_spans(body: str, ext: str, path: str = "") -> list:
    """`[name, start, end, kind]` for every declaration in `path`.

    One list, and the only pass over a file this module makes: `definitions`,
    `spans` and `declarations_in` are all read out of it, so they can never
    disagree about where a name is.

    Where a declaration comes from, best first. A tree-sitter parse tree is
    the whole answer for the languages `TS_LANG_BY_EXT` names: it knows the
    name, both ends and the kind, and it knows them for each of two
    declarations of one name in one file, which is the thing a table of
    line-start patterns cannot do. Everywhere else the pattern table finds the
    names and the start lines, and an end is added on top of them where
    something knows one: `ast` for Python, and a grammar for the languages in
    `TS_END_BY_EXT`, which are the ones this tool has a parser for but reads
    with patterns. What is left honestly reports no end at all: a pattern has
    seen the first line of a declaration and nothing that says where it stops.
    """
    ts_lang = TS_LANG_BY_EXT.get(ext)
    lines = body.splitlines()
    if ts_lang and path and _tree_sitter(ts_lang) is not None:
        rows = _ts_symbols(path, ts_lang)
        if rows:
            out = []
            for name, start, end, kind in rows:
                line = _line_for_name(lines, name, start, end or start)
                out.append([name, line,
                            end if end and end >= line else None,
                            kind or _kind_of(lines[line - 1]
                                             if 0 < line <= len(lines) else "",
                                             name)])
            return out
    pairs = _regex_declared_names(body, ext)
    exact = _py_spans(path) if path and ext in (".py", ".pyi") else {}
    from_tree: dict = {}
    end_lang = TS_END_BY_EXT.get(ext)
    if not exact and end_lang and path and _tree_sitter(end_lang) is not None:
        for row in _ts_symbols(path, end_lang):
            # By name and start line where the two passes agree, by name alone
            # where they do not: the pattern credited the declaration to a
            # line, and the grammar is only being asked how far it runs.
            from_tree.setdefault(f"{row[0]}\x1e{row[1]}", row)
            from_tree.setdefault(row[0], row)
    out = []
    for name, start in pairs:
        end, kind = None, ""
        known = exact.get(f"{name}\x1e{start}")
        if known:
            end, kind = known[0], known[1]
        else:
            row = from_tree.get(f"{name}\x1e{start}") or from_tree.get(name)
            if row:
                end = row[2] if row[2] and row[2] >= start else None
                kind = row[3]
        if not kind:
            text = lines[start - 1] if 0 < start <= len(lines) else ""
            kind = _kind_of(text, name)
        out.append([name, start, end, kind])
    return out


def _spans_of(body: str, ext: str, path: str = "") -> list:
    """`_declared_spans`, computed once per file per build.

    Routed through `_cached`, keyed on `path`, the same as every other real
    parse in this file. A caller with no path (a body handed over on its own)
    means "always recompute, never persist" rather than a crash.
    """
    return _cached(path, f"spans:{ext}",
                   lambda: _declared_spans(body, ext, path))


def record_span(name: str, path: str, start, end, kind: str) -> None:
    """Note one declaration site of `name`, for the map's `spans` key.

    Every place that fills `DEFINITIONS` calls this beside it, so a name in
    `definitions` is always a name `spans` holds a home for.
    """
    SPANS.setdefault(name, []).append([path, start, end, kind])


def spans_index() -> dict:
    """`SPANS` in the shape the map writes: `{name: [{file, start, end, kind}]}`.

    Sorted by file then start, and one row per site: the same file is walked
    as the suite and as the product on some layouts, and a name declared once
    is one home however many passes saw it. A site whose end is known wins the
    duplicate, since it is the more complete answer to the same question.
    """
    out = {}
    for name in sorted(SPANS):
        rows, seen = [], set()
        for path, start, end, kind in sorted(
                SPANS[name], key=lambda r: (r[0], r[1], r[2] is None, r[2] or 0, r[3])):
            if (path, start) in seen:
                continue
            seen.add((path, start))
            rows.append({"file": path, "start": start, "end": end, "kind": kind})
        out[name] = rows
    return out


# A byte order mark is the only thing in a source file that says which of
# these it is; without one, UTF-8 is the right guess and always was.
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _mostly_printable(text: str, sample: int = 2048) -> bool:
    """Is this decoded text, or a binary file that happened to start FF FE?

    The NUL test cannot answer that once a byte order mark has been honoured:
    UTF-16 decodes any even number of bytes into something, and four kilobytes
    of random bytes came back as mojibake that was then indexed as source. So
    the decoded characters are counted instead. A replacement character is
    what `errors="replace"` leaves where the bytes were not valid, and an
    unassigned or private-use code point is what random bytes decode to, so
    neither counts as printable here even though `str.isprintable` says the
    first one is.

    The gap is narrower than it looks, which is why the threshold is where it
    is. Measured: four kilobytes of random bytes behind an FF FE mark scores
    83.8 to 85.4 per cent over six seeds, because most of the UTF-16 plane is
    assigned and decodes to a real character. UTF-16, UTF-16BE, UTF-32 and
    UTF-8-sig files of ASCII source and of mixed-script prose (Greek,
    Cyrillic, Japanese, Korean, Arabic, accented Latin) all score 100. The
    gate is 97 per cent: twelve points clear of the noise and three points of
    slack for a real file with something odd in it.
    """
    head = text[:sample]
    if not head:
        return True
    good = sum(1 for ch in head
               if (ch in "\t\n\r") or (ch.isprintable() and ch != "\ufffd"))
    return good * 100 >= len(head) * 97


def _decode(raw: bytes):
    """This file's bytes as text, or None if it is not text at all.

    UTF-16 source is half NUL bytes, so reading it as UTF-8 and then calling
    any file with a NUL in its first 2 KB binary made every UTF-16 file
    invisible: no names, no lines, and not even a count of what was skipped,
    so `ask` reported a reach it did not have. Sniffing the byte order mark
    first decodes those files properly and leaves the NUL test to do its real
    job, which is rejecting compiled output.

    The mark is not proof on its own: a compiled file whose first two bytes
    happen to be FF FE decodes into mojibake rather than failing, and the NUL
    test can no longer catch it because the NULs were the encoding. Anything
    reached through a mark has to read as text as well.
    """
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            try:
                text = raw.decode(encoding, errors="replace")
            except (UnicodeDecodeError, LookupError):
                return None
            return text if _mostly_printable(text) else None
    return raw.decode("utf-8", errors="replace")


def _read_for_declarations(path: str):
    """This file's text, or None for anything too large or not text.

    Shared by `index_declarations` and `declarations_in` so the size cap and
    the binary sniff are one rule, not two that can drift apart.
    """
    try:
        if os.path.getsize(path) > 2 * 1024 * 1024:
            return None  # a generated bundle is names nobody asks about, by the ton
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    body = _decode(raw)
    if body is None or "\x00" in body[:2048]:
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
    # One list for both tables. `_declared_spans` keeps `_declared_names`'
    # order and its start lines, so `definitions` is the same index it was
    # before spans existed: the first site of each name, in walk order.
    for name, number, end, kind in _spans_of(body, ext, path):
        DEFINITIONS.setdefault(name, f"{path}:{number}")
        record_span(name, path, number, end, kind)


def _step_texts(path: str) -> list[str]:
    """The step phrases a steps module declares, from its decorators."""
    def _parse():
        out: list[str] = []
        defs: list[tuple] = []
        spans: list[list] = []
        # The same bound and the same retreat every other parse in this
        # package gets: an unbounded read here cost 414 MB on a 198 MB steps
        # module, and a steps module that large is one nobody wrote by hand.
        #
        # Imported here rather than at the top of the file: `build` imports
        # this module, so a module-level import back would be circular. By
        # the time this runs, `build` is loaded.
        try:
            from .build import _parse_source
        except ImportError:  # run as a plain file, with no package around it
            from build import _parse_source  # type: ignore[no-redef]
        tree = _parse_source(path)
        if tree is None:
            return {"texts": out, "defs": defs, "spans": spans}
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
                    spans.append([arg.value, node.lineno, node.end_lineno,
                                  "step"])
                    spans.append([f"def {node.name}", node.lineno,
                                  node.end_lineno, "function"])
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
        return {"texts": out, "defs": defs, "spans": spans}

    result = _cached(path, "step_texts", _parse)
    for name, loc in result["defs"]:
        DEFINITIONS.setdefault(name, loc)
    # A step phrase is a declared name like any other, so it gets a home in
    # `spans` like any other: `ast` knows where the decorated function ends.
    for name, start, end, kind in result.get("spans") or ():
        record_span(name, path, start, end, kind)
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


# What a tree-sitter node type declares. Anything not named here falls through
# to `_kind_of`, which reads the line the way the regex table's languages are
# read: the grammar knowing the node's shape does not oblige this table to
# hold a row for every spelling of it.
_TS_KIND = {
    "function_declaration": "function", "func_declaration": "function",
    "function_item": "function", "method_definition": "function",
    "method_declaration": "function", "method": "function",
    "singleton_method": "function", "delegate_declaration": "function",
    "class_declaration": "class", "class": "class",
    "object_declaration": "class", "record_declaration": "class",
    "interface_declaration": "interface", "trait_item": "trait",
    "struct_declaration": "struct", "struct_item": "struct",
    "enum_declaration": "enum", "enum_item": "enum",
    "type_alias_declaration": "type", "type_declaration": "type",
    "type_item": "type",
    "const_item": "constant", "static_item": "constant",
    "lexical_declaration": "constant",
    "mod_item": "module", "module": "module",
}


def _ts_symbols(path: str, lang: str) -> list:
    """Top-level declarations, from a parse tree rather than a pattern.

    `[name, start, end, kind]` per declaration, 1-based lines: a tree-sitter
    node carries `end_point`, which is the one thing the regex table cannot
    know, so where a grammar is installed the span it finds is exact.
    """
    parser = _tree_sitter(lang)
    if parser is None:
        return []

    def _parse():
        text = _slurp(path)
        try:
            tree = parser.parse(text.encode())
        except Exception:  # noqa: BLE001 - an optional third-party parser,
            # over a file this package did not write: a grammar built for
            # another version of tree-sitter raises whatever it raises, and a
            # file with no names in it is the right answer to all of it.
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
                            out.append([name, node.start_point[0] + 1,
                                        node.end_point[0] + 1,
                                        _TS_KIND.get(node.type, "")])
                        break
            for child in node.children:
                walk(child, exported)

        walk(tree.root_node)
        # `_slurp` reads a prefix of a large file, so the last declaration in
        # the parse tree is one whose end is the read limit rather than the
        # file's own. The same rule `_py_spans` applies to a cut Python file:
        # no end at all, rather than a confident wrong one.
        if len(text) >= SLURP_LIMIT:
            deepest = tree.root_node.end_point[0] + 1
            out = [[n, s, (e if e < deepest else None), k] for n, s, e, k in out]
        # No cap: the regex path this stands in for has none either, and a file
        # with more than a handful of declarations silently losing the ones past
        # some count is exactly the "indexed here, not there" gap this project
        # exists to close. Whatever bounds the reader sees are bounds `brief()`
        # applies once, in one place, when it renders the table for a prompt;
        # `framework_map.json` and `declarations_in` stay complete.
        #
        # Sorted by name, then by where it is, so the list is the same list on
        # every run and a name declared twice in one file keeps both rows.
        return sorted(out, key=lambda r: (r[0], r[1], r[2] is None, r[2] or 0))

    return _cached(path, f"ts:{lang}", _parse)
