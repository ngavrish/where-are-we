"""The command line: `where-are-we`, and the two things it can write into a
repository (a starter manifest, and the READMEs it is missing).

`main()` is the only place that reads argv, prints to stdout, or decides what
goes where; every other module in the package is a library it calls.

It lives here, beside the public modules, and not in `_mapper/`, because it is
the outermost layer: it depends on `build`, `render`, `ask`, `mcp`, `lsp`,
`hooks`, `readmes`, `semantic` and `specs`, and nothing depends on it except
the console script. While it sat inside the private package, the facade had to
re-export `main` from it, which made `mapper` depend on the layer above it and
put every module in the package on a cycle: eleven imports were written inside
functions for no reason other than to dodge one. They are ordinary top-level
imports now.
"""

import argparse
import contextlib
import html as html_mod
import io
import json
import os
import re
import sys

# Two-way imports, as everywhere else in this package: relative when there is a
# package around this file, plain when `mapper.py` is being run by path and
# `src/where_are_we` is itself the import root.
try:
    from . import ask as _ask, effects, hooks, lsp, mcp, specs
    from .ask import (IMPACT_MAX_DEPTH, RANK_LIMIT, ask, at, callees_line,
                       callers, context, file_list, impact, log_answer,
                       map_heads, rank_lines, spans_for)
    from ._mapper.build import build, declares_rows, sort_xrefs
    from ._mapper.render import (CTAGS_NAME, _as_dict, _cap_sections, brief,
                                 changed_since, cost, ctags, digest, export,
                                 for_audience, meaning_tail, pointer)
    from ._mapper.declare import spans_index
    from ._mapper import state
    from ._mapper.state import DEFINITIONS, INDEXED
    from ._mapper.walk import (SKIP_DIRS, _PARSE_CACHE_FILE, _config,
                               _load_parse_cache, _product_roots,
                               _write_atomic, _write_atomic_group,
                               content_root, fingerprint, redact)
except ImportError:  # run as a plain file, with no package around it
    import ask as _ask  # type: ignore[no-redef]
    import effects  # type: ignore[no-redef]
    import hooks  # type: ignore[no-redef]
    import lsp  # type: ignore[no-redef]
    import mcp  # type: ignore[no-redef]
    import specs  # type: ignore[no-redef]
    from ask import (IMPACT_MAX_DEPTH, RANK_LIMIT, ask,  # type: ignore[no-redef]
                     at, callees_line, callers, context, file_list, impact,
                     log_answer, map_heads, rank_lines, spans_for)
    from _mapper.build import (build,  # type: ignore[no-redef]
                               declares_rows, sort_xrefs)
    from _mapper.render import (CTAGS_NAME,  # type: ignore[no-redef]
                                _as_dict, _cap_sections, brief, changed_since,
                                cost, ctags, digest, export, for_audience,
                                meaning_tail, pointer)
    from _mapper.declare import spans_index  # type: ignore[no-redef]
    from _mapper import state  # type: ignore[no-redef]
    from _mapper.state import DEFINITIONS, INDEXED  # type: ignore[no-redef]
    from _mapper.walk import (SKIP_DIRS,  # type: ignore[no-redef]
                              _PARSE_CACHE_FILE, _config, _load_parse_cache,
                              _product_roots, _write_atomic,
                              _write_atomic_group, content_root, fingerprint,
                              redact)


def _write_error(exc: OSError, fallback: str = "") -> int:
    """One line naming the file that could not be written, and exit 1.

    Every write path here used to let a PermissionError out of main(): an
    unwritable --out, an --agent-file in a read-only directory, --init on a
    repository checked out read-only. This tool runs from a SessionStart hook,
    where a traceback is thirty lines of noise in a session transcript instead
    of the one line that says which path to fix.

    The atomic writer stages into `<path>.<pid>.tmp`, so the suffix is trimmed
    off before the name is printed: the caller cares about the file it asked
    for, not the temporary beside it.
    """
    path = getattr(exc, "filename", None) or fallback
    path = re.sub(r"\.\d+\.tmp$", "", str(path))
    print(f"framework_map: cannot write {path}: {exc.strerror or exc}",
          file=sys.stderr)
    return 1


# The three map files, in the order they are renamed into place once all three
# have been written to their temporaries.
#
# `framework_map.md` is renamed last on purpose. It is the file every read path
# opens first: `--ask`, `--sections`, `--pointer`, the MCP server, the language
# server, and `hooks._ensure_map`, which treats its presence as "this directory
# has a map". Renaming it last means a reader that has the new Markdown always
# has the new JSON behind it, so a name `ask` has just shown can always be
# located by `defines`. The other order gives the opposite, and worse, window:
# `ask` naming something that `defines` then says is not in the map.
def _write_map_files(out_dir: str, json_text: str, md_text: str,
                     brief_text: str) -> None:
    _write_atomic_group([
        (os.path.join(out_dir, "framework_map.json"), json_text),
        (os.path.join(out_dir, "framework_map_brief.md"), brief_text),
        (os.path.join(out_dir, "framework_map.md"), md_text),
    ])


