"""`ask()`: the part of the map that mentions these words, and nothing else.

Moved out of `mapper.py` because three places there trimmed a list to a
budget, each with its own copy of "keep whole items in order while they fit,
count what didn't" — the definitions block, a section's matching rows, and
`_cap_sections`'s per-section share. `fit_lines` is that one loop; everything
below it is naming what goes in and out.
"""

import json
import os
import re
from datetime import datetime, timezone

RESERVE_TAIL = 96  # a section's tail line ("… 37 more matching rows; 210 rows
# in this section do not mention these words"), paid for up front so the tail
# never pushes an answer past its limit. Longer than any tail the two counts
# can produce.
RESERVE_DEFINED = 32  # the "… N more definitions" line in `## Defined here`,
# paid for up front the same way.

_ROW_PATH = re.compile(r"^- `([^`]*/)([^`/]+)`(.*)$")


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


def fit_lines(lines: list, budget: int, cost=len, sep: int = 1) -> tuple:
    """Whole lines, in order, while `used + cost(line) + sep <= budget`.

    Best-fit, not a prefix: a line that does not fit is skipped and counted,
    and a later, shorter line may still fit. Returns the kept lines and how
    many were dropped.
    """
    kept, used, dropped = [], 0, 0
    for line in lines:
        c = cost(line)
        if used + c + sep > budget:
            dropped += 1
            continue
        kept.append(line)
        used += c + sep
    return kept, dropped


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


def _defined_here(exact: list, room: int) -> str:
    """The definitions block, whole lines up to `room`, with a count of what
    did not fit. Empty when not even one definition fits.

    The section loop bounds itself against `limit`; this block runs first, so
    30 short definitions used to come back 1186 characters at every limit
    from 50 to 1000 — a ceiling that only held after the block that runs
    first.
    """
    head = "## Defined here\n"
    budget = room - RESERVE_DEFINED
    if budget <= len(head):
        return ""  # not even the head fits: nothing, not a head with a count
    kept_rows, dropped = fit_lines(exact, budget - len(head))
    kept = [head] + kept_rows
    if dropped:
        kept.append(f"… {dropped} more definitions")
    return "\n".join(kept) if len(kept) > 1 else ""


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
    out.sort(key=lambda x: -x[0])
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
    matching, unmatched = [], 0
    for line in body:
        if not line.strip():
            continue
        if line.startswith("**"):
            continue
        if any(t in line.lower() for t in terms):
            matching.append(line)
        else:
            unmatched += 1
    return matching, unmatched


def _definitions_block(map_path: str, terms: list, room: int) -> str:
    """`## Defined here`, bounded to `room`; empty when nothing was defined
    under these terms."""
    # This import must stay right here, function-local, and reference the
    # module rather than pull a name out of it. mapper.py imports this module
    # at load time with a plain top-level `from .ask import ask, fit_lines`,
    # so a module-level or name-extracting import here
    # (`from .mapper import _definitions_for`) raises "cannot import name
    # from partially initialized module" whenever `where_are_we.ask` is
    # imported before `where_are_we.mapper`. Deferring the import to call
    # time, and only binding the module object, sidesteps that: by the time
    # this function actually runs, both modules have finished loading.
    try:
        from . import mapper as _mapper
    except ImportError:  # run as a plain file, with no package around it
        import mapper as _mapper  # type: ignore[no-redef]
    exact = _mapper._definitions_for(map_path, terms)
    if not exact:
        return ""
    return _defined_here(exact, room)


def _section_answer(head: str, body: list, terms: list, room: int) -> tuple:
    """One section's answer: matching rows, grouped by directory, with a tail
    saying what didn't fit or didn't match.

    Returns `(chunk, attempted)`. `chunk` is empty when the section has
    nothing to show. `attempted` is true whenever the section's head alone
    fit in `room` — independent of whether a chunk came out of it — and feeds
    `seen`, for the "more sections match" note.
    """
    matching, unmatched = _split_rows(body, terms)
    # `room` is a ceiling, not a target. The tail line is paid for up front,
    # the head is included only if it fits, and no row is forced in: a first
    # row longer than the room is a dropped row, not an exception. Measured
    # at review: a 3 KB head with limit=50 came back 68 times over budget
    # when the head and first row were forced.
    budget = room - RESERVE_TAIL
    if budget <= len(head):
        return "", False  # this section's head alone would overrun; skip it, not every section after
    kept_rows, dropped = fit_lines(matching, budget - len(head))
    kept = [head] + _group_dirs(kept_rows)
    tail = []
    if dropped:
        tail.append(f"… {dropped} more matching rows")
    if unmatched:
        tail.append(f"{unmatched} rows in this section do not mention these words")
    if tail:
        kept.append("; ".join(tail) if dropped else "… " + tail[0])
    if len(kept) == 1:
        return "", True
    return "\n".join(kept), True


def _more_note(room: int) -> str:
    """The "more sections match" note, only if it fits: a note that says
    "more" when there is no more, or that pushes the answer past its limit,
    is the defect this guards."""
    note = "… more sections match; ask for something narrower"
    return note if len(note) + 2 <= room else ""


def ask(map_path: str, words: str, limit: int = 12000) -> str:
    """The part of the map that mentions these words, and nothing else.

    A map is generated so nobody has to search the repository. Then it is 253 KB,
    and searching *it* is the same problem one size down: grep hands back matching
    lines with no idea which section they came from, so the reader either takes
    the lines without their meaning or opens the whole file — and opening the
    whole file puts it into every message that follows.

    So: sections, ranked by how much they mention what was asked, cut to a size
    that answers rather than a size that has to be paid for on every later turn.
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
    # `room` up front so that line never pushes an answer past `limit` -
    # `limit` is a ceiling for everyone who calls `ask()`, this note included.
    candidates = list(dict.fromkeys(t for t in expanded if t not in terms))
    note_room = len(f"(also matched: {', '.join(candidates)})") + 2 if candidates else 0

    blocks = _blocks(text)
    scored = _rank(blocks, expanded, half)
    if not scored:
        block = _definitions_block(map_path, expanded, limit)
        if block:
            return block
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

    scored.sort(key=lambda x: -x[0])
    out, room = [], limit - note_room
    block = _definitions_block(map_path, expanded, room)
    if block:
        out.append(block)
        room -= len(block) + 2
    seen = 0
    for hits, h, b in scored:
        chunk, attempted = _section_answer(h, b, expanded, room)
        if attempted:
            seen += 1
        if chunk:
            out.append(chunk)
            room -= len(chunk) + 2
    if seen < len(scored):
        # Only when a matching section really went unshown, and only if the
        # note itself fits: a note that says "more" when there is no more, or
        # that pushes the answer past its limit, is the defect this guards.
        note = _more_note(room)
        if note:
            out.append(note)
    answer = "\n\n".join(out)
    # Said once, up front, only when it earned its place: a synonym or a stem
    # that turned up nothing beyond what the literal words already found is
    # not worth a line, so this checks the answer itself rather than assuming
    # every expansion mattered.
    extra = [t for t in candidates if t in answer.lower()]
    if extra:
        answer = f"(also matched: {', '.join(extra)})\n\n" + answer
    return answer


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
    if os.environ.get("WAWE_ASK_LOG") == "0":
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
