# Framework map (brief)

1 step modules / 1 step phrases, 1 feature files / 1 scenarios. Full map with every step phrase: `framework_map.md` in this run's directory — grep that file instead of grepping the repository.

## What this codebase is made of

Python (1)

## Largest files

- steps/portal_steps.py (0 KB)

## Who has been touching what (last year)

- `README.md` — Claude Code (13), Dockerfile (1)
- `src/where_are_we/mapper.py` — Claude Code (11), LICENSE (1)
- `src/where_are_we/readmes.py` — Claude Code (1), LICENSE (1)
- `pyproject.toml` — Claude Code (2), LICENSE (1)
- `src/where_are_we/__init__.py` — Claude Code (2), LICENSE (1)
- `.github/workflows/packages.yml` — Claude Code (4)
- `packaging/install.sh` — Claude Code (2)
- `.pre-commit-hooks.yaml` — Claude Code (1)
- `action.yml` — Dockerfile (1)
- `packaging/index.html` — Claude Code (2)
- `tests/test_smoke.py` — Claude Code (2)
- `.github/workflows/brew.yml` — Claude Code (1)
- `packaging/apt-key.asc` — Claude Code (1)
- `CHANGELOG.md` — Claude Code (3)
- `.github/ISSUE_TEMPLATE/framework.md` — Claude Code (1)

## Lines of code

- Python: 5

## How much of this is tests

- 0 test files of 1 (0%)

## Files nothing imports

- `steps/portal_steps.py`

## Releases

- v0.3.0 2026-08-19, v0.2.0 2026-08-19, v0.1.0 2026-08-19

## How this suite is built

- **features** — Gherkin features — 1 files under tests
- **steps** — step definitions the features bind to — 1 files under steps
- **page_objects** — classes that own selectors and page actions: none found
- **driver** — browser/session driver: waits, screenshots: none found
- **environment** — hooks and per-scenario setup: none found


## Which feature is served by which modules

- `ui.feature` → steps: portal_steps.py

## Backend the tests touch

- tables queried: behave

## Most-changed files, last 90 days

- `README.md` — 5 commits, latest: 2026-08-19 Claude Code: Offer the repository the documentation it lacks
- `src/where_are_we/mapper.py` — 5 commits, latest: 2026-08-19 Claude Code: Offer the repository the documentation it lacks
- `.github/workflows/packages.yml` — 4 commits, latest: 2026-08-19 Claude Code: Fedora and RHEL, from the same origin and the same key
- `CHANGELOG.md` — 3 commits, latest: 2026-08-19 Claude Code: Locks, status codes, outbound calls, pod runtime, comple
- `pyproject.toml` — 3 commits, latest: 2026-08-19 Claude Code: Locks, status codes, outbound calls, pod runtime, comple
- `src/where_are_we/__init__.py` — 3 commits, latest: 2026-08-19 Claude Code: Locks, status codes, outbound calls, pod runtime, comple
- `src/where_are_we/readmes.py` — 2 commits, latest: 2026-08-19 Claude Code: Offer the repository the documentation it lacks
- `packaging/install.sh` — 2 commits, latest: 2026-08-19 Claude Code: Fedora and RHEL, from the same origin and the same key
- `packaging/index.html` — 2 commits, latest: 2026-08-19 Claude Code: One line to install on Debian, and a package for those w
- `tests/test_smoke.py` — 2 commits, latest: 2026-08-19 Claude Code: Two sections claimed the same name, and the brief died o
- `.github/workflows/release.yml` — 2 commits, latest: 2026-08-19 Claude Code: Publish with an API token from repository secrets
- `.github/workflows/ci.yml` — 2 commits, latest: 2026-08-19 Claude Code: One pass over the tree, a brief you can size, and a diff

## How a feature file is written here

Sample: `tests/ui.feature`

```gherkin
Feature: portal

  @smoke
  Scenario: it opens
    Given the portal is open
```

## Tags in use

@smoke (1)

## Step modules, largest first

- `steps/portal_steps.py` — 1 steps

## Biggest feature files (scenario line numbers are in the full map)

- `tests/ui.feature` — 1 scenarios
