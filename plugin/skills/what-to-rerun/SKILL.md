---
name: what-to-rerun
description: Use when a change has been made and you are about to run the suite, or when you want to know which tests reach a function, or which of the product nothing tests - `affected` takes the changed files and names the scenarios that reach them, `reaches` asks it of one name, `unreached` asks it of the whole product. Ask the map instead of running everything or guessing from directory names.
---

# Which tests reach this change

Running the whole suite after a one-file change is the default because nothing
knows which tests reach that file. The map does: `xrefs` holds every
cross-file call with the rule that placed it, so the scenarios that reach a
change are the ones the call graph reaches upward from it.

## The three questions

    affected(files=["pages/checkout.py"])

names the scenarios whose steps reach those files, the feature file each is
in, the routes and page objects reached, and the files no `xrefs` row names at
all. That last block is the answer saying what it does not cover, and its
count is in the first line as well, because it is the block a small budget
gives up first.

    reaches(name="CheckoutPage")

is the same question from the other end: one function or class, and the
scenarios, pytest cases and routes that reach it, grouped by feature file,
with the chain of calls under the first scenario of each and no depth cap.

    unreached(limit=40)

is the whole product: every function and class with no path up to a test,
grouped by file and ranked by the map's own `rank`, best first.

## Read them right

- **The first line carries the caveat, every time.** `affected` says how many
  of the files given have no `xrefs` row; `unreached` says what share of the
  callee names the graph could place at all. A map that resolved half its
  names calls half the product unreached whatever the suite covers, and a
  list of names under a head you did not read is a coverage report you have
  invented.
- **No call graph edges at all is a thing all three say.** A suite whose calls
  sit in an arrow passed to `it(...)` reads 100 percent resolved with an empty
  graph. When that happens all three answers say `There are no call graph
  edges in this map`. Believe that sentence over the list under it.
- **A file with no row is not "not affected".** It is in
  `## Unreachable from the graph`, and the honest response is the full run.
- **`unreached` leaves out `main`, `__main__`, `__init__` and any file on a
  test path.** That is a narrower list than `dead`'s on purpose: here every
  name a rule drops leaves the denominator with it.

## The selection a runner takes

    affected(files=[...], format="behave")

prints one `--name` per affected scenario and nothing else: no tag, no `-i`,
no file pattern. On the command line `--affected-out FILE` writes exactly that
to a file, and `--changed <base>` reads the changed files out of git so a
pipeline names nothing:

    where-are-we --out .wawe --changed "$BASE" \
      --affected-format behave --affected-out sel.txt > affected.txt
    if grep -q 'No xrefs row names' affected.txt; then
      behave
    elif [ -s sel.txt ]; then
      xargs behave < sel.txt
    else
      echo "nothing to run"
    fi

The `[ -s ]` guard is not decoration: an empty selection means run nothing,
and GNU `xargs` with empty input runs `behave` with no arguments, which is the
whole suite. `format="pytest"` is the same shape with node ids.

## What it cannot see

`affected` walks `xrefs` rows and nothing else, so a call the resolver could
not place is not a row and the scenario reaching the change through it is not
in the selection. On a suite, where a page object is called from step modules,
that is few; on a library it is most of the graph. Run the whole suite on a
schedule and on every release whatever the selection says.
