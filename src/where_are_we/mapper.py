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

STEP_DECORATORS = {"step", "given", "when", "then"}
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
    if raw:
        return [x for x in re.split(r"[:,]", raw) if x]
    repo = os.getenv("AGENT_REPO", "/work")
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
    for src_root in _product_roots():
        if not os.path.isdir(src_root):
            continue
        for p2 in _walk(src_root, ".tsx") + _walk(src_root, ".ts"):
            try:
                src = open(p2, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            product["routes"] += re.findall(r"path=[\"\']([/][\w/:-]*)", src)
            product["storage_keys"] += re.findall(r"localStorage\.(?:get|set|remove)Item\(\s*[\"\'`]([\w.:-]+)", src)
            product["storage_keys"] += re.findall(r"[\"\'`]([a-z][\w-]{2,}-[\w.-]+)[\"\'`]", src)
            product["api_paths"] += re.findall(r"[\"\'`](/api/v\d[\w/{}-]*)", src)
    product = {k: sorted(set(v))[:120] for k, v in product.items()}

    # Locators the page objects actually drive, and the timing constants that
    # decide how long anything waits. Both are grepped constantly and neither
    # can be guessed.
    locators: dict[str, list[str]] = {}
    timings: dict[str, list[str]] = {}
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
        found = re.findall(r".*\b(?:TODO|FIXME|XXX|HACK|@skip|@wip)\b.*", src)[:6]
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
        hits = re.findall(r".*\b(?:login|log_in|sign_in|cognito|sso|okta|token|cookie|session|auth)\w*\s*[=(].*",
                          src, re.I)[:4]
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
        for m2 in re.findall(r".*\b(?:lock|mutex|singleton|serial|not.thread.safe|shared)\b.*",
                             src, re.I)[:2]:
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
        hits = re.findall(r".*\b(?:ENV\s*==?\s*[\"\']?(?:uat|dev|local|prod)|if\s+\w*env\w*\s*[=!]=).*",
                          src, re.I)[:4]
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
        dep = re.findall(r".*\b(?:@deprecated|DeprecationWarning|Deprecated|@Deprecated)\b.*",
                         body)[:4]
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
        "## Where things are",
    ]
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
    st = m.get("stated") or {}
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
    lg = m.get("languages") or {}
    if lg:
        lines += ["## What this codebase is made of", "",
                  ", ".join(f"{k} ({n})" for k, n in list(lg.items())[:10]), ""]
    en = m.get("entry") or {}
    if en:
        lines += ["## Where it starts", ""]
        for k, v in list(en.items())[:10]:
            if k == "package.json scripts":
                lines.append("- npm scripts: " + ", ".join(f"`{a}` → {b[:40]}" for a, b in v[:8]))
            elif isinstance(v, list):
                lines.append(f"- {k}: " + ", ".join(str(x)[:60] for x in v[:8]))
        lines.append("")
    ws = m.get("workspaces") or []
    if ws:
        lines += ["## Monorepo layout", "", ", ".join(f"`{x}`" for x in ws[:12]), ""]
    rs = m.get("routes_served") or []
    if rs:
        lines += [f"## HTTP routes this codebase serves ({len(rs)})", ""]
        for r in rs[:30]:
            lines.append(f"- {r}")
        lines.append("")
    md2 = m.get("models") or {}
    if md2:
        lines += ["## Data model", ""]
        for name, fields in list(md2.items())[:15]:
            lines.append(f"- `{name}`: " + ", ".join(fields[:12]))
        lines.append("")
    ex = m.get("exports") or {}
    if ex:
        lines += ["## Public surface of the code", ""]
        for rel, names in list(ex.items())[:20]:
            lines.append(f"- `{rel}`: " + ", ".join(names[:10]))
        lines.append("")
    ig = m.get("import_graph") or {}
    if ig:
        lines += ["## How the top-level packages depend on each other", ""]
        for top, deps in ig.items():
            lines.append(f"- `{top}` → " + ", ".join(deps))
        lines.append("")
    def _sect(title: str, rows: list) -> None:
        if rows:
            lines.extend(["## " + title, ""] + rows + [""])

    ms = m.get("messaging") or {}
    _sect("Queues, topics and subjects",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:10]) for k, v in list(ms.items())[:12]])
    gr = m.get("grpc") or {}
    _sect("gRPC services", [f"- `{k}`: " + ", ".join(v[:12]) for k, v in list(gr.items())[:12]])
    sch = m.get("schedules") or {}
    _sect("Scheduled work",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:6]) for k, v in list(sch.items())[:12]])
    kb = m.get("kubernetes") or {}
    _sect("Kubernetes and Helm",
          [f"- `{k}` — {', '.join(v['kinds'][:6])}: {', '.join(v['names'][:6])}"
           for k, v in list(kb.items())[:12]])
    ic = m.get("iac") or {}
    _sect("Infrastructure as code",
          [f"- `{k}`: " + ", ".join(f"{a}.{b}" for a, b in v[:10]) for k, v in list(ic.items())[:10]])
    ck = m.get("cache_keys") or []
    _sect("Cache keys", ["- " + ", ".join(f"`{x}`" for x in ck[:25])] if ck else [])
    pm = m.get("permissions") or {}
    _sect("Permissions and roles",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:10]) for k, v in list(pm.items())[:12]])
    ob = m.get("observability") or {}
    _sect("Observability", [f"- {k}: " + ", ".join(v[:15]) for k, v in ob.items() if v])
    et = m.get("error_types") or {}
    _sect("Error types", ["- " + ", ".join(f"`{k}` ({v})" for k, v in list(et.items())[:20])] if et else [])
    cc = m.get("cli_commands") or {}
    _sect("Command line",
          [f"- `{os.path.basename(k)}`: " + ", ".join(v[:12]) for k, v in list(cc.items())[:10]])
    fe = m.get("frontend") or {}
    _sect("Frontend", [f"- {k}: " + ", ".join(str(x) for x in v[:15]) for k, v in fe.items() if v])
    ad = m.get("adrs") or []
    _sect("Architecture decisions", [f"- {x}" for x in ad[:15]])
    cov = m.get("coverage_reports") or {}
    _sect("Coverage reports", [f"- `{k}`: " + ", ".join(v) for k, v in list(cov.items())[:6]])
    hp = m.get("hotspots") or []
    _sect("Largest files", ["- " + ", ".join(hp[:12])] if hp else [])
    dl = m.get("dependency_licenses") or {}
    _sect("Declared licenses", [f"- `{k}`: " + ", ".join(v[:6]) for k, v in list(dl.items())[:6] if v])

    fc = m.get("call_graph_files") or {}
    _sect("Who calls whom, across files",
          [f"- `{k}` → " + ", ".join(v[:6]) for k, v in list(fc.items())[:20]])
    df = m.get("data_flow") or {}
    _sect("Which code touches which table",
          [f"- `{os.path.basename(k)}`: {', '.join(v['paths'][:4])} ↔ {', '.join(v['tables'][:5])}"
           for k, v in list(df.items())[:15]])
    bo = m.get("blame_owners") or {}
    _sect("Who has been touching what (last year)",
          [f"- `{k}` — {', '.join(v)}" for k, v in list(bo.items())[:15]])
    cbf = m.get("coverage_by_file") or {}
    _sect("Coverage by file",
          [f"- `{k}` — {v}" for k, v in list(cbf.items())[:20]])
    dep2 = m.get("deprecations") or {}
    _sect("Deprecations",
          [f"- `{os.path.basename(k)}`: " + " | ".join(v[:2]) for k, v in list(dep2.items())[:12]])
    av = m.get("api_versions") or []
    _sect("API versions in use", ["- " + ", ".join(av)] if av else [])
    dd = m.get("doc_drift") or []
    _sect("Documentation pointing at things that are not there",
          [f"- {x}" for x in dd[:15]])

    mss = m.get("more_suites") or {}
    _sect("More test suites",
          [f"- **{k}** — {len(v)} files: " + ", ".join(os.path.basename(x) for x in list(v)[:4])
           for k, v in mss.items()])
    ds = m.get("data_stack") or {}
    _sect("Data engineering",
          ([f"- dbt models: {len(ds['dbt_models'])}"] if ds.get("dbt_models") else [])
          + ([f"- Airflow: " + ", ".join(f"`{os.path.basename(k)}` ({len(v)} tasks)"
                                        for k, v in list(ds["airflow_dags"].items())[:6])]
             if ds.get("airflow_dags") else [])
          + ([f"- Spark jobs: {len(ds['spark_jobs'])}"] if ds.get("spark_jobs") else [])
          + ([f"- notebooks: {len(ds['notebooks'])}"] if ds.get("notebooks") else []))
    bs = m.get("build_systems") or {}
    _sect("Build systems", [f"- **{k}**: " + "; ".join(v[:4]) for k, v in bs.items()])
    st = m.get("stores") or {}
    _sect("Datastores and brokers", [f"- {k}: " + ", ".join(v[:12]) for k, v in st.items()])
    oc = m.get("obs_config") or {}
    _sect("Observability and policy configuration",
          [f"- {k}: " + ", ".join(str(x)[:70] for x in v[:5]) for k, v in oc.items()])
    ps = m.get("perf_suites") or {}
    _sect("Load testing", [f"- {k}: " + ", ".join(os.path.basename(x) for x in v[:8])
                           for k, v in ps.items()])
    fac = m.get("factories") or {}
    _sect("Test data factories",
          [f"- `{os.path.basename(k)}`: " + ", ".join(x for x in v[:8] if x)
           for k, v in list(fac.items())[:10]])

    lines += ["## How this suite is built", ""]
    for k, v in (m.get("layers") or {}).items():
        lines.append(f"- **{k}** — {v}")
    lines.append("")
    for label, key in (("Page objects", "page_objects"), ("Drivers", "drivers"),
                       ("behave environment", "behave_environment_files"), ("Scripts", "scripts")):
        if m[key]:
            lines.append(f"- **{label}**: " + ", ".join(f"`{p}`" for p in m[key][:6]))
    ep = m.get("entry_points") or {}
    if ep:
        lines += ["", "## How a scenario is run", ""]
        for path, usage in list(ep.items())[:5]:
            lines.append(f"- `{path}`: " + "; ".join(usage))
    api = m.get("public_api") or {}
    if api:
        lines += ["", "## What a step may call", ""]
        for path, methods in api.items():
            lines.append(f"- `{path}`: " + ", ".join(methods[:16])
                         + (f" … +{len(methods)-16} more in the full map" if len(methods) > 16 else ""))
    md = m.get("module_docs") or {}
    if md:
        lines += ["", "## What each module says it is for", ""]
        for path, doc in list(md.items())[:20]:
            lines.append(f"- `{path}` — {doc.splitlines()[0][:180]}")
    dc = m.get("docs") or {}
    if dc:
        lines += ["", "## The suite's own documentation", ""]
        for path, meta in list(dc.items())[:12]:
            lines.append(f"- `{path}` — " + ", ".join(meta["headings"][:6]))
    fl = m.get("feature_links") or {}
    if fl:
        lines += ["", "## Which feature is served by which modules", ""]
        for path, link in sorted(fl.items(), key=lambda kv: -len(kv[1]["step_modules"]))[:20]:
            if not link["step_modules"]:
                continue
            lines.append(f"- `{os.path.basename(path)}` → steps: "
                         + ", ".join(os.path.basename(x) for x in link["step_modules"][:6])
                         + (" · pages: " + ", ".join(os.path.basename(x) for x in link["page_objects"][:4])
                            if link["page_objects"] else ""))
    hl = m.get("helpers") or {}
    if hl:
        lines += ["", "## Shared helpers outside steps and page objects", ""]
        for path, methods in list(hl.items())[:12]:
            lines.append(f"- `{path}`: " + ", ".join(methods[:10]))
    hk = m.get("hooks") or {}
    if hk:
        lines += ["", "## behave hooks and what they do", ""]
        for name, meta in list(hk.items())[:12]:
            lines.append(f"- `{name}` — {meta['doc'] or 'no docstring'}"
                         + (f" · calls: {', '.join(meta['calls'][:8])}" if meta["calls"] else ""))
    pr = m.get("product") or {}
    if any(pr.values()):
        lines += ["", "## The product under test", ""]
        if pr.get("routes"):
            lines.append("- routes: " + ", ".join(pr["routes"][:20]))
        if pr.get("storage_keys"):
            lines.append("- localStorage keys: " + ", ".join(pr["storage_keys"][:20]))
        if pr.get("api_paths"):
            lines.append("- API: " + ", ".join(pr["api_paths"][:20]))
    ti = m.get("testids") or {}
    if ti.get("product") or ti.get("suite"):
        lines += ["", "## Test ids", ""]
        if ti.get("product"):
            lines.append(f"- product exposes {len(ti['product'])}: "
                         + ", ".join(ti["product"][:25]) + " … (full list in the full map)")
        if ti.get("suite"):
            lines.append(f"- suite drives {len(ti['suite'])}: " + ", ".join(ti["suite"][:15]))
    df = m.get("data_files") or []
    if df:
        lines += ["", "## Test data and fixtures", "",
                  ", ".join(f"`{x}`" for x in df[:20])
                  + (f" … +{len(df)-20}" if len(df) > 20 else "")]
    rp = m.get("reporting") or {}
    if rp:
        lines += ["", "## Reporting and artefacts", ""]
        for kw, files in rp.items():
            lines.append(f"- {kw}: " + ", ".join(f"`{os.path.basename(f)}`" for f in files))
    qz = m.get("quarantine") or {}
    if qz:
        lines += ["", "## Quarantined / known-unstable", ""]
        for path, marks in list(qz.items())[:15]:
            lines.append(f"- `{os.path.basename(path)}` — " + ", ".join("@"+x for x in marks[:6]))
    lc = m.get("locators") or {}
    if lc:
        lines += ["", "## Locator constants", ""]
        for path, items in list(lc.items())[:8]:
            lines.append(f"- `{os.path.basename(path)}`: " + "; ".join(items[:8]))
    tm = m.get("timings") or {}
    if tm:
        lines += ["", "## Timeouts, waits and budgets", ""]
        for path, items in list(tm.items())[:10]:
            lines.append(f"- `{os.path.basename(path)}`: " + "; ".join(items[:10]))
    bc = m.get("behave_config") or {}
    if bc:
        lines += ["", "## behave configuration", ""]
        for name, body in bc.items():
            first = " · ".join(l.strip() for l in body.splitlines() if l.strip())[:300]
            lines.append(f"- `{name}`: {first}")
    cd = m.get("coverage_docs") or {}
    if cd:
        lines += ["", "## Coverage documents (ticket → scenarios)", ""]
        for path, meta in list(cd.items())[:6]:
            lines.append(f"- `{path}` — {len(meta['tickets'])} tickets: "
                         + ", ".join(meta["tickets"][:12]))
    es = m.get("env_setup") or {}
    if es:
        lines += ["", "## Bringing the environment up", ""]
        for path, meta in list(es.items())[:8]:
            lines.append(f"- `{os.path.basename(path)}` — flags: "
                         + ", ".join(meta["flags"][:8])
                         + (" · ports: " + ", ".join(meta["ports"][:6]) if meta["ports"] else ""))
    bk = m.get("backend") or {}
    if any(bk.values()):
        lines += ["", "## Backend the tests touch", ""]
        if bk.get("endpoints"):
            lines.append("- endpoints: " + ", ".join(bk["endpoints"][:20]))
        if bk.get("tables"):
            lines.append("- tables queried: " + ", ".join(bk["tables"][:20]))
        if bk.get("seed_scripts"):
            lines.append("- seeding: " + ", ".join(f"`{os.path.basename(x)}`" for x in bk["seed_scripts"][:8]))
    at = m.get("api_tests") or []
    if at:
        lines += ["", "## API-level features (not UI)", "",
                  ", ".join(f"`{os.path.basename(x)}`" for x in at[:20])]
    cv = m.get("conventions") or {}
    if cv:
        lines += ["", "## Repository conventions", ""]
        for name, body in cv.items():
            head = " · ".join(l.strip("# ").strip() for l in body.splitlines()
                              if l.startswith("#"))[:240]
            lines.append(f"- `{name}`: {head}")
    hs = m.get("scenario_history") or {}
    if hs:
        lines += ["", "## What past runs measured (slowest first)", ""]
        for name, meta in list(hs.items())[:20]:
            lines.append(f"- {name[:90]} — ~{meta['avg_s']}s"
                         + (f", failed {meta['failed']}×" if meta["failed"] else ""))
    dr = m.get("dir_readmes") or {}
    if dr:
        lines += ["", "## What each directory says it is", ""]
        for d, meta in sorted(dr.items())[:40]:
            lines.append(f"- `{d}` — {meta['summary'] or ', '.join(meta['headings'][:4])}")
    nd = m.get("near_duplicates") or []
    if nd:
        lines += ["", f"## Steps that overlap ({len(nd)} pairs) — check whether one already does what you need", ""]
        for d in nd[:20]:
            lines.append(f"- {d['similarity']}: \"{d['a'][:60]}\" (`{os.path.basename(d['a_in'])}`)"
                         f" ≈ \"{d['b'][:60]}\" (`{os.path.basename(d['b_in'])}`)")
    cg = m.get("call_graph") or {}
    if cg:
        lines += ["", "## What each step calls", ""]
        for name, calls in list(cg.items())[:25]:
            lines.append(f"- `{name}` → " + ", ".join(calls[:8]))
    af = m.get("artefacts") or {}
    if af:
        lines += ["", "## What a run leaves behind", "",
                  ", ".join(f"`{k}`" for k in list(af)[:25])]
    dup = m.get("duplicates") or {}
    if dup:
        lines += ["", f"## Duplicate step phrases ({len(dup)} collisions) — reuse, do not re-declare", ""]
        for norm, owners in list(dup.items())[:20]:
            where = ", ".join(f"`{os.path.basename(r)}`" for r, _ in owners[:4])
            lines.append(f"- \"{norm[:80]}\" — {where}")
    us = m.get("unused_steps") or {}
    if us:
        total = sum(len(v) for v in us.values())
        lines += ["", f"## Step phrases no feature uses ({total}) — dead weight, do not imitate", ""]
        for rel, dead in list(us.items())[:10]:
            lines.append(f"- `{os.path.basename(rel)}`: " + "; ".join(x[:60] for x in dead[:4]))
    ua = m.get("unused_api") or {}
    if ua:
        lines += ["", "## Page-object methods nothing calls", ""]
        for rel, dead in list(ua.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + ", ".join(dead[:8]))
    db = m.get("debts") or {}
    if db:
        lines += ["", f"## Admitted debts (TODO/FIXME/skip) in {len(db)} files", ""]
        for rel, items in list(db.items())[:12]:
            lines.append(f"- `{os.path.basename(rel)}`: " + " | ".join(items[:2]))
    gh = m.get("git_history") or {}
    if gh:
        lines += ["", "## Most-changed files, last 90 days", ""]
        for rel, entries in list(gh.items())[:12]:
            lines.append(f"- `{rel}` — {len(entries)} commits, latest: {entries[0][:80]}")
    tl = m.get("ticket_links") or {}
    if tl:
        lines += ["", "## Recent tickets and the files they touched", ""]
        for t, meta in list(tl.items())[:12]:
            lines.append(f"- {t}: {meta['subject'][:60]} → "
                         + ", ".join(os.path.basename(f) for f in meta["files"][:4]))
    dp = m.get("dependencies") or {}
    if dp:
        lines += ["", "## Dependencies", ""]
        for name, pins in dp.items():
            lines.append(f"- `{name}`: " + ", ".join(f"{a}={b}" for a, b in pins[:14]))
    ci = m.get("ci") or {}
    if ci:
        lines += ["", "## CI", ""]
        for path, meta in list(ci.items())[:6]:
            lines.append(f"- `{path}` — jobs: {', '.join(meta['jobs'][:8])}"
                         + (f" · runs: {meta['runs'][0][:60]}" if meta["runs"] else ""))
    re_env = m.get("required_env") or []
    if re_env:
        lines += ["", "## Environment that must be set (from .envrc)", "",
                  ", ".join(f"`{x}`" for x in re_env[:40])]
    au = m.get("auth") or {}
    if au:
        lines += ["", "## How a test authenticates", ""]
        for rel, hits in list(au.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + " | ".join(h[:90] for h in hits[:2]))
    cc = m.get("concurrency") or {}
    if any(cc.values()):
        lines += ["", "## What cannot run beside something else", ""]
        if cc.get("serial_tags"):
            lines.append("- tags demanding isolation: " + ", ".join("@"+t for t in cc["serial_tags"]))
        if cc.get("shared_state"):
            lines.append("- module-level shared state: " + ", ".join(cc["shared_state"][:12]))
        for n in (cc.get("notes") or [])[:5]:
            lines.append(f"- {n}")
    fs = m.get("failure_signatures") or {}
    if fs:
        lines += ["", "## Failure messages this suite can produce", ""]
        for msg, where in list(fs.items())[:15]:
            lines.append(f"- \"{msg[:100]}\" — {', '.join(where[:2])}")
    sd = m.get("safe_data") or {}
    if sd:
        lines += ["", "## Test data the suite already uses", ""]
        for rel, ids in list(sd.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + ", ".join(ids[:15]))
    ss = m.get("slow_steps") or {}
    if ss:
        lines += ["", "## Slow steps (from past runs)", ""]
        for phrase, meta in list(ss.items())[:12]:
            lines.append(f"- {phrase[:70]} — up to {meta['avg_s']}s (`{meta['module']}`)")
    tmn = m.get("tag_meaning") or {}
    if tmn:
        lines += ["", "## What the tags mean, where it is written down", ""]
        for tag, sense in list(tmn.items())[:15]:
            lines.append(f"- `@{tag}` — {sense[:110]}")
    fr = m.get("fragile_locators") or {}
    if fr:
        lines += ["", "## Locators marked fragile, legacy or fallback", ""]
        for rel, items in list(fr.items())[:8]:
            lines.append(f"- `{os.path.basename(rel)}`: " + "; ".join(x[:80] for x in items[:4]))
    to = m.get("testid_owners") or {}
    if to:
        lines += ["", f"## Which component owns which test id ({len(to)})", ""]
        for tid, owner in list(to.items())[:25]:
            lines.append(f"- `{tid}` — {owner}")
    rc = m.get("rules_corpus") or []
    if rc:
        lines += ["", f"## The rules this work is held to ({len(rc)})", "",
                  ", ".join(rc[:60]) + (" …" if len(rc) > 60 else "")]
    us2 = m.get("ui_strings") or []
    if us2:
        lines += ["", "## Interface strings assertions can match", "",
                  ", ".join(f"\"{x}\"" for x in us2[:40])]
    inf = m.get("infrastructure") or {}
    if inf:
        lines += ["", "## Infrastructure the suite talks to", ""]
        for rel, meta in list(inf.items())[:8]:
            lines.append(f"- `{rel}` — services: {', '.join(meta['services'][:8])}"
                         + (f" · ports: {', '.join(meta['ports'][:8])}" if meta["ports"] else "")
                         + (f" · health: {meta['health'][0][:60]}" if meta["health"] else ""))
    sc = m.get("schemas") or {}
    if sc:
        lines += ["", "## Tables and the columns tests read", ""]
        for tbl, cols in list(sc.items())[:12]:
            lines.append(f"- `{tbl}`: " + ", ".join(cols[:12]))
    ow = m.get("owners") or {}
    if ow:
        lines += ["", "## Code owners", ""]
        for path, who in list(ow.items())[:12]:
            lines.append(f"- `{path}` — {', '.join(who)}")
    ed = m.get("env_differences") or {}
    if ed:
        lines += ["", "## Where the environments differ", ""]
        for rel, hits in list(ed.items())[:10]:
            lines.append(f"- `{os.path.basename(rel)}`: " + " | ".join(h[:80] for h in hits[:2]))
    pr2 = m.get("past_runs") or []
    if pr2:
        lines += ["", "## What earlier runs of this pipeline concluded", ""]
        for r in pr2[:10]:
            lines.append(f"- run {r['run']} {r['ticket']}: {r['verdict']} — {r['summary'][:100]}")
    vb = m.get("visual_baselines") or []
    if vb:
        lines += ["", "## Visual baselines", "", ", ".join(f"`{x}`" for x in vb[:15])]
    fst = m.get("feature_style") or {}
    if fst.get("sample"):
        lines += ["", "## How a feature file is written here", "",
                  f"Sample: `{fst['sample']}`"
                  + (", uses Scenario Outline" if fst.get("uses_outlines") else ""),
                  "", "```gherkin", fst.get("first_scenario", "")[:900], "```"]
    pt = m.get("pytest_tests") or {}
    if pt:
        lines += ["", f"## pytest cases ({sum(len(v) for v in pt.values())})", ""]
        for rel, cases in list(pt.items())[:15]:
            lines.append(f"- `{rel}`: " + ", ".join(cases[:8]))
    fx = m.get("fixtures") or {}
    if fx:
        lines += ["", "## Fixtures", ""]
        for rel, fs2 in list(fx.items())[:12]:
            lines.append(f"- `{rel}`: " + ", ".join(fs2[:12]))
    mk = m.get("markers") or []
    if mk:
        lines += ["", "## Markers in use", "", ", ".join(mk[:25])]
    jt = m.get("js_tests") or {}
    if jt:
        lines += ["", f"## JavaScript/TypeScript tests ({len(jt)} files)", ""]
        for rel, names in list(jt.items())[:12]:
            lines.append(f"- `{rel}`: " + "; ".join(n[:60] for n in names[:5]))
    tc = m.get("test_config") or {}
    if tc:
        lines += ["", "## Test configuration", ""]
        for name, hits in tc.items():
            lines.append(f"- `{name}`: " + " · ".join(h[:80] for h in hits[:4]))
    os2 = m.get("other_suites") or {}
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
    ct = m.get("contracts") or {}
    if any(ct.values()):
        lines += ["", "## Contracts, schemas and mocks", ""]
        for k, v in ct.items():
            if v:
                lines.append(f"- **{k}**: " + ", ".join(f"`{x}`" for x in v[:10])
                             + (f" … +{len(v)-10}" if len(v) > 10 else ""))
    cdet = m.get("contract_details") or {}
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
    ctg = m.get("ci_tags") or {}
    if ctg:
        lines += ["", "## Tags each CI job runs", ""]
        for path, tg2 in list(ctg.items())[:8]:
            lines.append(f"- `{path}`: " + ", ".join(tg2))
    tg = m.get("tags") or {}
    if tg:
        lines += ["", "## Tags in use", "",
                  ", ".join(f"@{t} ({n})" for t, n in list(tg.items())[:30])]
    env = m.get("environment") or {}
    if env:
        lines += ["", "## Environment the suite reads (name — where it is set)", ""]
        for name, files in list(env.items())[:40]:
            lines.append(f"- `{name}` — " + ", ".join(f"`{f}`" for f in files[:3]))
    lines += ["", "## Step modules, largest first", ""]
    for path, texts in sorted(m["steps"].items(), key=lambda kv: -len(kv[1]))[:40]:
        sym = (m.get("symbols") or {}).get(path, {})
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
        "layers": dict(m.get("layers") or {}),
        "product_src": _product_roots(),
        "entry_points": {k: "TODO: what this runs"
                         for k in list((m.get("entry_points") or {}).keys())[:6]},
        "conventions": ["TODO: the rules a newcomer must not break."],
        "notes": "",
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(skeleton, fh, indent=2, ensure_ascii=False)
    return f"wrote {path}"



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
                         "without it, siblings of the repo are tried")
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
    ap.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                    help="rebuild whenever the tree moves, checking every SECONDS")
    ap.add_argument("--html", action="store_true",
                    help="also write framework_map.html — the brief, readable in a browser")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when the existing map still matches the "
                         "repository (by default a map is built when it is missing "
                         "or the repository has moved, and skipped otherwise)")
    ap.add_argument("--quiet", action="store_true", help="no summary line")
    args = ap.parse_args()

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
    text = brief(m)
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
        cut = text.splitlines()[:args.max_lines]
        text = "\n".join(cut) + f"\n\n… trimmed to {args.max_lines} lines; " \
               "the full map is beside this file\n"
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

    c = m["counts"]
    if args.quiet:
        return 0
    print(f"framework map: {c['step_modules']} step modules, {c['steps']} steps, "
          f"{c['features']} features, {c['scenarios']} scenarios "
          f"-> {out_dir}/framework_map.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
