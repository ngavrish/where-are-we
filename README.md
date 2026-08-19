<div align="center">

<br>

# where are we

### The first question in an unfamiliar repository.<br>Answered in seconds, without a model.

<br>

[![PyPI](https://img.shields.io/pypi/v/where-are-we?style=for-the-badge&color=111111&labelColor=111111&logo=pypi&logoColor=white)](https://pypi.org/project/where-are-we/)
[![CI](https://img.shields.io/github/actions/workflow/status/ngavrish/where-are-we/ci.yml?style=for-the-badge&color=111111&labelColor=111111&label=ci)](https://github.com/ngavrish/where-are-we/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-111111?style=for-the-badge&labelColor=111111)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-none-111111?style=for-the-badge&labelColor=111111)](pyproject.toml)

**any codebase · any language · any agent**

<br>

</div>

```console
$ where-are-we --repo . --agent-file AGENTS.md

framework map: 66 step modules, 1446 steps, 182 features, 1889 scenarios -> .wawe/framework_map.md
```

Your next agent session opens already knowing where it is.

<br>

## Install

```bash
pip install where-are-we                              # anywhere
brew tap ngavrish/tap && brew install where-are-we    # macOS
curl -fsSL https://ngavrish.github.io/where-are-we/install.sh | sh   # Debian · Ubuntu · Fedora · RHEL
```

<details>
<summary><b>Without installing anything</b></summary>

```bash
docker run --rm -v "$PWD:/work" -v "$PWD/.wawe:/out" ghcr.io/ngavrish/where-are-we
```

</details>

<details>
<summary><b>Doing the Linux repository by hand</b></summary>

```bash
curl -fsSL https://ngavrish.github.io/where-are-we/apt-key.asc \
  | sudo gpg --dearmor -o /usr/share/keyrings/where-are-we.gpg
echo "deb [signed-by=/usr/share/keyrings/where-are-we.gpg] https://ngavrish.github.io/where-are-we stable main" \
  | sudo tee /etc/apt/sources.list.d/where-are-we.list
sudo apt-get update && sudo apt-get install where-are-we
```

Or the package alone: [`where-are-we_all.deb`](https://github.com/ngavrish/where-are-we/releases/latest/download/where-are-we_all.deb) · `where-are-we-*.rpm`

</details>

<br>

## The problem

An agent opening a repository it has never seen spends its first forty tool
calls on questions that have the same answer every time:

> *Where do the tests live? What may a step call? How is a scenario launched?
> Which environment variables must be set? What does the product expose?*

At a minute a turn that is **half an hour, per session**, for answers no model is
needed to produce. Seven parallel branches means seven copies of it, every run.

This walks the tree instead, and writes the answers where the agent will read
them.

<br>

## Who it is for

|  | |
|---|---|
| **You run agents on a codebase** | The brief goes in the prompt. The session starts at turn one, not turn forty. |
| **You maintain a pipeline that fans out** | Every branch gets the same map, built once, for free. |
| **Someone new is joining** | The onboarding document that cannot go stale — it is derived, not written. |
| **You inherited something nobody can explain** | Point it at the thing: routes, data model, queues, dead code, who has been touching what. |

<br>

## What you get

| file | what it is |
|---|---|
| **`framework_map_brief.md`** | the digest for a prompt — sizeable with `--only`, `--skip`, `--max-lines` |
| **`framework_map.md`** | the full map: every step phrase, every scenario with its line number |
| **`framework_map.json`** | the same as data — a versioned contract, see [SCHEMA.md](SCHEMA.md) |

`--agent-file` writes the brief between markers into `AGENTS.md`, `CLAUDE.md`,
`.cursorrules`, `.github/copilot-instructions.md`. Anything else in the file
survives.

<br>

## What it reads

<table>
<tr>
<td width="33%" valign="top">

#### The code

languages and lines · entry points ·
`make` targets · npm scripts ·
container `CMD` · HTTP routes it
serves · status codes it returns ·
data model · public surface of
every module · cross-file call
graph · package dependency graph
and its cycles · files nothing
imports · the functions carrying
the complexity · blocks that
appear twice · monorepo layout

</td>
<td width="33%" valign="top">

#### What it runs on

queues, topics, subjects · gRPC
services · scheduled work ·
Kubernetes probes, resources,
replicas · Terraform, Pulumi,
Ansible · cache keys · permissions
and roles · metrics, spans, log
fields · error types · retries,
timeouts, breakers, rate limits ·
transactions and idempotency ·
third-party services it calls ·
what is actually installed

</td>
<td width="33%" valign="top">

#### Contracts and decay

OpenAPI to method and path ·
GraphQL types · migrations to
tables and columns · mocks ·
feature flags and where they are
branched on · locale keys · pinned
images · secret paths, never
values · ADRs · coverage ·
deprecations · docs pointing at
files that are gone · git history ·
who has been touching what

</td>
</tr>
</table>

#### And a test suite, if there is one

Layers and entry points · what a step may call, with signatures · every scenario
with its line number · hooks, locators, timeouts, fixtures · tags and what they
mean · which modules and page objects serve each feature · **step phrases that
overlap**, so a new one is not written when one exists · **phrases no feature
uses** · dead page-object methods · quarantined scenarios · and, from past
junit, the slow ones.

<br>

## Supported

<table>
<tr><td><b>Test runners</b></td><td>

behave · pytest · jest · vitest · playwright · cypress · robot · JUnit · TestNG ·
Cucumber-JVM · cucumber-js · cucumber-ruby · rspec · go test · xUnit · NUnit ·
SpecFlow · PHPUnit · Behat · Rust · XCTest · ExUnit · Flutter · Spock ·
clojure.test · hspec · busted · Foundry · karate · gauge · k6 · gatling ·
JMeter · Locust · Espresso · Detox

</td></tr>
<tr><td><b>Languages</b></td><td>

Python · TypeScript · JavaScript · Go · Java · Kotlin · Scala · Ruby · Rust ·
C# · PHP · Swift · C/C++ · Elixir · Erlang · Dart · Groovy · Clojure · Haskell ·
Lua · Perl · R · Julia · Objective-C · F# · VB.NET · Solidity · Shell · SQL

</td></tr>
<tr><td><b>Web</b></td><td>

Flask · FastAPI · Django · Express · Nest · Go net/http · chi · Spring · Rails ·
React · Vue · Svelte · Angular · Storybook

</td></tr>
<tr><td><b>Infrastructure</b></td><td>

Docker · Compose · Kubernetes · Helm · Terraform · CloudFormation · Pulumi ·
Bicep · Ansible · Chef · Puppet · GitHub Actions · GitLab CI · Jenkins ·
CircleCI · Azure Pipelines · Travis · Buildkite · Drone

</td></tr>
<tr><td><b>Data</b></td><td>

PostgreSQL and friends · MongoDB · Elasticsearch · DynamoDB · Cassandra ·
ClickHouse · Kafka · RabbitMQ · SQS · NATS · Pulsar · MQTT · dbt · Airflow ·
Spark · notebooks

</td></tr>
</table>

Detection is by shape, not by directory name: a page object is a class that owns
selectors — wherever it lives, whatever the team calls it. Point it at a
repository before you know what is in it.

<br>

## In CI, and in other people's repositories

```yaml
- uses: ngavrish/where-are-we@v1
  with:
    agent-file: AGENTS.md
    comment: "true"          # post the summary on the pull request
```

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/ngavrish/where-are-we
  rev: v0.3.0
  hooks: [{id: where-are-we}]
```

<br>

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

`.framework-map.json` at the root, or the same block fenced as ` ```framework-map `
in `README.md`. Directories can explain themselves too — `wawe-readmes` writes
one into every content directory that lacks it, derived from what is in it.

<br>

## Keeping it current

The commit and the newest file in the tree are recorded with the map, so running
it on every checkout costs a stat walk and nothing else.

```bash
where-are-we --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --install-hook agent   # SessionStart, before the first turn
where-are-we --diff                 # what changed since the last map
```

<br>

## Options

```
--repo PATH                  the repository to index
--product PATH,…             source roots of the application under test
--also PATH,…                other repositories to fold into the same map
--out DIR                    where the three files land
--agent-file FILE            also write the brief into AGENTS.md / CLAUDE.md / …
--only "routes,data model"   keep only these sections in the brief
--skip "coverage,history"    drop these
--max-lines N                cap the brief; the full map is untouched
--diff                       what changed since the map already in --out
--init                       write a starter .framework-map.json
--install-hook git|agent     wire it into something that already runs
--watch SECONDS              rebuild whenever the tree moves
--html                       also write framework_map.html
--rules PATH                 a corpus of rules to list by name
--force                      rebuild even when nothing moved
--quiet                      no summary line
```

`.wawe.toml` holds any of these as defaults. `.wawe-ignore` (falling back to
`.gitignore`) keeps build output out. Anything shaped like a credential is
redacted before it reaches a file.

<br>

## As a library

```python
from where_are_we import build, brief

m = build("/path/to/repo")
print(m["counts"], len(m["routes_served"]))
open("AGENTS.md", "w").write(brief(m))
```

<br>

## Why it exists

It was built inside an agentic QA pipeline where seven branches ran at once and
each opened the same way: forty greps to find where the steps live, which page
object owns the portal, how the driver is built, what `environment.py` does.
Identical in every branch, identical every run, derivable without a model — and
three runs died at their deadline with the branches still reading.

Nothing about it turned out to be specific to that pipeline, that agent, or that
language.

<br>

## Contributing

Issues and pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). A
change keeps the JSON contract in [SCHEMA.md](SCHEMA.md) and comes with a case
in `tests/` built from a real directory.

<br>

<div align="center">

**MIT** · built for agents, useful to people

</div>
