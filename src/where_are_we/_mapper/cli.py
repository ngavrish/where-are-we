"""The command line: `where-are-we`, and the two things it can write into a
repository (a starter manifest, and the READMEs it is missing).

`main()` is the only place that reads argv, prints to stdout, or decides what
goes where; every other module in the package is a library it calls.
"""

import argparse
import json
import os
import re
import sys

try:
    from .. import specs
except ImportError:  # run as a plain file, with no package around it
    import specs  # type: ignore[no-redef]

try:
    from .. import ask as _ask
    from ..ask import ask, map_heads, log_answer, callers
except ImportError:  # run as a plain file, with no package around it
    import ask as _ask  # type: ignore[no-redef]
    from ask import ask, map_heads, log_answer, callers  # type: ignore[no-redef]

from .build import build
from .render import (_as_dict, _cap_sections, brief, changed_since, digest,
                     for_audience, meaning_tail, pointer)
from .state import DEFINITIONS, INDEXED, _IGNORE_CACHE, _WALK_CACHE
from .walk import SKIP_DIRS, _config, _fingerprint, _product_roots, redact


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
        from .. import readmes as _readmes
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

    The implementation lives in hooks.py, where cursor, codex and gemini were
    added alongside the original git and Claude Code kinds; this name stays
    because scripts and the CLI already call it.
    """
    from .. import hooks
    return hooks.install(repo, kind, product, out, agent_file)


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
    ap.add_argument("--callers", default="", metavar="NAME",
                    help="print who calls NAME, exactly: one `file:func` per "
                         "line, from the call graphs already in the map. "
                         "Case-sensitive, like the identifier itself. Reads "
                         "framework_map.json under --out")
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
            from .. import mcp as _mcp
        except ImportError:  # run as a plain file, with no package around it
            import mcp as _mcp  # type: ignore[no-redef]
        syn = _config(os.path.abspath(args.repo)).get("synonyms")
        _ask.set_synonyms(syn if isinstance(syn, dict) else {})
        return _mcp.serve(os.path.abspath(args.out))

    if args.lsp:
        try:
            from .. import lsp as _lsp
        except ImportError:  # run as a plain file, with no package around it
            import lsp as _lsp  # type: ignore[no-redef]
        return _lsp.serve(os.path.abspath(args.out), os.path.abspath(args.repo))

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
        os.makedirs(out_dir, exist_ok=True)
        roots = [k.strip() for k in args.specs.split(",") if k.strip()]
        say = None if args.quiet else (lambda line: print(line, flush=True))
        spec = specs.walk(args.spec_cmd, roots,
                          depth=args.spec_depth or specs.DEFAULT_DEPTH,
                          limit=args.spec_limit or specs.DEFAULT_LIMIT, say=say,
                          key_re=key_re, stdin=spec_stdin)
        with open(os.path.join(out_dir, "spec_map.json"), "w", encoding="utf-8") as fh:
            json.dump(spec, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(out_dir, "spec_map.md"), "w", encoding="utf-8") as fh:
            fh.write(specs.digest(spec))
        if not args.quiet:
            print(f"spec map: {len(spec['tickets'])} ticket(s) -> "
                  f"{os.path.join(out_dir, 'spec_map.md')}")
        return 0

    if args.sections or args.ask or args.pointer or args.callers:
        out_dir = os.path.abspath(args.out)
        map_path = os.path.join(out_dir, "framework_map.md")
        # Both maps answer, because a question about this work is as likely to be
        # about what was asked for as about where the code is.
        spec_path = os.path.join(out_dir, "spec_map.md")
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
        if args.callers:
            json_path = os.path.join(out_dir, "framework_map.json")
            hits = callers(json_path, args.callers)
            answer = ("\n".join(hits) if hits
                      else f"nothing in the map calls {args.callers}")
            log_answer(out_dir, "callers", args.callers, answer, len(answer))
            print(answer)
            return 0
        # `--ask` answers from a map already on disk and never builds one, so
        # this is the one path that skips `conf = _config(repo)` below; a
        # project's `[synonyms]` still has to reach `ask()` from here.
        syn = _config(os.path.abspath(args.repo)).get("synonyms")
        _ask.set_synonyms(syn if isinstance(syn, dict) else {})
        answer = ask(map_path, args.ask)
        if os.path.exists(spec_path):
            answer += "\n\n" + ask(spec_path, args.ask)
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

    # Build when there is no map, or when the repository has moved since the one
    # that is there was built. Otherwise the map on disk is the map that would
    # be built, and a second walk of the tree buys nothing.
    if args.docs:
        m2 = build(repo, out_dir=out_dir)
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
                # Before the build, same reasoning as the primary path: build()
                # only saves the parse cache into a directory that already
                # exists.
                os.makedirs(out_dir, exist_ok=True)
                m2 = build(repo, out_dir=out_dir)
                m2["fingerprint"] = now_fp
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
        msg = install_hook(repo, args.install_hook, args.product, args.out,
                           args.agent_file)
        print(msg)
        # Both messages say a write was refused rather than attempted: no
        # git hooks directory, or an existing file this tool will not guess
        # the shape of and overwrite.
        if "does not exist" in msg or "nothing was written" in msg:
            return 2
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
        now = build(repo, out_dir=out_dir)
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
    # Created before the build, not after: build() saves the parse cache into
    # out_dir itself, and only when out_dir already exists (a --docs preview,
    # a few lines up, never creates it and so never gets a cache file either).
    # --init writes into the repository, not out_dir, so it is excluded here
    # the same way. build() itself takes out_dir=None as "no cache", which
    # --init also needs: --out defaults to ".", so without this it would
    # write .wawe-cache.json into whatever directory --init ran from.
    if not args.init:
        os.makedirs(out_dir, exist_ok=True)
    m = build(repo, out_dir=None if args.init else out_dir)
    if len(repos) > 1:
        m["also"] = {}
        for extra in repos[1:]:
            if not os.path.isdir(extra):
                continue
            os.environ["AGENT_REPO"] = extra
            _WALK_CACHE.clear()
            _IGNORE_CACHE.clear()
            m["also"][os.path.basename(extra)] = build(extra, out_dir=out_dir)
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
            from .. import semantic as _sem
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