def _write_artifacts(out_dir: str, m: dict, args) -> None:
    """Everything a build leaves behind, from one map dict and the flags.

    A helper rather than a block inside `main()` because `--watch` has to
    write exactly the same set. It used to write `framework_map.json` and
    `framework_map_brief.md` and nothing else, so a watched repository never
    got `framework_map.md` at all - the file `--ask`, `--sections`,
    `--pointer`, the MCP server and the language server all open first - and
    a session pointed at a watcher's output directory was told there was no
    map. Its brief also skipped `--for`, `--only`, `--skip` and `--max-lines`,
    and it redacted the JSON but not the Markdown.
    """
    os.makedirs(out_dir, exist_ok=True)
    map_json = json.dumps(m, indent=2)
    map_md = digest(m)
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
    # All three at once, and only now: the brief is trimmed by --only/--skip
    # and --max-lines above, so the set is not complete until here.
    _write_map_files(out_dir, map_json, map_md, text)
    if args.html:
        # Deliberately one file with no assets: it gets opened from a terminal,
        # not served.
        #
        # Every interpolated line is repository content: a manifest's purpose,
        # a docstring, a README fence, a file name. It used to go into the
        # element verbatim, so a cloned repository could put <script> in the
        # page, and the page is opened as file://, where script in it can read
        # other local files. html.escape() on each line is the whole defence;
        # the brief is plain text, so nothing here wanted markup anyway.
        body_html = []
        for line in text.splitlines():
            if line.startswith("## "):
                body_html.append(f"<h2>{html_mod.escape(line[3:])}</h2>")
            elif line.startswith("# "):
                body_html.append(f"<h1>{html_mod.escape(line[2:])}</h1>")
            elif line.startswith("- "):
                body_html.append(f"<li>{html_mod.escape(line[2:])}</li>")
            elif line.strip():
                body_html.append(f"<p>{html_mod.escape(line)}</p>")
        html = ("<!doctype html><meta charset=utf-8><title>where are we</title>"
                "<style>body{max-width:60rem;margin:3rem auto;padding:0 1rem;"
                "font:15px/1.6 ui-sans-serif,system-ui,sans-serif;color:#111}"
                "h1{font-size:1.7rem}h2{font-size:1.05rem;margin-top:2.2rem;"
                "border-bottom:1px solid #ddd;padding-bottom:.3rem}"
                "li{margin:.15rem 0}code{background:#f4f4f4;padding:0 .2em;border-radius:3px}"
                "@media(prefers-color-scheme:dark){body{background:#111;color:#eee}"
                "h2{border-color:#333}code{background:#222}}</style>"
                + "\n".join(body_html))
        _write_atomic(os.path.join(out_dir, "framework_map.html"), html)
    if args.ctags:
        # Atomically like every other artefact: an editor reads `tags` while
        # a build is running exactly as often as the MCP server reads the
        # JSON, and a half-written tags file is a binary search over garbage.
        _write_atomic(os.path.join(out_dir, CTAGS_NAME), ctags(m))
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
        _write_atomic(args.agent_file, cur)


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
    _write_atomic(path, json.dumps(skeleton, indent=2, ensure_ascii=False))
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
            _write_atomic(path, text)

    return planned


def install_hook(repo: str, kind: str, product: str, out: str, agent_file: str) -> str:
    """Wire the map into something that already runs, so nobody has to remember it.

    The implementation lives in hooks.py, where cursor, codex and gemini were
    added alongside the original git and Claude Code kinds; this name stays
    because scripts and the CLI already call it.
    """
    return hooks.install(repo, kind, product, out, agent_file)



def _impact_depth(text: str) -> int:
    """`--impact-depth`, refused at the parser rather than answered.

    A depth of 0, 7 or -1 used to reach `impact()`, which printed its
    complaint on stdout and exited 0, with the complaint logged as though it
    were an answer. A caller checking $? believed it, the same way `--callers`
    on a directory with no map used to report an empty result for a search
    that never happened. argparse's own failure is exit 2 and stderr.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a whole number") from None
    if not 1 <= value <= IMPACT_MAX_DEPTH:
        raise argparse.ArgumentTypeError(
            f"must be from 1 to {IMPACT_MAX_DEPTH}, not {value}")
    return value


def _row_limit(text: str) -> int:
    """`--limit`, refused at the parser the way `--impact-depth` is.

    A limit is a ceiling, and a ceiling below one is not a smaller answer.
    `--limit -3` used to reach a list slice, so it printed every definition in
    the map but the last three, and `--limit 0` printed the default two
    hundred; the MCP `rank` tool refused both with -32602. Two spellings of
    one tool disagreeing about what the input means is worse than either
    answer.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer, not {value}")
    return value


def _say_unknown(map_path: str, files) -> None:
    """One line on stderr for a named path nothing in the map matches.

    stdout is untouched, so `--rank` and the MCP `rank` tool still print the
    same bytes; what changes is that a typo is visible instead of answering
    the question the reader did not ask.
    """
    missing = _ask.unknown_files(map_path, files)
    if missing:
        print("nothing indexed under " + ", ".join(repr(m) for m in missing),
              file=sys.stderr)


def _resolve_repo(given, out):
    """The repository a run is about, when --repo was not spelled out.

    The read paths (--mcp, --ask, --pointer, --callers) used to fall back to
    $AGENT_REPO or /work like the build path does, so a server started by a
    hook as `where-are-we --out .wawe --mcp` read another tree's .wawe.toml,
    or none, and a project's own [synonyms] never reached its answers. A
    .wawe directory sits inside the repository it maps, so its parent is the
    repository; /work stays as the container default; the current directory
    is the last resort.
    """
    if given:
        return given
    env = os.getenv("AGENT_REPO")
    if env:
        return env
    out_abs = os.path.abspath(out or ".")
    if os.path.basename(out_abs) == ".wawe":
        return os.path.dirname(out_abs)
    if os.path.isdir("/work"):
        return "/work"
    return os.getcwd()


