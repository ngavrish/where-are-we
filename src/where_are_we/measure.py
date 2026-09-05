"""Turns and searches per session, counted from Claude Code agent transcripts.

A session under `~/.claude/projects/<project>/<session>.jsonl` is one JSON
object per line: "assistant", "user" and other event types ("summary",
"system", "queue-operation", "attachment", ...) share the file, and only
"assistant" lines carry the tool calls an agent made. This module counts, per
session, how many turns (assistant messages) it took, how many of those
turns were spent looking around (`Grep`/`Glob`, a `Bash` search command, or
this project's own map tools) versus doing something else (an edit, a write,
a test run), and how many turns went by before the first non-looking-around
action - the numbers behind "orientation replaced by one --ask" in the
README.

Nothing here reads a whole transcript into memory at once beyond one file's
lines; a session can run to tens of thousands of lines.

`ask_log_summary()` is a second, unrelated report over a different file:
`ask.log_answer` writes one line per map answer to `.wawe-ask.log`, and this
reduces that log to the numbers a README row can quote instead of promising -
median, worst case, and which tool asked for it. `--ask-log DIR` prints it.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime

# A Bash command counts as a search when it starts with one of these words,
# optionally after "cd <dir> &&" (an agent moving into a directory first).
_SEARCH_COMMAND = re.compile(
    r"^(?:cd\s+\S+\s*&&\s*)?(grep|rg|find|ls|ag|ack|fd|tree)\b"
)


def _classify(name: str, tool_input: dict) -> str:
    """Classify one tool_use block as "map", "search", "read" or "other"."""
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str):
        command = ""
    if "where-are-we" in name or "where_are_we" in name:
        return "map"
    if name == "Bash" and "where-are-we --" in command:
        return "map"
    if name in ("Grep", "Glob"):
        return "search"
    if name == "Bash" and _SEARCH_COMMAND.match(command.strip()):
        return "search"
    if name == "Read":
        return "read"
    return "other"


def _tool_uses(message: dict) -> list[tuple[str, dict]]:
    """The (name, input) pairs of every tool_use block in one message."""
    content = message.get("content")
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            out.append((block.get("name", ""), block.get("input") or {}))
    return out


def _parse_session(path: str) -> tuple[dict, int]:
    """One session's summary dict, and the count of lines that did not parse."""
    turns = 0
    searches = 0
    map_calls = 0
    reads = 0
    first_map_call_turn = None
    first_other_turn = None
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(event, dict) or event.get("type") != "assistant":
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            turns += 1
            kinds = [_classify(n, i) for n, i in _tool_uses(message)]
            if "map" in kinds:
                map_calls += kinds.count("map")
                if first_map_call_turn is None:
                    first_map_call_turn = turns
            searches += kinds.count("search")
            reads += kinds.count("read")
            if first_other_turn is None and "other" in kinds:
                first_other_turn = turns
    orientation_turns = (first_other_turn - 1) if first_other_turn is not None else turns
    summary = {
        "session": os.path.basename(path),
        "turns": turns,
        "searches": searches,
        "map_calls": map_calls,
        "reads": reads,
        "first_map_call_turn": first_map_call_turn,
        "orientation_turns": orientation_turns,
    }
    return summary, skipped


def _summarise_with_skips(paths: list[str]) -> tuple[list[dict], int]:
    rows = []
    skipped_total = 0
    for path in paths:
        row, skipped = _parse_session(path)
        rows.append(row)
        skipped_total += skipped
    return rows, skipped_total


def summarise(paths: list[str]) -> list[dict]:
    """One summary dict per session file in `paths`, in the order given."""
    rows, _ = _summarise_with_skips(paths)
    return rows


def _default_session_files() -> list[str]:
    return glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))


def _session_files(sessions_dir: str | None) -> list[str]:
    if sessions_dir is None:
        return _default_session_files()
    return glob.glob(os.path.join(sessions_dir, "*.jsonl"))


def _median(values) -> float | None:
    values = list(values)
    return statistics.median(values) if values else None


def _median_row(rows: list[dict]) -> dict:
    row = {"session": "median"}
    for key in ("turns", "searches", "map_calls", "reads", "orientation_turns"):
        row[key] = _median(r[key] for r in rows)
    row["first_map_call_turn"] = _median(
        r["first_map_call_turn"] for r in rows if r["first_map_call_turn"] is not None
    )
    return row


_HEADERS = [
    "session", "turns", "searches", "map_calls", "reads",
    "first_map_call_turn", "orientation_turns",
]


def _print_table(rows: list[dict]) -> None:
    display_rows = rows + [_median_row(rows)] if rows else []
    widths = {h: len(h) for h in _HEADERS}
    for row in display_rows:
        for h in _HEADERS:
            widths[h] = max(widths[h], len(str(row.get(h, ""))))

    def fmt(values: dict) -> str:
        return "  ".join(str(values.get(h, "")).ljust(widths[h]) for h in _HEADERS)

    print(fmt({h: h for h in _HEADERS}))
    for row in display_rows:
        print(fmt(row))


def _percentile(sorted_vals: list, pct: float) -> float:
    """Linear-interpolation percentile, the way most stats libraries define
    it, without pulling one in for four lines of arithmetic."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(sorted_vals[int(k)])
    return (sorted_vals[lo] * (hi - k)) + (sorted_vals[hi] * (k - lo))


def ask_log_summary(path: str) -> dict:
    """Median, p95 and max token size of every logged answer, plus how many
    came from each tool. A missing or empty log summarises to all zeros -
    there is nothing wrong with a run that never asked."""
    tokens, by_tool = [], collections.Counter()
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        tokens.append(row.get("tokens", 0))
        by_tool[row.get("tool", "?")] += 1
    if not tokens:
        return {"n": 0, "median_tokens": 0, "p95_tokens": 0, "max_tokens": 0,
                "by_tool": {}}
    ordered = sorted(tokens)
    return {
        "n": len(tokens),
        "median_tokens": int(round(statistics.median(ordered))),
        "p95_tokens": int(round(_percentile(ordered, 0.95))),
        "max_tokens": max(ordered),
        "by_tool": dict(by_tool),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wawe-measure",
        description="Turns, searches and map calls per session, from Claude Code agent transcripts.",
    )
    parser.add_argument(
        "--sessions", default=None,
        help="directory of *.jsonl transcripts (default: every ~/.claude/projects/*/ directory)",
    )
    parser.add_argument(
        "--since", default=None,
        help="only sessions whose file was modified on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument("--json", action="store_true", help="print the rows as JSON, no table")
    parser.add_argument(
        "--ask-log", default=None, metavar="DIR",
        help="print the size of every map answer logged under DIR/.wawe-ask.log "
             "instead: n, median/p95/max tokens, and how many came from each tool",
    )
    args = parser.parse_args(argv)

    if args.ask_log:
        summary = ask_log_summary(os.path.join(args.ask_log, ".wawe-ask.log"))
        if args.json:
            print(json.dumps(summary))
        else:
            print(f"n={summary['n']}  median_tokens={summary['median_tokens']}  "
                  f"p95_tokens={summary['p95_tokens']}  max_tokens={summary['max_tokens']}  "
                  f"by_tool={summary['by_tool']}")
        return 0

    paths = sorted(_session_files(args.sessions))
    if args.since:
        cutoff = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        paths = [p for p in paths if os.path.getmtime(p) >= cutoff]

    rows, skipped = _summarise_with_skips(paths)

    if args.json:
        print(json.dumps(rows))
    else:
        _print_table(rows)

    if skipped:
        print(f"skipped {skipped} unparsable lines", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
