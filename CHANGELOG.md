# Changelog

## 0.5.1

A limit that stops quietly produces a map that looks complete and is not, and an
absence in a silent map reads as a fact about the codebase.

- Both walks name what they left out, at the top of the map: the tracker walk
  already did, the file walk did not and silently stopped at 40000 files.
- `--spec-limit` is a flag rather than a constant, beside `--spec-depth`.

## 0.5.0

A codebase is not the only thing an agent gropes around in. The other is the
tracker, and it gropes there for the same reason: no map, so it asks, and asks
again. On one run of a real pipeline sixteen tickets were fetched over and over —
one agent pulled fourteen neighbours, the next pulled the same fourteen again,
three were fetched three times inside a single session — and every answer then
sat in a context for ever, paid for on every later turn.

- `--specs KEY[,KEY]` with `--spec-cmd 'your-fetcher {key}'` walks the tracker
  once, two hops out, into `spec_map.json` and `spec_map.md`. This tool learns
  nothing about any tracker: it is handed a command that turns a key into JSON.
- Links are read out of the whole document rather than out of a schema's link
  fields — a key mentioned in a comment is a link somebody made on purpose.
- `--ask` answers from both maps: a question about a piece of work is as likely
  to be about what was asked for as about where the code is.

## 0.4.1

- `--for author|coder`. The vocabulary is what a scenario is written in, so the
  author writing scenarios gets all of it (64k tokens here) and the coder
  changing what it runs against does not (30k) — that context is worth more to
  them as room to work than as fourteen hundred phrases.
- The vocabulary is no longer capped by default: whole-map arithmetic favours
  carrying it, since one turn spent grepping for a phrase re-reads the entire
  context twice.

## 0.4.0

- The brief carries the vocabulary, not a count of it. It used to say "this
  module declares 211 steps" and leave the 211 in a file beside it, so the
  agents writing scenarios spent a hundred and forty-nine turns grepping for
  words they were entitled to be handed. Now: behave phrases, cucumber glue in
  any language, Robot keywords, pytest fixtures and page-object methods, in one
  section, capped by WAWE_VOCAB (700 by default) with the rest in the full map.

## 0.3.1

- An hour to nine seconds. The "interesting line" sections matched with patterns
  shaped `.*(?:a|b|c).*`, which makes the engine try every position of every
  line of every file; a substring test gives the same answer. On the repository
  this was written for the map had been running for an hour and the run it was
  meant to help never started.

## 0.3.0

- Lock files (what is actually installed), the status codes each file returns,
  the services this code calls out to, Kubernetes probes, resources and
  replicas, the asset inventory, which schema belongs to which topic, where
  feature flags are branched on, assumptions about time and locale, the
  functions carrying the complexity, and blocks of code that appear more than
  once.

## 0.2.0

- Every remaining ecosystem: Elixir, Dart, Groovy, Clojure, Haskell, Lua, Perl,
  Julia, Objective-C, Solidity; Vue, Svelte, Angular, Storybook; dbt, Airflow,
  Spark, notebooks; AsyncAPI, JSON Schema, Avro, Thrift, SOAP, tRPC, Pact;
  CloudFormation, Pulumi, Bicep, Ansible, Chef, Puppet; Jenkins, CircleCI, Azure
  Pipelines, Travis, Buildkite, Drone; Gradle, Maven, Bazel, sbt, CMake, Rake;
  MongoDB, Elasticsearch, DynamoDB, Cassandra, ClickHouse, NATS, Pulsar, MQTT;
  Prometheus rules, Grafana dashboards, OpenTelemetry, OPA, flag platforms;
  JMeter, Locust, Artillery; test data factories.
- Indexes and constraints, generated code, declared types, environment per
  service, retries/timeouts/breakers/limits, transactions and idempotency,
  logging levels, contribution templates, license headers.
- `.wawe.toml` for defaults, `--also` to fold several repositories into one map,
  `--watch`, `--html`, `--only`, `--skip`, `--max-lines`, `--diff`.
- A parse cache that survives between runs, and redaction of anything shaped
  like a credential before it reaches a file.

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
