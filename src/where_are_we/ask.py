"""`ask()`: the part of the map that mentions these words, and nothing else.

Moved out of `mapper.py` because three places there trimmed a list to a
budget, each with its own copy of "keep whole items in order while they fit,
count what didn't" — the definitions block, a section's matching rows, and
`_cap_sections`'s per-section share. `fit_lines` is that one loop; everything
below it is naming what goes in and out.
"""

import hashlib
import json
import os
import re
from itertools import accumulate
from datetime import datetime, timezone

# Named imports rather than `from . import graph`: that spelling names the
# package as well as the module, and this module is one the package's own
# `__init__` can reach, so it would put `ask` on a cycle with the facade.
# `tests/golden/import_graph.py` is what says so.
try:
    from ._mapper import rank as _rank_graph
    from .graph import (BLOCKS as AFFECTED_BLOCKS, DEFAULT_DEPTH,
                        FORMATS as AFFECTED_FORMATS, HEADS as AFFECTED_HEADS,
                        NAMES as AFFECTED_NAMES, affected, block_lines,
                        format_head, load as load_map, summary)
except ImportError:  # run as a plain file, with no package around it
    from _mapper import rank as _rank_graph  # type: ignore[no-redef]
    from graph import (BLOCKS as AFFECTED_BLOCKS,  # type: ignore[no-redef]
                       DEFAULT_DEPTH, FORMATS as AFFECTED_FORMATS,
                       HEADS as AFFECTED_HEADS, NAMES as AFFECTED_NAMES,
                       affected, block_lines, format_head, load as load_map,
                       summary)

# The default `--rank` and the MCP `rank` tool print, and the length of the
# map's own `rank` key. The same number in both, so `--rank` with no files is
# the stored ranking rather than a prefix of it.
RANK_LIMIT = _rank_graph.TOP

RESERVE_TAIL = 96  # the prose of a section's tail line ("… 37 more matching
# rows; 210 rows in this section do not mention these words"), paid for up
# front so the tail never pushes an answer past its limit. Longer than any
# tail the two counts can produce.
RESERVE_DEFINED = 32  # the "… N more definitions" line in `## Defined here`,
# paid for up front the same way.
RESERVE_CONTEXT = 48  # the "… N more lines" tail under one `context` block,
# paid for up front the same way. Longer than that line can be without its
# handle, which is the longer of its two forms: "… 123456 more lines; no room
# for a handle" is 41 characters, and the count is a line number, so no block
# gets near six digits of them.
# What a tail's `(more:...)` handles cost is not a constant and is not
# reserved up front. Reserving a fixed amount from every section's row budget
# would have cost a row in 26 of the 150 golden answers, including sections
# that print no tail at all and so carry no handle; the room a tail actually
# leaves over already covers the handle in 74 of the 76 places the golden
# suite prints one. So `_rows_chunk` and `_defined_here` fit their rows first,
# build the finished block, measure it, and hand room back to the tail only
# when the handle does not fit beside the rows, and then exactly the handle's
# own length. A row nobody can ask for again is worse than a row this answer
# does not print, so the handle wins that trade and the rows go.
#
# The give-back was capped at a constant, which was the same mistake one step
# down: a handle carries the question itself, percent-encoded, so a
# 200-character question is a 290-character handle and a 200-character one in
# a script that needs three bytes a character is 794, and past the cap those
# sections printed a tail with no handle and their rows were unreachable. The
# cap is now the section's own row budget: a tail may give up every row it
# had, and no more. A question longer than the whole budget still cannot
# carry a per-section handle; then the tail keeps its counts, and the
# `sections` handle points back at the section so a wider call can reach it.

# Handles: `more:<kind>:<payload>`, a string an answer prints and `more()`
# resolves. Nothing is stored between the two calls. The payload names the
# section, the words and how far into the list this answer got, and `more()`
# recomputes the same ranking from the same map on disk and continues from
# there. A map rebuilt in between may no longer hold that section, or may
# hold fewer rows in it, and then the handle is stale and says so.
HANDLE_PREFIX = "more:"
_SLUG_BAD = re.compile(r"[^a-z0-9_]+")

# Whether an answer is logged. Read here, once, rather than inside
# `log_answer()`, where a caller had no way to see that the function read the
# environment at all. Set it to "0" to stop the log.
LOG_ANSWERS = os.environ.get("WAWE_ASK_LOG") != "0"

_ROW_PATH = re.compile(r"^- `([^`]*/)([^`/]+)`(.*)$")
_DEF_ROW = re.compile(r"^- `([^`]+)`")  # a "## Defined here" row: the name in backticks


# Synonyms and stemming: the map says "signin()", the question says "login",
# and neither side is wrong. Groups are the words a reader means the same
# thing by; the stem catches the plural or the "-ing" the question happened
# to type. Both feed `_expand`, which is what `ask()` actually searches with.
SYNONYMS: dict = {
    "login": ["login", "signin", "sign_in", "sign-in", "auth", "authenticate", "authentication"],
    "logout": ["logout", "signout", "sign_out"],
    "invoice": ["invoice", "bill", "billing"],
    "payment": ["payment", "pay", "charge", "checkout"],
    "user": ["user", "account", "customer", "member"],
    "config": ["config", "configuration", "settings", "setup"],
    "error": ["error", "exception", "failure", "fault"],
    "endpoint": ["endpoint", "route", "handler", "api"],
    "test": ["test", "spec", "scenario", "case"],
    "db": ["db", "database", "table", "model", "schema"],
    "delete": ["delete", "remove", "destroy", "drop"],
    "create": ["create", "add", "insert", "new"],
    "update": ["update", "edit", "modify", "patch", "change"],
    "fetch": ["fetch", "get", "load", "read", "retrieve"],
    "queue": ["queue", "topic", "subject", "message", "event"],
    "deploy": ["deploy", "release", "ship", "rollout"],
    "cache": ["cache", "memo", "memoize"],
    "cron": ["cron", "schedule", "job", "task"],
    "permission": ["permission", "role", "scope", "guard", "acl"],
    "secret": ["secret", "credential", "token", "key", "password"],
}

_user_synonyms: dict = {}


def set_synonyms(mapping: dict) -> None:
    """Replace the extra groups read from `.wawe.toml`'s `[synonyms]` table.

    Called once by `mapper.main()` before `ask()` runs, with whatever that
    file names; an empty mapping goes back to only the built-in groups above.
    A module setter rather than a parameter on `ask()`, because `--ask` and
    the MCP tool both call `ask()` the same way, and neither should have to
    thread a project's config through every call to reach this one.
    """
    global _user_synonyms
    _user_synonyms = dict(mapping or {})


def _groups() -> list:
    """Every synonym group: the built-in ones above, plus `.wawe.toml`'s
    `[synonyms]` merged in, one project's word added to the group its key
    already belongs to, or as a new group of its own when no group has it."""
    groups = [list(g) for g in SYNONYMS.values()]
    for key, extra in _user_synonyms.items():
        key = str(key).lower()
        extra = [str(e).lower() for e in extra]
        for g in groups:
            if key in g:
                g.extend(e for e in extra if e not in g)
                break
        else:
            groups.append([key] + extra)
    return groups


