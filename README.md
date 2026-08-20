<div align="center">

# where are we

**Stop paying your agent to grep.**

[![PyPI](https://img.shields.io/pypi/v/where-are-we?style=flat-square&color=1a1a1a&labelColor=1a1a1a)](https://pypi.org/project/where-are-we/)
[![CI](https://img.shields.io/github/actions/workflow/status/ngavrish/where-are-we/ci.yml?style=flat-square&color=1a1a1a&labelColor=1a1a1a&label=ci)](https://github.com/ngavrish/where-are-we/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/MIT-1a1a1a?style=flat-square&labelColor=1a1a1a)](LICENSE)

</div>

One tree walk writes entry points, routes, data model, step signatures, and
every duplicate or dead test into `AGENTS.md` — or JSON for your own harness.
Your agent starts working at turn one, not turn 41.

## What it does

No model, no network, no tokens: it reads the tree, so the same tree always
gives the same map. Without it, every session opens the same way:

```console
# turn 1   ls; find . -name "*steps*"
# turn 7   grep -rn "def click_pay" .
# turn 19  cat conftest.py; cat tox.ini; cat Makefile
# turn 34  grep -rn "BASE_URL" .
# turn 41  first line of actual work
```

With it:

```console
$ where-are-we --repo . --agent-file AGENTS.md --max-lines 200

framework map: 66 step modules, 1359 steps, 179 features, 1782 scenarios -> ./framework_map.md
```

`AGENTS.md` gets a pointer — 849 bytes, not the map:

```markdown
## The framework map

`framework_map.md` (123 KB) is a generated map of this suite and the product it
tests. It is on disk on purpose: read from it, do not carry it. Ask it before
grepping the repository — it already knows.

    where-are-we --ask "the words you need"

That prints only the sections that mention those words. `--sections` lists what
is in it.

It has these sections:

- Where things are
- What a step may call
- Steps that overlap (14 pairs) — check whether one already does what you need
- What past runs measured (slowest first)
- …
```

And the map answers questions instead of being read:

```console
$ where-are-we --ask "refund settled invoice"

## What past runs measured (slowest first)
- billing/refund.feature:88 Refund a settled invoice — ~252s, failed 3×

## Steps that overlap (14 pairs)
- 0.88: "the invoice is settled" (`billing_steps.py`) ≈ "an invoice has settled" (`api_steps.py`)
```

## Why install it

- **The first forty turns stop repeating.** The answers never change between
  sessions and need no model to produce, so produce them once and commit them.
- **A step that exists stops being written twice.** Overlapping phrases, dead
  phrases and uncalled page-object methods are listed by name.
- **It reads a repo it has never seen.** Detection is by shape, not directory
  name: a page object is a class that owns selectors, wherever it lives.
- **It costs a tree walk.** 3s on a 6k-file repo, 2.5min on a 36k-file one,
  cold. Deterministic — same tree, same map, no API bill.

## Install

```bash
pip install where-are-we
brew tap ngavrish/tap && brew install where-are-we
curl -fsSL https://ngavrish.github.io/where-are-we/install.sh | sh
```

macOS, Debian, Ubuntu, Fedora, RHEL. Or `ghcr.io/ngavrish/where-are-we`.

## Output

| File | Contents |
|---|---|
| `framework_map_brief.md` | the digest for a prompt |
| `framework_map.md` | every step phrase, every scenario with its line number |
| `framework_map.json` | the same as data, under a versioned contract |

`--agent-file` writes a **pointer** into `AGENTS.md`, `CLAUDE.md` or
`.cursorrules` between markers. The rest of the file survives.

### Why a pointer and not the map

A prompt is re-sent in full on every turn — that is what a conversation is — so
anything put in one is paid for on every turn of the session, read or not.

Measured on a real run: the brief inlined whole was 253 KB, the agent carrying it
took 424 turns, and the map alone came to **27.4 million tokens re-sent** — a
quarter of everything that run consumed, and the reason a five-hour allowance
emptied in seventy-four minutes. Trimming it to an index still cost 6k a turn for
a document most turns never opened.

| in the prompt | per turn |
|---|---|
| the brief, inlined | 253 KB ≈ 64k tokens |
| an index of its sections | 27 KB ≈ 6k tokens |
| **a pointer** | **849 B ≈ 212 tokens** |

The sections are still named in the pointer, because an agent that cannot see
that a section exists goes back to grepping the repository — which is the thing
this was built to end. Naming them costs two hundred tokens; carrying them costs
sixty-four thousand, every turn.

| command | what it prints |
|---|---|
| `--pointer` | what belongs in a prompt: the path, the sections, how to ask |
| `--ask "words"` | only the sections that mention those words, ranked |
| `--sections` | the section headings |

## What it reads

- **Code** — languages, entry points, make targets, npm scripts, container
  commands, HTTP routes and status codes, data model, module public surface,
  call and package graphs, cycles, unimported files, complexity hotspots,
  duplicate blocks.
- **Runtime** — queues, topics, gRPC, cron, Kubernetes probes and resources,
  Terraform, Pulumi, Ansible, cache keys, permissions, metrics, spans, log
  fields, error types, retries, timeouts, breakers, rate limits, transactions,
  idempotency, outbound services, installed versions from lock files.
- **Contracts** — OpenAPI, GraphQL, migrations, mocks, feature flags and their
  branch points, locale keys, pinned images, secret paths (never values).
- **Decay** — deprecations, coverage, docs pointing at deleted files, git
  history and who touches what.
- **Tests** — layers, entry points, callable step signatures, hooks, locators,
  timeouts, fixtures, tag meanings, overlapping and unused step phrases, dead
  page-object methods, slow scenarios from past junit.

<details>
<summary><b>Supported stacks</b></summary>

**Test runners** — behave, pytest, jest, vitest, playwright, cypress, robot,
JUnit, TestNG, Cucumber (JVM/JS/Ruby), rspec, go test, xUnit, NUnit, SpecFlow,
PHPUnit, Behat, Rust, XCTest, ExUnit, Flutter, Spock, clojure.test, hspec,
busted, Foundry, karate, gauge, k6, gatling, JMeter, Locust, Espresso, Detox.

**Languages** — Python, TypeScript, JavaScript, Go, Java, Kotlin, Scala, Ruby,
Rust, C#, PHP, Swift, C, C++, Elixir, Erlang, Dart, Groovy, Clojure, Haskell,
Lua, Perl, R, Julia, Objective-C, F#, Solidity, Shell, SQL.

**Web** — Flask, FastAPI, Django, Express, Nest, Go net/http, chi, Spring,
Rails, React, Vue, Svelte, Angular, Storybook.

**Infrastructure** — Docker, Compose, Kubernetes, Helm, Terraform,
CloudFormation, Pulumi, Bicep, Ansible, Chef, Puppet, GitHub Actions, GitLab CI,
Jenkins, CircleCI, Azure Pipelines, Buildkite, Drone.

**Data** — PostgreSQL and friends, MongoDB, Elasticsearch, DynamoDB, Cassandra,
ClickHouse, Kafka, RabbitMQ, SQS, NATS, Pulsar, MQTT, dbt, Airflow, Spark,
notebooks.

</details>

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

## Keeping it honest

```bash
where-are-we --init                 # starter .framework-map.json
where-are-we --docs                 # list the docs the repo lacks (--docs write to create)
where-are-we --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --install-hook agent   # before the first turn of a session
where-are-we --diff                 # what changed since the last map
```

Autodetection gets the shape right and the vocabulary wrong, so a repo states
its own in `.framework-map.json` and what it states wins:

```json
{
  "name": "billing-e2e",
  "purpose": "End-to-end tests for the billing portal.",
  "layers": {"steps": "steps/*.py — steps own no selectors, they call page objects"},
  "product_src": ["../billing-web/src"],
  "conventions": ["After a fix, re-run only what failed."]
}
```

`.wawe.toml` holds CLI flags as defaults, `.wawe-ignore` keeps build output out,
existing files are never overwritten, and anything shaped like a credential is
redacted before it reaches a file. The commit and the newest file in the tree are
recorded with the map, so a re-run on an unchanged tree costs a stat walk.

<details>
<summary><b>All options</b></summary>

```
--repo PATH                  the repository to index
--product PATH,…             source roots of the application under test
--also PATH,…                other repositories to fold into the same map
--out DIR                    where the three files land
--agent-file FILE            also write the brief into AGENTS.md, CLAUDE.md, …
--docs [write]               offer the repository the documentation it lacks
--for author|coder           author gets the whole vocabulary; coder gets the rest
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

</details>

## As a library

```python
from where_are_we import build, brief

m = build("/path/to/repo")
open("AGENTS.md", "w").write(brief(m))
```

## Examples

Real output on a behave suite, a Go service and a React app —
[`docs/examples`](docs/examples/README.md). Generated by running the tool, not
by hand.

## Why it exists

Built inside an agentic QA pipeline where seven branches ran at once, each
opening with the same forty greps. Three runs died at their deadline with the
branches still reading. None of it was specific to that pipeline, agent, or
language.

## Contributing

Issues and PRs welcome — [CONTRIBUTING.md](CONTRIBUTING.md). A change keeps the
contract in [SCHEMA.md](SCHEMA.md) and comes with a case in `tests/` built from
a real directory.

<div align="center">

MIT

</div>
