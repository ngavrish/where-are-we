"""What the tests themselves say: where coverage survives, which suites measure
load or contracts, and the factories that make their data.
"""

import os
import re

from ..walk import _slurp


def coverage_by_file(ctx) -> dict:
    """Coverage per file, where a report survives."""
    _read = ctx.read
    code_files = ctx.code_files
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
    return {"coverage_by_file": coverage_by_file}


def performance_and_factories(ctx) -> dict:
    """Load and contract testing, and the factories that make test data."""
    code_files = ctx.code_files
    repo = ctx.repo
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
    return {"factories": factories, "perf_suites": perf_suites}
