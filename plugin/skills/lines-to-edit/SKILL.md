---
name: lines-to-edit
description: Use before editing a definition you have not opened, or when you need to know how one function gets to another - `range` returns every home of a name with its first line, its last line and the line after, so an Edit can anchor without a read, and `path` returns the shortest call chain from A to B with the rule that placed each hop. Ask the map instead of reading a file to find where a definition stops.
---

# The lines an edit needs, and the chain between two names

An `Edit` needs an anchor, and an anchor needs the line a definition starts on
and the line it stops on. Reading the file to find them costs the file. The
map already holds both: `spans` records every declaration's range, and `xrefs`
records every cross-file call.

## Where a definition starts and stops

    range(name="pay")

    `pay` is declared in 1 place. 12000 characters.

    ## Every home of this name, as file:start-end kind
    - `pages/checkout.py:5-6` function

    ## The shortest of them whole: `pages/checkout.py:5-6`
        def pay(self):
            return charge(1)

    ## The lines an editor anchors on: first, last, and the one after the last
    - start 5: `    def pay(self):`
    - end 6: `        return charge(1)`

A name with two homes prints both, and the text shown is the shortest that
fits the budget. There is no write path here: this answers where to edit, it
does not edit.

- **An `end` of `?` means nothing knew where the declaration stops.** The
  pattern table sees where a declaration starts and not where it ends, and the
  answer says which case it is. Do not anchor on a guess; open the file.
- **A redacted line is printed with a warning beside it.** It is not the line
  on disk, so an edit anchored there will not match.

## How one function reaches another

    path(a="step_pay", b="charge")

    `step_pay` reaches `charge` in 2 hops, the shortest chain the graph holds.

    ## The chain, one hop per line, with how each edge was resolved
    1. `features/steps/shop_steps.py:step_pay` calls `pay` at line 19,
       sole_declarer, declared in `pages/checkout.py`
    2. `pages/checkout.py:pay` calls `charge` at line 6, sole_declarer,
       declared in `app/billing.py`

Breadth first over the same `calls` rows, forward, with a visited set, so a
cycle is walked once and the first chain found is the shortest. Every hop
carries the rule that placed the edge, so you can see which hops are certain:
`sole_declarer` and `import_line` are, `ambiguous` is a list of candidates and
the answer prints them.

- **Only cross-file calls are in this graph.** A call inside the file that
  declares the callee is not a row, so a hop through one is a hop this cannot
  walk, and `no path from A to B` can mean the graph is short rather than the
  code is. The answer names the nearest names it did reach.
- **`## How this was counted` under both answers carries the rest of the
  rules.** The first line carries only the count and the one caveat that
  decides what it means, because a first line is read again on every turn and
  a rules block is not.

Pair `range` with `defines`, which names every home without the text, and with
`at(file, line)`, which goes the other way: a `file:line` from a stack trace
back to the whole definition around it.
