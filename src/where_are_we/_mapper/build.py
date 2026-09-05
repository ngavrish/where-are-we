"""The one walk of the repository that produces the map.

`build()` is one long function rather than a chain of small ones, and stays
that way here. Its sections share more than a hundred locals: most are filled
by one section and read by a dozen later ones, several are extended again
further down, and a few blocks read a loop variable the block above them left
behind. Cutting it up is a rewrite, not a move, and this task is a move.

What could be cut without changing a byte of output is in `extract/`: the
topics that are a function of `(repo, code_files, read)` and of nothing else.
"""

import ast
import json
import os
import re
import sys

from . import extract, state
from .declare import _step_texts, index_declarations
from .state import DEFINITIONS, INDEXED, LINES
from .walk import (SKIP_DIRS, _cached, _lines_matching, _load_parse_cache,
                   _manifest, _product_roots, _save_parse_cache, _slurp, _walk)


def _layer_line(paths: list, what: str) -> str:
    """One line describing a layer by what was actually found in this repo,
    rather than by the names one particular suite happens to use."""
    if not paths:
        return f"{what}: none found"
    dirs = sorted({os.path.dirname(p) or "." for p in paths})
    where = ", ".join(dirs[:3]) + (f" (+{len(dirs)-3} more)" if len(dirs) > 3 else "")
    return f"{what} — {len(paths)} files under {where}"


