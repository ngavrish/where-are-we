<div align="center">

# where-are-we

**The first question in an unfamiliar repository — answered in seconds, without a model.**

*Any codebase. Any language. Any agent.*

[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-black.svg)](https://www.python.org)
[![Frameworks](https://img.shields.io/badge/frameworks-20%2B-black.svg)](#frameworks)
[![No dependencies](https://img.shields.io/badge/dependencies-none-black.svg)](pyproject.toml)

</div>

---

An agent opening a repository it has never seen spends its first forty tool
calls on the same questions. Where do the tests live. What may a step call. How
is a scenario launched. Which environment variables must be set. What does the
product actually expose.

At roughly a minute per turn that is half an hour, in every session, for answers
that are identical every time and derivable without a model.

`where-are-we` derives them by walking the tree, and writes them where the agent
will read them.

```bash
pip install git+https://github.com/ngavrish/where-are-we

where-are-we --repo ~/work/my-suite --product ~/work/my-app/src --out /tmp/map
```

```
framework map: 66 step modules, 1446 steps, 182 features, 1889 scenarios -> /tmp/map/framework_map.md
```

## What you get

| file | what it is | typical size |
|---|---|---|
| `framework_map_brief.md` | the digest to put in a prompt | ~40 KB |
| `framework_map.md` | the full map: every step phrase, every scenario with its line number | ~135 KB |
| `framework_map.json` | the same as data, for tooling | — |

Or straight into the file your harness already reads:

```bash
where-are-we --repo . --agent-file AGENTS.md      # also CLAUDE.md, .cursorrules, …
```

The map is written between markers. Whatever else lives in that file survives.

## What it finds

Whatever the repository is. A service, a library, a monorepo, a test suite — it
is read the same way: what it is made of, where it starts, what it serves, what
it exposes, and how its parts depend on each other.


<table>
<tr><td width="50%" valign="top">

**Any codebase**

- languages, by file count
- where execution starts: entry points, `make` targets, npm scripts, container `CMD`
- the HTTP routes it serves — Flask, FastAPI, Django, Express, Go, Spring, Rails
- its data model — SQLAlchemy, Django, Prisma, TypeORM
- the public surface of each module
- how the top-level packages depend on each other
- monorepo layout, where there is one

**Shape of a test suite**

- how the suite is layered, and where each layer lives
- how a scenario is launched, from the runner scripts' own usage headers
- what a step may call — public methods, with signatures
- which step modules and page objects serve each feature
- what each step actually calls

**Facts you would otherwise grep for**

- every scenario, with its line number
- every environment variable, and the file that sets it
- locator constants, timeouts, budgets, retries
- module constants and helpers
- hooks, and what they do
- fixtures, test data, coverage documents
- code owners, per-directory READMEs

</td><td width="50%" valign="top">

**The product under test**

- routes, storage keys, API paths
- every `data-testid`, and which component owns it
- interface strings an assertion can match

**Contracts**

- OpenAPI parsed to method and path
- GraphQL to its types
- migrations to the tables and columns they create
- mock servers, feature flags, locale keys
- pinned image tags, secret paths (paths only)

**The state of the suite itself**

- step phrases that overlap — so a new one is not written when one exists
- phrases no feature uses
- page-object methods nothing calls
- the TODO and FIXME the code already admits to
- git history, and which ticket touched what
- quarantined scenarios, and the slow ones

</td></tr>
</table>

## Frameworks

behave · pytest · jest · playwright · cypress · robot · JUnit · TestNG ·
Cucumber-JVM (Java · Kotlin · Scala) · cucumber-js (TypeScript · JavaScript) ·
cucumber-ruby · rspec · go test · xUnit · NUnit · SpecFlow · PHPUnit · Behat ·
Rust · XCTest · karate · gauge · k6 · gatling

Detection is by shape, not by directory name: a page object is a class that owns
selectors — wherever it lives, whatever the team calls it. Run it on a
repository before you know what is in it.

## When the repository knows better

Autodetection gets the shape right and the vocabulary wrong. A repository states
its own, and what it states wins:

```bash
where-are-we --repo . --init      # writes a starter manifest from what was detected
```

```json
{
  "name": "billing-e2e",
  "purpose": "End-to-end tests for the billing portal.",
  "layers": {
    "steps": "steps/*.py — steps own no selectors, they call page objects"
  },
  "product_src": ["../billing-web/src"],
  "conventions": ["After a fix, re-run only what failed."]
}
```

`.framework-map.json` at the root, or the same block fenced as
` ```framework-map ` inside `README.md`.

Directories can explain themselves too:

```bash
wawe-readmes --repo .    # a README in every content directory that lacks one,
                         # derived from what is in it, with one TODO line for a human
```

The map reads them back.

## Keeping it current

A map is worth rebuilding when the thing it describes has moved. The commit and
the newest file in the tree are recorded with it, so running the command on
every checkout costs a stat walk and nothing else. `--force` rebuilds regardless.

```bash
where-are-we --repo . --install-hook git     # post-checkout, post-merge, post-commit
where-are-we --repo . --install-hook agent   # SessionStart, before the first turn
```

## Options

```
--repo PATH          the test repository to index
--product PATH,…     source roots of the application under test
--out DIR            where the three files land
--agent-file FILE    also write the brief into AGENTS.md / CLAUDE.md / .cursorrules
--rules PATH         a corpus of rules to list by name
--runs-api URL       a runs database, to carry what earlier runs concluded
--init               write a starter .framework-map.json
--install-hook git|agent
--force              rebuild even when nothing moved
--quiet              no summary line
```

## Why it exists

It was built for an agentic QA pipeline where seven branches ran at once and
each one opened the same way: forty greps to find where the steps live, which
page object owns the portal, how the driver is built, what `environment.py`
does. Identical in every branch, identical every run, and derivable without a
model — three runs died at their deadline with the branches still reading.

Nothing about it turned out to be specific to that pipeline, or to that agent,
or to Python. So it lives here.

## License

MIT
