<div align="center">

# where are we

Codebase context for agents. Derived from the tree, not written by hand.

[![PyPI](https://img.shields.io/pypi/v/where-are-we?style=flat-square&color=1a1a1a&labelColor=1a1a1a)](https://pypi.org/project/where-are-we/)
[![CI](https://img.shields.io/github/actions/workflow/status/ngavrish/where-are-we/ci.yml?style=flat-square&color=1a1a1a&labelColor=1a1a1a&label=ci)](https://github.com/ngavrish/where-are-we/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/MIT-1a1a1a?style=flat-square&labelColor=1a1a1a)](LICENSE)

</div>

<br>

An agent opening an unfamiliar repository spends its first forty tool calls
finding out where the tests live, what a step may call, how a scenario is
launched, which variables must be set. Half an hour, every session, for answers
that never change and need no model to produce.

This walks the tree instead. Two seconds, no model, no network.

```console
$ where-are-we --repo . --agent-file AGENTS.md

framework map: 66 step modules, 1446 steps, 182 features, 1889 scenarios
```

The next session starts at turn one.

<br>

## Install

```bash
pip install where-are-we
brew tap ngavrish/tap && brew install where-are-we
curl -fsSL https://ngavrish.github.io/where-are-we/install.sh | sh
```

macOS, Debian, Ubuntu, Fedora, RHEL. Or `ghcr.io/ngavrish/where-are-we`, and
install nothing.

<br>

## Three files

`framework_map_brief.md` — the digest for a prompt.
`framework_map.md` — every step phrase, every scenario with its line number.
`framework_map.json` — the same as data, under a versioned contract.

`--agent-file` writes the brief into `AGENTS.md`, `CLAUDE.md` or `.cursorrules`,
between markers. Everything else in the file survives.

<br>

## What it reads

**The code.** Languages and lines. Entry points, make targets, npm scripts,
container commands. The HTTP routes it serves and the status codes it returns.
The data model. The public surface of every module. Call graph across files,
package graph and its cycles. Files nothing imports. The functions carrying the
complexity. Blocks that appear twice.

**What it runs on.** Queues and topics. gRPC services. Scheduled work.
Kubernetes probes, resources, replicas. Terraform, Pulumi, Ansible. Cache keys.
Permissions. Metrics, spans, log fields. Error types. Retries, timeouts,
breakers, rate limits. Transactions and idempotency. The services it calls. What
is actually installed, from the lock files.

**Contracts.** OpenAPI to method and path. GraphQL to its types. Migrations to
tables and columns. Mocks, feature flags and where they are branched on. Locale
keys. Pinned images. Secret paths — never values.

**Decay.** Deprecations. Coverage. Documentation pointing at files that are
gone. Git history and who has been touching what.

**The test suite, if there is one.** Layers and entry points. What a step may
call, with signatures. Hooks, locators, timeouts, fixtures. Tags and what they
mean. Step phrases that overlap, so a new one is not written when one exists.
Phrases no feature uses. Dead page-object methods. The slow scenarios, from past
junit.

<br>

## Supported

Test runners — behave, pytest, jest, vitest, playwright, cypress, robot, JUnit,
TestNG, Cucumber for JVM, JavaScript and Ruby, rspec, go test, xUnit, NUnit,
SpecFlow, PHPUnit, Behat, Rust, XCTest, ExUnit, Flutter, Spock, clojure.test,
hspec, busted, Foundry, karate, gauge, k6, gatling, JMeter, Locust, Espresso,
Detox.

Languages — Python, TypeScript, JavaScript, Go, Java, Kotlin, Scala, Ruby, Rust,
C#, PHP, Swift, C, C++, Elixir, Erlang, Dart, Groovy, Clojure, Haskell, Lua,
Perl, R, Julia, Objective-C, F#, Solidity, Shell, SQL.

Web — Flask, FastAPI, Django, Express, Nest, Go net/http, chi, Spring, Rails,
React, Vue, Svelte, Angular, Storybook.

Infrastructure — Docker, Compose, Kubernetes, Helm, Terraform, CloudFormation,
Pulumi, Bicep, Ansible, Chef, Puppet, GitHub Actions, GitLab CI, Jenkins,
CircleCI, Azure Pipelines, Buildkite, Drone.

Data — PostgreSQL and friends, MongoDB, Elasticsearch, DynamoDB, Cassandra,
ClickHouse, Kafka, RabbitMQ, SQS, NATS, Pulsar, MQTT, dbt, Airflow, Spark,
notebooks.

Detection is by shape, not by directory name. A page object is a class that owns
selectors, wherever it lives and whatever the team calls it. Point it at a
repository before you know what is in it.

<br>

## In a pipeline

```yaml
- uses: ngavrish/where-are-we@v1
  with:
    agent-file: AGENTS.md
    comment: "true"
```

```yaml
- repo: https://github.com/ngavrish/where-are-we
  rev: v0.3.0
  hooks: [{id: where-are-we}]
```

<br>

## Leaving the repository better than you found it

```console
$ where-are-we --docs

would write steps/README.md — explains what this directory holds
would write .framework-map.json — lets this repository state its own vocabulary
would write AGENTS.md — the brief, where every agent harness already looks
would write docs/ARCHITECTURE.md — one page to read before touching anything

4 files. Run with --docs write to create them; existing files are never touched.
```

A map helps one session. A repository that explains itself helps every session,
and a person can correct the explanation.

<br>

## When the repository knows better

Autodetection gets the shape right and the vocabulary wrong. A repository states
its own in `.framework-map.json`, and what it states wins.

```bash
where-are-we --init
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

<br>

## Staying current

The commit and the newest file in the tree are recorded with the map. Running it
on every checkout costs a stat walk and nothing else.

```bash
where-are-we --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --install-hook agent   # before the first turn of a session
where-are-we --diff                 # what changed since the last map
```

<br>

## Options

```
--repo PATH                  the repository to index
--product PATH,…             source roots of the application under test
--also PATH,…                other repositories to fold into the same map
--out DIR                    where the three files land
--agent-file FILE            also write the brief into AGENTS.md, CLAUDE.md, …
--docs [write]               offer the repository the documentation it lacks
--only "routes,data model"   keep only these sections in the brief
--skip "coverage,history"    drop these
--max-lines N                cap the brief; the full map is untouched
--diff                       what changed since the map already in --out
--init                       write a starter .framework-map.json
--install-hook git|agent     wire it into something that already runs
--watch SECONDS              rebuild whenever the tree moves
--html                       also write framework_map.html
--force                      rebuild even when nothing moved
--quiet                      no summary line
```

`.wawe.toml` holds any of these as defaults. `.wawe-ignore` keeps build output
out. Anything shaped like a credential is redacted before it reaches a file.

<br>

## As a library

```python
from where_are_we import build, brief

m = build("/path/to/repo")
open("AGENTS.md", "w").write(brief(m))
```

<br>

## Examples

Real output on three fixtures — a behave suite, a Go service, a React app — in
[`docs/examples`](docs/examples/README.md). Generated by running the tool on
them, not by hand.

<br>

## Why it exists

Built inside an agentic QA pipeline where seven branches ran at once, each
opening the same way: forty greps for where the steps live, which page object
owns the portal, how the driver is built. Identical in every branch, identical
every run, derivable without a model. Three runs died at their deadline with the
branches still reading.

Nothing about it turned out to be specific to that pipeline, that agent, or that
language.

<br>

## Contributing

Issues and pull requests welcome — [CONTRIBUTING.md](CONTRIBUTING.md). A change
keeps the contract in [SCHEMA.md](SCHEMA.md) and comes with a case in `tests/`
built from a real directory.

<br>

<div align="center">

MIT

</div>