def _stem(word: str) -> str:
    """A search stem, not a linguistic one: lowercase, one suffix off, never
    down to fewer than 3 letters, and left alone under 5.

    Plurals in "-ies" become "-y" ("categories" becomes "category"). "-es" is
    stripped only after a sibilant ("boxes" becomes "box"), because English
    spells a plain "-s" plural the same way when the word already ends in a
    silent "e" ("invoices" becomes "invoice", not "invoic"). Then "-ing",
    "-ed", a bare "-s", in that order, first one that fits.
    """
    w = word.lower()
    if len(w) < 5:
        return w
    if w.endswith("ies") and len(w) - 2 >= 3:
        return w[:-3] + "y"
    if (w.endswith("es") and len(w) - 2 >= 3
            and (w[-3] in "sxz" or w[-4:-2] in ("ch", "sh"))):
        return w[:-2]
    for suf in ("ing", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _expand(terms: list) -> list:
    """`terms`, in order, plus each term's stem and every member of a group
    that contains the term or its stem, each word added once.

    The literal terms stay first and unchanged, so a caller can still tell
    what was asked from what this turned up besides it, by set difference.
    """
    groups = _groups()
    out = list(terms)
    seen = set(out)

    def add(word):
        if word not in seen:
            out.append(word)
            seen.add(word)

    for t in terms:
        stem = _stem(t)
        if stem != t:
            add(stem)
        for g in groups:
            if t in g or stem in g:
                for member in g:
                    add(member)
    return out


def _slug(text: str) -> str:
    """`text` as a handle field: lower case, `[a-z0-9_]` kept, every other run
    of characters one `-`.

    Lossy on purpose, and the loss is the price of a handle a reader can read:
    `## Step phrases that overlap` is `step-phrases-that-overlap`, and asking
    for it again finds the section by that same slug rather than by an opaque
    id. `:` cannot survive this, which is what lets the payload use it as its
    field separator.
    """
    return _SLUG_BAD.sub("-", (text or "").lower()).strip("-") or "-"


SLUG_HEAD_MAX = 24  # how long a section slug may be before its hash suffix. A
# handle is a tail line's whole cost, and a tail line is paid for out of the
# section's own rows: `## Biggest feature files (scenario line numbers are in
# the full map)` slugs to 63 characters, and left whole it cost four sections
# of the 12,000-character answer for this suite. Cut on whole pieces, never
# mid-word, so the short slug is still a name a reader can read, and `more()`
# matches it by recomputing the same cut from the same heading.


def _cut_slug(slug: str, cap: int) -> str:
    """`slug` at `cap` characters, dropping whole `-` pieces from the end.

    Never a half word: the piece that would straddle the cap goes, unless it
    is the first one, which is truncated because something has to be left.
    """
    if len(slug) <= cap:
        return slug
    pieces = slug.split("-")
    out = pieces[0][:cap]
    for piece in pieces[1:]:
        if len(out) + 1 + len(piece) > cap:
            break
        out += "-" + piece
    return out


def _head_slug(head: str) -> str:
    """A section heading as a handle field: its slug, cut, then four hex
    digits of the whole heading.

    The cut alone is not an identifier. `## What you can already write with
    (85)` and `## What you can already write with (40)` both cut to
    `what-you-can-already`, and `more()` resolves a slug by taking the first
    ranked section that matches, so one of them was unreachable. The suffix is
    of the heading before the cut, so two headings that differ anywhere differ
    here; blake2s rather than `hash()` because it has to be the same number in
    the next process.
    """
    text = head.lstrip("#").strip()
    digest = hashlib.blake2s(text.encode("utf-8"), digest_size=2).hexdigest()
    return f"{_cut_slug(_slug(text), SLUG_HEAD_MAX)}-{digest}"


# Everything a handle field may carry as itself. Everything else is
# percent-encoded, so the field holds no space, no parenthesis and no `:`, and
# the parser regex a reader is given still finds the whole handle.
_FIELD_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _encode(text: str) -> str:
    """The question, exactly, as one handle field.

    Percent-encoded UTF-8, like a URL: `pre-commit` is `pre%2Dcommit` and
    `支払い処理` is its bytes. Lossless on purpose, and the reason is not
    tidiness. A slug of the words dropped their punctuation, so the handle on
    `ask("pre-commit")`'s tail re-asked the map about `pre` and `commit`, two
    different words with two different rankings, and handed back rows that
    were not the rows that answer left out. A word in a script this cannot
    spell in ASCII slugged to nothing at all.
    """
    out = []
    for byte in (text or "").encode("utf-8"):
        char = chr(byte)
        out.append(char if char in _FIELD_SAFE else f"%{byte:02X}")
    return "".join(out) or "%20"


def _decode(field: str) -> str:
    """A handle field back into the question that made it.

    Raises `ValueError` on a field this did not write: a truncated escape, or
    bytes that are not UTF-8. `more()` turns that into a stale handle rather
    than asking the map a question nobody typed.
    """
    raw, i = bytearray(), 0
    while i < len(field):
        if field[i] == "%":
            if len(field) - i < 3:
                raise ValueError(f"{field!r} ends in a half escape")
            raw.append(int(field[i + 1:i + 3], 16))
            i += 3
        else:
            raw.append(ord(field[i]))
            i += 1
    return raw.decode("utf-8")


def fit_indices(lines: list, budget: int, cost=len, sep: int = 1) -> list:
    """The indices of the whole lines that fit, in order, while
    `used + cost(line) + sep <= budget`.

    Best-fit, not a prefix: a line that does not fit is skipped, and a later,
    shorter line may still fit. Split out of `fit_lines` because a handle has
    to say where in the list this answer stopped, and the lines alone cannot
    say that when two of them read the same.
    """
    kept, used = [], 0
    for i, line in enumerate(lines):
        c = cost(line)
        if used + c + sep > budget:
            continue
        kept.append(i)
        used += c + sep
    return kept


def fit_lines(lines: list, budget: int, cost=len, sep: int = 1) -> tuple:
    """Whole lines, in order, while `used + cost(line) + sep <= budget`.

    Best-fit, not a prefix: a line that does not fit is skipped and counted,
    and a later, shorter line may still fit. Returns the kept lines and how
    many were dropped.
    """
    kept = fit_indices(lines, budget, cost, sep)
    return [lines[i] for i in kept], len(lines) - len(kept)


def _first_gap(total: int, kept: list) -> int:
    """The first index in `range(total)` that `kept` does not hold; `total`
    when it holds every one.

    This is what a handle's offset is: the first item the answer did not
    print. Where the fit skipped one long item and kept a shorter one after
    it, `more()` starting here repeats that shorter item rather than lose the
    one in between, because a repeated row is a smaller fault than a row no
    handle can ever reach.
    """
    have = set(kept)
    for i in range(total):
        if i not in have:
            return i
    return total


def _group_dirs(rows: list) -> list:
    """Consecutive rows under one directory, printed under it once.

    `features/checkout/payment.feature`, `features/checkout/refund.feature`
    is the directory twice; an answer that lists forty rows of one package
    spends a third of its room on the same prefix. Rendering only — the map on
    disk keeps full paths, and so does everything that parses it.
    """
    out, i = [], 0
    while i < len(rows):
        m = _ROW_PATH.match(rows[i])
        if not m:
            out.append(rows[i])
            i += 1
            continue
        d = m.group(1)
        run = [m]
        j = i + 1
        while j < len(rows):
            n = _ROW_PATH.match(rows[j])
            if not n or n.group(1) != d:
                break
            run.append(n)
            j += 1
        if len(run) < 2:
            out.append(rows[i])
            i += 1
            continue
        out.append(f"- `{d}`")
        out += [f"  - `{r.group(2)}`{r.group(3)}" for r in run]
        i = j
    return out


# A rendered row's path tokens. Rows are written several ways: a backticked
# relative path with a note after it, a definition row whose name comes first
# and whose absolute path and line come last, a call graph key of
# `file.py:func`, a prose line naming a file. All of them agree on what a path
# may hold, so the row is split on everything a path may not and the pieces
# that look like a path are tried.
_ROW_SPLIT = re.compile(r"[^A-Za-z0-9_@.+/:~-]+")
_LINE_SUFFIX = re.compile(r":\d+(?:-(?:\d+|\?))?$")


def _row_paths(row: str) -> list:
    """Every path-shaped token in one rendered row, without what follows it.

    A row names a file three ways: on its own, as a backticked relative path;
    with the line it is on, which is the shape a definition row ends in; and
    with the function inside it, `a.py:charge`, which is how both call graphs
    write a key. The part before the colon is the file in all three, so it is
    what comes back.
    """
    out = []
    for token in _ROW_SPLIT.split(row):
        token = _LINE_SUFFIX.sub("", token).rstrip(".,;:")
        for form in (token, token.split(":", 1)[0]):
            if form and form not in out and ("/" in form or "." in form):
                out.append(form)
    return out


def _scope(map_path: str, files) -> dict | None:
    """What `--files` needs to decide whether a row is about one of them.

    The repository root, because a definition row carries the absolute path a
    name was declared at and every other row carries a relative one; and every
    indexed file by basename, because the call graph's rows name a file the
    way a stack trace does. `refund.py:refund` is `billing/refund.py:refund`
    to a reader who asked for `billing/`, and the map already knows which file
    of that name it walked.

    `None` when no files were named, which is the case that reads no second
    file and takes exactly the path this took before `--files` existed.
    """
    if not files:
        return None
    path = os.path.join(os.path.dirname(map_path) or ".", "framework_map.json")
    root, homes = "", {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh) or {}
        root = data.get("repo") or ""
        for full in (data.get("lines") or ()):
            rel = _rank_graph.relative(full, root)
            homes.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    except (OSError, ValueError):
        pass
    # The same list as one handle field, percent-encoded like the question
    # beside it. A tail printed under a scoped answer carries it, and `more()`
    # rebuilds this dict from it, so the continuation reorders the section the
    # way the answer that printed the handle did. Without it the offset counts
    # into one order and the slice comes out of another, and a row `--files`
    # pushed past the cut is unreachable through the handle that promised it.
    return {"root": root, "homes": homes, "files": list(files),
            "field": _encode(",".join(files))}


def _scope_field(scope) -> str:
    """One scope's handle field, or `""` when there is no scope.

    Empty for an unscoped answer, and every handle builder appends the field
    only when it is non-empty, so an answer asked without `--files` prints the
    handles it printed before this existed. The golden suite is the proof:
    156 expected files, none of them moved.
    """
    return (scope or {}).get("field") or ""


def _scope_from_field(map_path: str, field: str) -> dict | None:
    """The scope a handle's own field names, rebuilt from the map on disk.

    Nothing is stored between the two calls. The file list is in the handle,
    the map is on disk, and `_scope` resolves the one against the other the
    same way it did for the answer that printed it.
    """
    files = [part for part in _decode(field).split(",") if part]
    return _scope(map_path, files)


def _in_scope(row: str, scope: dict) -> bool:
    """Whether one rendered row is about a file the reader named."""
    root, homes, wanted = scope["root"], scope["homes"], scope["files"]
    for token in _row_paths(row):
        if _rank_graph.matches(token, root, wanted):
            return True
        if "/" in token:
            continue
        # A bare basename, which is what the call graph and several other
        # sections print. Every file of that name the walk indexed counts:
        # naming one of them would make the answer depend on walk order, and
        # a repository with two `refund.py` has two answers to this question.
        for candidate in homes.get(token, ()):
            if _rank_graph.matches(candidate, root, wanted):
                return True
    return False


def _files_first(rows: list, scope: dict | None) -> list:
    """`rows` with the ones naming a file the reader asked for in front.

    A stable partition, not a sort: inside each half the order is the order
    the section already had, so `--files` moves rows and changes nothing else
    about them. The tail under the section still counts what did not fit and
    still hands back the same handle, because the handle names the section and
    the words rather than this ordering, and `more()` continues the list the
    section itself holds.
    """
    if not scope:
        return rows
    first, rest = [], []
    for row in rows:
        (first if _in_scope(row, scope) else rest).append(row)
    return first + rest


def _defined_here(exact: list, room: int, words: str = "",
                  base: int = 0, sfield: str = "") -> tuple:
    """The definitions block, whole lines up to `room`, with a count of what
    did not fit and, when `words` is given, the handle that fetches it.

    Returns `(block, reached)`: the text, and how far into `exact` this got,
    counted from `base`. `more()` needs the second one to know whether it made
    any progress at all, and refuses to print a handle that would send a
    caller back to the same place.

    The section loop bounds itself against `limit`; this block runs first, so
    30 short definitions used to come back 1186 characters at every limit
    from 50 to 1000 — a ceiling that only held after the block that runs
    first.
    """
    head = "## Defined here\n"
    slug = _encode(words) if words else ""

    def tail_for(dropped: int, got: int, handles: bool) -> str:
        if not dropped:
            return ""
        scoped = f":{sfield}" if sfield else ""
        suffix = f" (more:defs:{slug}:{got}{scoped})" if handles and slug else ""
        return f"… {dropped} more definitions{suffix}"

    block, reached, body_lines, tail = _fit_chunk(
        head, exact, room, RESERVE_DEFINED, tail_for, base=base)
    # A head with nothing under it is not a block. The two callers of
    # `_fit_chunk` that print sections keep theirs, because a section head is
    # itself an answer; this block's head says only that definitions exist,
    # and printing it alone would spend the room on saying nothing.
    if body_lines <= 1 and not tail:
        return "", reached
    return block, reached


# Ranking, with the two things counting words leaves out.
#
# The old score was `sum(hay.count(t) for t in terms)`, and on a map of a
# product called InventoryForecasting the word "forecast" is in nearly every
# section: it separates nothing and counted as much as the rare word that
# separates everything. A long section also won for being long, since more
# text holds more of any word. Measured on this repository's own map, three
# real questions:
#
#   "persistence across reload"  the right module was 2nd, now 1st
#   "cross tab sync"                                  5th, now 1st
#   "export forecast to csv"           not in the top five at all, now 1st
#
# First place is what matters, because every answer here is cut to a budget
# and the cut takes the tail. On the third question a branch asking about
# export was handed the 132 KB general module and never shown the export
# module, which exists, is indexed, and did not fit.
#
# BM25: a rare term outweighs a common one (idf), the tenth occurrence adds
# almost nothing (k1), and a long section is discounted for its length (b).
# The constants are the standard ones and are not tuned to anything here.
_BM25_K1 = 1.5
_BM25_B = 0.75


def _rank(blocks, terms, half=None):
    """Sections that mention these words, best first.

    `half`, when given, is the terms `_expand` added that were not asked for
    literally: a synonym or a stem earns a section a place, but at half the
    weight of a word the reader actually typed, so a section that only
    matches through an expansion never outranks one that matches the words
    themselves.
    """
    import collections
    import math

    half = half or ()
    docs = []
    for head, body in blocks:
        words = re.findall(r"[a-z][a-z_]{1,}",
                           (head + "\n" + "\n".join(body)).lower())
        docs.append((head, body, collections.Counter(words), len(words)))
    n = len(docs)
    if not n:
        return []
    seen = collections.Counter()
    for _, _, tf, _ in docs:
        seen.update(tf.keys())
    avgdl = sum(dl for _, _, _, dl in docs) / n or 1.0
    out = []
    for head, body, tf, dl in docs:
        score = 0.0
        for t in terms:
            f = tf.get(t, 0)
            if not f:
                # Still counted when it is only a substring — "forecast"
                # inside "forecasting" is a hit a reader means, and tokenising
                # alone would lose it. Given the weight of one occurrence, no
                # more.
                if t in head.lower() or any(t in ln.lower() for ln in body):
                    f = 1
                else:
                    continue
            idf = math.log(1 + (n - seen[t] + 0.5) / (seen[t] + 0.5))
            weight = 0.5 if t in half else 1.0
            score += weight * idf * (f * (_BM25_K1 + 1)) / (
                f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl))
        if score <= 0:
            continue
        # A heading that matches still says the section is about this rather
        # than that the word passed through it. Kept, as a multiplier now
        # rather than a flat five, so it cannot outweigh the ranking itself.
        if any(t in head.lower() for t in terms):
            score *= 1.6
        out.append((score, head, body))
    # Rounded for the sort only, not for the score itself: two sections whose
    # difference is noise rather than signal (found live on "invoice
    # checkout" - a summary line naming this run's own build path tokenises
    # to a different word count call to call, nudging every score's length
    # normalisation by a few parts in ten thousand) would otherwise change
    # places from one run to the next on the same tree. Sort is stable, so a
    # real tie falls back to `docs`' own order, itself fixed by the map text.
    out.sort(key=lambda x: -round(x[0], 2))
    return out


def _blocks(text: str) -> list:
    """The map's `#`/`##` sections as `(head, body_lines)` pairs."""
    blocks, head, body = [], "", []
    for line in text.splitlines():
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            if head or body:
                blocks.append((head, body))
            head, body = line, []
        else:
            body.append(line)
    blocks.append((head, body))
    return blocks

BRIEF_NAME = "framework_map_brief.md"


def map_text(map_path: str) -> str:
    """The map as one text: `framework_map.md` plus every section of the brief
    beside it whose heading the map does not already have.

    For a behave suite the map carries the step and feature sections and the
    brief summarises them. For a plain code repository the map is a 1 KB
    skeleton of three empty suite sections while the brief holds the seventy
    that matter - entry points, routes, data model, public surface - and an
    `ask` that read only the map answered nothing about the code. Reading both
    costs nothing: the brief is a few dozen KB on disk, read once per question.
    """
    with open(map_path, encoding="utf-8") as fh:
        text = fh.read()
    brief = os.path.join(os.path.dirname(map_path) or ".", BRIEF_NAME)
    try:
        with open(brief, encoding="utf-8") as fh:
            extra = fh.read()
    except OSError:
        return text
    have = {h.strip() for h, _ in _blocks(text) if h.startswith("## ")}
    keep = []
    for head, body in _blocks(extra):
        if head.startswith("## ") and head.strip() not in have:
            keep.append("\n".join([head] + body))
    return text if not keep else text.rstrip("\n") + "\n\n" + "\n\n".join(keep) + "\n"


def map_heads(map_path: str) -> list:
    """The `## ` headings of the map and its brief, in order, without repeats."""
    return [h.strip() for h, _ in _blocks(map_text(map_path)) if h.startswith("## ")]



def _split_rows(body: list, terms: list) -> tuple:
    """This section's rows that mention a term, and how many did not. A bare
    bold subhead — structure, not a row — is neither shown nor counted."""
    matching, other = _rows_by_match(body, terms)
    return matching, len(other)


def is_row(line: str) -> bool:
    """Whether one line under a heading is a row a reader asked for.

    A blank line is spacing and a bold line is a subhead, so neither counts.
    Public and used from two places: this module says "N rows do not mention
    these words" and `render.cost` says how many rows a section costs, and
    the two have to mean the same thing by a row or the second is describing
    a file nobody reads.
    """
    return bool(line.strip()) and not line.startswith("**")


def _rows_by_match(body: list, terms: list) -> tuple:
    """The same split as `_split_rows`, with the rows that did not match kept
    rather than counted: `more:unmatched:` has to print them."""
    matching, other = [], []
    for line in body:
        if not is_row(line):
            continue
        if any(t in line.lower() for t in terms):
            matching.append(line)
        else:
            other.append(line)
    return matching, other