def _reconfigure_streams() -> None:
    """Never let the terminal's encoding turn an answer into a traceback.

    A harness that exports PYTHONIOENCODING=ascii, or an interpreter whose
    stdout landed on a codec narrower than the map's text, used to make
    `--pointer` fail on every repository (pointer() writes an em dash
    unconditionally) and `--ask` fail on any repository with an accent in a
    name. Both are hook-facing commands, so the failure arrived as thirty
    lines of traceback in a session transcript. Replacing the characters the
    codec cannot carry loses a glyph and keeps the answer, which is the right
    trade for a stream nobody chose.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            # Not a TextIOWrapper (a test capturing into StringIO, a closed
            # stream): nothing to reconfigure and nothing to report.
            pass


def build_parser() -> argparse.ArgumentParser:
    """The whole command line, in one place.

    `main()` parses argv with it and `--effects` classifies a command line
    with it, so what a guard is told about this tool is what this tool
    accepts; a CI step compares the flags this parser knows against the
    effects table and fails on either half of the difference.
    """
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
    ap.add_argument("--repo", default=None,
                    help="the repository to index or answer about (default: "
                         "$AGENT_REPO; then the parent of a .wawe --out; then "
                         "/work if it exists; then the current directory)")
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
    ap.add_argument("--install-hook",
                    choices=["git", "agent", "claude", "cursor", "codex", "gemini"],
                    default="",
                    help="wire the map into something that already runs: git "
                         "hooks (post-checkout, post-merge, post-commit); claude "
                         "(agent is the same thing) for a SessionStart hook in "
                         "Claude Code; cursor, codex or gemini to point that "
                         "CLI's own conventions and MCP config at this repository")
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
                    help="print what changed since the map already in --out: "
                         "the files that moved, then the keys, and exit")
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
    ap.add_argument("--ctags", action="store_true",
                    help="also write <out>/tags: every declaration the map "
                         "holds in universal-ctags format, sorted by name in "
                         "the C locale, with the kind, the line it starts on "
                         "and, where a parser knew it, the line it ends on. "
                         "vim, emacs, helix, kakoune and readtags read it with "
                         "no server running")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when the existing map still matches the "
                         "repository (by default a map is built when it is missing "
                         "or the repository has moved, and skipped otherwise), and "
                         "read nothing from the parse cache while doing it: every "
                         "file is parsed again and the cache is rewritten from "
                         "what this build found. Use it when a file was restored "
                         "or copied with its timestamp kept (rsync --times, cp -p, "
                         "a build cache), which the cache cannot tell from no "
                         "change at all")
    ap.add_argument("--quiet", action="store_true", help="no summary line")
    ap.add_argument("--ask", default="", metavar="WORDS",
                    help="answer from an existing map instead of building one: "
                         "print the rows that mention these words, whole, with a "
                         "count of what was left out, and nothing else. Reads "
                         "framework_map.md under --out.")
    ap.add_argument("--more", default="", dest="more_handle", metavar="HANDLE",
                    help="print what an answer left out, by the handle it "
                         "ended with: `--more 'more:rows:step-phrases:"
                         "invoice:12'`. Continues that same list where the "
                         "answer stopped and ends with the next handle if "
                         "there is more still. Reads the map under --out")
    ap.add_argument("--defines", default="", metavar="NAME",
                    help="print every place NAME is declared: one line per "
                         "name, each home as `file:start-end (kind)`, in path "
                         "order. `-` for an end no parser knew. Reads "
                         "framework_map.json under --out")
    ap.add_argument("--at", default="", dest="at_place", metavar="FILE:LINE",
                    help="print the whole definition that encloses that line, "
                         "the way a stack trace names it: the innermost one, "
                         "whole lines, cut to 12000 characters with a handle "
                         "for the rest. Reads framework_map.json under --out")
    ap.add_argument("--context", default="", dest="context_name",
                    metavar="NAME",
                    help="print everything the map holds about NAME in one "
                         "answer: where it is declared, the map rows that "
                         "mention it, its callers, its callees and its "
                         "impact one hop out. The five reads --defines, "
                         "--ask, --callers, --callees and --impact do, in "
                         "one, each block on a fixed share of 12000 "
                         "characters with a handle for what it cut. Reads "
                         "the map under --out")
    ap.add_argument("--rank", nargs="?", const="", default=None,
                    dest="rank_files", metavar="FILE[,FILE...]",
                    help="print the definitions this repository is built "
                         "around, best first, by PageRank over its own file "
                         "graph. Given files, the walk is personalised on "
                         "them: what to read when you are editing those. "
                         "`--ask WORDS` alongside it weighs the names in the "
                         "question ten times. Reads framework_map.json "
                         "under --out")
    ap.add_argument("--files", default="", metavar="FILE[,FILE...]",
                    help="the files you are working in: on --ask, the rows "
                         "naming one of them are printed first inside every "
                         "section and the rest follow as usual. `-` reads a "
                         "newline separated list on stdin, which is what "
                         "`git diff --name-only` hands over")
    ap.add_argument("--limit", type=_row_limit, default=0, metavar="N",
                    help="how many rows --rank prints (default 200)")
    ap.add_argument("--callers", default="", metavar="NAME",
                    help="print who calls NAME, exactly: one `file:func` per "
                         "line, from the call graphs already in the map. "
                         "Case-sensitive, like the identifier itself. Reads "
                         "framework_map.json under --out")
    ap.add_argument("--callees", default="", metavar="NAME",
                    help="print what NAME calls, the other direction of "
                         "--callers: every callee with the file it is defined "
                         "in, from the same graphs. Cross-file only. Reads "
                         "framework_map.json under --out")
    ap.add_argument("--impact", default="", metavar="NAME",
                    help="print the blast radius of NAME: every `file:func` "
                         "that reaches it, grouped by how many calls away it "
                         "is. Cycles are walked once. Reads "
                         "framework_map.json under --out")
    ap.add_argument("--impact-depth", type=_impact_depth, default=3,
                    metavar="N",
                    help="how many hops back --impact follows, 1 to 6 "
                         "(default 3)")
    ap.add_argument("--specs", default=os.getenv("SPEC_ROOTS", ""),
                    help="ticket keys to map, comma separated: the tracker walked "
                         "once into spec_map.{json,md} so no session has to ask it "
                         "again")
    ap.add_argument("--spec-cmd", default=os.getenv("SPEC_FETCH_CMD", ""),
                    help="how to fetch one ticket as JSON; {key} is substituted. "
                         "This tool knows no tracker — the caller supplies the "
                         "source, as with everything else here. Ignored when "
                         "--spec-source is github or linear, which fill it in")
    ap.add_argument("--spec-source", choices=["cmd", "github", "linear"],
                    default=os.getenv("SPEC_SOURCE", "cmd"),
                    help="'cmd' (default) uses --spec-cmd as given. 'github' "
                         "builds the gh CLI command for the repo under --repo, "
                         "reading owner/name off its origin remote. 'linear' "
                         "builds the GraphQL call and needs LINEAR_API_KEY set")
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
    ap.add_argument("--lsp", action="store_true",
                    help="serve the map as a language server on stdin/stdout: "
                         "go to definition and workspace symbol search, "
                         "answered from the same index as --mcp, framed for "
                         "an editor instead of an agent")
    ap.add_argument("--pointer", action="store_true",
                    help="print what belongs in a prompt: where the map is, what "
                         "sections it has, and how to ask it — never the map itself")
    ap.add_argument("--sections", action="store_true",
                    help="list the section headings of an existing map and exit")
    ap.add_argument("--cost", nargs="?", type=int, const=0, default=None,
                    metavar="THRESHOLD",
                    help="print what each section of an existing map costs to "
                         "carry: rows, bytes and tokens, heaviest first, with "
                         "a total. THRESHOLD hides every section under that "
                         "many bytes. With --json, the same table as JSON. "
                         "Reads framework_map.md under --out")
    ap.add_argument("--export", default=None, metavar="FILE",
                    help="write the map as one self-contained file: what it "
                         "admits it is missing, what it indexed, its sections "
                         "and what each costs, then the brief. For a channel "
                         "with no filesystem - a PR comment, a paste. `-` "
                         "writes it to stdout, which is where a paste usually "
                         "comes from. Any other FILE is wherever the caller "
                         "says, which is why the effects table calls this "
                         "flag writes-repo")
    ap.add_argument("--corpus", action="append", default=[], metavar="NAME=PATH",
                    help="an extra corpus for the semantic index: a markdown "
                         "file or a directory of md/mdc/txt (a rules corpus, a "
                         "runbook). Repeatable. Indexed beside the map when the "
                         "optional [semantic] extra is installed; ignored, "
                         "loudly, when it is not")
    ap.add_argument("--no-semantic", action="store_true",
                    help="skip building the semantic index even when fastembed "
                         "is available")
    ap.add_argument("--effects", action="store_true",
                    help="print what every flag of this tool does to the disk: "
                         "read, writes-map-dir, writes-repo, writes-config or "
                         "network. With --json, the same table as JSON, which "
                         "is also installed beside the code as effects.json. "
                         "With `-- <command line>`, the class of that command "
                         "line and the flags that gave it")
    ap.add_argument("--json", action="store_true",
                    help="with --effects or --cost: print the table as JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every path this command line would write, one "
                         "per line, and exit without writing any of them")
    return ap


def _effects_command(ap: argparse.ArgumentParser, argv: list) -> int:
    """`--effects`: what this tool does to the disk, before it does it.

    Without arguments it prints the table `effects.py` holds; with `--json`
    the manifest that also ships as `effects.json`; with `-- <argv...>` the
    class of that command line and the flag that gave it each class.

    A command line is classified by the parser above, in the one mode that
    runs nothing: `parse_known_args` fills a namespace and stops, so no
    repository is walked and no file is opened. argparse's own complaint
    about a line it cannot parse is caught rather than printed, because a
    command line a guard asks about is one it has not run.
    """
    cut = argv.index("--") if "--" in argv else len(argv)
    head, rest = argv[:cut], argv[cut + 1:]
    if not rest:
        print(effects.as_json() if "--json" in head else effects.as_text(), end="")
        return 0
    cls, reasons = effects.classify(rest, effects.option_strings(ap))
    refused = False
    # Both streams, not just stderr: `--help` is an argparse action that
    # prints the whole help to stdout and then raises SystemExit, and the
    # first line of this command's output is the class.
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        try:
            ap.parse_known_args(rest)
        except SystemExit:
            refused = True
    if any(flag in ("-h", "--help") for flag, _why in reasons):
        # A line asking for help parses; argparse simply answers it and
        # leaves by the same door a bad line does.
        refused = False
    print(cls)
    for name, why in reasons:
        print(f"{name} {why}")
    if refused:
        # Said last, so the first line is still the class: this command line
        # would not run as written, and its class is what its flags carry.
        print("this command line does not parse")
    return 0


def _would(path: str) -> str:
    """One preview line for one path: `would write` when nothing is there,
    `would replace` when a file is."""
    return f"would {'replace' if os.path.exists(path) else 'write'} {path}"


# What `--export` says when it is given a path that is not one. An empty
# string used to be indistinguishable from the flag not being there at all,
# so `--export ""` fell through every read branch and built the map, which is
# the opposite of what the line asked for.
EXPORT_EMPTY = ("--export needs a path, or `-` for stdout; "
                "an empty one names no file")


def _missing_parents(path: str) -> list:
    """The directories a write to `path` would have to create, outermost
    first, and nothing when every one of them is already there.

    A preview that names the file and not the two directories under it is
    describing half of what the run does.
    """
    missing, base = [], os.path.dirname(os.path.abspath(path))
    while base and not os.path.exists(base):
        missing.append(base)
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    return list(reversed(missing))


def _dry_run_answer(args) -> int:
    """`--dry-run` on the command lines that answer instead of building.

    Reached before the branches that serve, fetch and answer, so none of them
    runs: a preview of `--specs` that fetched the tickets first would be the
    write it was asked to describe, and `--spec-cmd` is a command of the
    caller's that this tool is not going to run to find out what it writes.
    A line that only reads has no paths to name, so it says so and prints no
    answer: an answer is not a preview.
    """
    out_dir = os.path.abspath(args.out)
    if args.specs:
        for name in ("spec_map.json", "spec_map.md"):
            print(_would(os.path.join(out_dir, name)))
        return 0
    if args.export is not None:
        # The one read that writes. The path is the caller's, so it is named
        # rather than described, and so are the directories that would have
        # to exist first: `--export docs/pack/map.md` creates them, and a
        # preview that named only the file would be describing half the
        # write. `-` creates nothing and writes nothing: it is stdout.
        if args.export == "-":
            print("nothing to write: --export - writes to stdout")
            return 0
        if not args.export.strip():
            print(EXPORT_EMPTY, file=sys.stderr)
            return 2
        target = os.path.abspath(args.export)
        for missing in _missing_parents(target):
            print(f"would create {missing}")
        print(_would(target))
        return 0
    named = [flag for flag, given in (
        ("--mcp", args.mcp), ("--lsp", args.lsp), ("--sections", args.sections),
        ("--pointer", args.pointer), ("--ask", args.ask),
        ("--more", args.more_handle), ("--callers", args.callers),
        ("--callees", args.callees), ("--impact", args.impact),
        ("--defines", args.defines), ("--at", args.at_place),
        ("--context", args.context_name),
        ("--rank", args.rank_files is not None),
        ("--cost", args.cost is not None)) if given]
    print(f"nothing to write: {', '.join(named)} only read")
    return 0


def _dry_run(args, repo: str) -> int:
    """`--dry-run`: every path this command line can write, and none of them
    written.

    One line per path. The paths come from the same expressions the writers
    use -- `hooks.paths` for the hook kinds, `propose_docs` for `--docs
    write` -- so a preview names what the real run names. Whether a listed
    file is then written depends on what is already in it: a target that
    already says what this tool would say is left as it is.

    The branches are in the order `main()` takes them, so a command line
    naming two of them is previewed as the one that would run.
    """
    out_dir = os.path.abspath(args.out)
    if args.docs:
        if args.docs != "write":
            print("nothing to write: --docs without `write` already only says "
                  "what it would write")
            return 0
        # The plan comes from a map built for this preview alone:
        # `out_dir=None` is build()'s "no cache", so previewing `--docs
        # write` leaves nothing behind either. `propose_docs` without
        # `apply` writes nothing and never plans a file that exists.
        planned = propose_docs(repo, build(repo, out_dir=None), apply=False)
        if not planned:
            print("nothing to write: every directory already explains itself")
            return 0
        targets = [os.path.join(repo, rel) for rel, _text, _why in planned]
    elif args.install_hook:
        # The kinds that write under ~ refuse a home they only found in the
        # passwd entry, and so does their preview: no path is better than an
        # invented one.
        refusal = hooks.home_refusal(args.install_hook)
        if refusal:
            print(refusal)
            return 2
        targets = hooks.paths(repo, args.install_hook)
    elif args.init:
        targets = [os.path.join(repo, ".framework-map.json")]
    else:
        # A build, whether it was asked for by itself, by --agent-file or by
        # --watch: the parse cache, the three map files, and the two optional
        # ones. The semantic index adds semantic_index.json and .npy to the
        # same directory when the optional extra is installed.
        targets = [os.path.join(out_dir, _PARSE_CACHE_FILE),
                   os.path.join(out_dir, "framework_map.json"),
                   os.path.join(out_dir, "framework_map_brief.md"),
                   os.path.join(out_dir, "framework_map.md")]
        if args.html:
            targets.append(os.path.join(out_dir, "framework_map.html"))
        if args.ctags:
            targets.append(os.path.join(out_dir, CTAGS_NAME))
        if args.agent_file:
            targets.append(os.path.abspath(args.agent_file))
    for path in targets:
        print(_would(path))
    return 0


def main() -> int:
    _reconfigure_streams()
    ap = build_parser()
    argv = sys.argv[1:]
    # Read off argv rather than parsed: `--effects -- <command line>` carries
    # a command line of its own, which is not this parser's to consume, and
    # the answer is about the tool rather than about any repository.
    #
    # Resolved through `flags_in`, not matched as a literal. argparse accepts
    # any unambiguous prefix, so `--effect` and `--eff` are `--effects`, and
    # the classifier resolves them the same way: matching the string alone
    # let `--effect` fall through to a build while `--effects -- ... --effect`
    # called that same line a read.
    if "--effects" in effects.flags_in(argv, effects.option_strings(ap)):
        return _effects_command(ap, argv)
    args = ap.parse_args()
    args.repo = _resolve_repo(args.repo, args.out)

    # The preview comes before the branches that serve, fetch or answer, so
    # asking what a command line writes never runs it. What each of them
    # would write is `_dry_run_answer`'s to say.
    if args.dry_run and (args.mcp or args.lsp or args.specs or args.sections
                         or args.ask or args.pointer or args.callers
                         or args.callees or args.impact or args.more_handle
                         or args.defines or args.at_place
                         or args.context_name or args.export is not None
                         or args.rank_files is not None
                         or args.cost is not None):
        return _dry_run_answer(args)

    # Answering from a map that already exists needs none of what follows: no
    # repository walk, no product roots, no config. It is a read.
    if args.mcp:
        syn = _config(os.path.abspath(args.repo)).get("synonyms")
        _ask.set_synonyms(syn if isinstance(syn, dict) else {})
        return mcp.serve(os.path.abspath(args.out))

    if args.lsp:
        return lsp.serve(os.path.abspath(args.out), os.path.abspath(args.repo))

    if args.specs:
        key_re = specs.KEY
        spec_stdin = None
        if args.spec_source != "cmd":
            try:
                args.spec_cmd, key_re = specs.command_for(
                    args.spec_source, os.path.abspath(args.repo))
            except ValueError as exc:
                print(f"--spec-source {args.spec_source}: {exc}", file=sys.stderr)
                return 2
            if args.spec_source == "linear":
                spec_stdin = specs.linear_query
        if not args.spec_cmd:
            print("--specs needs --spec-cmd: this tool does not know your tracker",
                  file=sys.stderr)
            return 2
        out_dir = os.path.abspath(args.out)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return _write_error(exc, out_dir)
        roots = [k.strip() for k in args.specs.split(",") if k.strip()]
        say = None if args.quiet else (lambda line: print(line, flush=True))
        spec = specs.walk(args.spec_cmd, roots,
                          depth=args.spec_depth or specs.DEFAULT_DEPTH,
                          limit=args.spec_limit or specs.DEFAULT_LIMIT, say=say,
                          key_re=key_re, stdin=spec_stdin)
        # Both replaced only once both are written, so nothing reads a new
        # spec_map.json beside the previous spec_map.md.
        try:
            _write_atomic_group([
                (os.path.join(out_dir, "spec_map.json"),
                 json.dumps(spec, indent=2, ensure_ascii=False)),
                (os.path.join(out_dir, "spec_map.md"), specs.digest(spec)),
            ])
        except OSError as exc:
            return _write_error(exc, out_dir)
        if not args.quiet:
            print(f"spec map: {len(spec['tickets'])} ticket(s) -> "
                  f"{os.path.join(out_dir, 'spec_map.md')}")
        return 0

    if (args.sections or args.ask or args.pointer or args.callers
            or args.callees or args.impact or args.more_handle
            or args.defines or args.at_place or args.context_name
            or args.export is not None or args.rank_files is not None
            or args.cost is not None):
        out_dir = os.path.abspath(args.out)
        map_path = os.path.join(out_dir, "framework_map.md")
        # Both maps answer, because a question about this work is as likely to be
        # about what was asked for as about where the code is.
        spec_path = os.path.join(out_dir, "spec_map.md")
        # No map is not an answer. --sections said so and returned 1; --ask
        # printed the same complaint and returned 0; --callers said "nothing
        # in the map calls X" and returned 0, which is worse than a bad exit
        # code because it reports an empty result for a search that never
        # happened. A CI step or a hook that checks $? believed all three.
        #
        # "No map" means neither map. A `--specs` run writes spec_map.md
        # without a framework_map.md beside it, and `--ask` has always read
        # both, so a question about a ticket in a directory that holds only
        # the specification map is still a question this can answer.
        have_map = os.path.exists(map_path)
        have_spec = os.path.exists(spec_path)
        if not have_map and not have_spec:
            print(f"no map at {map_path}: build one with "
                  f"`where-are-we --repo . --out {args.out}`", file=sys.stderr)
            return 1
        # Per flag, not per invocation. These four are separate branches and
        # the first one given wins, so the question is what the branch that
        # will actually run needs, not what the command line also mentions.
        # `--ask x --callers foo` runs --callers, and gating on "did anyone
        # say --ask" let it answer "nothing in the map calls foo" from a
        # directory with no code map in it at all.
        if not have_map and (args.pointer or args.sections or args.callers
                             or args.callees or args.impact
                             or args.more_handle or args.defines
                             or args.at_place or args.context_name
                             or args.export is not None
                             or args.rank_files is not None
                             or args.cost is not None):
            # These three read the code map and only the code map, so for
            # them the spec map beside it is not an answer. Say which file is
            # missing and which one is there.
            print(f"no map at {map_path}: {spec_path} is there, and only "
                  f"--ask reads it", file=sys.stderr)
            return 1
        if args.pointer:
            changed = changed_since(os.path.abspath(args.repo), out_dir)
            print(pointer(map_path, changed=changed), end="")
            return 0
        if args.sections:
            try:
                answer = "\n".join(map_heads(map_path))
            except OSError as exc:
                print(f"no map at {map_path}: {exc}", file=sys.stderr)
                return 1
            log_answer(out_dir, "sections", "", answer, len(answer))
            print(answer)
            return 0
        if args.cost is not None:
            # `--cost` with no number is `--cost 0`: every section, nothing
            # hidden. A threshold of 0 is a real answer, so the flag is read
            # as "was it given at all" rather than as a truth value.
            answer = cost(map_path, args.cost, as_json=args.json)
            log_answer(out_dir, "cost", str(args.cost), answer, len(answer))
            print(answer, end="")
            return 0
        if args.export is not None:
            text = export(map_path)
            if args.export == "-":
                # `-` is stdout, the way every tool that writes a file spells
                # it. The destination for this flag is a PR comment or a
                # paste, so the pipe is the common case and a file literally
                # named `-` in the current directory is never what was meant.
                print(text, end="")
                return 0
            if not args.export.strip():
                print(EXPORT_EMPTY, file=sys.stderr)
                return 2
            target = os.path.abspath(args.export)
            try:
                os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                _write_atomic(target, text)
            except OSError as exc:
                return _write_error(exc, target)
            print(f"wrote {target}")
            return 0
        if args.more_handle:
            # `--more` is the same call the MCP `more` tool makes, at the same
            # budget `--ask` prints at, so a handle read off a CLI answer and
            # a handle read off a tool result resolve to the same text.
            answer = _ask.more(map_path, args.more_handle, 12000)
            log_answer(out_dir, "more", args.more_handle, answer, 12000)
            print(answer)
            return 0
        if args.defines:
            # The same call the MCP `defines` tool makes, through the same
            # function, so a name asked here and asked there comes back byte
            # for byte the same.
            hits = spans_for(map_path, [args.defines.lower()])
            answer = ("\n".join(hits) if hits
                      else f"no declaration of {args.defines!r} in the map")
            log_answer(out_dir, "defines", args.defines, answer, len(answer))
            print(answer)
            return 0
        if args.at_place:
            answer = at(map_path, args.at_place)
            log_answer(out_dir, "at", args.at_place, answer, _ask.AT_BUDGET)
            print(answer)
            return 0
        if args.context_name:
            # The same call the MCP `context` tool makes, at the same budget,
            # so a name asked here and asked there comes back byte for byte
            # the same.
            answer = context(map_path, args.context_name)
            log_answer(out_dir, "context", args.context_name, answer,
                       _ask.CONTEXT_BUDGET)
            print(answer)
            return 0
        if args.rank_files is not None:
            # The same call the MCP `rank` tool makes, through the same
            # function. `--ask` alongside it is the tool's `words`: the names
            # in the question count ten times, which is aider's first
            # multiplier and the only one a question can move.
            # `--files` reads as "the files I am working in", which is what
            # `--rank`'s own argument is, so the two are one list rather than
            # one flag quietly answering the other's question.
            chosen = file_list(args.rank_files) + file_list(args.files,
                                                            sys.stdin.read)
            chosen = list(dict.fromkeys(chosen))
            _say_unknown(map_path, chosen)
            answer = rank_lines(map_path, chosen, args.ask,
                                args.limit or RANK_LIMIT)
            log_answer(out_dir, "rank", ",".join(chosen), answer, len(answer))
            print(answer)
            return 0
        if args.callers:
            json_path = os.path.join(out_dir, "framework_map.json")
            hits = callers(json_path, args.callers)
            answer = ("\n".join(hits) if hits
                      else f"nothing in the map calls {args.callers}")
            log_answer(out_dir, "callers", args.callers, answer, len(answer))
            print(answer)
            return 0
        if args.callees:
            # The same call the MCP `callees` tool makes, formatted by the
            # same function, so a name asked here and asked there comes back
            # byte for byte the same.
            json_path = os.path.join(out_dir, "framework_map.json")
            answer = callees_line(json_path, args.callees)
            log_answer(out_dir, "callees", args.callees, answer, len(answer))
            print(answer)
            return 0
        if args.impact:
            json_path = os.path.join(out_dir, "framework_map.json")
            answer = impact(json_path, args.impact, args.impact_depth)
            log_answer(out_dir, "impact", args.impact, answer, len(answer))
            print(answer)
            return 0
        # `--ask` answers from a map already on disk and never builds one, so
        # this is the one path that skips `conf = _config(repo)` below; a
        # project's `[synonyms]` still has to reach `ask()` from here.
        syn = _config(os.path.abspath(args.repo)).get("synonyms")
        _ask.set_synonyms(syn if isinstance(syn, dict) else {})
        scope = file_list(args.files, sys.stdin.read)
        _say_unknown(map_path, scope)
        parts = []
        if have_map:
            parts.append(ask(map_path, args.ask, files=scope))
        if have_spec:
            parts.append(ask(spec_path, args.ask, files=scope))
        answer = "\n\n".join(parts)
        answer += meaning_tail(out_dir, args.ask, answer)
        log_answer(out_dir, "ask", args.ask, answer, 12000)  # ask()'s own default limit
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

    # Before the first write of any path below, and after the manifest has
    # had its say about --out and --agent-file, so the preview names the
    # paths this same command line would write.
    if args.dry_run:
        return _dry_run(args, repo)

    # Build when there is no map, or when the repository has moved since the one
    # that is there was built. Otherwise the map on disk is the map that would
    # be built, and a second walk of the tree buys nothing.
    if args.docs:
        m2 = build(repo, out_dir=out_dir)
        try:
            planned = propose_docs(repo, m2, apply=(args.docs == "write"))
        except OSError as exc:
            # --docs write into a read-only checkout: name the file, do not
            # unwind through main() with a traceback.
            return _write_error(exc, repo)
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
        last, last_root = "", None
        print(f"watching {repo}, every {args.watch}s — Ctrl-C to stop")
        while True:
            try:
                now_fp = fingerprint(repo)
                # The same two questions the one-shot path asks, in the same
                # order and for the same reason. The fingerprint is the cheap
                # one; when it says nothing has moved, the content root is
                # what catches a rewrite that put its timestamp back. A
                # watcher that asked only the first went on serving the old
                # parse for as long as it ran, which is worse than the
                # one-shot case it was fixed for: nothing else was ever going
                # to look.
                now_root = last_root
                if now_fp == last:
                    if os.path.isdir(out_dir):
                        _load_parse_cache(out_dir)
                    state.HASH_MARK = state.HASH_COUNT
                    now_root = content_root(repo)
                if now_fp != last or now_root != last_root:
                    last = now_fp
                    # Before the build, same reasoning as the primary path:
                    # build() only saves the parse cache into a directory that
                    # already exists.
                    os.makedirs(out_dir, exist_ok=True)
                    # A whole rebuild, and the whole set of files, exactly as
                    # the primary path writes them. build() clears the walk
                    # and file caches itself, so an iteration sees files added
                    # since the last one and forgets names deleted since.
                    m2 = redact(build(repo, out_dir=out_dir, force=args.force))
                    m2["fingerprint"] = now_fp
                    last_root = m2.get("content_root")
                    _write_artifacts(out_dir, m2, args)
                    c2 = m2["counts"]
                    print(f"rebuilt: {c2['steps']} steps, {c2['scenarios']} scenarios")
            except Exception as exc:  # noqa: BLE001 - a watcher outlives the tree
                # A watcher is meant to outlive whatever the tree does to it.
                # One raised iteration used to end the loop for good, and the
                # map then quietly stopped following the repository: a file
                # deleted mid-walk, a full disk, an output directory replaced
                # underneath it. Say what happened, forget the fingerprint so
                # the next tick tries again even if nothing has moved since,
                # and keep watching. Ctrl-C is a BaseException and still stops.
                print(f"rebuild failed, still watching: {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
                last, last_root = "", None
            _t.sleep(args.watch)

    if args.install_hook:
        msg = install_hook(repo, args.install_hook, args.product, args.out,
                           args.agent_file)
        print(msg)
        # Both messages say a write was refused rather than attempted: no
        # git hooks directory, or an existing file this tool will not guess
        # the shape of and overwrite.
        if "does not exist" in msg or "nothing was written" in msg:
            return 2
        return 0

    stamp_now = fingerprint(repo)
    existing = os.path.join(out_dir, "framework_map.json")
    if not args.force and not args.init and os.path.exists(existing):
        try:
            with open(existing, encoding="utf-8") as fh:
                prev = json.load(fh)
        except (OSError, ValueError):
            prev = {}
        # Both, in that order. The fingerprint is the cheap question -- has
        # anything been written here since -- and it answers no for the one
        # case that matters: a rewrite of the same byte count with the
        # timestamp put back. So when it says nothing moved, the content root
        # is asked, and it reads the stored hashes first and hashes only the
        # files whose stat block moved, which on a tree nobody touched is no
        # files at all. A map written before this key existed has no root to
        # compare against and is trusted on the fingerprint alone.
        if prev.get("fingerprint") == stamp_now:
            _load_parse_cache(out_dir)
            # What is hashed answering this question belongs to the build it
            # decides on, so `hashed N files` covers the whole invocation and
            # not only the half of it that happened after this line.
            state.HASH_MARK = state.HASH_COUNT
            prev_root = prev.get("content_root")
            unchanged = prev_root is None or prev_root == content_root(repo)
        else:
            unchanged = False
        if unchanged:
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
        # Every line this prints is measured against the map already in
        # --out, and the hashes beside that map in the parse cache are the
        # record of what it was built from. So this build reads that record
        # and does not write over it: a --diff that rewrote the cache moved
        # its own baseline, and the same command over the same tree named the
        # files that moved the first time and nothing the second, while the
        # `content_root:` row went on saying the root had moved. The build
        # after this one writes the cache as usual.
        state.PARSE_CACHE_WRITES = False
        now = build(repo, out_dir=out_dir)
        changed = []
        # Which files moved, before which keys did. The map's `content_root`
        # says the tree is not the tree it was; these are the files that made
        # that true, and they are what a reader actually wants named.
        for label, names in (("files whose content moved", state.HASHES_MOVED),
                             ("files added", state.HASHES_ADDED),
                             ("files gone", state.HASHES_GONE)):
            if not names:
                continue
            shown = names[:20]
            more_files = len(names) - len(shown)
            changed.append(f"{label}: " + ", ".join(shown)
                           + (f", and {more_files} more" if more_files > 0 else ""))
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
    # Created before the build, not after: build() saves the parse cache into
    # out_dir itself, and only when out_dir already exists (a --docs preview,
    # a few lines up, never creates it and so never gets a cache file either).
    # --init writes into the repository, not out_dir, so it is excluded here
    # the same way. build() itself takes out_dir=None as "no cache", which
    # --init also needs: --out defaults to ".", so without this it would
    # write .wawe-cache.json into whatever directory --init ran from.
    if not args.init:
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return _write_error(exc, out_dir)
    m = build(repo, out_dir=None if args.init else out_dir, force=args.force)
    if len(repos) > 1:
        m["also"] = {}
        for extra in repos[1:]:
            if not os.path.isdir(extra):
                continue
            os.environ["AGENT_REPO"] = extra
            # keep_indexes: --also is the one place where a second root's
            # names belong in the first root's map. The walk and file caches
            # are cleared by the reset either way, which is what the two
            # .clear() calls that used to be here did by hand.
            m["also"][os.path.basename(extra)] = build(
                extra, out_dir=out_dir, keep_indexes=True, force=args.force)
        os.environ["AGENT_REPO"] = repo
        # The name index is a copy taken when the first root finished; the line
        # index is the live dict. So a second root's lines were searchable and
        # its names were not, and a question about a name defined in it came
        # back "nothing in the map defines this" — the one answer that sends a
        # reader off to grep with confidence.
        m["definitions"] = dict(sorted(DEFINITIONS.items()))
        # And every home of every one of them, for the same reason: the spans
        # index is a copy taken when the first root finished.
        m["spans"] = spans_index()
        # `xrefs` holds one row per span, so those rows are a copy of a copy:
        # rebuilt here from the merged index, or a merged map would carry a
        # table that names fewer files than the `spans` key beside it. The
        # `calls` and `imports` rows are the first root's, as
        # `call_graph_files` and `import_graph` are: a second root's call
        # graph is under `also`, and SCHEMA.md says so.
        m["xrefs"] = sort_xrefs(
            [r for r in (m.get("xrefs") or []) if r["edge"] != "declares"]
            + declares_rows(m["spans"], repo))
        m["indexed"] = dict(sorted(INDEXED.items()))
    m = redact(m)
    m["fingerprint"] = stamp_now
    if args.init:
        try:
            print(init_manifest(repo, m))
        except OSError as exc:
            return _write_error(exc, os.path.join(repo, ".framework-map.json"))
        return 0
    try:
        # The map files, the optional --html page and the --agent-file block
        # are one write step: an unwritable --out and an unwritable
        # --agent-file are the same complaint with a different path in it,
        # and the OSError carries which.
        _write_artifacts(out_dir, m, args)
    except OSError as exc:
        return _write_error(exc, out_dir)

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
