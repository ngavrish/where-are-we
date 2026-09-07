---
name: where-defined
description: Use when you need the file and line where a function, class, constant, type, step phrase or scenario is defined, the whole definition around a line a stack trace named, or everything the map holds about one name at once - instead of grep -rn; the map holds every declared name with every place it is declared, first line to last.
---

# Where is it defined

The map indexes every declared name in every file the walk reached: functions,
classes, constants, types, step phrases, scenario names. A question about a
name is a question about where it is.

    defines(name=["MAX_PERSISTED_FORECAST_RESULTS", "click_pay"])

returns one line per name, and every place that name is declared:

    MAX_PERSISTED_FORECAST_RESULTS: src/constants/forecastStorage.ts:31-31 (constant)
    click_pay: steps/pay_steps.py:14-19 (function), steps/legacy_steps.py:88-91 (function)

- Pass a list: every name you are about to grep for, in one call.
- Case does not matter; a substring of a longer name is matched too and says so.
- A name with two homes prints both, in path order. Do not assume the first is
  the one that runs; the map is telling you the question has two answers.
- `start-end` is the whole declaration, first line to last. An end of `?` is a
  language read by the pattern table: the start is right and the end is not
  known, so do not edit by anchor against it.
- Open the file at that line with `Read` and `offset`; do not read the whole
  file to find the line you were just given.
- When the answer is "no declaration of X in the map", it lists what was
  indexed. Names in files past the walk's bounds, or in languages the indexer
  does not parse, are not there - check `## This map is incomplete` in the map
  before concluding the name does not exist, and only then grep the repository.

When what you have is a line rather than a name - a stack trace, a test
failure, a review comment - `at` hands back the definition around it:

    at(place="src/billing/core.py:147")

returns the innermost definition enclosing that line, whole:

    src/billing/core.py:140-168 charge (function)
    def charge(amount):
        ...

- Use it instead of `Read` with a guessed offset. A guess that lands mid
  function costs a second read; this one is the whole thing or says what it
  cut, with a `more:at:` handle for the rest.
- `place` takes a list: every frame of a stack trace in one call.
- When nothing encloses the line the answer says so and names the nearest
  declarations, rather than handing you a definition that is not the one you
  are standing in.

When you have landed on a name and want all of that at once, `context` is the
five calls in one:

    context(name="charge")

returns, in this order and each under its own head: every home of the name with
its span, the rows of the map that mention it, its callers, its callees, and
its impact one hop out. The first line says so and names the floor share of the
budget each block was given (15 percent declared, 35 map rows, 15 callers, 15
callees, 20 impact); a block that does not need its share hands the rest on to
the blocks that do, so when the five answers fit the budget you get all five
whole.

- Reach for it first when a name is new to you. `defines`, `ask`, `callers`,
  `callees` and `impact` are five round trips for the same map; this is one.
- Reach for the single tools when you already know which of the five you want,
  or when you want a block wider than its share.
- A block that could not print all of itself ends in `… N more lines
  (more:ctx:...)`. Pass that handle to `more` for the rest of that block; do
  not ask `context` again at the same budget, which returns the part you have.
- `name` takes a list, and `limit` sets the budget in characters.

Once you know where a name is defined, `callers(name=["click_pay"])` says who
calls it: every `<file>:<func>` from the call graph, exact and case-sensitive.

    callers(name="charge")

returns:

    charge: b.ts:pay, y.py:g

or, when nothing in the map calls it, `nothing in the map calls charge`. Use
it instead of grepping for a call site: the graph was already built from the
same files `defines` reads.

`callees(name="pay")` is the other direction: what that function calls, each
callee with the file it is declared in. Where several files declare one name
the callee lists all of them and ends in `?`, because the map cannot tell
which one this call reaches.

    pay: charge (a.ts), settle (a.py|b.py)?

And when the question is what a change to a name would reach, not who calls it
once, `impact(name="charge", depth=3)` walks the same graph back several hops
and groups the answer by distance:

    Impact of `charge` to depth 3. How to read it: hops are followed by name, ...
    depth 1: b.ts:pay
    depth 2: app.ts:checkout

Read that first line. Hops are followed by name, so where several files define
one name their callers are unioned into the answer; only cross-file calls are
in the graph; the map keeps a bounded number of graph keys, so on a large
repository the radius is a floor rather than the whole of it; and an edge
ending in `?` names every file that declares the callee, because more than one
does. A cycle is walked once, not looped. The depth is 1 to 6 and 3 by
default, and a depth outside that is refused rather than answered. At most 200
`file:func` entries come back, the keys in any `note:` line counted: when the
answer says what it left out, ask again at a smaller depth rather than paging,
which is why there is no handle for the rest.