def build(repo: str, out_dir: str | None = None) -> dict:
    # Where the parse cache lives: the run directory a caller names, or
    # $RUN_DIR. Neither given, there is nowhere this build was told is safe
    # to write into, so it runs with no cache rather than guessing ".":
    # `mapper.build(repo)` called bare, from a smoke test or a one-off
    # script, used to leave a `.wawe-cache.json` in whatever the current
    # directory happened to be. WAWE_NO_CACHE=1 does the same on purpose.
    if out_dir is None:
        out_dir = os.getenv("RUN_DIR")
    no_cache = bool(os.environ.get("WAWE_NO_CACHE")) or out_dir is None
    if not no_cache:
        _load_parse_cache(out_dir)
    parses_before = state.PARSE_COUNT

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
        full = os.path.join(repo, rel)

        def _symbols_of(full=full):
            try:
                tree = ast.parse(open(full, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return None
            consts, funcs = [], []
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id.isupper():
                            consts.append(t.id)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("__"):
                        funcs.append(node.name)
            return {"constants": sorted(consts), "functions": sorted(funcs)}

        found_symbols = _cached(full, "symbols", _symbols_of)
        if found_symbols and (found_symbols["constants"] or found_symbols["functions"]):
            symbols[rel] = found_symbols

    def _public_api(rel: str) -> list[str]:
        """The surface a step is allowed to call, with signatures. Without it an
        agent either greps the class or invents a method that does not exist."""
        full = os.path.join(repo, rel)

        def _api_of(full=full, rel=rel):
            try:
                tree = ast.parse(open(full, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return {"api": [], "defs": []}
            out, defs = [], []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                                and not sub.name.startswith("_"):
                            args = [a.arg for a in sub.args.args if a.arg != "self"]
                            out.append(f"{node.name}.{sub.name}({', '.join(args)})")
                            defs.append((f"{node.name}.{sub.name}", f"{rel}:{sub.lineno}"))
                    defs.append((f"class {node.name}", f"{rel}:{node.lineno}"))
            return {"api": sorted(out), "defs": defs}

        api_result = _cached(full, "public_api", _api_of)
        for name, loc in api_result["defs"]:
            DEFINITIONS.setdefault(name, loc)
        return api_result["api"]

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
        full = os.path.join(repo, rel)

        def _doc_of(full=full):
            try:
                tree = ast.parse(open(full, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return None
            return ast.get_docstring(tree)

        d = _cached(full, "module_doc", _doc_of)
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
        full = os.path.join(repo, rel)

        def _hooks_of(full=full, rel=rel):
            try:
                tree = ast.parse(open(full, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return {}
            found = {}
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node.name.startswith(("before_", "after_")):
                    doc = (ast.get_docstring(node) or "").strip().split("\n")[0]
                    calls = sorted({c.func.attr for c in ast.walk(node)
                                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
                    found[f"{rel}:{node.name}"] = {"doc": doc[:200], "calls": calls[:12]}
            return found

        hooks.update(_cached(full, "hooks", _hooks_of))

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
    # knowing which scenario is a twenty-minute one. Where to look is
    # `WAWE_JUNIT_DIRS` (os.pathsep separated); by default the repository's
    # own report directories plus `/runs`, a well-known mount for a scoped
    # run's output. Never `/tmp`: it is shared with everything else that runs
    # on the machine, so reading it made the map depend on whatever another
    # process happened to leave behind rather than on this repository, and
    # walking all of it on every build was slow besides.
    history: dict[str, dict] = {}
    junit_env = os.getenv("WAWE_JUNIT_DIRS", "")
    junit_dirs = (junit_env.split(os.pathsep) if junit_env else
                  [os.path.join(repo, d) for d in
                   ("reports", "test-results", "junit", os.path.join("build", "test-results"))]
                  + ["/runs"])
    for root in junit_dirs:
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
        full = os.path.join(repo, rel)

        def _call_graph_of(full=full, rel=rel):
            try:
                tree = ast.parse(open(full, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return {}
            found = {}
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = sorted({c.func.attr for c in ast.walk(node)
                                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
                if calls:
                    found[f"{os.path.basename(rel)}:{node.name}"] = calls[:12]
            return found

        call_graph.update(_cached(full, "call_graph", _call_graph_of))
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

        def _pytest_of(p2=p2):
            try:
                tree = ast.parse(open(p2, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return {"cases": [], "fixs": [], "markers": []}
            cases, fixs, marks = [], [], []
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decs = []
                for d in node.decorator_list:
                    f = d.func if isinstance(d, ast.Call) else d
                    decs.append(getattr(f, "attr", "") or getattr(f, "id", ""))
                if node.name.startswith("test"):
                    cases.append(node.name + (f" [{', '.join(decs)}]" if decs else ""))
                    marks += [x for x in decs if x not in ("parametrize", "fixture")]
                elif "fixture" in decs:
                    fixs.append(node.name)
            return {"cases": cases, "fixs": fixs, "markers": marks}

        pytest_found = _cached(p2, "pytest_ast", _pytest_of)
        if pytest_found["cases"]:
            pytest_tests[rel] = pytest_found["cases"][:30]
        if pytest_found["fixs"]:
            fixtures[rel] = pytest_found["fixs"][:30]
        markers += pytest_found["markers"]

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

        def _exports_of(p2=p2):
            try:
                tree = ast.parse(open(p2, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                return []
            return [n.name for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and not n.name.startswith("_")]

        names = _cached(p2, "exports_py", _exports_of)
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
            if fn.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt",
                            ".rb", ".rs", ".cs", ".yaml", ".yml", ".tf", ".proto",
                            ".xml", ".json", ".md", ".sh", ".sql", ".ex", ".exs",
                            ".dart", ".sol", ".vue", ".svelte", ".rego", ".jmx",
                            ".bicep", ".pp", ".avsc", ".thrift", ".wsdl", ".ipynb")) \
                    or fn in ("Jenkinsfile", "Makefile", "Dockerfile", "Rakefile",
                              "BUILD", "BUILD.bazel", "WORKSPACE", "CMakeLists.txt",
                              "pom.xml", "build.sbt", "Gemfile", "Procfile"):
                code_files.append(os.path.relpath(os.path.join(base, fn), repo))

    # Everything below that is a function of the file list and nothing
    # else is an extractor; read `extract/__init__.py` for the rule.
    ctx = extract.Ctx(repo=repo, code_files=code_files, read=_read)

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
    # One parse per file gathers both the names it defines and the raw call
    # names inside each of them; resolving those against every file's
    # definitions has to wait until all of them have been read, so it happens
    # in a second, parse-free pass below.
    func_calls: dict[str, list] = {}
    defined_at: dict[str, str] = {}
    raw_calls_by_rel: dict[str, dict] = {}
    for rel in code_files:
        if not rel.endswith(".py"):
            continue
        full = os.path.join(repo, rel)

        def _func_calls_of(rel=rel):
            try:
                tree = ast.parse(_read(rel))
            except (SyntaxError, ValueError):
                return {"defs": [], "calls": {}}
            defs = []
            calls = {}
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                defs.append(node.name)
                targets = sorted({getattr(c.func, "id", "") or getattr(c.func, "attr", "")
                                   for c in ast.walk(node) if isinstance(c, ast.Call)})
                calls[node.name] = [t for t in targets if t]
            return {"defs": defs, "calls": calls}

        func_info = _cached(full, "func_calls", _func_calls_of)
        raw_calls_by_rel[rel] = func_info["calls"]
        for name in func_info["defs"]:
            defined_at.setdefault(name, rel)
    for rel, calls in raw_calls_by_rel.items():
        for func_name, raw_targets in calls.items():
            targets = set()
            for name in raw_targets:
                home = defined_at.get(name)
                if home and home != rel:
                    targets.add(f"{name} ({os.path.basename(home)})")
            if targets:
                func_calls[f"{os.path.basename(rel)}:{func_name}"] = sorted(targets)[:8]

    # Same call graph for TypeScript, JavaScript and Go: there is no AST here,
    # so a definition is found by pattern and a call graph body by matching
    # braces from the definition line, capped at 400 lines. ts/js and go are
    # kept as separate name tables, so a callee only counts when it is
    # defined in another file of the same language group.
    ts_js_ext = (".ts", ".tsx", ".js", ".jsx")
    _js_not_a_method = {"if", "for", "while", "switch", "catch", "else", "do",
                         "function", "return", "yield", "await", "typeof",
                         "new", "delete", "instanceof"}

    def _tsjs_def_names(body: str) -> list:
        found = []
        for m in re.finditer(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
                              body, re.M):
            found.append((m.group(1), body.count("\n", 0, m.start())))
        for m in re.finditer(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(", body, re.M):
            found.append((m.group(1), body.count("\n", 0, m.start())))
        for m in re.finditer(r"^  (\w+)\s*\([^)]*\)\s*\{", body, re.M):
            if m.group(1) not in _js_not_a_method:
                found.append((m.group(1), body.count("\n", 0, m.start())))
        return found

    def _go_def_names(body: str) -> list:
        found = []
        for m in re.finditer(r"^func\s+(\w+)\s*\(", body, re.M):
            found.append((m.group(1), body.count("\n", 0, m.start())))
        for m in re.finditer(r"^func\s+\([^)]*\)\s+(\w+)\s*\(", body, re.M):
            found.append((m.group(1), body.count("\n", 0, m.start())))
        return found

    def _brace_body(lines: list, start: int) -> str:
        depth, started, out = 0, False, []
        for i in range(start, min(start + 400, len(lines))):
            line = lines[i]
            out.append(line)
            for ch in line:
                if ch == "{":
                    depth += 1
                    started = True
                elif ch == "}":
                    depth -= 1
            if started and depth <= 0:
                break
        return "\n".join(out)

    defined_tsjs: dict[str, str] = {}
    defined_go: dict[str, str] = {}
    defs_by_file: dict[str, list] = {}
    for rel in code_files:
        if rel.endswith(ts_js_ext):
            table, finder = defined_tsjs, _tsjs_def_names
        elif rel.endswith(".go"):
            table, finder = defined_go, _go_def_names
        else:
            continue
        body = _read(rel)
        if not body:
            continue
        defs = finder(body)
        if defs:
            defs_by_file[rel] = defs
        for name, _ in defs:
            table.setdefault(name, rel)

    for rel, defs in defs_by_file.items():
        table = defined_tsjs if rel.endswith(ts_js_ext) else defined_go
        body = _read(rel)
        if not body:
            continue
        lines = body.splitlines()
        for name, line_idx in defs:
            fn_body = _brace_body(lines, line_idx)
            targets = set()
            for callee in set(re.findall(r"\b(\w+)\s*\(", fn_body)):
                home = table.get(callee)
                if home and home != rel:
                    targets.add(f"{callee} ({os.path.basename(home)})")
            if targets:
                func_calls[f"{os.path.basename(rel)}:{name}"] = sorted(targets)[:8]

    # One cap across both languages, tie-broken by key so ties do not depend
    # on os.walk order.
    func_calls = dict(sorted(func_calls.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:60])

    data_flow = extract.code.data_flow(ctx)["data_flow"]

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

    coverage_by_file = extract.tests.coverage_by_file(ctx)["coverage_by_file"]

    _topic = extract.code.deprecations(ctx)
    api_versions, deprecations = _topic["api_versions"], _topic["deprecations"]

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

    build_systems = extract.infra.build_systems(ctx)["build_systems"]

    stores = extract.data.datastores(ctx)["stores"]

    obs_config = extract.infra.observability_config(ctx)["obs_config"]

    _topic = extract.tests.performance_and_factories(ctx)
    factories, perf_suites = _topic["factories"], _topic["perf_suites"]

    db_constraints = extract.data.db_constraints(ctx)["db_constraints"]

    generated = extract.code.generated(ctx)["generated"]

    types_declared = extract.code.types_declared(ctx)["types_declared"]

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

    client_policies = extract.data.client_policies(ctx)["client_policies"]

    transactions = extract.data.transactions(ctx)["transactions"]

    logging_config = extract.infra.logging_config(ctx)["logging_config"]

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

    license_headers = extract.code.license_headers(ctx)["license_headers"]

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

    status_codes = extract.data.status_codes(ctx)["status_codes"]

    outbound = extract.data.outbound_calls(ctx)["outbound"]

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

    time_assumptions = extract.infra.time_assumptions(ctx)["time_assumptions"]

    complexity = extract.code.complexity(ctx)["complexity"]

    clones = extract.code.clones(ctx)["clones"]

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

    sdks = extract.infra.sdks(ctx)["sdks"]

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

    result = {
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

    if not no_cache:
        _save_parse_cache(out_dir)
    if os.environ.get("WAWE_DEBUG_PARSES"):
        print(f"parsed {state.PARSE_COUNT - parses_before} files", file=sys.stderr)
    return result
