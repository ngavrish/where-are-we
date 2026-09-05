"""Three small, fully deterministic repositories, mapped the same way
`mapper.main()` maps a real checkout: `build()` then `digest()` and `brief()`
written to `framework_map.json/.md/_brief.md` under an `--out` directory.

No dates, no random data, no absolute path baked into any file's content: two
calls with two different roots produce byte-identical maps once the root
itself is stripped out, which is what `test_map_is_deterministic` checks.

Three fixtures:
- `suite`: a behave suite (features, steps, a page object).
- `code`: a plain repository with no test framework at all.
- `poly`: two languages and a migration, to exercise more than Python.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from where_are_we import mapper  # noqa: E402

FIXTURES = ("suite", "code", "poly")

# The three files `build_all()` writes per fixture, and the only three
# `check.py` pins byte for byte against `tests/golden/maps/`.
MAP_FILES = ("framework_map.md", "framework_map_brief.md", "framework_map.json")


def normalised_map(out_dir: str, filename: str, root: str) -> str:
    """One map file's text with everything run-specific taken out of it.

    Two things move between runs and mean nothing: the temporary root the
    fixture was built under (it lands inside absolute paths, the same way
    `check.py` strips it out of an `ask()` answer), and the JSON's own
    `fingerprint` and `repo`, which record which checkout was mapped and
    when. Both are replaced by fixed markers so a map built here and a map
    built by `regen.py` a month ago compare byte for byte.
    """
    text = open(os.path.join(out_dir, filename), encoding="utf-8").read()
    text = text.replace(root, "<root>")
    if filename.endswith(".json"):
        m = json.loads(text)
        for key in ("fingerprint", "repo"):
            if key in m:
                m[key] = "<" + key + ">"
        text = json.dumps(m, indent=2)
    return text

_STEP_COUNT = 40  # steps/pay_steps.py: step_pay_1..40, each calling page.click_N()
_CLICK_COUNT = 40  # pages/checkout.py: CheckoutPage.click_1..40


def _write(path: str, content: str) -> None:
    # Skips the write, and so the mtime bump, when the content already
    # matches: `build_all()` regenerates a fixture's repo on every call, and
    # a real, unchanged tree does not get every file rewritten between two
    # builds of it either. Without this, calling `build_all()` twice on the
    # same root looks cold to the parse cache both times - every file's
    # mtime moved even though nothing in it did - and a "warm rebuild"
    # check built on top of that would never actually be warm.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == content:
                return
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _build_suite(repo: str) -> None:
    _write(os.path.join(repo, "features", "checkout", "pay.feature"), """\
Feature: Pay for an order

  Scenario: Customer pays with a saved card
    Given a customer with a saved card
    When they pay for the invoice
    Then the payment is charged
    And a receipt is emailed

  Scenario: Customer pays and the charge is declined
    Given a customer with a card that will be declined
    When they pay for the invoice
    Then the charge is declined
    And they see a retry prompt

  Scenario: Customer pays with a new card
    Given a customer with no saved card
    When they add a new card and pay for the invoice
    Then the payment is charged
""")
    _write(os.path.join(repo, "features", "login.feature"), """\
Feature: Log in

  Scenario: Successful login
    Given a registered user
    When they log in with valid credentials
    Then they land on the dashboard

  Scenario: Failed login
    Given a registered user
    When they log in with the wrong password
    Then they see an error message
""")

    pay_lines = [
        '"""Step definitions for paying at checkout."""',
        "",
        "from behave import step",
        "",
        "from pages.checkout import CheckoutPage",
        "",
        "page = CheckoutPage()",
        "",
    ]
    for i in range(1, _STEP_COUNT + 1):
        pay_lines += [
            "",
            f'@step("pay step {i}")',
            f"def step_pay_{i}(context):",
            f"    page.click_{i}()",
        ]
    _write(os.path.join(repo, "steps", "pay_steps.py"), "\n".join(pay_lines) + "\n")

    _write(os.path.join(repo, "steps", "login_steps.py"), '''\
"""Step definitions for logging in."""

from behave import given, then, when


@given("a registered user")
def step_registered_user(context):
    pass


@when("they log in with valid credentials")
def step_login_valid(context):
    pass


@when("they log in with the wrong password")
def step_login_invalid(context):
    pass


@then("they land on the dashboard")
def step_on_dashboard(context):
    pass


@then("they see an error message")
def step_login_error(context):
    pass
''')

    page_lines = [
        '"""The checkout page: every element pay_steps.py clicks through."""',
        "",
        "",
        "class CheckoutPage:",
        '    """Page object for the checkout flow."""',
    ]
    for i in range(1, _CLICK_COUNT + 1):
        page_lines += [
            "",
            f"    def click_{i}(self):",
            "        pass",
        ]
    _write(os.path.join(repo, "pages", "checkout.py"), "\n".join(page_lines) + "\n")


def _build_code(repo: str) -> None:
    _write(os.path.join(repo, "app", "api.py"), '''\
"""HTTP routes for invoices."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/invoice")
def list_invoices():
    """Return every invoice."""
    return []


@app.get("/invoice/{id}")
def get_invoice(id: str):
    """Return one invoice by id."""
    return {"id": id}


@app.get("/health")
def health():
    """Liveness check."""
    return {"status": "ok"}
''')

    _write(os.path.join(repo, "app", "models.py"), '''\
"""The billing data model."""

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Invoice(Base):
    """An invoice raised for a customer."""

    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer)
    amount = Column(Integer)


