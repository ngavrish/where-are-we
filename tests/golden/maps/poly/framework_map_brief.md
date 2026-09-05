# Framework map (brief)

0 step modules / 0 step phrases, 0 feature files / 0 scenarios. Full map with every step phrase: `framework_map.md` in this run's directory — grep that file instead of grepping the repository.

## What this codebase is made of

TypeScript (2), Go (1), SQL (1)

## Where it starts

- main.go: present
- go binaries: main.go

## Public surface of the code

- `main.go`: Serve, TestServe
- `a.ts`: charge
- `b.ts`: payInvoice

## Largest files

- main.go (0 KB), b.ts (0 KB), a.ts (0 KB)

## Who calls whom, across files

- `b.ts:payInvoice` → charge (a.ts)

## Defined here

- `Serve` — <root>/poly/repo/main.go:3
- `TestServe` — <root>/poly/repo/main.go:7
- `charge` — <root>/poly/repo/a.ts:1
- `customers` — <root>/poly/repo/migrations/V1__init.sql:1
- `main` — <root>/poly/repo/main.go:1
- `payInvoice` — <root>/poly/repo/b.ts:3

## Lines of code

- Go: 14, TypeScript: 8, SQL: 4

## How much of this is tests

- 0 test files of 4 (0%)

## Files nothing imports

- `b.ts`

## Which binary serves what

- `main.go`: (routes not attributable by directory)

## How this suite is built

- **features** — Gherkin features: none found
- **steps** — step definitions the features bind to: none found
- **page_objects** — classes that own selectors and page actions: none found
- **driver** — browser/session driver: waits, screenshots: none found
- **environment** — hooks and per-scenario setup: none found


## Contracts, schemas and mocks

- **migrations**: `migrations/V1__init.sql`

## What those contracts actually say

- tables created by migrations: customers(id, name)

## Step modules, largest first

