# where-are-we

The first question any newcomer asks in an unfamiliar repository — a person on
their first day, or an agent on its first turn — is *where are we*: where the
tests live, what a step may call, how a scenario is launched, which environment
variables must be set, what the product under test actually exposes.

Answering it by reading the code costs an agent forty tool calls before it can
change one line. This answers it in seconds, deterministically, with no model
involved, and writes the answer where the agent will read it.

```bash
pip install where-are-we

where-are-we --repo ~/work/my-suite --product ~/work/my-app/src --out /tmp/map
```

Three files land in `--out`:

| file | what it is |
|---|---|
| `framework_map_brief.md` | the digest to put in a prompt |
| `framework_map.md` | the full map: every step phrase, every scenario with its line number |
| `framework_map.json` | the same as data |

## What it finds

**Shape** — how the suite is layered and where each layer lives, how a scenario
is launched (from the runner scripts' own usage headers), what a step may call
(public methods with signatures), which step modules and page objects serve each
feature, what each step calls.

**Facts you would otherwise grep for** — every scenario with its line number,
every environment variable and the file that sets it, locator constants,
timeouts and budgets, module constants and helpers, behave hooks and what they
do, test data, fixtures, coverage documents, code owners, per-directory READMEs.

**The product under test** — routes, storage keys, API paths, every
`data-testid` and which component owns it, interface strings assertions can
match. Point at it with `--product`; without it, siblings of the repo are tried.

**Contracts** — OpenAPI parsed to method and path, GraphQL to its types,
migrations to the tables and columns they create, mock servers, feature flags,
locale keys, the image tags a compose file pins, secret paths (paths only).

**The state of the suite itself** — step phrases that overlap (so a new one is
not written when one exists), phrases no feature uses, page-object methods
nothing calls, the TODO and FIXME the code already admits to, git history and
which ticket touched which files, quarantined scenarios, and — where junit from
past runs survives — which scenarios are the slow ones.

## Frameworks

behave · pytest · jest · playwright · cypress · robot · JUnit · TestNG ·
Cucumber-JVM (Java, Kotlin, Scala) · cucumber-js (TypeScript, JavaScript) ·
cucumber-ruby · rspec · go test · xUnit / NUnit / SpecFlow · PHPUnit · Behat ·
Rust · XCTest · karate · gauge · k6 / gatling.

Detection is by shape, not by directory name: a page object is a class that owns
selectors, wherever it lives and whatever the team calls it.

## When a repository knows better

Autodetection gets the shape right and the vocabulary wrong. A repository can
state its own in `.framework-map.json`, and whatever it states wins:

```bash
where-are-we --repo . --init      # writes a starter manifest from what was detected
```

```json
{
  "name": "my-suite",
  "purpose": "End-to-end tests for the billing portal.",
  "layers": {"steps": "steps/*.py — steps own no selectors, they call page objects"},
  "product_src": ["../billing-web/src"],
  "conventions": ["After a fix, re-run only what failed."]
}
```

The same block works inside `README.md` fenced as ` ```framework-map `.

Directories can explain themselves too — `wawe-readmes` writes a README into
every content directory that lacks one, derived from what is in it, leaving one
TODO line for the sentence a human should write. The map reads them back.

## Why it exists

It was built for an agentic QA pipeline whose branches each spent their first
half hour rediscovering the same suite: forty greps for where the steps live,
which page object owns the portal, how the driver is built. Identical in every
branch, identical every run, and derivable without a model.

## License

MIT