class Customer(Base):
    """A billed customer."""

    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String)
''')

    _write(os.path.join(repo, "app", "billing.py"), '''\
"""Charging and refunding a customer's card."""


def charge(customer_id: int, amount: int) -> str:
    """Charge a customer's card for an invoice."""
    return "charged"


def refund(customer_id: int, amount: int) -> str:
    """Refund a customer's card."""
    return "refunded"
''')

    _write(os.path.join(repo, "app", "cli.py"), '''\
"""Command line entry point for billing operations."""

import argparse


def main() -> int:
    """Send or retry a billing job, picked from the command line."""
    parser = argparse.ArgumentParser(prog="billing")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("send")
    sub.add_parser("retry")
    parser.parse_args()
    return 0


if __name__ == "__main__":
    main()
''')

    _write(os.path.join(repo, "Makefile"), """\
test:
\tpytest

lint:
\truff check .
""")


def _build_poly(repo: str) -> None:
    _write(os.path.join(repo, "a.ts"), """\
export function charge(amount: number): string {
  return `charged ${amount}`;
}
""")

    _write(os.path.join(repo, "b.ts"), """\
import { charge } from "./a";

export function payInvoice(amount: number): string {
  return charge(amount);
}
""")

    _write(os.path.join(repo, "main.go"), """\
package main

func Serve() {
	// starts the HTTP server
}

func TestServe() {
	// exercises Serve directly, with no test file
	Serve()
}

func main() {
	Serve()
}
""")

    _write(os.path.join(repo, "migrations", "V1__init.sql"), """\
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
""")


_BUILDERS = {"suite": _build_suite, "code": _build_code, "poly": _build_poly}


def _reset_state() -> None:
    """Clear mapper's module-level indexes before mapping a fresh repository.

    They are global by design: `--also` merges a service and its client into
    one map, so a second root's names stay searchable in the first root's
    map too. Building three unrelated fixtures in one process is the opposite
    case, and without this reset the second and third fixture's map would
    carry the first one's definitions, index counts and truncation notes
    forward, and `regen.py` or the test running twice in one process would not
    match a fresh process running it once.
    """
    mapper.DEFINITIONS.clear()
    mapper.INDEXED.clear()
    mapper.LINES.clear()
    mapper.TRUNCATED.clear()
    mapper._WALK_CACHE.clear()
    mapper._IGNORE_CACHE.clear()
    mapper._FILE_CACHE.clear()
    mapper._PARSE_CACHE.clear()


def build_all(root: str) -> dict:
    """Build the three fixtures under `root`, map each the way `main()` maps a
    repository, and return `{fixture: out_dir}`.

    Mirrors `main()`'s three writes (read there: `build()`, then `digest()`
    and `brief()` written to `framework_map.json`, `.md` and `_brief.md`)
    without the parts `main()` adds around them that do not affect those
    three files: the CLI's `--only`/`--skip`/`--max-lines` trimming (all off
    by default) and the git/mtime fingerprint (recorded in the JSON for cache
    invalidation, never read back out of it here).

    `redact(m)`, which `main()` also calls, is deliberately skipped: it
    replaces anything shaped like a credential with `[redacted]`, and its
    generic base64-like pattern occasionally matches a long, separator-free
    stretch of a real temporary directory name, redacting part of a path
    unpredictably depending on what that run's OS-assigned temp name happens
    to be. A fixture never carries a real secret, so there is nothing here
    for `redact()` to protect, and skipping it keeps the absolute paths that
    land in `## Defined here` intact and equally easy to normalise away in
    `check.py`/`regen.py`.
    """
    saved_env = {k: os.environ.get(k)
                 for k in ("AGENT_REPO", "PRODUCT_SRC", "WAWE_JUNIT_DIRS")}
    outs = {}
    try:
        for name in FIXTURES:
            repo = os.path.join(root, name, "repo")
            out_dir = os.path.join(root, name, "out")
            os.makedirs(repo, exist_ok=True)
            _BUILDERS[name](repo)

            _reset_state()
            os.environ["AGENT_REPO"] = repo
            # A fixture has no product checked out beside it; without this,
            # `_product_roots()` would look for an `src` sibling of `repo` and,
            # given three fixtures living under one `root`, could see another
            # fixture's directory and index it as "the product".
            os.environ["PRODUCT_SRC"] = "none"
            # `build()`'s default junit roots include `/runs` when it exists,
            # which a machine set up for real scoped runs (this project's own)
            # may well have. A fixture has no scenario history of its own, so
            # it points at a directory that never exists rather than at
            # nothing: an empty `WAWE_JUNIT_DIRS` is treated as unset, and
            # falls back to that same default.
            os.environ["WAWE_JUNIT_DIRS"] = os.path.join(repo, ".no-junit-dirs")

            # Before the build, not after: build() saves its parse cache into
            # out_dir itself, and only into a directory that already exists
            # (main() creates out_dir the same way, before its own build()
            # call, for the same reason).
            os.makedirs(out_dir, exist_ok=True)
            m = mapper.build(repo, out_dir=out_dir)
            with open(os.path.join(out_dir, "framework_map.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(m, fh, indent=2)
            with open(os.path.join(out_dir, "framework_map.md"), "w",
                      encoding="utf-8") as fh:
                fh.write(mapper.digest(m))
            with open(os.path.join(out_dir, "framework_map_brief.md"), "w",
                      encoding="utf-8") as fh:
                fh.write(mapper.brief(m))
            outs[name] = out_dir
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return outs
