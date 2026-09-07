# `framework_map.json` — schema `where-are-we/1`

Stable contract. Sections may be added within a major version; a section that
exists keeps its shape. `schema` names the version; `fingerprint` is what the map
was built from (the commit, and the newest mtime in the tree in nanoseconds
since the epoch) and is how staleness is decided.

| key | shape | what it is |
|---|---|---|
| `schema` | string | `where-are-we/<major>` |
| `repo` | string | absolute path indexed |
| `stated` | object | what `.framework-map.json` declared, verbatim |
| `layers` | {layer: string} | one sentence per layer (features, steps, page objects, driver, environment) naming where it lives, with anything the manifest stated replacing the guess. Absent when the manifest states a `layers` that is not an object |
| `public_api` | {file: [signatures]} | what a step may call: the methods page objects and helpers expose |
| `definitions` | {name: file:line} | every name this walk saw declared, and where. A question about a name is a question about where it is |
| `spans` | {name: [{file, start, end, kind}]} | every home of every name, not only the first the walk reached, sorted by file then start. `end` is the last line of the declaration where a parser knew it (`ast` for Python, a tree-sitter node under `[precise]`) and null where the pattern table read the language, which sees where a declaration starts and not where it stops. `kind` is one of class, constant, enum, feature, function, interface, module, name, scenario, step, struct, trait, type, variable; `name` is the honest fallback for a declaration whose pattern did not say what it declares |
| `indexed` | {side: count} | how many files were looked at per side (suite, product), so a "not found" can say what it looked at |
| `lines` | {file: [lines]} | every line of every file read, so a phrase search is a lookup rather than a second walk. For the tool, not for a prompt |
| `feature_links` | {feature: {step_modules, page_objects}} | traceability |
| `data_files` | {file: [rows]} | test data the suite reads that is not code: CSV, JSON and YAML fixtures with their first rows or keys |
| `testids` | {side: [ids]} | the test ids the suite drives and the ones the product exposes, one list each |
| `helpers` | {file: [names]} | the shared toolbox outside steps and page objects |
| `reporting` | {file: [lines]} | where results and artefacts are configured to land |
| `hooks` | {file: [what each hook does]} | behave hooks, described by what they actually do rather than by name |
| `quarantine` | {tag: [scenarios]} | known flakiness, from the tags the suite already uses |
| `product` | {routes, storage_keys, api_paths} | the product side a test asserts against |
| `locators` | {file: [selectors]} | the locators page objects actually drive |
| `timings` | {file: [name = value]} | the timing constants that decide how long anything waits |
| `behave_config` | {file: [settings]} | behave's own configuration: the defaults nobody states out loud |
| `coverage_docs` | {file: [rows]} | a hand-maintained coverage document, ticket to scenarios, where the traceability actually lives |
| `env_setup` | {file: {flags, waits, services}} | how the environment is brought up and proven ready |
| `backend` | {endpoints, tables, seed_scripts} | the backend a test can call directly, and the data it seeds |
| `api_tests` | [paths] | the API level suite, which is not the UI suite and has its own entry point |
| `conventions` | {file: text} | the repository's own written conventions, from its contributing and style documents |
| `scenario_history` | {scenario: {runs, failures}} | what past runs recorded per scenario, from JUnit XML |
| `dir_readmes` | {dir: {path, summary, headings}} | directories explaining themselves |
| `duplicates` | {normalised phrase: [[file, phrase]]} | step phrases that collide once case and punctuation are normalised |
| `near_duplicates` | [{a, a_in, b, b_in, similarity}] | overlapping phrases |
| `call_graph` | {file:step: [callees]} | which helper or page object method each step function actually calls |
| `artefacts` | {kind: [paths]} | what a finished run leaves behind, and where |
| `unused_steps` | {file: [names]} | steps no feature binds to |
| `unused_api` | {file: [names]} | page object and helper methods no step calls |
| `debts` | {file: [lines]} | TODO, FIXME, skip |
| `git_history` | {file: [commits]} | most-changed files |
| `ticket_links` | {ticket: {subject, files}} | what a ticket touched |
| `dependencies` | {file: [[name, version]]} | what the suite runs on, from its manifests and lock files |
| `ci` | {file: {jobs, runs}} | the CI workflows, their jobs and the commands those jobs run |
| `required_env` | [names] | environment variables that must be set for anything to run, without values |
| `auth` | {file: [lines]} | how a session is obtained: the login, token and header lines a test depends on |
| `concurrency` | {shared_state, serial_tags, notes} | what must not run at the same time as something else |
| `failure_signatures` | {file: [lines]} | the failure messages the suite already knows how to read |
| `safe_data` | {file: [values]} | values a test may safely use, taken from the data the suite ships |
| `slow_steps` | {step: seconds} | what past runs measured, from JUnit XML |
| `tag_meaning` | {tag: text} | what a tag means, where anyone wrote it down |
| `fragile_locators` | {file: [lines]} | locators the suite itself marks as fragile or dead |
| `testid_owners` | {testid: file} | which product component owns which test id |
| `rules_corpus` | [names] | the agent rule files this run is held to, by name, from `--rules`/`RULES_REPO` and `.cursor/rules` |
| `ui_strings` | [strings] | interface strings the assertions depend on |
| `infrastructure` | {file: {services, ports, health}} | the infrastructure the suite talks to: compose files, service names, ports and health endpoints |
| `schemas` | {table: [columns]} | columns, not just table names: what a data test is allowed to assert on |
| `owners` | {path: [owners]} | who owns what, where the repository says so |
| `env_differences` | {file: [lines]} | how the environments differ, from the branches the code takes on ENV |
| `past_runs` | [{verdict, ...}] | what past runs of this pipeline already found in this product, from `RUNS_API_READ` |
| `visual_baselines` | [paths] | visual baselines a comparison could use |
| `feature_style` | {sample, first_scenario, ...} | how a feature file is written here, by example |
| `pytest_tests` | {file: [test names]} | the pytest suite: its cases |
| `fixtures` | {file: [names]} | pytest fixtures, which is where a pytest suite keeps its shared setup |
| `markers` | [names] | pytest markers the suite uses |
| `js_tests` | {file: [describe/it names]} | the JavaScript suite: its cases |
| `test_config` | {file: [lines]} | the configuration files that decide how the tests run |
| `other_suites` | {runner: {file: [cases]}} | the other runners a repository might use (go, rspec, cucumber-js, dotnet and the rest), each read for where its cases live and what they are called |
| `contracts` | {openapi, graphql, migrations, mocks, feature_flags, i18n, images, secret_paths} | files |
| `contract_details` | {endpoints, graphql, migration_tables, i18n_keys, flags} | parsed contents |
| `languages` | {lang: count} | files per language |
| `entry` | {what: [lines]} | entry points, make targets, npm scripts, container CMD |
| `exports` | {file: [names]} | public surface per module |
| `routes_served` | [string] | HTTP routes the code serves |
| `models` | {name: [fields]} | ORM models and their fields |
| `import_graph` | {package: [packages]} | dependencies between top-level packages |
| `workspaces` | [names] | monorepo layout, if this is one |
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
| `adrs` | [string] | architecture decision records, by file and title |
| `coverage_reports` | {file: percent} | the coverage reports found, and what they total |
| `hotspots` | [string] | the largest files, by bytes |
| `dependency_licenses` | {file: [licenses]} | the licences the declared dependencies carry |
| `call_graph_files` | {file:func: [callees]} | cross-file calls, Python by AST, TypeScript, JavaScript and Go by pattern. A callee is written `<name> (<file>)` where one indexed file of that language declares the name, and `<name> (<a.py>\|<b.py>)?` where several do: the edge names every one of them, sorted, and the trailing question mark says the map is choosing between them. A call to a name the caller's own file declares is not an edge, and neither is one made through a module the tree does not declare, whichever way the receiver was bound (`import os` then `os.walk`, `from os import path` then `path.join`); a call the caller's own import line resolves to a single file is written plain. Three shapes of receiver are read further, none of them needing a type. A receiver that resolves to one indexed file which does not declare the name is a facade, and that file's own `from M import name` line is followed, up to three hops, to the file with the `def` (`mapper.build(...)` is `_mapper/build.py`'s `build`). A receiver the function itself bound to a builtin, a literal, a comprehension or one of `defaultdict`, `Counter`, `deque` and `OrderedDict` is not a first-party object at all, so `out = set()` then `out.add(key)` is no edge; a parameter's default counts as what the function bound (`None` does not, because it says nothing about what a caller passes), `*args` and `**kwargs` are a tuple and a dict, a name a nested function never binds is the one written around it, and `d.setdefault(k, set())` is a set whatever `d` is. A name bound to anything else even once, and a receiver that is not a name (`d[k]`), keep the candidate list. `self.name(...)` and `cls.name(...)` go to the class the method is in, or to a base of it: declared in the same file, no edge, and declared by exactly one base in another file, an edge naming that file. A base is followed only where the file says where it came from, so `class D(Base)` with no import of `Base`, and `class D(other.Base)` where nothing binds `other`, keep the candidate list. Anything else keeps it too. The `?` is about the name and not about the receiver: a call through a variable (`pattern.search(...)`) to a name one file declares is written unmarked, because the name is unambiguous even where what it was called on is unknown. `callers`, `callees` and `impact` match on the name alone and print the mark as they find it |
| `call_graph_stats` | {lang: {sites, resolved, ambiguous, edges, marked}} | what the walk above looked at and what it wrote, per language group (`python`, `ts_js`, `go`). `sites` is the callee names it looked at, counted once per function per distinct name, and a call written inside a nested function counts for that function and for each function enclosing it, because each of them is a key the graph can hold; `resolved` is how many of those names some indexed file declares; `ambiguous` is how many several files declare. Those three are a property of the tree: builtins, methods and standard library names are in `sites`, and a name the caller's own file declares counts as resolved without ever becoming an edge. `edges` and `marked` are a property of the graph: cross-file edges written, and how many of them carry the `?`. Counted over the whole walk, before `call_graph_files` is cut to its 60 keys, so a ratio measures the walk and not the cap. `wawe-eval --map OUT --graph` prints it |
| `data_flow` | {file: {paths, tables}} | endpoints and tables co-located |
| `blame_owners` | {file: [people]} | who has been touching what |
| `coverage_by_file` | {file: percent} | from coverage reports |
| `deprecations` | {file: [lines]} | what the code announces as deprecated |
| `api_versions` | [string] | the API versions the code names |
| `doc_drift` | [string] | documentation that talks about things the code no longer has |
| `more_suites` | {runner: {file: [cases]}} | the long tail of runners: exunit, phpunit and the rest, read the same way as `other_suites` |
| `data_stack` | {dbt_models, airflow_dags, spark_jobs, notebooks} | data engineering |
| `build_systems` | {file: [targets]} | build systems and their module graphs |
| `stores` | {store: [files]} | datastores and brokers beyond SQL and Kafka |
| `obs_config` | {file: [lines]} | observability configuration and policy, from config rather than code |
| `perf_suites` | {file: [cases]} | load and contract testing |
| `factories` | {file: [names]} | the factories that make test data |
| `db_constraints` | {file: [lines]} | indexes and constraints: where uniqueness is declared |
| `generated` | {file: marker} | generated code, and what it was generated from |
| `types_declared` | {file: [names]} | the type surface: interfaces, protocols, enums and dataclasses |
| `env_by_service` | {file:service: [names]} | environment by service, not one flat list |
| `client_policies` | {file: [lines]} | retries, timeouts, circuit breakers, rate limits |
| `transactions` | {file: [lines]} | transaction boundaries and idempotency, where the code marks them |
| `logging_config` | {file: [lines]} | logging levels and handlers, from config rather than code |
| `templates` | {name: [files]} | the templates this repository makes people fill in |
| `license_headers` | {file: licence} | license headers, where files carry them |
| `locked` | {file: [pins]} | lock files: what is actually installed, as opposed to what a manifest would accept |
| `status_codes` | {file: [codes]} | which status codes a route can answer with |
| `outbound` | {file: [urls]} | calls out to services this codebase does not own |
| `k8s_runtime` | {file: [lines]} | what keeps a pod alive and what it is allowed: probes, limits, security context |
| `assets` | {kind: [paths]} | what ships that is not code |
| `topic_schemas` | {file: {topics, schemas}} | which schema belongs to which topic, where the code says both in one place |
| `flag_uses` | {file: [flags]} | where a feature flag is branched on, not merely defined |
| `time_assumptions` | {file: [lines]} | assumptions about time: a suite that ignores them fails at midnight |
| `complexity` | [string] | size and shape of functions: where the complexity actually sits |
| `clones` | {shape: [files]} | blocks of code that appear more than once |
| `loc` | {lang: count} | lines per language, not just files |
| `comment_lines` | {lang: count} | comment lines per language |
| `dead_files` | [paths] | modules nothing imports or requires |
| `cycles` | [string] | cycles between top-level packages |
| `sdks` | {service: [files]} | which third-party services the code actually talks to |
| `quality_tools` | {file: [rules]} | the tools that police this repository, and what they enforce |
| `releases` | [string] | the tags, newest first, with their dates |
| `changelog_entries` | [[version, date]] | what the changelog says about them |
| `docs_site` | {file: [lines]} | the documentation site, where there is one |
| `env_parity` | {in_ci_only, in_example_only} | what CI sets that the example environment file never mentions, and the other way round |
| `test_ratio` | {code_files, test_files, share} | how much of this repository is tests |
| `binaries_routes` | {binary: [routes]} | which binary serves which routes, where a repository has more than one |
| `ci_tags` | {job: [tags]} | which tags each CI job actually runs |
| `entry_points` | {script: usage} | how a scenario is launched here, from the scripts' own usage headers |
| `docs` | {file: {headings, ...}} | the repository's own prose, by heading |
| `module_docs` | {file: docstring} | the first line of each module's docstring |
| `tags` | {tag: count} | every tag in the feature files, by how often it is used |
| `environment` | {name: [files]} | every environment variable the tree reads, and where |
| `symbols` | {file: {constants, functions}} | module-level constants and public functions of the step modules |
| `steps` | {file: [phrases]} | step definitions |
| `features` | {file: {scenarios: [{line, name}], tags}} | feature files |
| `page_objects` | [paths] | classes that own selectors and page actions |
| `drivers` | [paths] | the browser or session driver |
| `behave_environment_files` | [paths] | behave's `environment.py` files |
| `scripts` | [paths] | the scripts that run something |
| `counts` | {step_modules, steps, features, scenarios} | totals |
| `fingerprint` | string | `<commit>:<newest mtime in nanoseconds>`. Whole seconds until 1.1.1: an edit inside the same second as the build before it was invisible. The mtime covers every file the map indexes, not a fixed list of extensions. Written by the caller that saves the map, not by `build()` |

Every key `build()` emits is listed above, in the order the map writes them,
and `where-are-we --sections` prints the ones a given map actually has. `{}`
and `[]` are what a repository with none of that gets: an absent value means
the repository has none of it, not that the tool failed.

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
