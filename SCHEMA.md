# `framework_map.json` — schema `where-are-we/1`

Stable contract. Sections may be added within a major version; a section that
exists keeps its shape. `schema` names the version; `fingerprint` is what the map
was built from (commit and newest mtime) and is how staleness is decided.

| key | shape | what it is |
|---|---|---|
| `schema` | string | `where-are-we/<major>` |
| `repo` | string | absolute path indexed |
| `fingerprint` | string | `<commit>:<newest mtime>` |
| `stated` | object | what `.framework-map.json` declared, verbatim |
| `languages` | {lang: count} | files per language |
| `entry` | {what: [lines]} | entry points, make targets, npm scripts, container CMD |
| `exports` | {file: [names]} | public surface per module |
| `routes_served` | [string] | HTTP routes the code serves |
| `models` | {name: [fields]} | ORM models and their fields |
| `import_graph` | {package: [packages]} | dependencies between top-level packages |
| `call_graph_files` | {file:func: [callees]} | cross-file calls, Python by AST, TypeScript, JavaScript and Go by pattern |
| `data_flow` | {file: {paths, tables}} | endpoints and tables co-located |
| `messaging` | {file: [topics]} | queues, topics, subjects |
| `grpc` | {service: [methods]} | from `.proto` |
| `schedules` | {file: [expressions]} | cron, beat, DAGs, CronJobs |
| `kubernetes` | {file: {kinds, names}} | manifests |
| `iac` | {file: [[type, name]]} | Terraform resources |
| `cache_keys` | [string] | cache keys the code uses |
| `permissions` | {file: [names]} | roles, scopes, guards |
| `observability` | {metrics, spans, log_fields} | names emitted |
| `error_types` | {class: file} | error and exception types |
| `cli_commands` | {file: [commands]} | click, argparse, cobra |
| `frontend` | {components, stores, hooks} | UI structure |
| `contracts` | {openapi, graphql, migrations, mocks, feature_flags, i18n, images, secret_paths} | files |
| `contract_details` | {endpoints, graphql, migration_tables, i18n_keys, flags} | parsed contents |
| `steps` | {file: [phrases]} | step definitions |
| `features` | {file: {scenarios: [{line, name}], tags}} | feature files |
| `page_objects`, `drivers`, `scripts` | [paths] | test layers |
| `public_api` | {file: [signatures]} | what a step may call |
| `feature_links` | {feature: {step_modules, page_objects}} | traceability |
| `near_duplicates` | [{a, a_in, b, b_in, similarity}] | overlapping phrases |
| `unused_steps`, `unused_api` | {file: [names]} | dead weight |
| `debts` | {file: [lines]} | TODO, FIXME, skip |
| `git_history` | {file: [commits]} | most-changed files |
| `ticket_links` | {ticket: {subject, files}} | what a ticket touched |
| `blame_owners` | {file: [people]} | who has been touching what |
| `coverage_by_file` | {file: percent} | from coverage reports |
| `deprecations`, `api_versions`, `doc_drift` | see README | decay signals |
| `scenario_history`, `slow_steps` | from junit | what past runs measured |
| `dir_readmes` | {dir: {path, summary, headings}} | directories explaining themselves |
| `counts` | {step_modules, steps, features, scenarios} | totals |

Everything is derived; nothing is inferred by a model. An absent section means
the repository has none of that, not that the tool failed.

## Stability

`where-are-we/1` is the contract of the 1.x releases. Within the major:
sections may be added; a section that exists keeps its shape and meaning; a
key is never renamed or removed. A change that must break one of those bumps
the schema to `where-are-we/2` and the tool to 2.0.0, and the map says which
schema it is in its first key. The CLI flags and the four MCP tools (`ask`,
`find`, `defines`, `sections`) are held to the same rule: a flag or a tool
that exists in 1.0 exists, with the same meaning, in every 1.x.
