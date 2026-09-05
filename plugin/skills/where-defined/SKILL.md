---
name: where-defined
description: Use when you need the file and line where a function, class, constant, type, step phrase or scenario is defined - instead of grep -rn; the map holds every declared name with its line.
---

# Where is it defined

The map indexes every declared name in every file the walk reached: functions,
classes, constants, types, step phrases, scenario names. A question about a
name is a question about where it is.

    defines(name=["MAX_PERSISTED_FORECAST_RESULTS", "click_pay"])

returns, per name:

    ## Defined here
    - `MAX_PERSISTED_FORECAST_RESULTS` — src/constants/forecastStorage.ts:31

- Pass a list: every name you are about to grep for, in one call.
- Case does not matter; a substring of a longer name is matched too and says so.
- Open the file at that line with `Read` and `offset`; do not read the whole
  file to find the line you were just given.
- When the answer is "no declaration of X in the map", it lists what was
  indexed. Names in files past the walk's bounds, or in languages the indexer
  does not parse, are not there - check `## This map is incomplete` in the map
  before concluding the name does not exist, and only then grep the repository.

Once you know where a name is defined, `callers(name=["click_pay"])` says who
calls it: every `<file>:<func>` from the call graph, exact and case-sensitive.

    callers(name="charge")

returns:

    charge: b.ts:pay, y.py:g

or, when nothing in the map calls it, `nothing in the map calls charge`. Use
it instead of grepping for a call site: the graph was already built from the
same files `defines` reads.
