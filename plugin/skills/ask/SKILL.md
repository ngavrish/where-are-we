---
name: ask
description: Use when you have a question about this repository - where something is, what calls what, which scenarios cover a feature, what is slow or duplicated - and are about to grep for it; ask the map with words and read the tail that says what was left out.
---

# Ask the map

`ask(words=[...])` on the `where-are-we` MCP server (or `where-are-we --out
.wawe --ask "words"` on the command line) returns, for each section of the map
that mentions your words, the rows that mention them - whole rows, never cut
in the middle - and ends each section with what it left out, and a handle
that fetches it:

    … 3 more matching rows (more:rows:step-phrases:invoice:12); 41 rows in this section do not mention these words

`more(handle=[...])` (or `where-are-we --out .wawe --more "more:rows:..."`)
returns that same list continued from where the answer stopped, with the next
handle when there is still more after it. Every place an answer cuts prints
one: a section's rows (`more:rows:`), the rows in it that never matched
(`more:unmatched:`), the definitions past the block's cap (`more:defs:`), the
sections that did not fit (`more:sections:`, in the "more sections match"
line), and `find`'s hits past its limit (`more:find:`).

## Ask well

- **Words, not sentences.** The map matches words. `refund settled invoice`
  finds more than "how is a settled invoice refunded".
- **One call, several questions.** `words` is a list: `["refund", "invoice
  settled", "MAX_RETRIES"]` is one round trip, three answers.
- **Say where you are working.** `files=["billing/", "core.py"]` puts the rows
  naming those paths first inside every section; the rest still print, with
  the same tail and the same handle. A directory prefix counts, and paths are
  read relative to the repository root.
- **When you do not know what to ask for, `rank` first.** `ask` answers what
  mentions a word; `rank(files=[...])` answers which definitions the codebase
  is built around, and which matter given the files you are in.
- **Names go to `defines`, phrases go to `find`, lines go to `at`.** `ask`
  ranks sections; `defines(name=[...])` answers "where is X declared" with
  every home and its span, `at(place=["f.py:147"])` answers "what is this line
  inside" with the whole definition, and `find(phrase=[...])` answers "where
  does this step / string live". Use the narrower tool when you have a name,
  and `context(name=[...])` when the name is new to you and you want all five
  answers about it in one call.
- **After an edit, ask what it reaches.** `affected(files=[...])` answers which
  scenarios, feature files, routes and page objects a change to those files
  reaches, by walking the map's call rows upward from what they declare, and
  names the files it holds no row for so you know what the answer leaves out.
  `format="behave"` or `"pytest"` gives the runner's own selection: one
  `--name` per affected scenario, or node ids. Ask it before running a suite,
  instead of running all of it or guessing a subset. A selection too large for
  one reply comes back as its count and its first selectors, with the
  `where-are-we --affected ... --affected-out FILE` command that writes the
  whole of it to a file; run that rather than asking again.
- **Before changing or deleting a function, ask what reaches it.**
  `reaches(name="charge")` names the scenarios, pytest cases and routes that
  reach one function or class, grouped by feature file, with the chain of
  calls under the first scenario of each and no depth cap. `unreached()` is
  the other half: the product definitions no test reaches at all, ranked,
  with the graph's own resolution rate in the first line, because that is how
  much of the list is untested rather than unknown. Read both first lines:
  they say when the map, rather than the suite, is the reason a count is
  zero.
  `format="behave"` or `"pytest"` gives the runner's own selection. Ask it
  before running a suite, instead of running all of it or guessing a subset.
- **Before an edit, ask for the lines.** `range(name="charge")` gives every
  home of the name as `file:start-end kind`, the text of the shortest, and
  the first line, the last, and the one after the last, each with the text of
  that line. Anchor an `Edit` on those rather than reading the file at a
  guessed offset; an insertion after the last line lands outside the
  definition. One line you must not anchor on: one holding `[redacted]`,
  where this map wrote over a value that looked like a secret. It is not the
  line on disk, the row says so, and the first line repeats it.
- **When you need the chain, not the neighbours.** `path(a="handler",
  b="charge")` prints the shortest call chain between two names, one hop per
  line with the rule that placed each edge and the line the call is on, in
  one call rather than walking `callers` or `callees` outward and joining the
  answers by hand. Only cross-file calls are in that graph, so a chain that
  runs through a call inside one file is not one it can walk, and the first
  line says so.
- **Reviewing, not editing.** `hot()` is the map's `rank` score times how
  often each file changes, both numbers shown, which is where to read first.
  Its first line carries the bound that decides what the ranking is: the
  churn comes from the forty busiest files, so anything outside that set
  counts 1. `## How this was counted` under the rows carries the rest,
  including that an older map can only count five commit lines a file and
  every count then reads `5+`.
- **`dead()` is not a list of dead code.** It is the definitions no call row
  lands on, and on a library most of those are calls the map could not place:
  a call through an imported module leaves no row, and neither does a call
  inside the file that declares the callee. It is sharp on a test suite,
  where a page object is called from step modules, and blunt on a library.
  Read it as questions and check the callers before deleting anything; the
  answer's first line says the same thing before it says anything else, and
  `## How this was counted` under the rows says how the list was made.
- **Read the tail, then take its handle.** "12 more matching rows
  (more:rows:...)" means call `more` with that string, not `ask` again at a
  bigger budget: `more` returns the twelve you have not seen, `ask` returns
  the ones you have and then some. Chase handles until one says
  "no such handle in this map" and you have the whole list. "did not match"
  rows are the section's other content, not misses; a line that shows both
  counts carries the handle for the matching rows, and the other list is the
  same handle with `rows` changed to `unmatched` and the offset set to 0.
- **A handle is only as good as the map it came from.** It stores nothing: it
  names a section, your words and a position, and `more` recomputes the rest
  from the map on disk. After a rebuild it may answer "no such handle in this
  map", which means ask again rather than that the rows are gone.
- **An answer with `## Defined here`** is the definitive location; go there.
- **"no match for … indexed: …"** says what was searched. It is not a claim
  that the thing does not exist - the walk has bounds.

## Do not

- Do not `Read` the whole map to "get an overview": the pointer already lists
  the sections, and `sections()` repeats them.
- Do not ask the same question again at a larger budget to see the rest: that
  pays for the part you already read a second time. The handle is the cheaper
  half of the answer.
- Do not fall back to `grep -r` over the repository when the map answered
  little; ask with other words first, then grep the map file, then the
  repository - in that order.
