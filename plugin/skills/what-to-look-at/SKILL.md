---
name: what-to-look-at
description: Use when opening an unfamiliar repository to decide where to read first, or during a review or a cleanup to find what nothing calls - `hot` ranks definitions by how much of the codebase reaches them times how often their file changed, and `dead` lists the definitions no call row lands on. Ask the map instead of guessing from file size or directory names.
---

# Where the work is, and what nothing calls

`rank` says which definitions the repository is built around. It does not know
which of them anybody has touched, and a definition everything reaches that
nobody has changed in a year is not where the work is.

## Where to look first

    hot(limit=20)

multiplies each definition's `rank` score by how many commits touched its file
in the last ninety days, and prints both numbers beside the product so you can
see which half a row got its place from.

- **The first line carries the bound that decides the ranking**: churn covers
  the forty busiest files only, and a definition in any other file counts 1.
  So `hot` is a ranking within the busy part of the tree, not over all of it.
- **A map built before `git_commits` existed counts commit lines instead**,
  and `git_history` keeps at most five a file, so every count at the cap is
  written `5+`. Two rows of `## How this was counted` say which case you are
  reading.
- **A tree with no git history has no churn**, and the answer says so rather
  than ranking on `rank` alone and calling it `hot`.

## What nothing calls

    dead(limit=40)

is a list of questions, not a list of dead code, and its first line says that
before it says anything else.

- **Most rows on a library are calls the map could not place**, not
  definitions nothing calls: only cross-file calls are in the graph, so a call
  inside the file that declares the callee leaves no row, and neither does a
  call through an imported module. On this repository 359 of 517, of which a
  spot check found one genuinely dead. On a test suite, where a page object is
  called from step modules, it is sharp.
- **A class only ever constructed is in the list.** The resolver places a
  callee by the function declarations it indexed and keeps class names in a
  table of its own, so `page = CheckoutPage()` writes no call row from
  anywhere. `## How this was counted` says so.
- **The exclusions are in that block too**: a dunder, `main`, a name starting
  `test` and every `pytest_tests` case, a step function, a definition in a
  file a route is served from or that `entry_points` names. That is a wider
  list than `unreached`'s, and deliberately so: this question is about what
  nothing calls, and a name the runtime or the runner calls is not an answer.
- **Delete nothing on this list alone.** Check the row: open the file, grep
  the name, and look at the resolution rate the map prints for itself. The
  answer is where to look, not what to remove.

Both are grouped and cut by the same budget rules as every other answer here,
with a `more:hot:` or `more:dead:` handle under a block that was cut.
