# Framework map (brief)

0 step modules / 0 step phrases, 0 feature files / 0 scenarios. Full map with every step phrase: `framework_map.md` in this run's directory — grep that file instead of grepping the repository.

## What this codebase is made of

Python (4)

## Where it starts

- make targets: test, lint

## HTTP routes this codebase serves (3)

- GET /health  (api.py)
- GET /invoice  (api.py)
- GET /invoice/{id}  (api.py)

## Data model

- `Invoice (models.py)`: amount, customer_id, id, name
- `Customer (models.py)`: amount, customer_id, id, name

## Public surface of the code

- `app/api.py`: list_invoices, get_invoice, health
- `app/billing.py`: charge, refund
- `app/models.py`: Invoice, Customer
- `app/cli.py`: main

## Command line

- `cli.py`: retry, send

## Largest files

- app/models.py (0 KB), app/cli.py (0 KB), app/api.py (0 KB), app/billing.py (0 KB)

## Which code touches which table

- `api.py`: /health, /invoice, /invoice/{id} ↔ fastapi

## Defined here

- `Customer` — <root>/code/repo/app/models.py:19
- `Invoice` — <root>/code/repo/app/models.py:9
- `charge` — <root>/code/repo/app/billing.py:4
- `get_invoice` — <root>/code/repo/app/api.py:15
- `health` — <root>/code/repo/app/api.py:21
- `list_invoices` — <root>/code/repo/app/api.py:9
- `main` — <root>/code/repo/app/cli.py:6
- `refund` — <root>/code/repo/app/billing.py:9

## Lines of code

- Python: 76

## How much of this is tests

- 0 test files of 5 (0%)

## Files nothing imports

- `app/api.py`, `app/billing.py`, `app/cli.py`, `app/models.py`

## How this suite is built

- **features** — Gherkin features: none found
- **steps** — step definitions the features bind to: none found
- **page_objects** — classes that own selectors and page actions: none found
- **driver** — browser/session driver: waits, screenshots: none found
- **environment** — hooks and per-scenario setup: none found


## Step modules, largest first

