"""The data layer and what crosses the wire: constraints and indexes, the
datastores and brokers in use, transaction boundaries, the status codes a route
answers with, and the services this code calls out to.
"""

import os
import re

from ..walk import _lines_matching, _slurp


def datastores(ctx) -> dict:
    """Datastores and brokers beyond SQL and Kafka."""
    code_files = ctx.code_files
    repo = ctx.repo
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
    return {"stores": stores}


def db_constraints(ctx) -> dict:
    """Indexes and constraints: a table is not its columns alone, and a test
    that asserts uniqueness wants to know where uniqueness is declared."""
    code_files = ctx.code_files
    repo = ctx.repo
    db_constraints: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        found = re.findall(
            r"(?:CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?([\w.]+)"
            r"|CONSTRAINT\s+([\w.]+)|(?:PRIMARY|FOREIGN)\s+KEY\s*\(([^)]{1,60})\)"
            r"|UNIQUE\s*\(([^)]{1,60})\))", body, re.I)[:20]
        names = [next(x for x in t if x) for t in found]
        if names:
            db_constraints[rel] = sorted(set(names))[:15]
    db_constraints = dict(list(db_constraints.items())[:20])
    return {"db_constraints": db_constraints}


def client_policies(ctx) -> dict:
    """Retries, timeouts, circuit breakers, rate limits: the behaviour a flaky
    test is usually arguing with."""
    code_files = ctx.code_files
    repo = ctx.repo
    client_policies: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = _lines_matching(body, ('backoff', 'breaker', 'circuitw', 'connect_timeout', 'max_retries', 'rate_limit', 'ratelimiter', 'read_timeout"\n            r"', 'retries', 'throttlw', 'timeout'), 5)
        if hits:
            client_policies[rel] = [h.strip()[:110] for h in hits]
    client_policies = dict(list(client_policies.items())[:25])
    return {"client_policies": client_policies}


def transactions(ctx) -> dict:
    """Transaction boundaries and idempotency, where the code marks them."""
    code_files = ctx.code_files
    repo = ctx.repo
    transactions: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = _lines_matching(body, ('@transactional', 'atomic', 'begin', 'commit', 'idempotencw', 'idempotency-key', 'rollback', 'transaction"\n                          r"'), 4)
        if hits:
            transactions[rel] = [h.strip()[:110] for h in hits]
    transactions = dict(list(transactions.items())[:20])
    return {"transactions": transactions}


def status_codes(ctx) -> dict:
    """Which status codes a route can answer with."""
    code_files = ctx.code_files
    repo = ctx.repo
    status_codes: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        codes = re.findall(r"(?:status_code\s*=\s*|status\(|WriteHeader\(|HttpStatus\.|"
                           r"res\.status\(|abort\()\s*(\d{3})", body)[:20]
        codes += re.findall(r"\b(?:return|raise)[^\n]{0,40}?\b(\d{3})\b[^\n]{0,20}(?:Error|Response)",
                            body)[:10]
        codes = [c for c in codes if c.startswith(("2", "3", "4", "5"))]
        if codes:
            status_codes[rel] = sorted(set(codes))[:12]
    status_codes = dict(sorted(status_codes.items(), key=lambda kv: -len(kv[1]))[:25])
    return {"status_codes": status_codes}


def outbound_calls(ctx) -> dict:
    """Calls out to other services: the URLs of things this codebase does not own."""
    code_files = ctx.code_files
    repo = ctx.repo
    outbound = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        urls = re.findall(r"[\"\'`](https?://(?!localhost|127\.0\.0\.1)[\w.:%-]+)(?:/[\w./{}-]*)?[\"\'`]",
                          body)[:12]
        hosts = re.findall(r"(?:host|HOST|BASE_URL|_URL)\W{1,4}[\"\']([\w.-]+\.[a-z]{2,})", body)[:8]
        both = sorted(set(urls + hosts))
        if both:
            outbound[rel] = both[:10]
    outbound = dict(sorted(outbound.items(), key=lambda kv: -len(kv[1]))[:25])
    return {"outbound": outbound}