def _definitions_block(map_path: str, terms: list, room: int,
                       extra: list | None = None, words: str = "",
                       scope: dict | None = None) -> str:
    """`## Defined here`, bounded to `room`; empty when nothing was defined
    under these terms.

    `terms` keeps `definitions_for`'s AND semantics: a name counts when it
    holds every literal word, or is exactly one of them. `extra`, when
    given, is synonym and stem words from `_expand`; any one of them is
    enough on its own, and a name that only matches through `extra` is
    listed after every name that matches `terms`.
    """
    exact = definitions_for(map_path, terms, extra)
    if not exact:
        return ""
    return _defined_here(_files_first(exact, scope), room, words, 0,
                         _scope_field(scope))[0]


def _tail_line(dropped: int, unmatched: int, sec: str, words: str,
               offset: int, kind: str = "rows", sfield: str = "") -> str:
    """The one line under a section that says what was left out, with the
    handle that fetches it when `sec` and `words` are given.

    Two clauses, joined by `; `, exactly as before handles: what did not fit
    ("… 37 more matching rows") and what never matched ("210 rows in this
    section do not mention these words"). They are two different lists and
    either can be asked for, but only one handle goes on a line: two of them
    cost about 110 characters, which is a section's worth of rows at the
    budgets these answers are actually cut to. The rows are the ones the
    question was about, so on a line that has both they get the handle, and
    the other list is reachable by hand from the same two slugs with the kind
    changed and the offset at zero.

    `sfield` is the scope `--files` was given, already encoded, appended as a
    fifth field. Empty without `--files`, and then the handle is character for
    character the one this printed before scopes existed.
    """
    tail = f":{sfield}" if sfield else ""
    parts = []
    if dropped:
        noun = ("more matching rows" if kind == "rows"
                else "more rows that do not mention these words")
        h = f" (more:{kind}:{sec}:{words}:{offset}{tail})" if sec and words else ""
        parts.append(f"… {dropped} {noun}{h}")
    if unmatched:
        h = (f" (more:unmatched:{sec}:{words}:0{tail})"
             if sec and words and not dropped else "")
        parts.append(f"{unmatched} rows in this section do not mention "
                     f"these words{h}")
    if not parts:
        return ""
    return "; ".join(parts) if dropped else "… " + parts[0]


def _rows_chunk(head: str, rows: list, unmatched: int, room: int,
                sec: str = "", words: str = "", base: int = 0,
                kind: str = "rows", sfield: str = "") -> tuple:
    """`head` plus as many of `rows` as fit in `room`, grouped by directory,
    with the tail that says what was left and how to ask for it.

    Returns `(chunk, attempted, reached, handed)`: the two `_section_answer`
    has always handed back, how far into `rows` this got counted from `base`,
    and whether every row it did not print is reachable from the handle it
    did print. Shared with `more()`, which continues one of these lists from
    an offset and has to cut it under exactly the same rules, or the answer a
    handle gives would not be the answer the handle promised.

    `handed` is false when the room left was enough for the tail's prose but
    not for its handle: the rows are then unreachable from this tail, the
    `sections` handle above is pointed back at this section instead, and the
    walk in `more()` stops rather than step past it.

    A handle carries the question, so a long question makes a long handle, and
    below about two and a half times its length there is no budget in which a
    section can print both rows and a handle for the rest of them. Measured on
    the suite fixture with a 200-character question: 304 characters of handle
    needs 800 characters of budget before nothing is out of reach, and 584
    needs 1,500. Under that, the answer is honest rather than complete: the
    tail keeps its counts, the note above carries the `sections` handle, and
    the same question at a wider budget reaches the rest.

    `reached` counts rows, not printed lines. `_group_dirs` runs after the
    fit and prints a directory head (``- `steps/` ``) that is not a row, so a
    handle counting output lines would skip one row per link of a chain.
    """
    def tail_for(dropped: int, got: int, handles: bool) -> str:
        # `sfield` rides in the closure, not through `_fit_chunk`: the fitter
        # is shared with `context`, which has no scope, and a tail builder is
        # exactly where the two callers are allowed to differ.
        return _tail_line(dropped, unmatched, sec if handles else "",
                          words if handles else "", got, kind,
                          sfield if handles else "")

    chunk, reached, lines, tail = _fit_chunk(head, rows, room, RESERVE_TAIL,
                                             tail_for, _group_dirs, base)
    if not lines:
        # This section's head alone would overrun; skip it, not every section
        # after it.
        return "", False, base, True
    handed = reached >= base + len(rows) or f"more:{kind}:" in tail
    if lines == 1 and not tail:
        return "", True, reached, handed
    return chunk, True, reached, handed


def _fit_chunk(head: str, rows: list, room: int, reserve: int, tail_for,
               render=None, base: int = 0) -> tuple:
    """`head` plus as many of `rows` as fit in `room`, and the tail that says
    what was left out.

    Returns `(chunk, reached, body_lines, tail)`: the text, how far into
    `rows` this got counted from `base`, how many lines of it are head and
    rows rather than tail, and the tail itself. `body_lines` is zero, and
    `chunk` empty, when the head alone would overrun.

    `room` is a ceiling, not a target. The tail line is paid for up front out
    of `reserve`, the head is included only if it fits, and no row is forced
    in: a first row longer than the room is a dropped row, not an exception.
    Measured at review: a 3 KB head with limit=50 came back 68 times over
    budget when the head and first row were forced.

    `tail_for(dropped, reached, handles)` builds the tail, and is where the
    two callers differ: `_rows_chunk` writes a section's two counts and a
    `more:rows:` handle, `_context_chunk` a line count and a `more:ctx:` one.
    `render`, when given, is applied to the rows that fit before they are
    printed, which is how `_rows_chunk` groups them by directory after the
    cut rather than before it.

    Both callers used to hold their own copy of the loop below, which is the
    give-back trade and nothing else: it is the one part of a cut that is not
    obvious, and a fix to it landing in one copy and not the other is the
    defect that shape invites.
    """
    budget = room - reserve
    if budget <= len(head):
        return "", base, 0, ""

    def build(give: int, handles: bool) -> tuple:
        idx = fit_indices(rows, budget - len(head) - give)
        got = base + _first_gap(len(rows), idx)
        kept = [rows[i] for i in idx]
        body = [head] + (render(kept) if render else kept)
        line = tail_for(len(rows) - len(idx), got, handles)
        return "\n".join(body + ([line] if line else [])), got, len(body), line

    give, most = 0, budget - len(head)
    chunk, reached, lines, tail = build(0, True)
    for _ in range(4):
        if len(chunk) <= room:
            return chunk, reached, lines, tail
        if give >= most:
            break  # every row is already given up and it still does not fit
        # Give the tail exactly what its handles cost, not the overflow: the
        # overflow is smaller than one row, so paying it back a few characters
        # at a time frees no row at all and the four goes run out with the
        # handles still unaffordable. Measured on `## How a feature file is
        # written here` at 262 characters, where the chain lost the section.
        plain = build(give, False)[3]
        give = min(most, max(give + len(chunk) - room,
                             len(tail) - len(plain)))
        chunk, reached, lines, tail = build(give, True)
    if len(chunk) > room:
        # The handles still overrun the ceiling. Print the tail without them:
        # that is what this line said before handles existed, and the reserve
        # is the room already set aside for it.
        chunk, reached, lines, tail = build(0, False)
    return chunk, reached, lines, tail


def _section_answer(head: str, body: list, terms: list, room: int,
                    words: str = "", scope: dict | None = None) -> tuple:
    """One section's answer: matching rows, grouped by directory, with a tail
    saying what didn't fit or didn't match.

    Returns `(chunk, attempted, handed)`. `chunk` is empty when the section
    has nothing to show. `attempted` is true whenever the section's head alone
    fit in `room` — independent of whether a chunk came out of it — and feeds
    `seen`, for the "more sections match" note. `handed` says whether the rows
    it left out can be asked for; when they cannot, the "more sections match"
    handle is pointed back at this section instead of past it.

    `words` is the question as it was asked, unexpanded: the handle carries
    it so `more()` can expand it the same way and rank the same sections.
    Without it the tail is the plain one this printed before handles.

    `files`, when given, are the paths the reader said they are working in,
    and the rows naming one of them are printed first. Which rows the section
    shows at a budget can change with it; which rows the section has does not,
    and neither does the tail's arithmetic.
    """
    matching, unmatched = _split_rows(body, terms)
    matching = _files_first(matching, scope)
    chunk, attempted, _reached, handed = _rows_chunk(
        head, matching, unmatched, room,
        _head_slug(head) if words else "", _encode(words) if words else "",
        kind="rows", sfield=_scope_field(scope))
    return chunk, attempted, handed


def callers(map_json_path: str, name: str) -> list:
    """Every `<file>:<func>` whose call graph entry mentions `name`.

    Reads the two call graphs already written to the map: `call_graph_files`
    (cross-file, values shaped `"<callee> (<basename>)"`, or
    `"<callee> (<a>|<b>)?"` where several files declare the callee and the map
    names all of them) and `call_graph` (behave step functions, values bare
    names). Matching is case-sensitive and exact, because these are
    identifiers as written, not prose, and it is on the name alone: the file
    half of an edge, and the `?` that says the map is choosing between the
    files it lists, are not part of the identifier. A trailing `(` on `name`
    is stripped first, so `callers(m, "charge(")` reads the same as
    `callers(m, "charge")`.
    """
    m = _call_graphs(map_json_path)
    return sorted(_calling_keys(m, _bare(name)))


def _bare(name: str) -> str:
    """A name as the call graphs spell it: `charge(` and `charge` are one."""
    name = (name or "").strip()
    return name[:-1] if name.endswith("(") else name


