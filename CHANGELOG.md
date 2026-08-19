# Changelog

## 0.1.0

First release.

- Indexes any codebase into `framework_map.{json,md}` and a brief for a prompt:
  languages, entry points, HTTP routes, data model, public surface, import and
  cross-file call graphs, queues, gRPC, schedules, Kubernetes, Terraform, cache
  keys, permissions, observability, error types, CLI, frontend, contracts
  (OpenAPI, GraphQL, migrations, mocks, flags, i18n), ADRs, coverage, hotspots,
  licenses, git history, blame owners, deprecations and documentation drift.
- Test suites across behave, pytest, jest, playwright, cypress, robot, JUnit,
  TestNG, Cucumber in Java, Kotlin, Scala, TypeScript, JavaScript and Ruby,
  rspec, go test, xUnit, NUnit, SpecFlow, PHPUnit, Behat, Rust, XCTest, karate,
  gauge, k6 — plus the suite's own state: overlapping phrases, unused steps,
  dead page-object methods, admitted debts, quarantine and past-run timings.
- `--init` writes a manifest a repository can correct; what it states wins.
- `--install-hook git|agent`, `--agent-file`, `--only`, `--skip`, `--max-lines`,
  `--diff`, `--force`, `.wawe-ignore`.
- Rebuilds only when the tree has moved; JSON contract versioned as
  `where-are-we/1` and documented in `SCHEMA.md`.
