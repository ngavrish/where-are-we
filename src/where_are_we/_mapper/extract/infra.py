"""How the code is built, run and watched: build systems, third-party SDKs,
logging and observability configuration, and the assumptions it makes about
time.
"""

import os
import re

from ..walk import _lines_matching, _slurp


def build_systems(ctx) -> dict:
    """Build systems and their module graphs."""
    code_files = ctx.code_files
    repo = ctx.repo
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
    return {"build_systems": build_systems}


def observability_config(ctx) -> dict:
    """Observability configuration and policy."""
    code_files = ctx.code_files
    repo = ctx.repo
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
    return {"obs_config": obs_config}


def logging_config(ctx) -> dict:
    """Logging configuration: levels and handlers, from config rather than code."""
    code_files = ctx.code_files
    repo = ctx.repo
    logging_config = {}
    for rel in code_files:
        low = rel.lower()
        if not any(k in low for k in ("logging", "log4j", "logback", "serilog", "nlog")):
            continue
        body = _slurp(os.path.join(repo, rel))
        levels = re.findall(r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|TRACE)\b", body)[:12]
        if levels:
            logging_config[rel] = sorted(set(levels))
    return {"logging_config": logging_config}


def time_assumptions(ctx) -> dict:
    """Assumptions about time: a suite that ignores them fails at midnight."""
    code_files = ctx.code_files
    repo = ctx.repo
    time_assumptions: dict[str, list] = {}
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel))
        if not body:
            continue
        hits = _lines_matching(body, ('america/w', 'dayjs.tz', 'europe/w"\n                          r"', 'locale.', 'pytz', 'strftime', 'timezone', 'tolocalew', 'tzinfo', 'utc', 'zoneinfo'), 4)
        if hits:
            time_assumptions[rel] = [h.strip()[:110] for h in hits]
    time_assumptions = dict(list(time_assumptions.items())[:20])
    return {"time_assumptions": time_assumptions}


def sdks(ctx) -> dict:
    """Which third-party services the code actually talks to."""
    code_files = ctx.code_files
    repo = ctx.repo
    sdks: dict[str, list] = {}
    SDK_HINTS = {
        "aws": r"\bboto3|aws-sdk|AWS\.|amazonaws", "gcp": r"google\.cloud|googleapis",
        "azure": r"azure\.\w+|Azure\.", "stripe": r"\bstripe\b",
        "twilio": r"\btwilio\b", "sendgrid": r"\bsendgrid\b",
        "datadog": r"\bdatadog|ddtrace", "sentry": r"\bsentry\b",
        "segment": r"\bsegment\b|analytics\.track", "slack": r"slack_sdk|slack-sdk|hooks\.slack",
        "github": r"PyGithub|@octokit|api\.github\.com", "jira": r"\bjira\b",
        "openai": r"\bopenai\b", "anthropic": r"\banthropic\b",
        "kubernetes": r"kubernetes\.client|client-go", "redis": r"\bredis\b",
        "postgres": r"psycopg|pgx|node-postgres", "snowflake": r"\bsnowflake\b",
        "databricks": r"\bdatabricks\b", "salesforce": r"\bsalesforce|simple_salesforce",
    }
    for rel in code_files:
        body = _slurp(os.path.join(repo, rel), 60000)
        if not body:
            continue
        for name, pat in SDK_HINTS.items():
            if re.search(pat, body, re.I):
                sdks.setdefault(name, []).append(os.path.basename(rel))
    sdks = {k: sorted(set(v))[:8] for k, v in sorted(sdks.items(), key=lambda kv: -len(kv[1]))[:20]}
    return {"sdks": sdks}