def _call_graphs(map_json_path: str) -> dict:
    """The map's JSON, or an empty dict when there is none to read.

    Three functions here walk the same two graphs, and each of them used to
    open and parse the file for itself.
    """
    try:
        with open(map_json_path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _calling_keys(m: dict, target: str) -> set:
    """Every `<file>:<func>` key whose call graph entry names `target`.

    Both graphs, matched the way each stores its callees: `call_graph_files`
    holds `"<callee> (<file>)"`, and `"<callee> (<a>|<b>)?"` where two or more
    files declare the callee, in which case the edge names every one of them
    and carries the mark; `call_graph` (behave steps) holds bare names. The
    split at `" ("` takes the name off the front of all three spellings, so a
    marked edge matches exactly as an unmarked one does, however many files it
    lists. Case-sensitive and exact, because these are identifiers as written,
    not prose.
    """
    out = set()
    for key, calls in (m.get("call_graph_files") or {}).items():
        for c in calls:
            if c.split(" (", 1)[0] == target:
                out.add(key)
                break
    for key, calls in (m.get("call_graph") or {}).items():
        if target in calls:
            out.add(key)
    return out


def _keys_named(m: dict, target: str) -> list:
    """The graph keys that define `target`: `<file>:<func>` with that func.

    A caller graph is walked by name, because a callee is recorded by name.
    Several files may define one name, and then a hop through it reaches the
    callers of all of them; these keys are what `impact` names when it says
    so.
    """
    out = set()
    for graph in ("call_graph_files", "call_graph"):
        for key in (m.get(graph) or {}):
            if key.rsplit(":", 1)[-1] == target:
                out.add(key)
    return sorted(out)


def callees(map_json_path: str, name: str) -> list:
    """What the functions named `name` call: the other direction of `callers`.

    Reads the same two graphs. `call_graph_files` already carries the file a
    callee is declared in (`"charge (a.ts)"`, or `"charge (a.ts|c.ts)?"`,
    every file that declares it, where more than one does) and that is
    returned whole, mark included: the caller asked what this function calls,
    and how sure the map is about the answer is part of the answer;
    `call_graph` (behave steps) records bare names and those come back bare,
    because the map has no file to attach to them. Cross-file only, like the
    graphs themselves: a call to a function defined in the same file is not
    in them.
    """
    m = _call_graphs(map_json_path)
    target = _bare(name)
    out = set()
    for graph in ("call_graph_files", "call_graph"):
        for key, calls in (m.get(graph) or {}).items():
            if key.rsplit(":", 1)[-1] == target:
                out.update(calls)
    # A behave step function is in both graphs, so one callee could come back
    # twice: `click_1` from the step graph and `click_1 (checkout.py)` from
    # the cross-file one. The bare spelling is the same fact with the file
    # missing, so it goes when the qualified one is there.
    qualified = {c.split(" (", 1)[0] for c in out if " (" in c}
    return sorted(c for c in out if " (" in c or c not in qualified)


def callees_line(map_json_path: str, name: str) -> str:
    """`callees` as one line, so the CLI and the MCP tool answer the same."""
    hits = callees(map_json_path, name)
    if not hits:
        return f"{name} calls nothing in the map"
    return f"{name}: " + ", ".join(hits)


IMPACT_CAP = 200  # entries one `impact` answer prints, counting the keys a
# `note:` line names. Past it the answer says how many are left and where,
# and stops. There is no handle to fetch the rest with, on purpose: this tool
# already takes a `depth`, and a blast radius that overflows at depth 5 is
# not read by paging through it, it is read by asking again at depth 2.
# Narrowing is the reader's move.
IMPACT_MAX_DEPTH = 6
NOTE_KEYS = 5  # keys a `note:` line names before it says how many more there
# are. Unbounded, a name three hundred files define wrote a four-kilobyte
# footnote under a two-hundred-entry answer: the cap the reply advertises,
# defeated by its own aside.

# What the map itself keeps of each graph, set in `_mapper/build.py` (the
# `[:60]` on `func_calls` and the `[:120]` on `call_graph`). Named here
# because the caveat tells the reader that a radius from a large repository
# is a floor rather than the whole of it, and a number nobody can see is not
# telling them anything. `ask` cannot import them: `_mapper.build` imports
# `_mapper.declare`, which imports this module. A CI step asserts the two
# spellings still agree.
MAP_CALL_GRAPH_KEYS = 60
MAP_STEP_GRAPH_KEYS = 120


def _impact_caveat(target: str, depth: int, how: bool = False) -> str:
    """The first line of every `impact` reply: how to read the rest of it.

    Unconditional, and not only when the key data happens to show an
    ambiguity. A second definition that calls nothing across files has no key
    in the graph at all, so its callers are unioned into the answer with
    nothing to notice it by; a rule stated every time is the only honest way
    to say that.

    The `?` clause reads the mark the map writes on an edge whose callee two
    or more files declare, and which therefore names all of them. `impact`
    prints keys rather than edges, so nothing below carries the mark; the
    reader meets it in `callees` and in the map itself, and this is where it
    is explained.

    `how` adds the last clause, and only a map that holds `xrefs` gets it: a
    map built before 1.5.0 has no rule to name for any edge, and a line
    promising a `how:` under each hop that never comes is worse than the
    silence 1.4.x kept.
    """
    return (f"Impact of `{target}` to depth {depth}. How to read it: hops are "
            "followed by name, so where several files define one name their "
            "callers are unioned here; only cross-file calls are in the "
            "graph, a call inside the file a name is defined in is not; "
            f"the map keeps at most {MAP_CALL_GRAPH_KEYS} cross-file call "
            f"graph keys and {MAP_STEP_GRAPH_KEYS} step ones, so on a large "
            "repository this radius is a floor; and an edge ending in ? "
            "names every file that declares the callee, because more than one "
            "does."
            + (" Under each hop, a how: line names, in the same order, the "
               "rule that placed each of its edges." if how else ""))


def _resolutions(m: dict) -> dict:
    """`{(graph key, callee name): {resolution}}` from the map's `xrefs`.

    The graph keys `impact` walks are `<basename>:<func>` and an `xrefs`
    subject is the same function under the path the walk read it at, so the
    subject is read down to its basename here. Two files of one basename
    share a key in the graph and share it here.

    Empty where the map holds no `xrefs` at all, which is every map built
    before 1.5.0, and empty where it holds only declarations: either way
    there is no call edge here to name a rule for.
    """
    rows = m.get("xrefs")
    if not rows:
        return {}
    out: dict = {}
    for row in rows:
        if row.get("edge") != "calls":
            continue
        rel, _, func = str(row.get("subject") or "").rpartition(":")
        key = f"{os.path.basename(rel)}:{func}"
        out.setdefault((key, row.get("object")), set()).add(
            row.get("resolution"))
    return out


# What a hop through the behave step graph says about itself. That graph
# records a bare callee name and no file, so there is no candidate list, no
# rule that chose between candidates, and no `xrefs` row: the column says
# which graph the edge came from rather than leaving a blank under it.
STEP_GRAPH_HOW = "step_graph"


def impact(map_json_path: str, name: str, depth: int = 3) -> str:
    """The blast radius of `name`: who reaches it, grouped by hop distance.

    Hop 1 is exactly what `callers` returns. Hop 2 is who calls those, and
    so on to `depth`.

    A hop is walked by name, not by `<file>:<func>` key, even though a value
    in `call_graph_files` carries a file (`"charge (a.ts)"`). That file is
    where the extractor believed the callee lived, which for an imported
    name is a guess: it is read off the import, and re-exports, aliases and
    two modules exporting one name all defeat it. Matching on it would also
    make `impact NAME` at depth 1 disagree with `callers NAME`, which
    matches on the name alone. One rule, stated in the first line of every
    reply, and the key data's own evidence of a clash added as a `note:`
    when there is any.

    A visited set carries across hops, so a cycle (`d` calls `b`, `b`
    reaches `d`) is walked once and terminates rather than looping. The keys
    that define `name` itself are visited before the walk starts: they are
    the change, not its radius.

    The whole reply names at most `IMPACT_CAP` (200) `<file>:<func>`
    entries, the keys inside `note:` lines included, and says in its tail
    what it left out and where. `depth` is validated by the two callers that
    take it from a user (the command line refuses it, the MCP server replies
    -32602); the check here is the library's own.
    """
    target = _bare(name)
    if not isinstance(depth, int) or isinstance(depth, bool) \
            or depth < 1 or depth > IMPACT_MAX_DEPTH:
        return f"depth must be a whole number from 1 to {IMPACT_MAX_DEPTH}, not {depth!r}"
    if not target:
        return "impact needs a name to walk back from"
    m = _call_graphs(map_json_path)
    # The rule behind each edge, and the hops it explains. A map with no
    # `xrefs` key says nothing about any edge, and this answer then reads
    # exactly as 1.4.x wrote it.
    how_by_edge = _resolutions(m)
    how_by_hop: list = []
    has_rows = bool(m.get("xrefs"))
    caveat = _impact_caveat(target, depth, has_rows)

    hops, notes, gave = [], [], {}
    seen_keys = set(_keys_named(m, target))
    seen_names = {target}
    frontier = [target]
    for _hop in range(depth):
        if not frontier:
            break
        found, by_name = set(), {}
        for n in frontier:
            keys = _keys_named(m, n)
            if len(keys) > 1 and n not in [a[0] for a in notes]:
                notes.append((n, keys))
            by_name[n] = _calling_keys(m, n)
            found |= by_name[n]
        fresh = sorted(found - seen_keys)
        if not fresh:
            break
        for n, keys in by_name.items():
            # What this name actually put into the answer, so a note is
            # printed only about a name whose callers a reader can see.
            gave.setdefault(n, set()).update(keys & set(fresh))
        seen_keys.update(fresh)
        hops.append(fresh)
        # How each of these keys got here: the resolution of the edge from it
        # to the name it was found under, and both of them where one key
        # reaches two names of this hop.
        this_hop: dict = {}
        for n, keys in by_name.items():
            for key in keys & set(fresh):
                this_hop.setdefault(key, set()).update(
                    how_by_edge.get((key, n)) or {STEP_GRAPH_HOW})
        how_by_hop.append(this_hop)
        frontier = []
        for key in fresh:
            n = key.rsplit(":", 1)[-1]
            if n not in seen_names:
                seen_names.add(n)
                frontier.append(n)

    if not hops:
        return caveat + f"\nnothing in the map calls {target}"

    lines, left, room, printed = [caveat], [], IMPACT_CAP, set()
    for i, hop in enumerate(hops, 1):
        shown = hop[:room] if room > 0 else []
        room -= len(shown)
        printed.update(shown)
        if shown:
            lines.append(f"depth {i}: " + ", ".join(shown))
            if has_rows:
                how = how_by_hop[i - 1]
                lines.append("how: " + ", ".join(
                    f"{key} {'/'.join(sorted(how.get(key) or {STEP_GRAPH_HOW}))}"
                    for key in shown))
        if len(shown) < len(hop):
            left.append(f"{len(hop) - len(shown)} more at depth {i}")
    unshown_notes = 0
    for n, keys in notes:
        if not (gave.get(n) or set()) & printed:
            continue  # this name contributed nothing the reader can see
        cost = min(len(keys), NOTE_KEYS)
        if cost > room:
            unshown_notes += 1
            continue
        room -= cost
        named = ", ".join(keys[:NOTE_KEYS])
        if len(keys) > NOTE_KEYS:
            named += f", … and {len(keys) - NOTE_KEYS} more"
        lines.append(f"note: {len(keys)} files define `{n}` ({named}); "
                     "callers of any of them are counted.")
    if unshown_notes:
        left.append(f"{unshown_notes} note{'s' if unshown_notes > 1 else ''} "
                    "not shown")
    if left:
        lines.append("… " + ", ".join(left) + ". Ask again with a smaller depth.")
    return "\n".join(lines)


def _callers_block(map_path: str, words: str, room: int) -> str:
    """"## Called by `name`", one per raw term that has a caller, cut to
    `room`. Terms come from `words` unlowered: `ask()` lowercases everything
    else for ranking prose, but a call graph is built from identifiers as
    written, and `Charge` is not `charge`.
    """
    json_path = os.path.join(os.path.dirname(map_path) or ".",
                              "framework_map.json")
    terms, seen = [], set()
    for w in re.split(r"[\s,]+", words):
        if len(w) > 1 and w not in seen:
            seen.add(w)
            terms.append(w)
    out = []
    for t in terms:
        hits = callers(json_path, t)
        if not hits:
            continue
        block = f"## Called by `{t}`\n" + "\n".join(f"- {h}" for h in hits)
        if len(block) + 2 > room:
            continue
        out.append(block)
        room -= len(block) + 2
    return "\n\n".join(out)


def _also_matched(def_block: str, section_chunks: list, terms: list, candidates: list) -> str:
    """The "(also matched: signin, auth)" line, with its trailing blank line,
    or an empty string: causal, not incidental.

    A candidate earns a place only for a row (or a defined name) the literal
    words did not already match on their own - riding along in a row the
    literal words earned does not count. `definitions_for`'s AND semantics
    apply to a name; `_split_rows`'s OR semantics apply to a section row, so
    each is checked the way it was matched.
    """
    if not candidates:
        return ""
    extra, seen = [], set()

    def credit(low):
        for c in candidates:
            if c not in seen and c in low:
                extra.append(c)
                seen.add(c)

    if def_block:
        for line in def_block.splitlines()[1:]:
            if line.startswith("…"):
                continue
            m = _DEF_ROW.match(line)
            if not m:
                continue
            name_low = m.group(1).lower()
            if all(t in name_low for t in terms) or any(t == name_low for t in terms):
                continue
            credit(name_low)
    for chunk in section_chunks:
        for line in chunk.splitlines()[1:]:
            if line.startswith("…"):
                continue
            low = line.lower()
            if any(t in low for t in terms):
                continue
            credit(low)
    return f"(also matched: {', '.join(extra)})\n\n" if extra else ""


def _more_note(room: int, words: str = "", offset: int = 0,
               unshown: bool = True, sfield: str = "") -> str:
    """The "more sections match" note, only if it fits: a note that says
    "more" when there is no more, or that pushes the answer past its limit,
    is the defect this guards.

    With `words` it also carries the handle for the sections that went
    unshown. When that longer note does not fit but the plain one does, the
    plain one goes out: half the note is still true.
    """
    for form in _note_forms(words, offset, unshown, sfield):
        if len(form) + 2 <= room:
            return form
    return ""


def _note_forms(words: str, offset: int, unshown: bool = True,
                sfield: str = "") -> list:
    """The note under an answer that could not finish, longest first.

    The order is what the answer gives up first. The long form is the sentence
    with the handle after it. The short form is the handle with just enough
    words to say what it is: at limit 100 the sentence alone is half the
    answer, and a note that says there is more without saying how to get it is
    a fact with nothing behind it. The bare sentence is last, because it is
    the one that leaves those sections unreachable.

    `unshown` is false in the other case this note answers: every matching
    section was shown, but one of them could not print the handle for the rows
    it cut, because the question is long and a handle carries the question.
    Then "more sections match" would not be true, and only the forms that
    carry the handle are worth printing at all.
    """
    plain = "… more sections match; ask for something narrower"
    if not words:
        return [plain] if unshown else []
    field = _encode(words)
    tail = f":{sfield}" if sfield else ""
    if not unshown:
        return [f"… more of these sections than fit here; "
                f"more:sections:{field}:{offset}{tail}"]
    return [f"{plain}, or more:sections:{field}:{offset}{tail}",
            f"… more sections: more:sections:{field}:{offset}{tail}",
            plain]


_HANDLE_KIND = re.compile(r"more:([a-z]+):")


# The one kind of handle a `sections` handle cannot stand in for.
#
# Room bought for one part of an answer is paid for by another, and the only
# price never worth paying is a list the reader could have asked for in full,
# traded for one they could not. A `sections` handle re-renders the sections
# from the first one this answer could not finish, and a section that could
# not print its own `rows` handle is exactly what sets that index, so giving
# up `rows` (or `unmatched`, which points at lines no answer to this question
# would have printed) to buy the `sections` handle loses nothing: the wider
# call reaches those rows. `## Defined here` past its cap is a different list,
# reached only through `more:defs:`, and nothing else stands in for it.
_KEPT_KINDS = frozenset(("defs",))


def _handle_kinds(blocks: list) -> set:
    """The handles in an answer whose loss no other handle would make good."""
    return set(_HANDLE_KIND.findall("\n\n".join(blocks))) & _KEPT_KINDS


def _assemble(map_path: str, terms: list, expanded: list, candidates: list,
              words: str, scored: list, room: int, hold: int,
              scope: dict | None = None) -> tuple:
    """The answer's blocks, in order, with `hold` characters kept back from
    everything above the "more sections match" note so the note can still be
    printed.

    Returns `(out, def_block, section_chunks, wanted_note, note, unshown)`,
    where `unshown` says whether a matching section went unshown, as against
    one shown without a handle for the rows it cut. `ask()`
    runs this once with `hold` at zero and, only when a note was wanted and
    came out without its handle, once more with room set aside for it: a
    pointer to the sections nobody saw is worth more than the row it costs,
    and the row it costs is one the tail's own handle can fetch back.
    """
    out, section_chunks = [], []
    start = room
    room -= hold
    def_block = _definitions_block(map_path, terms, room, candidates, words,
                                   scope)
    if def_block:
        out.append(def_block)
        room -= len(def_block) + 2
    seen = 0
    first_unshown = len(scored)
    for i, (_hits, h, b) in enumerate(scored):
        chunk, attempted, handed = _section_answer(h, b, expanded, room, words,
                                                   scope)
        if attempted:
            seen += 1
        # Where a `more:sections:` handle resumes: the first section this
        # answer could not show, or could not show all of and could not print
        # a handle for. The second kind is printed here as well as pointed at,
        # so a chained walk sees it twice rather than not at all.
        if (not attempted or not handed) and first_unshown == len(scored):
            first_unshown = i
        if chunk:
            out.append(chunk)
            section_chunks.append(chunk)
            room -= len(chunk) + 2
    # `hold` was set aside for the note and the blank line before it, and
    # every block above has already been charged its own blank line, so the
    # two characters `_more_note` adds again are given back with it. Never
    # past `start`: with nothing printed there is no blank line to pay for.
    room = min(room + hold + 2, start) if hold else room
    note = ""
    if first_unshown < len(scored):
        # Only when a matching section really went unshown, or was shown
        # without the handle for what it cut, and only if the note itself
        # fits: a note that says "more" when there is no more, or that pushes
        # the answer past its limit, is the defect this guards.
        note = _more_note(room, words, first_unshown, seen < len(scored),
                          _scope_field(scope))
        if note:
            out.append(note)
            room -= len(note) + 2
    cblock = _callers_block(map_path, words, room)
    if cblock:
        out.append(cblock)
    return (out, def_block, section_chunks, first_unshown < len(scored), note,
            seen < len(scored))


def ask(map_path: str, words: str, limit: int = 12000, files=()) -> str:
    """The part of the map that mentions these words, and nothing else.

    A map is generated so nobody has to search the repository. Then it is 253 KB,
    and searching *it* is the same problem one size down: grep hands back matching
    lines with no idea which section they came from, so the reader either takes
    the lines without their meaning or opens the whole file — and opening the
    whole file puts it into every message that follows.

    So: sections, ranked by how much they mention what was asked, cut to a size
    that answers rather than a size that has to be paid for on every later turn.

    `files` are the paths the reader is working in, from `--files a.py,b.py`
    or the MCP `files` argument. Inside each section the rows naming one of
    them come first and the rest follow with the section's usual tail, so an
    agent editing `billing/` gets the same answer with its own half of the
    repository at the top. Without it nothing about the answer changes, which
    is checked by the golden suite: every expected file was recorded without
    `files` and none of them moved when this was added.
    """
    try:
        text = map_text(map_path)
    except OSError as exc:
        return f"no map at {map_path}: {exc}"

    terms = [w.lower() for w in re.split(r"[\s,]+", words) if len(w) > 1]
    if not terms:
        return "ask what?"
    expanded = _expand(terms)
    half = set(expanded) - set(terms)
    # Every word `_expand` added beyond what was typed, in order, deduped:
    # the largest an "also matched" line could possibly be, reserved from
    # `room` up front so that line never pushes an answer past `limit`.
    # `limit` is a ceiling for everyone who calls `ask()`, this note included.
    candidates = list(dict.fromkeys(t for t in expanded if t not in terms))
    note_room = len(f"(also matched: {', '.join(candidates)})") + 2 if candidates else 0
    # What the named files are, resolved once against the map beside this
    # one. A question asked without `--files` opens no second file and takes
    # exactly the path it took before.
    scope = _scope(map_path, files)

    # `ask()` synthesises its own "## Defined here" below, from
    # `_definitions_block`, so the brief's own section of that name (kept
    # in the map text for the pointer's section list and for a human
    # reading the brief directly) is dropped here before ranking. Left in,
    # a question that matches both would answer with the same rows twice.
    blocks = [(h, b) for h, b in _blocks(text) if h.strip() != "## Defined here"]
    scored = _rank(blocks, expanded, half)
    if not scored:
        block = _definitions_block(map_path, terms, limit - note_room,
                                   candidates, words, scope)
        if block:
            return _also_matched(block, [], terms, candidates) + block
        cblock = _callers_block(map_path, words, limit)
        if cblock:
            return cblock
        # What was indexed, said out loud. The old wording promised more than
        # it knew — "a real absence rather than a search that missed" — about a
        # constant that was in the product on line 31, in a language the index
        # did not cover. A map that overstates its reach turns "I did not look"
        # into "it is not there", and the reader stops looking too.
        looked = ""
        try:
            with open(os.path.join(os.path.dirname(map_path) or ".",
                                   "framework_map.json"), encoding="utf-8") as fh:
                counts = (json.load(fh) or {}).get("indexed") or {}
            if counts:
                looked = (" indexed: "
                          + ", ".join(f"{where} {n} files"
                                      for where, n in sorted(counts.items())))
        except (OSError, ValueError):
            pass
        # Facts, not counsel. This is a script — a walk, some patterns, a JSON
        # file — and an answer that reasons about what the reader should
        # conclude is a script pretending to be an opinion. Say what was
        # searched and what was found; the conclusion is the reader's.
        return f"no match for {words!r}.{looked}"

    scored.sort(key=lambda x: -round(x[0], 2))  # same rounding as _rank's own sort, so this no-op re-sort cannot undo it
    room = limit - note_room
    args = (map_path, terms, expanded, candidates, words, scored)
    built = _assemble(*args, room, 0, scope)
    if built[3] and "more:sections:" not in built[4]:
        # A section went unshown and the note that says so did not fit, or fit
        # only in the form that cannot say where to look. Buy it back with
        # room from the blocks above, trying the three forms of the note in
        # turn, and keep the first answer that is better than this one.
        #
        # Better is not "has a note". Two rules bound the trade. The room
        # has to come from somewhere, and it must not come out of the
        # definitions handle: at limit 100 an answer with `… 2 more
        # definitions (more:defs:click_7:0)` can reach all 41 of them, and a
        # note pointing at the sections does not reach those definitions,
        # which are a different list. And it must not come out of the whole
        # `## Defined here` block, because where a name was declared is the
        # question this tool is asked most.
        for form in _note_forms(words, len(scored), built[5],
                                _scope_field(scope)):
            if built[4] and ("more:sections:" in built[4]
                             or "more:sections:" not in form):
                break
            retry = _assemble(*args, room, len(form) + 2, scope)
            if not retry[4] or ("more:sections:" in form
                                and "more:sections:" not in retry[4]):
                continue
            if (_handle_kinds(retry[0]) >= _handle_kinds(built[0])
                    and (retry[1] or not built[1])):
                built = retry
                break
    out, def_block, section_chunks = built[0], built[1], built[2]
    answer = "\n\n".join(out)
    return _also_matched(def_block, section_chunks, terms, candidates) + answer


def _stale(reason: str) -> str:
    """What `more()` says when a handle no longer names anything.

    One sentence, always the same opening, because a caller that chains
    handles has to be able to tell "there is nothing more" from an answer.
    """
    return f"no such handle in this map: {reason}"


def _handle_words(field: str) -> tuple:
    """`(words, terms, expanded, candidates)` for a handle's words field.

    The same four things `ask()` computes from the question it was given, from
    the same string it was given: the field is the question itself, not a slug
    of it, so `terms` here is the list `ask()` split, character for character,
    and the ranking and the row filter behind a handle are the ones that
    printed it.
    """
    words = _decode(field)
    terms = [w.lower() for w in re.split(r"[\s,]+", words) if len(w) > 1]
    if not terms:
        return words, [], [], []
    expanded = _expand(terms)
    candidates = [t for t in expanded if t not in terms]
    return words, terms, expanded, candidates


def _ranked(map_path: str, expanded: list, terms: list) -> list:
    """The map's sections that mention these words, best first: `ask()`'s own
    ranking, recomputed from the file on disk."""
    text = map_text(map_path)
    blocks = [(h, b) for h, b in _blocks(text) if h.strip() != "## Defined here"]
    scored = _rank(blocks, expanded, set(expanded) - set(terms))
    scored.sort(key=lambda x: -round(x[0], 2))
    return scored


def more(map_path: str, handle: str, limit: int = 4000) -> str:
    """The rest of a list an answer cut short, from the handle it printed.

    Every place `ask()` and `find` stop early now print where they stopped:
    `more:rows:<section>:<words>:<offset>` and its four siblings. Nothing is
    written down between the two calls. This reads the same map, ranks it the
    same way, filters the same rows, and continues from `offset`, so the only
    state is the handle itself and a map that has not changed underneath it.

    An answer asked with `--files` carries the scope in one more field, and
    the four scoped kinds accept it: `more:rows:<section>:<words>:<offset>:
    <files>`. It has to be there. The offset counts rows in the order the
    scoped answer printed, and without the scope this would slice the
    unscoped order at that number: every row `--files` demoted past the cut
    would be skipped and every row it promoted would come back twice. That is
    the one promise this project makes above all others, and a scoped answer
    used to void it silently.

    When it has changed, the handle is stale rather than wrong: a section the
    rebuild dropped, or a list that is now shorter than the offset, comes back
    as `no such handle in this map: ...` instead of a slice of some other
    list.

    The slice obeys the same rules the first answer did: whole rows, `limit`
    as a ceiling and not a target, and a tail carrying the next handle when
    there is still more after this.
    """
    handle = (handle or "").strip()
    if not handle.startswith(HANDLE_PREFIX):
        return _stale(f"{handle!r} is not a handle; they start with 'more:'")
    parts = handle[len(HANDLE_PREFIX):].split(":")
    kind = parts[0] if parts else ""
    fields = parts[1:]
    widths = {"rows": 3, "unmatched": 3, "defs": 2, "sections": 2, "find": 2,
              "at": 2, "ctx": 3, "aff": 4}
    # The four kinds an answer's scope can reach. `find` searches the lines
    # and `at` a definition; neither is ordered by `--files`, so neither
    # carries the field and a handle that puts one there is malformed. `ctx`
    # is out for the same reason from the other side: `context` takes no
    # files, so no answer it prints is ordered by a scope. If it ever gains
    # one, it belongs in this tuple and nowhere else. `aff` carries a file
    # list of its own and is still not scoped: those files are the question
    # it answers rather than an ordering laid over an answer to another one.
    scoped = ("rows", "unmatched", "defs", "sections")
    if kind not in widths:
        return _stale(f"{kind!r} is not one of rows, unmatched, defs, "
                      "sections, find, at, ctx, aff")
    sfield = ""
    if kind in scoped and len(fields) == widths[kind] + 1:
        sfield, fields = fields[-1], fields[:-1]
    if len(fields) != widths[kind]:
        want = (f"{widths[kind]} fields after the kind, or {widths[kind] + 1} "
                f"with a scope," if kind in scoped
                else f"{widths[kind]} fields after the kind,")
        return _stale(f"a more:{kind} handle has {want} this one has "
                      f"{len(fields) + (1 if sfield else 0)}")
    try:
        scope = _scope_from_field(map_path, sfield) if sfield else None
    except ValueError as exc:
        return _stale(f"{sfield!r} is not a file list this wrote: {exc}")
    try:
        offset = int(fields[-1])
    except ValueError:
        return _stale(f"{fields[-1]!r} is not an offset")
    if offset < 0:
        return _stale("an offset cannot be negative")

    if kind == "at":
        # The same lookup `at()` did, from the same map, continuing from the
        # line this offset counts to. Nothing is stored between the two calls:
        # the place is in the handle, and the definition it names is whatever
        # the map on disk now says it is.
        try:
            place = _decode(fields[0])
        except ValueError as exc:
            return _stale(f"{fields[0]!r} is not a place this wrote: {exc}")
        return at(map_path, place, limit, offset)

    if kind == "ctx":
        # One block of a `context` answer, from the line this offset counts
        # to. Nothing is stored between the two calls either: the block and
        # the name are in the handle, and the block is composed again from
        # the same functions over the map on disk, at this call's own budget.
        block = fields[0]
        if block not in CONTEXT_NAMES:
            return _stale(f"{block!r} is not a context block; they are "
                          + ", ".join(CONTEXT_NAMES))
        try:
            named = _decode(fields[1])
        except ValueError as exc:
            return _stale(f"{fields[1]!r} is not a name this wrote: {exc}")
        lines = _context_lines(map_path, block, named, limit)
        if offset >= len(lines):
            return _stale(f"the {block} block for {named!r} is {len(lines)} "
                          f"line{'' if len(lines) == 1 else 's'} long, and "
                          f"this handle asks for line {offset + 1} of it")
        chunk, reached = _context_chunk(CONTEXT_HEADS[block], lines[offset:],
                                        limit, block, fields[1], offset)
        if reached == offset:
            return _stale(f"line {offset + 1} of the {block} block does not "
                          f"fit in {limit} characters")
        return chunk

    if kind == "aff":
        # The same walk `affected` did, from the same map, continuing from
        # the line this offset counts to. Nothing is stored between the two
        # calls: the block, the files and the depth are in the handle, and
        # the graph is whatever the map on disk now holds.
        block = fields[0]
        if block not in AFFECTED_NAMES and block not in AFFECTED_FORMATS:
            return _stale(f"{block!r} is not an affected block; they are "
                          + ", ".join(AFFECTED_NAMES + AFFECTED_FORMATS))
        try:
            named = [f for f in _decode(fields[1]).split(",") if f]
        except ValueError as exc:
            return _stale(f"{fields[1]!r} is not a file list this wrote: {exc}")
        try:
            walked = int(fields[2])
        except ValueError:
            return _stale(f"{fields[2]!r} is not a depth")
        result = affected(load_map(os.path.dirname(map_path) or "."), named,
                          walked)
        lines = block_lines(result, block)
        if offset >= len(lines):
            return _stale(f"the {block} block for {', '.join(named)} is "
                          f"{len(lines)} line{'' if len(lines) == 1 else 's'} "
                          f"long, and this handle asks for line {offset + 1} "
                          "of it")
        head = (format_head(result, block) if block in AFFECTED_FORMATS
                else AFFECTED_HEADS[block])
        chunk, reached = _block_chunk(
            head, lines[offset:], limit,
            lambda got: f"more:aff:{block}:{fields[1]}:{walked}:{got}", offset)
        if reached == offset:
            return _stale(f"line {offset + 1} of the {block} block does not "
                          f"fit in {limit} characters")
        return chunk

    if kind == "find":
        try:
            from ._mapper.declare import find_text
        except ImportError:  # run as a plain file, with no package around it
            from _mapper.declare import find_text  # type: ignore[no-redef]
        try:
            phrase = _decode(fields[0])
        except ValueError as exc:
            return _stale(f"{fields[0]!r} is not a phrase this wrote: {exc}")
        # Two ceilings, because `find` counts hits and `more` counts
        # characters: 40 is `find`'s own limit, so `more` never returns more
        # hits than `find` would, and `room` is this call's budget, which
        # `find_text` fills with whole hits and no more.
        return find_text(os.path.dirname(map_path) or ".", phrase, 40,
                         offset, room=limit)

    try:
        words, terms, expanded, candidates = _handle_words(fields[-2])
    except ValueError as exc:
        return _stale(f"{fields[-2]!r} is not a question this wrote: {exc}")
    if not terms:
        return _stale(f"{words!r} holds no word to ask about")

    if kind == "defs":
        rows = _files_first(definitions_for(map_path, terms, candidates, cap=0),
                            scope)
        if offset >= len(rows):
            return _stale(f"{len(rows)} names in this map hold {words!r}, "
                          f"and this handle asks for number {offset + 1}")
        block, reached = _defined_here(rows[offset:], limit, words, offset,
                                       sfield)
        if reached == offset:
            return _stale(f"definition {offset + 1} of {len(rows)} does not "
                          f"fit in {limit} characters")
        return block

    try:
        scored = _ranked(map_path, expanded, terms)
    except OSError as exc:
        return f"no map at {map_path}: {exc}"

    if kind == "sections":
        if offset >= len(scored):
            return _stale(f"{len(scored)} sections mention {words!r}, and this "
                          f"handle asks for number {offset + 1}")
        # Contiguous, unlike `ask()`'s own loop: this is walking a list from
        # an offset, and the handle it prints has to be further along than the
        # one it was given or a caller chaining handles never terminates. So
        # it stops at the first section that does not fit rather than skipping
        # it for a shorter one behind it.
        # The note is held back before anything else is printed, not offered
        # whatever is left at the end. It carries the handle that continues
        # this walk, and a continuation that cannot say where it stopped ends
        # the chain in the middle of the list it was asked to finish.
        hold = len(f"… more sections match; ask for something narrower, or "
                   f"more:sections:{_encode(words)}:{len(scored)}"
                   f"{':' + sfield if sfield else ''}") + 2
        out, room, reached = [], limit - hold, offset
        for i, (_hits, h, b) in enumerate(scored[offset:], offset):
            chunk, attempted, handed = _section_answer(h, b, expanded, room,
                                                       words, scope)
            if not attempted:
                break
            if chunk and not handed and i > offset:
                break  # leave this whole section to the next call, with room
            reached = i + 1
            if chunk:
                out.append(chunk)
                room -= len(chunk) + 2
        if reached == offset:
            return _stale(f"section {offset + 1} of {len(scored)} does not "
                          f"fit in {limit} characters")
        room += hold
        if reached < len(scored):
            note = _more_note(room, words, reached, True, sfield)
            if note:
                out.append(note)
        return "\n\n".join(out) or (
            f"sections {offset + 1} to {reached} of {len(scored)} hold no row "
            f"that mentions {words!r}")

    for _hits, h, b in scored:
        if _head_slug(h) != fields[0]:
            continue
        matching, other = _rows_by_match(b, expanded)
        rows = _files_first(matching if kind == "rows" else other, scope)
        what = "matching rows" if kind == "rows" else "rows that do not mention it"
        if offset >= len(rows):
            return _stale(f"{h.lstrip('#').strip()!r} has {len(rows)} "
                          f"{what} for {words!r}, and this handle asks for "
                          f"number {offset + 1}")
        chunk, _attempted, reached, _handed = _rows_chunk(
            h, rows[offset:], 0, limit, fields[0], _encode(words), offset, kind,
            sfield)
        if reached == offset:
            return _stale(f"row {offset + 1} of {len(rows)} does not fit in "
                          f"{limit} characters")
        return chunk
    return _stale(f"no section called {fields[0]!r} mentions {words!r}")


LOG_NAME = ".wawe-ask.log"


def log_answer(out_dir: str, tool: str, words: str, answer: str, room: int) -> None:
    """Append one JSON line to `<out_dir>/.wawe-ask.log`: how big this answer
    was, and against what room it was cut.

    Every answer here is trimmed to a budget, and until now nothing recorded
    what that budget actually cost in a real session - `ask`'s own claims about
    tokens saved rested on one production run, not on what every call since
    has spent. Off with `WAWE_ASK_LOG=0`. Never raises: a log is a
    convenience, not a reason to fail the question it is logging.
    """
    if not LOG_ANSWERS:
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "words": words,
        "chars": len(answer),
        "tokens": len(answer) // 4,
        "room": room,
    }
    try:
        with open(os.path.join(out_dir, LOG_NAME), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


# Lives here rather than in the renderer it grew up in: it reads a written
# map off disk and hands back rows, which is this module's job, and three
# callers (this module, the MCP server and the language server) reach it
# through the facade. While it sat in `_mapper/render.py`, the renderer
# imported this module for `fit_lines` and this module imported the facade to
# reach back, which is the cycle the fourteen-line comment that used to sit in
# `_defined_block` was apologising for.
DEFINITIONS_CAP = 40  # how many definitions one answer prints; `more()` passes
# `cap=0` to see past it, which is the only way rows 41 and after were ever
# reachable.


def definitions_for(map_path: str, terms: list[str],
                    extra: list[str] | None = None,
                    cap: int = DEFINITIONS_CAP) -> list[str]:
    """Exact places, from the map's own index of what was defined where.

    Answered before any prose, because this is the question actually being
    asked. A scenario author looking for `def ad_product_shows` wants a file and
    a line; told which module it lives in, they grep the module. Over one run
    that was forty hand searches against three questions to the map.

    `terms` keeps its original meaning: a name counts only when it holds
    every one of them, or is exactly one of them - "invoice checkout" is a
    name naming both, not a name naming either. `extra` is `ask()`'s
    synonym and stem words, each of which is enough on its own; asking for
    "login" should not lose `def login` because it does not also mention
    "auth". Literal matches are returned before expansion-only ones so a
    name that answers what was actually typed is never pushed out of the
    40-row cap by one that only answers a synonym.
    """
    path = os.path.join(os.path.dirname(map_path) or ".", "framework_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            defs = (json.load(fh) or {}).get("definitions") or {}
    except (OSError, ValueError):
        return []
    extra = extra or []
    literal, expansion = [], []
    for name, where in defs.items():
        row = f"- `{name}` — {where}"
        found = _name_matches(name, terms, extra)
        if found == "literal":
            literal.append(row)
        elif found == "expansion":
            expansion.append(row)
    rows = sorted(literal) + sorted(expansion)
    return rows[:cap] if cap else rows


# The name this was called before it was admitted to be public, kept so a
# caller that already imported it does not break. Deprecated: use
# `definitions_for`.
_definitions_for = definitions_for


def _name_matches(name: str, terms: list, extra: list) -> str:
    """`"literal"`, `"expansion"` or `""` for one name against a question.

    The rule `definitions_for` has always used, named so `spans_for` answers
    the same question about the same names: the two differ in what they print
    about a name, never in which names they print.
    """
    low = name.lower()
    if terms and (all(t in low for t in terms) or any(t == low for t in terms)):
        return "literal"
    if any(t in low for t in extra):
        return "expansion"
    return ""


def _site(site: dict) -> str:
    """One declaration site: `a.py:10-24 (function)`.

    `?` for an end nothing knew, which is the convention the call graph
    already uses for a callee it could not resolve. A start with a wrong end
    would be worse than no end at all: an agent editing by anchor would cut
    the file at a line this map guessed.
    """
    end = site.get("end")
    return (f"{site.get('file')}:{site.get('start')}-"
            f"{end if end is not None else '?'} ({site.get('kind') or 'name'})")


def file_list(text: str, read_stdin=None) -> list:
    """The files a `--files` value or an MCP `files` argument names.

    A comma or newline separated list, or `-` for a newline list on stdin,
    which is how a caller hands over the output of `git diff --name-only`
    without building a command line out of it. Blank entries are dropped and
    the order is kept: it is a set, and printing it back in the order it was
    given is what makes an error message recognisable.
    """
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        given = [str(x) for x in text]
    elif text.strip() == "-":
        given = (read_stdin() if read_stdin else "").splitlines()
    else:
        given = [text]
    out = []
    for chunk in given:
        for part in re.split(r"[,\n]", chunk):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def unknown_files(map_path: str, files) -> list:
    """The paths named that no file this map indexed matches.

    A typo used to be silent: `--rank nosuch.py` personalises on nothing and
    returns the global order, which reads exactly like `--rank` with no
    argument. The command line says so on stderr; stdout is untouched, so the
    flag and the MCP tool still print the same bytes.
    """
    scope = _scope(map_path, files)
    if not scope or not scope["homes"]:
        # No files named, or no map beside this one to check them against.
        # Silence is the honest answer to "is this path real" when there is
        # nothing to ask.
        return []
    known = [rel for rels in scope["homes"].values() for rel in rels]
    return [want for want in scope["files"]
            if not any(_rank_graph.matches(rel, "", [want]) for rel in known)]


def rank_lines(map_path: str, files=(), words=(), limit: int = RANK_LIMIT) -> str:
    """The top definitions by PageRank over the file graph, one per line.

        0.044812401 build /repo/src/where_are_we/_mapper/build.py:243

    Score first, so the list reads as a ranking and sorts as one; nine digits,
    which is what the map rounded to before it sorted, so a row printed here
    and a row stored under `rank` are the same characters.

    `files` personalises the walk on the paths the reader named and `words`
    are the identifiers they asked about. Given neither, this recomputes what
    the build stored, from the same two keys of the same file: the CI step
    compares the two lists rather than trusting that they agree.

    `words` is split the way `ask()` splits a question, whether it arrives as
    one string from `--ask` or as a list from the MCP tool, so the flag and
    the tool weigh the same identifiers and print the same bytes.
    """
    if isinstance(words, str):
        words = [words]
    words = [w for part in (words or ()) for w in re.split(r"[\s,]+", str(part)) if w]
    path = os.path.join(os.path.dirname(map_path) or ".", "framework_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, ValueError) as exc:
        return f"no map at {path}: {exc}"
    rows = _rank_graph.rows(data, files=files, words=words, limit=limit)
    if not rows:
        return "nothing to rank: the map declares no name any file references"
    return "\n".join(f"{row['score']:.9f} {row['name']} "
                     f"{row['file']}:{row['line']}" for row in rows)


def spans_for(map_path: str, terms: list[str], extra: list[str] | None = None,
              cap: int = DEFINITIONS_CAP) -> list[str]:
    """Every home of every name these words name, one line per name.

        charge: a.py:10-24 (function), b.py:88-91 (function)

    The same names `definitions_for` returns, and all of their sites rather
    than the first one the walk happened to reach. A name declared in two
    files used to come back as one of the two, chosen by directory order, and
    nothing in the answer said the other existed.

    A map with no `spans` key was built before 1.5.0; then this is
    `definitions_for`, which every such map does hold.
    """
    path = os.path.join(os.path.dirname(map_path) or ".", "framework_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh) or {}
    except (OSError, ValueError):
        return []
    spans = doc.get("spans")
    if not spans:
        return definitions_for(map_path, terms, extra, cap)
    extra = extra or []
    literal, expansion = [], []
    for name, sites in spans.items():
        row = f"{name}: " + ", ".join(_site(s) for s in sites)
        found = _name_matches(name, terms, extra)
        if found == "literal":
            literal.append(row)
        elif found == "expansion":
            expansion.append(row)
    rows = sorted(literal) + sorted(expansion)
    return rows[:cap] if cap else rows


# What `--at` and the MCP `at` tool print at, in characters: the same budget
# one `ask` answer gets, because it lands in the same conversation.
AT_BUDGET = 12000


def _at_target(target: str) -> tuple:
    """`(file, line)` from `FILE:LINE`, or `(None, complaint)`."""
    text = (target or "").strip()
    file, sep, number = text.rpartition(":")
    if not sep or not file:
        return None, (f"{text!r} is not a place: give me FILE:LINE, the file "
                      "and line a stack trace names")
    try:
        line = int(number)
    except ValueError:
        return None, f"{number!r} is not a line number"
    if line < 1:
        return None, "a line number starts at 1"
    return (file, line), ""


def _at_files(paths, wanted: str) -> list:
    """The indexed paths `wanted` names, best match first.

    A stack trace says `billing/charge.py`, the map holds whatever path the
    walk saw, and both are the same file. So: the exact path if the map holds
    it, else every path ending in it, else every path with that basename. One
    rung at a time, and never two rungs at once, so a question that names a
    path the map holds is answered about that path and no other.

    The last rung can match several files, because two directories may both
    hold an `m.py` and a bare basename does not say which. This returns all of
    them, sorted; `at` answers about the first in path order and names the
    rest, rather than picking one silently.
    """
    paths = sorted(paths)
    exact = [p for p in paths if p == wanted]
    if exact:
        return exact
    suffix = [p for p in paths if p.endswith("/" + wanted)
              or p.endswith(os.sep + wanted)]
    if suffix:
        return suffix
    base = os.path.basename(wanted)
    return [p for p in paths if os.path.basename(p) == base]


def at(map_path: str, target: str, limit: int = AT_BUDGET,
       offset: int = 0) -> str:
    """The whole definition enclosing `FILE:LINE`, from the map's own index.

    The move an agent makes after every stack trace, which until now was a
    `Read` with a guessed offset around the line and a second one when the
    guess cut the function in half. The map already knows where that
    definition starts and ends, and already holds the lines.

    The innermost enclosing definition, because a method inside a class is
    what a line inside that method is part of; ask about the class's own line
    to get the class. A definition whose end nothing knew cannot be said to
    enclose anything, so it is offered as a neighbour instead: that is the
    honest answer for a language read by the regex table, and `file:10-?` is
    what it looks like.

    Whole lines, up to `limit`, with a tail carrying the handle that fetches
    the rest. `offset` is how many lines of the definition to skip, which is
    what `more:at:` continues from.
    """
    where, complaint = _at_target(target)
    if where is None:
        return complaint
    wanted, line = where
    path = os.path.join(os.path.dirname(map_path) or ".", "framework_map.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh) or {}
    except (OSError, ValueError) as exc:
        return f"no map at {path}: {exc}"
    # `"spans" not in doc`, not `not spans`: a 1.5.0 map of a tree that
    # declares nothing holds an empty index, and telling its reader the map is
    # from an older release would send them to rebuild something that is
    # already current.
    if "spans" not in doc:
        return ("this map has no spans index: it was built by a version "
                "before 1.5.0, which recorded one line per name and no end. "
                "Rebuild with --force: a build skips a tree that has not "
                "moved, so an upgrade alone does not add the key")
    spans = doc.get("spans") or {}
    lines = doc.get("lines") or {}
    files = _at_files(set(lines) | {s["file"] for rows in spans.values()
                                    for s in rows}, wanted)
    if not files:
        return (f"no file in this map is called {wanted!r}; "
                f"{len(lines)} files were indexed")
    here = []
    for name, rows in spans.items():
        for site in rows:
            if site.get("file") in files:
                here.append((site["file"], site["start"], site.get("end"),
                             site.get("kind") or "name", name))
    if not here:
        return (f"no definition encloses {wanted}:{line} "
                f"(nothing in this map is declared in {', '.join(files)})")
    # Innermost first: the deepest declaration that still contains the line,
    # then the tightest of those, then by name, so the answer to one question
    # is one definition and the same one every time.
    holding = sorted((s for s in here
                      if s[2] is not None and s[1] <= line <= s[2]),
                     key=lambda s: (-s[1], s[2], s[4], s[0]))
    if not holding:
        near = sorted(here, key=lambda s: (abs(s[1] - line), s[1] > line,
                                            s[0], s[1], s[4]))[:3]
        answer = (f"no definition encloses {wanted}:{line} (nearest: "
                  + ", ".join(f"{s[4]} " + _site({"file": s[0], "start": s[1],
                                                  "end": s[2], "kind": s[3]})
                              for s in near) + ")")
        # A declaration that starts above the line and ends nobody knows where
        # may well be the one the line is in. Saying only "nothing encloses it"
        # would report a bound of this index as a fact about the code.
        if any(s[2] is None and s[1] <= line for s in here):
            answer += ("; an end of ? is a declaration this map could not "
                       "measure, so one of them may be the one you are in")
        return answer
    # One file answers. Where a bare name matched several and more than one of
    # them holds a definition here, the header names them all: an answer that
    # picked one silently would be the map choosing, which is the thing it
    # says out loud everywhere else.
    also = sorted({s[0] for s in holding})
    file, start, end, kind, name = next(s for s in holding if s[0] == also[0])
    body = (lines.get(file) or [])[start - 1:end]
    if not body:
        return (f"{file}:{start}-{end} {name} ({kind}), and this map holds no "
                "lines for that file")
    head = f"{file}:{start}-{end} {name} ({kind})"
    if len(also) > 1:
        head += (f" ({wanted} also matches "
                 + ", ".join(f for f in also if f != file)
                 + "; this is the first in path order)")
    if offset >= len(body):
        return _stale(f"{name} is {len(body)} lines long, and this handle asks "
                      f"for line {offset + 1} of it")

    rest = body[offset:]
    most = len(rest)
    field = _encode(target)

    def tail(count: int, handle: bool) -> str:
        left = most - count
        if not left:
            return ""
        with_handle = f" (more:at:{field}:{offset + count})" if handle else ""
        return f"\n… {left} more lines{with_handle}"

    def block(count: int, handle: bool) -> str:
        return "\n".join([head] + rest[:count]) + tail(count, handle)

    # How long the block would be, without building it. `at` is asked about a
    # definition, and a definition can be eleven thousand lines: joining the
    # whole list once per candidate count took 1.4 seconds on one, against
    # 0.06 for every other lookup this tool answers. The lengths are a running
    # sum, the count is found by bisection over it, and the text is joined
    # once, at the end.
    grown = list(accumulate((len(row) + 1 for row in rest), initial=0))

    def size(count: int, handle: bool) -> int:
        return len(head) + grown[count] + len(tail(count, handle))

    for handle in (True, False):
        # A handle only where at least one line came back: a tail pointing at
        # the offset it was given is a chain that never advances.
        low, high = (1 if handle else 0), most
        if size(low, handle) > limit:
            continue
        while low < high:
            mid = (low + high + 1) // 2
            if size(mid, handle) <= limit:
                low = mid
            else:
                high = mid - 1
        # The bisection is over the lines, which only grow; the tail shrinks by
        # a digit or two as the count rises, so the found count can be one or
        # two long. Walked back, never far.
        while low > (1 if handle else 0) and size(low, handle) > limit:
            low -= 1
        if size(low, handle) <= limit:
            return block(low, handle)
    return head


# What `--context` and the MCP `context` tool print at, in characters: the
# same budget one `ask` answer gets, because it lands in the same
# conversation and is paid for again on every turn after.
CONTEXT_BUDGET = 12000

# How far `context` walks the blast radius. One hop, because the block is a
# fifth of one answer and depth 3 on a name forty files reach is the whole
# answer; the first line of every reply says so, and `impact` itself takes a
# depth for the reader who wants more.
CONTEXT_DEPTH = 1

# The five blocks `context` composes, in the order it prints them: the tool
# each block is the answer of, the head it prints, and the percentage of the
# budget it is guaranteed.
#
# A floor, not a cap. `_context_rooms` spends the budget in two passes: pass
# one asks every block what printing all of itself would cost, and pass two
# gives every block the smaller of that need and its floor and then hands
# what nobody claimed on, in this order, to the blocks still short. So a
# block never takes room from a block that wanted it, and a block is never
# cut while room the answer was allowed goes unspent.
#
# Strict shares were tried first and are the wrong shape: on the suite
# fixture at a 12000 character budget, `CheckoutPage` printed 6,462 characters
# of it and left 12 of its 41 declarations behind a handle, because its
# declarations wanted more than 15 percent while callers, callees and impact
# between them left thousands unspent. Eleven of the 224 names were cut that
# way with room to spare. What a fixed share buys is being able to say in
# advance what each block costs; the two passes keep the answer to a name
# deterministic, which is the half of that anyone reads.
#
# The order is the printing order, so what is said first is served first.
# The shares are stated in the first line of every answer and in the README
# beside the flag.
CONTEXT_BLOCKS = (
    ("spans", "## Declared in", 15),
    ("ask", "## What the map says", 35),
    ("callers", "## Callers", 15),
    ("callees", "## Callees", 15),
    ("impact", "## Impact", 20),
)
CONTEXT_NAMES = tuple(block for block, _head, _pct in CONTEXT_BLOCKS)
CONTEXT_HEADS = {block: head for block, head, _pct in CONTEXT_BLOCKS}

# A directory head `_group_dirs` wrote (``- `steps/` ``) and the rows it owns.
_GROUPED_HEAD = re.compile(r"^- `([^`]*/)`$")
_GROUPED_ROW = re.compile(r"^  - `([^`]+)`(.*)$")


def _ungroup_dirs(lines: list) -> list:
    """`_group_dirs` undone: every row carrying its own whole path again.

    `ask()` prints a run of rows under one directory head to save repeating
    the prefix, which reads well in an answer nobody is going to cut a second
    time. A `context` block is cut a second time, and a row that only means
    something under a head three lines above it is not a whole row: cut
    between the two, ``  - `login_steps.py` `` is a file the reader cannot
    place, and no handle puts the head back, because the handle continues the
    list from below it.

    Measured on the suite fixture at 1500 characters: seventeen names lost a
    row exactly this way, and none of them after this.
    """
    out, directory = [], None
    for line in lines:
        head = _GROUPED_HEAD.match(line)
        if head:
            directory = head.group(1)
            continue
        row = _GROUPED_ROW.match(line) if directory else None
        if row:
            out.append(f"- `{directory}{row.group(1)}`{row.group(2)}")
            continue
        directory = None
        out.append(line)
    return out


def _context_lines(map_path: str, block: str, name: str, limit: int) -> list:
    """One block's whole answer, as lines, before it is cut to its share.

    Each block is what the tool of that name returns for this name, and
    nothing is summarised on the way: an empty block carries the same
    sentence the single call prints, so a `context` answer at a budget that
    fits it holds every row the five calls hold.

    `callers` and `callees` print one row per hit rather than the one comma
    separated line their flags print, and `spans` one row per name, because a
    block is cut by whole rows and a single line cannot be cut at all.

    `limit` is this call's own budget, and the `ask` block is rendered at it
    rather than at its share: the share decides how much of that answer is
    printed here, and the handle under it fetches the rest of the same
    answer, so a reader following the handle never meets a differently
    ranked one.
    """
    json_path = os.path.join(os.path.dirname(map_path) or ".",
                             "framework_map.json")
    if block == "spans":
        rows = spans_for(map_path, [name.lower()], cap=0)
        return [f"- {r}" for r in rows] or \
            [f"no declaration of {name!r} in the map"]
    if block == "ask":
        # Without its blank lines, and with the directory grouping undone. A
        # blank line is not a row, and this block is cut by whole rows: left
        # in, they cost nothing to fit and so always fit, and a block small
        # enough to hold two of them and nothing else came back as two blank
        # lines under a head.
        return _ungroup_dirs([line for line
                              in ask(map_path, name, limit).splitlines()
                              if line.strip()])
    if block == "callers":
        hits = callers(json_path, name)
        return [f"- {h}" for h in hits] or [f"nothing in the map calls {name}"]
    if block == "callees":
        hits = callees(json_path, name)
        return [f"- {h}" for h in hits] or [f"{name} calls nothing in the map"]
    return impact(json_path, name, CONTEXT_DEPTH).splitlines()


def _context_chunk(head: str, lines: list, room: int, block: str,
                   field: str, base: int) -> tuple:
    """One `context` block, cut to `room`, with its `more:ctx:` handle."""
    return _block_chunk(head, lines, room,
                        lambda got: f"more:ctx:{block}:{field}:{got}", base)


def _block_chunk(head: str, lines: list, room: int, handle_at, base: int) -> tuple:
    """`head` plus as many of `lines` as fit in `room`, with the tail that
    says how many are left and the handle that fetches them.

    Returns `(chunk, reached)`: the text, and how far into `lines` this got
    counted from `base`, which is what the handle's offset is and what
    `more()` checks to see whether it made any progress.

    `_fit_chunk` is the cut, shared with `_rows_chunk`; what belongs to this
    block is the tail it writes. A block whose head alone would overrun
    prints nothing, rather than a head with a count under it. A block with no
    line printed still prints its head and its tail: at a small budget the
    impact block is one caveat longer than the room it was given, and a head
    with `… 6 more lines (more:ctx:impact:charge:0)` under it is the
    difference between a block a reader can fetch and a block they cannot see
    exists.

    `handle_at(reached)` writes the handle that fetches the rest, and is
    where the two kinds of block differ: `context` prints a `more:ctx:` one
    and `affected` a `more:aff:`. Everything else about the cut, the tail and
    the floor below is the same for both, so both are the same code.
    """
    def tail_for(left: int, got: int, handle: bool) -> str:
        if not left:
            return ""
        plural = "" if left == 1 else "s"
        if handle:
            return f"… {left} more line{plural} ({handle_at(got)})"
        # No room for the handle beside the count. Say that, rather than
        # print a count of lines with nothing that fetches them: a reader
        # told there is more and not told how to get it has been handed a
        # fact with nothing behind it.
        #
        # `context` never gets here: `_block_floor` is the room for a head
        # and a tail with its handle, and a block that cannot be given that
        # much is left out of the answer instead. `more()` can, since it cuts
        # a block at whatever budget it was called with and a caller may ask
        # for two hundred characters. Measured: 0 of 1,666 `context` answers
        # over the three fixtures at seven budgets print this line.
        return f"… {left} more line{plural}; no room for a handle"

    chunk, reached, _lines, _tail = _fit_chunk(head, lines, room,
                                               RESERVE_CONTEXT, tail_for,
                                               None, base)
    return chunk, reached


def _context_need(head: str, lines: list) -> int:
    """The room one block needs to print all of itself.

    Its head, its lines with the newline each one costs, and the tail's
    reserve, which every block pays whether or not it ends up printing a
    tail. Exactly the number `_fit_chunk` has to be given for `fit_indices`
    to keep every line, so a block given this much is never cut and a block
    given less always is.
    """
    return RESERVE_CONTEXT + len(head) + sum(len(line) + 1 for line in lines)


def _block_floor(head: str, lines: list, handle: str) -> int:
    """The smallest room a block can be given and still be worth printing:
    its head, and a tail carrying the handle that fetches the whole of it.

    A head with a count under it and no handle beside the count names a list
    nobody can ask for, and the room it costs is room the block above it
    could have spent on its own handle. So this is a block's floor as much as
    its percentage share is, and below it the block is left out of the answer
    rather than printed as a stub.
    """
    tail = (f"… {len(lines)} more line{'' if len(lines) == 1 else 's'} "
            f"({handle})")
    return max(len(head) + RESERVE_CONTEXT + 1, len(head) + 1 + len(tail))


def _context_rooms(room: int, lines: dict, field: str) -> dict:
    """How much of `room` each `context` block gets."""
    return _block_rooms(room, CONTEXT_BLOCKS, lines,
                        lambda block: f"more:ctx:{block}:{field}:0")


def _block_rooms(room: int, blocks: tuple, lines: dict, handle_for) -> dict:
    """How much of `room` each block gets, in two passes.

    Pass one asks every block what printing all of itself would cost
    (`_context_need`). Pass two walks the blocks in the order they are
    printed in and gives each one the smaller of that need and its floor, out
    of what is left; then it walks them again and hands what nobody claimed
    to the blocks still short of their need, each taking up to what it is
    missing. `context` and `affected` are both cut this way, with their own
    block tuples and their own handles.

    So the percentages beside the blocks are floors rather than caps: a
    block is guaranteed its share and may have more when the others do not
    want theirs. The consequence worth stating is the one the whole tool is
    for: when the five answers together fit the budget, every one of them is
    printed whole, and `context` really is the five calls rather than five
    cuts of them.

    Two passes rather than a forward carry, because the block that is short
    is usually the first one. `spans` is printed before `callers`, `callees`
    and `impact`, and it is their unspent share that covers it; a carry could
    only ever help the blocks after the one that saved. Measured on the suite
    fixture at 12000 characters, `CheckoutPage`: `spans` needs 3,411 against a
    floor of 1,777, and the second pass covers the difference out of the 4,000
    or so that `callers` (96 needed against 1,777), `callees` (the same) and
    `impact` (647 against 2,370) never wanted.

    A block's floor is the larger of its percentage share and
    `_block_floor`, and a block that cannot be given that much out of what
    is left is given nothing at all. That happens below about six hundred
    characters, where five heads, five counts and five handles do not fit
    between them: there the blocks are served in order and the ones that fit
    are printed as a head and a handle, so the answer says what it did not
    print and how to fetch it. A block is printed whole only once its share
    covers all of it, which is later still. Measured on the same fixture,
    `click_7`: two blocks at 300 characters, three at 350, all five at 600,
    and the first block printed whole at 800.

    Deterministic: the needs come from the map, the floors from the block
    tuple and the heads, and the order is the order the blocks are printed
    in, so the same question at the same budget is always allocated the same
    way.
    """
    need = {block: _context_need(head, lines[block])
            for block, head, _pct in blocks}
    given, spare = {}, room
    for block, head, pct in blocks:
        want = min(need[block], max((room * pct) // 100,
                                    _block_floor(head, lines[block],
                                                 handle_for(block))))
        given[block] = want if want <= spare else 0
        spare -= given[block]
    for block, _head, _pct in blocks:
        if spare <= 0:
            break
        if not given[block]:
            continue  # a block there was no room to print stays unprinted
        extra = min(spare, need[block] - given[block])
        given[block] += extra
        spare -= extra
    return given


def context(map_path: str, name: str, limit: int = CONTEXT_BUDGET) -> str:
    """Everything the map holds about one name, in one answer.

    Five calls: `defines` for every home with its span, `ask` for the
    signature and the rows that mention it, `callers`, `callees`, and
    `impact` at depth 1. An agent that lands on a name made all five, paid
    the tool call overhead five times and read the same map file five times
    to do it. This is those functions, over that map, once.

    The blocks are `CONTEXT_BLOCKS`, and the percentage beside each one is
    the floor of what it gets: `_context_rooms` gives every block the smaller
    of its share and what it needs, then hands the rest on in that order to
    the blocks still short. The first line of every answer says so, so a
    reader who is handed a cut block knows what cut it. Whole rows; a tail
    under every block that could not print all of itself; a `more:ctx:`
    handle on that tail, which the `more` tool resolves like any other.

    The map rows block is `ask()`'s answer whole, its own `## Defined here`
    and `## Called by` included, so a home or a caller can appear twice: once
    in the block that is only about that, and once inside the answer `ask`
    would have given on its own. That is the point rather than an oversight.
    This is the five answers, not a summary of them, and a reader comparing
    it against the single call has to find the single call's own text in it.
    """
    name = _bare(name)
    if not name:
        return "context needs a name"
    field = _encode(name)
    shares = "/".join(str(pct) for _b, _h, pct in CONTEXT_BLOCKS)
    # Every character of this line is a character no block gets. At 12000 it
    # is one percent of the answer and at the MCP server's 1500 floor it is
    # twelve, so it says what the reader has to act on and nothing else: the
    # five blocks in order, the ceiling, and the shares. That the shares are
    # floors rather than caps is what `floor` says; the README and the skill
    # file explain the pass-on rule, and a reader who wants it there does not
    # need it in every answer.
    head = (f"Context for `{name}`: declared, map rows, callers, callees, "
            f"impact to depth {CONTEXT_DEPTH}. {limit} characters, floor "
            f"shares {shares} percent.")
    if len(head) > limit:
        # `limit` is a ceiling, as it is for `ask()`, and this line is the
        # smallest thing this tool has to say. Under it there is no answer,
        # not a first line that overruns.
        return ""
    # Every block pays for the blank line above it, so what the blocks divide
    # is what is left after the first line and those separators, and the
    # answer is inside `limit` however it divides.
    room = limit - len(head) - 2 * len(CONTEXT_BLOCKS)
    out = [head]
    if room > 0:
        lines = {block: _context_lines(map_path, block, name, limit)
                 for block in CONTEXT_NAMES}
        rooms = _context_rooms(room, lines, field)
        for block, bhead, _pct in CONTEXT_BLOCKS:
            if not rooms[block]:
                continue
            chunk, _reached = _context_chunk(bhead, lines[block],
                                             rooms[block], block, field, 0)
            if chunk:
                out.append(chunk)
    return "\n\n".join(out)


# What one `affected` answer may take, in characters. The same ceiling
# `ask()` and `context` print at, so a selection read off the command line
# and a selection read off the MCP tool are the same answer at the same size.
AFFECTED_BUDGET = 12000


def affected_answer(map_path: str, files, depth: int = DEFAULT_DEPTH,
                    fmt: str = "", limit: int = AFFECTED_BUDGET) -> str:
    """Which tests a change to `files` reaches, from the graph in the map.

    `graph.affected` does the walk and this cuts it: the first line states
    the counts, the depth and the ceiling, and each block below gets the
    smaller of what it needs and its floor share, with what nobody claimed
    handed on in printing order, exactly as `context` divides its own budget.
    A block that could not print all of itself ends in a tail carrying a
    `more:aff:` handle, and `more()` continues that block from the line the
    handle names.

    A block with nothing in it is not printed at all: the first line has
    already said the count, and five heads over five empty lists are five
    rows of a budget spent saying nothing twice. `fmt` replaces the blocks
    with the one list a runner takes, `behave` or `pytest`, which is then the
    whole answer and is printed even when it is empty, because there the
    empty list is the answer.

    A block there is no room to print at all still gets a line: `… 2 rows in
    pages; raise the budget (more:aff:pages:...)`. `context` drops such a
    block silently, which is bearable when the reader asked about a name and
    can ask again; here the answer is a test selection, and a list of rows
    the reader cannot see and cannot fetch is the shape that makes a
    selection wrong rather than short. The room for those lines is taken out
    of the blocks' own share before they are allocated.
    """
    named = [f for f in files if f]
    if not named:
        return "affected needs the files a change touched"
    if fmt and fmt not in AFFECTED_FORMATS:
        return (f"{fmt!r} is not a format; they are "
                + ", ".join(AFFECTED_FORMATS))
    result = affected(load_map(os.path.dirname(map_path) or "."), named, depth)
    head = summary(result, limit)
    if len(head) > limit:
        # `limit` is a ceiling here as it is for `ask()` and `context`, and
        # this line is the smallest thing this tool has to say. Under it
        # there is no answer, not a first line that overruns.
        return ""
    field = _encode(",".join(named))
    walked = result["depth"]

    def handle_for(block: str):
        return lambda got: f"more:aff:{block}:{field}:{walked}:{got}"

    if fmt:
        room = limit - len(head) - 2
        chunk = ""
        if room > 0:
            chunk, _reached = _block_chunk(format_head(result, fmt),
                                           block_lines(result, fmt), room,
                                           handle_for(fmt), 0)
        out = [head] + ([chunk] if chunk else [])
        if not chunk:
            out += _left_out([fmt], {fmt: block_lines(result, fmt)},
                             handle_for, limit - len(head) - 2)
        return "\n\n".join(out)

    lines = {block: block_lines(result, block) for block in AFFECTED_NAMES}
    blocks = tuple(entry for entry in AFFECTED_BLOCKS if lines[entry[0]])
    out = [head]
    # Every block pays for the blank line above it, so what the blocks divide
    # is what is left after the first line and those separators, and the
    # answer is inside `limit` however it divides.
    room = limit - len(head) - 2 * len(blocks)
    rooms: dict = {}
    if blocks and room > 0:
        rooms = _affected_rooms(room, blocks, lines, handle_for)
        for block, bhead, _pct in blocks:
            if not rooms.get(block):
                continue
            chunk, _reached = _block_chunk(bhead, lines[block], rooms[block],
                                           handle_for(block), 0)
            if chunk:
                out.append(chunk)
    text = "\n\n".join(out)
    short = [block for block, _h, _p in blocks if not rooms.get(block)]
    return "\n\n".join([text] + _left_out(short, lines, handle_for,
                                           limit - len(text) - 2))


def _left_line(block: str, rows: list, handle_for) -> str:
    """The one line a block nobody had room for gets: how many rows it holds
    and the handle that fetches them."""
    n = len(rows)
    return (f"… {n} row{'' if n == 1 else 's'} in {block}; raise the budget "
            f"({handle_for(block)(0)})")


def _left_out(short: list, lines: dict, handle_for, room: int) -> list:
    """Those lines for every block that was not printed, as one paragraph,
    while they fit in what is left.

    In order, and the ones that do not fit are dropped: at a budget that
    cannot hold five of these there is nothing better to do than print the
    ones it can hold, and the first line still carries the counts.
    """
    out: list = []
    for block in short:
        line = _left_line(block, lines[block], handle_for)
        cost = len(line) + (1 if out else 0)
        if cost > room:
            continue
        out.append(line)
        room -= cost
    return ["\n".join(out)] if out else []


def _affected_rooms(room: int, blocks: tuple, lines: dict, handle_for) -> dict:
    """`_block_rooms`, with the room those "raise the budget" lines need
    taken out of the share first.

    Two or three passes, not one: which blocks are left out decides how much
    those lines cost, and that cost decides which blocks are left out. It
    settles quickly, because giving a block less can only ever leave more
    blocks out, and the loop stops as soon as the same set comes back twice.
    """
    given = _block_rooms(room, blocks, lines, lambda b: handle_for(b)(0))
    for _ in range(3):
        short = tuple(b for b, _h, _p in blocks if not given[b])
        if not short:
            break
        cost = sum(len(_left_line(b, lines[b], handle_for)) + 1
                   for b in short) + 1
        fresh = _block_rooms(max(room - cost, 0), blocks, lines,
                             lambda b: handle_for(b)(0))
        again = tuple(b for b, _h, _p in blocks if not fresh[b])
        given = fresh
        if again == short:
            break
    return given
