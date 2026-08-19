<div align="center">

# where-are-we

**The first question in an unfamiliar repository — answered in seconds, without a model.**

*Any codebase · any language · any agent*

[![PyPI](https://img.shields.io/pypi/v/where-are-we?color=black)](https://pypi.org/project/where-are-we/)
[![CI](https://github.com/ngavrish/where-are-we/actions/workflows/ci.yml/badge.svg)](https://github.com/ngavrish/where-are-we/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-black.svg)](https://www.python.org)
[![Dependencies](https://img.shields.io/badge/dependencies-none-black.svg)](pyproject.toml)

</div>

---

```bash
pip install where-are-we
where-are-we --repo . --agent-file AGENTS.md
```

That is the whole setup. The next agent session opens already knowing where it
is.

## Who this is for

**You run agents on a codebase.** Every session opens with the same forty tool
calls: where do the tests live, what may a step call, how is a scenario
launched, which environment variables must be set, what does the product
expose. At a minute a turn that is half an hour of your budget, per session, for
answers that never change between sessions and need no model to produce.

**You maintain a pipeline that fans out.** Seven branches means seven copies of
that half hour, in parallel, every run. This was built when three runs in a row
died at their deadline with the branches still reading.

**Someone new is joining.** The same map is the onboarding document, and it
cannot go stale: it is rebuilt from the checkout, not written by hand.

**You inherited a repository nobody can explain.** Point it at the thing and
read what comes out — routes, data model, queues, schedules, dead code, who has
been touching what.

## What you get

| file | what it is | typical size |
|---|---|---|
| `framework_map_brief.md` | the digest to put in a prompt | 40–85 KB, sizeable with `--only` / `--max-lines` |
| `framework_map.md` | the full map: every step phrase, every scenario with its line number | ~135 KB |
| `framework_map.json` | the same as data — versioned contract, see [SCHEMA.md](SCHEMA.md) | — |

`--agent-file` writes the brief between markers into `AGENTS.md`, `CLAUDE.md`,
`.cursorrules`, `.github/copilot-instructions.md` — anything else in the file
survives.

## What it reads

<table>
<tr><td width="50%" valign="top">

### Any codebase

- languages, by file count
- entry points, `make` targets, npm scripts, container `CMD`
- HTTP routes it serves — Flask, FastAPI, Django, Express, Go, Spring, Rails
- data model — SQLAlchemy, Django, Prisma, TypeORM
- public surface of every module
- cross-file call graph, and how top-level packages depend on each other
- queues, topics, subjects — Kafka, RabbitMQ, SQS, pub/sub
- gRPC services and methods, from `.proto`
- scheduled work — cron, Celery beat, Airflow, CronJobs
- Kubernetes, Helm, Terraform
- cache keys, permissions, roles
- metrics, spans, log fields
- error types, CLI commands, frontend components, stores and hooks
- monorepo layout

</td><td width="50%" valign="top">

### Contracts and decay

- OpenAPI parsed to method and path
- GraphQL to its types
- migrations to the tables and columns they create
- mock servers, feature flags, locale keys
- pinned image tags, secret paths (paths only, never values)
- ADRs, coverage reports, largest files, declared licenses
- deprecations, API versions, documentation that points at files
  that are not there
- git history, and who has been touching what

### A test suite, if there is one

- layers, entry points, what a step may call — with signatures
- every scenario with its line number, every step phrase
- hooks, locators, timeouts, fixtures, tags and what they mean
- which modules and page objects serve each feature
- **overlapping step phrases**, so a new one is not written when one exists
- **phrases no feature uses**, dead page-object methods, admitted TODOs
- quarantined scenarios, and — from past junit — the slow ones

</td></tr>
</table>

## Supported

**Test runners** — behave · pytest · jest · vitest · playwright · cypress ·
robot · JUnit · TestNG · Cucumber-JVM (Java, Kotlin, Scala) · cucumber-js
(TypeScript, JavaScript) · cucumber-ruby · rspec · go test · xUnit · NUnit ·
SpecFlow · PHPUnit · Behat · Rust · XCTest · karate · gauge · k6 · gatling

**Languages** — Python · TypeScript · JavaScript · Go · Java · Kotlin · Scala ·
Ruby · Rust · C# · PHP · Swift · C/C++ · Shell · SQL · Protobuf

**Web frameworks** — Flask · FastAPI · Django · Express · Nest · Go net/http and
chi · Spring · Rails

**Infrastructure** — Docker · Compose · Kubernetes · Helm · Terraform · GitHub
Actions · GitLab CI

Detection is by shape, not by directory name: a page object is a class that owns
selectors — wherever it lives, whatever the team calls it. Point it at a
repository before you know what is in it.

## When the repository knows better

Autodetection gets the shape right and the vocabulary wrong. A repository states
its own, and what it states wins:

```bash
where-are-we --repo . --init      # a starter manifest, from what was detected
```

```json
{
  "name": "billing-e2e",
  "purpose": "End-to-end tests for the billing portal.",
  "layers": {"steps": "steps/*.py — steps own no selectors, they call page objects"},
  "product_src": ["../billing-web/src"],
  "conventions": ["After a fix, re-run only what failed."]
}
```

`.framework-map.json` at the root, or the same block fenced as
` ```framework-map ` in `README.md`.

Directories can explain themselves too:

```bash
wawe-readmes --repo .   # a README in every content directory that lacks one,
                        # derived from what is in it, one TODO line for a human
```

The map reads them back.

## Keeping it current

The commit and the newest file in the tree are recorded with the map, so running
it on every checkout costs a stat walk and nothing else.

```bash
where-are-we --repo . --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --repo . --install-hook agent   # SessionStart, before the first turn
where-are-we --repo . --diff                 # what changed since the last map
```

## Options

```
--repo PATH                  the repository to index
--product PATH,…             source roots of the application under test
--out DIR                    where the three files land
--agent-file FILE            also write the brief into AGENTS.md / CLAUDE.md / …
--only "routes,data model"   keep only these sections in the brief
--skip "coverage,history"    drop these
--max-lines N                cap the brief; the full map is untouched
--diff                       what changed since the map already in --out
--init                       write a starter .framework-map.json
--install-hook git|agent     wire it into something that already runs
--rules PATH                 a corpus of rules to list by name
--runs-api URL               a runs database, to carry what earlier runs concluded
--force                      rebuild even when nothing moved
--quiet                      no summary line
```

`.wawe-ignore` (falling back to `.gitignore`) keeps build output out;
`WAWE_MAX_FILES` bounds the walk.

## As a library

```python
from where_are_we import build, brief

m = build("/path/to/repo")
print(m["counts"], len(m["routes_served"]))
open("AGENTS.md", "w").write(brief(m))
```

## Why it exists

It was built inside an agentic QA pipeline where seven branches ran at once and
each opened the same way: forty greps to find where the steps live, which page
object owns the portal, how the driver is built, what `environment.py` does.
Identical in every branch, identical every run, derivable without a model — and
three runs died at their deadline with the branches still reading.

Nothing about it turned out to be specific to that pipeline, that agent, or that
language.

## Contributing

Issues and pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Changes are expected to keep the JSON contract in [SCHEMA.md](SCHEMA.md) and to
come with a case in `tests/` built from a real directory.

## License

MIT
