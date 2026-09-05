"""The map as text: the full digest, the brief, the pointer that goes in a
prompt, and the lookups the CLI and the MCP server answer out of a map that was
already written.

Nothing here walks a repository. Everything is a function of the map dict, or
of the files a previous build left behind.
"""

import json
import os

from . import state
from .state import TRUNCATED

try:
    from ..ask import fit_lines, map_heads
except ImportError:  # run as a plain file, with no package around it
    from ask import fit_lines, map_heads  # type: ignore[no-redef]


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
    # Every name index_declarations found, everywhere it looked: Rust, Kotlin,
    # C#, Ruby and the rest, next to each other because a name is a name
    # whatever it is written in. `ask.py`'s own "Defined here" answers one
    # query against the same table; this is the same heading with nothing
    # asked yet, so a reader skimming this file sees that the map reaches
    # these languages at all before it ever needs to ask about one of them.
    # The brief is what `--agent-file` writes straight into a prompt, so this
    # list is capped hard: a large repository's full name table belongs in
    # framework_map.json (`_definitions_for` reads it there, uncapped), not
    # in the tens of thousands of tokens a prompt actually pays for.
    defs = _as_dict(m.get("definitions"))
    if defs:
        _cap = 80
        rows = [f"- `{name}` — {loc}" for name, loc in sorted(defs.items())[:_cap]]
        if len(defs) > _cap:
            rows.append(f"… {len(defs) - _cap} more declared names; ask `defines`")
        _sect("Defined here", rows)
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


def changed_since(repo: str, out_dir: str) -> list[str]:
    """Files that moved since the last time `--pointer` was asked here.

    A session's boundaries are invisible to git; the only trace of "last
    time" is whatever the previous `--pointer` call wrote down. That trace
    is a commit hash, kept in `<out_dir>/.pointer-head`. This diffs it
    against the current HEAD, folds in whatever is still uncommitted, and
    then overwrites the file with the current HEAD for the call after this
    one. A repository with no git, or a first call with nothing recorded
    yet to compare against, reports nothing changed.
    """
    import subprocess

    def _git(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                               text=True, timeout=15)
            return r.stdout if r.returncode == 0 else None
        except Exception:  # noqa: BLE001, a repository without git reports nothing
            return None

    head = _git("rev-parse", "HEAD")
    if head is None:
        return []
    head = head.strip()

    head_path = os.path.join(out_dir, ".pointer-head")
    try:
        with open(head_path, encoding="utf-8") as fh:
            prev = fh.read().strip()
    except OSError:
        prev = ""

    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(head_path, "w", encoding="utf-8") as fh:
            fh.write(head + "\n")
    except OSError:
        pass

    if not prev:
        return []

    changed: set[str] = set()
    diff = _git("diff", "--name-only", f"{prev}..{head}")
    if diff:
        changed.update(line for line in diff.splitlines() if line)
    status = _git("status", "--porcelain")
    if status:
        for line in status.splitlines():
            code, path = line[:2], line[3:].strip()
            # A rename or copy (R/C) reports "old -> new"; only the new
            # path is a file that exists to be read, so that is what goes
            # in the list, not the arrow notation.
            if ("R" in code or "C" in code) and " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            if path:
                changed.add(path)
    return sorted(changed)


def pointer(map_path: str, brief_path: str = "", changed: list[str] | None = None) -> str:
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
        size = os.path.getsize(map_path)
        brief = os.path.join(os.path.dirname(map_path) or ".", "framework_map_brief.md")
        if os.path.exists(brief):
            size += os.path.getsize(brief)
        size = max(1, size // 1024)
    except OSError as exc:
        return f"(no framework map: {exc})"
    # A suite has step modules; a plain repository does not, and calling its
    # map "a map of this suite and the product it tests" told the reader to
    # look for tests that are not there.
    suite = False
    try:
        with open(os.path.join(os.path.dirname(map_path) or ".",
                               "framework_map.json"), encoding="utf-8") as fh:
            counts = (json.load(fh) or {}).get("counts") or {}
        suite = bool(counts.get("step_modules") or counts.get("features"))
    except (OSError, ValueError):
        pass
    what = "this suite and the product it tests" if suite else "this repository"

    lines = [
        f"## The framework map",
        "",
        f"`{map_path}` ({size} KB with its brief) is a generated map of {what}. "
        "It is on disk on purpose: read from it, do not carry "
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
        if sum(len(x) + 1 for x in lines) + len(line) > state.POINTER_MAX:
            lines.append(f"- … and {len(heads) - (len(lines) - 8)} more; "
                         "`--sections` lists them all")
            break
        lines.append(line)
    if brief_path:
        lines += ["", f"A shorter brief of the same thing is `{brief_path}`."]
    if changed:
        shown = changed[:10]
        more = len(changed) - len(shown)
        names = ", ".join(shown)
        if more:
            names += f", … and {more} more"
        note = (f"Since the last session {len(changed)} file{'s' if len(changed) != 1 else ''} changed: {names}. "
                "Ask the map about them before reading them whole.")
        # Same budget as the rest of the pointer: said only when it fits,
        # never at the cost of going over what a prompt should carry.
        if len(("\n".join(lines) + "\n\n" + note + "\n").encode()) <= state.POINTER_MAX:
            lines += ["", note]
    return "\n".join(lines) + "\n"


def _definitions_for(map_path: str, terms: list[str],
                     extra: list[str] | None = None) -> list[str]:
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
        low = name.lower()
        row = f"- `{name}` — {where}"
        if terms and (all(t in low for t in terms) or any(t == low for t in terms)):
            literal.append(row)
        elif any(t in low for t in extra):
            expansion.append(row)
    return (sorted(literal) + sorted(expansion))[:40]


def meaning_tail(out_dir: str, words: str, already: str, k: int = 4,
                 room: int = 5000) -> str:
    """The 'Related by meaning' section, deduplicated against an answer
    already built by keywords. Empty string when there is no index, no
    library, or nothing new to add - the keyword answer stands alone."""
    try:
        from .. import semantic as _sem
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
