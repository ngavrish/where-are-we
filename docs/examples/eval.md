# `wawe-eval`: does the budget lose answers?

Every answer the map gives is cut to a byte budget, and a cut is a claim:
that what was dropped was worth less than what was kept. `wawe-eval` tests
the weaker and more important half of that claim, which is that nothing is
lost for good.

It has two halves. The deterministic half needs no model, runs in a second,
and runs in CI. The `--agent` half calls the Claude API, costs money, and is
run by hand.

## The deterministic half

```bash
pip install where-are-we
where-are-we --repo . --out .wawe            # build a map first
wawe-eval --map .wawe --questions 100 --budgets 350,1500,12000
```

```
budget  questions  first_answer_recall  pooled_recall  top5_recall  recall_with_handles  rows_over_budget  mean_bytes
   350        100               0.4756         0.1046       0.7245                    -                34       302.6
  1500        100               0.8572         0.3047          1.0                    -                 0       884.9
 12000        100               0.9999          0.999          1.0                    -                 0      2050.9
map: /tmp/wawe-eval/suite/out  questions: 100 of 285 in the pool (name 59/224, step 35/37, heading 6/24)  seed: 0
handles: not available in this build
```

### How to read it

**The questions come from the map, not from a person.** Three sources, as
many of each as the map has: every declared name, every step phrase's most
distinctive word (the one that separates that phrase from the others), and
the longest word of every section heading. They are sorted, shuffled by
`--seed`, and walked until `--questions` of them match something, taking up
to a third of the run from each source that has anything before filling the
rest from what is left: a map with two thousand declared names and thirty
headings would otherwise answer for the headings with two questions. The
line under the table says how many came from each source and how big each
source was. A question the map cannot answer at any budget measures nothing
about the budget, so it is skipped and counted (`skipped_no_rows` in
`--json`).

**The reference is the whole answer.** For each question, `ask(words, 10**9)`
is asked once: every row the map holds for those words, with no budget at
all. Rows are compared with the directory grouping undone, so the same row
is the same string whether or not a neighbour happened to fit beside it.

**`first_answer_recall`** is the share of the rows of the full answer that
the budgeted answer shows before any `more`, averaged over the questions. It
is a macro average: each question's recall is computed, then those are
averaged, so a question with two rows counts as much as a question with
three hundred. It is meant to be below 1.0. That is what a budget is, and
the number is not a score to raise; it is the size of the thing
`recall_with_handles` has to cover.

**`pooled_recall`** is the same quantity averaged the other way: all rows
shown over all rows there were, so the biggest questions dominate. It runs
well below the macro number, which is the honest reading of a budget: the
questions with the most to say lose the most.

**`top5_recall`** is rank aware. `ask` ranks what it shows, so this is the
share of the *first five* rows of the full answer that survived the cut,
averaged per question. A budget that drops the tail and keeps the top scores
high here and low on the other two, which is the intended behaviour.

**`rows_over_budget`** counts reference rows longer than the whole budget.
A row of 446 characters cannot be printed at a budget of 350 by anything:
not the first answer, and not `more`, which reports such a row rather than
skipping it. It is a property of the map and the budget, not of `more`, so
it is counted and named, per question in `--json` and as a total in the
table, and never asserted. These rows do count against `first_answer_recall`
and `pooled_recall`, because a reader who asked for them did not get them.

**`recall_with_handles`** is the share of the rows *that fit the budget*
reached once every `more:` handle in the budgeted answer has been followed,
and every handle in the replies after that, until none is left. This one is
meant to be 1.0 at every budget, and `wawe-eval` exits 1 if it is not,
naming the questions that lost rows and how many of their rows were over
budget and therefore not counted. A budget that hides a row is the design.
A budget that loses a row it could have shown is a bug in `more`.

A dash in that column and `handles: not available in this build` under the
table means this build has no `more` tool: the deterministic half still
reports what the first answer holds, and says plainly that it cannot report
the rest.

**`mean_bytes`** is the average size of the budgeted answer. It is usually
well under the budget, because `ask` keeps whole rows and pays for its tail
line up front rather than filling to the ceiling.

`--json` prints the same numbers plus `rows_over_budget_by_question`,
`max_more_calls` (the longest handle chain any one question needed),
`chains_cut_short` (chains stopped by `--max-more`, which should be zero),
`questions_by_kind` and `pool_by_kind`, and one entry per lost row under
`losses`.

An answer is asked for once and remembered, keyed on the map, the words and
the budget, so a run that repeats a budget, or asks at a budget the
unbudgeted reference already covered, does not read and rank the whole map
twice for the same answer.

### In CI

The CI step `wawe-eval: the budget loses no row the map holds` builds the
three golden fixtures and runs the suite fixture at 350 and 1500 bytes over
100 questions. The exit code is the gate: 0 when every question comes back
whole, 1 naming the questions that lost rows. A second, `--json` run is
checked for having measured anything at all (both budgets present, a hundred
questions each, every recall a fraction), because an exit code of 0 also
comes back from a run that measured nothing. And when the build has `more`
in it, a run that prints `handles: not available in this build` fails the
step: the property the step is named for is the one it must not skip.

## The call graph half

`--graph` answers a different question about the same map: not what the
budget lost, but how much of the call tree the walk could resolve in the
first place.

```bash
wawe-eval --map .wawe --graph
```

```
language  sites  resolved  ambiguous  resolution_rate  ambiguous_share
  python   2185       517        102           0.2366           0.0467
   ts_js      2         2          0              1.0              0.0
      go      3         2          0           0.6667              0.0
```

`sites` is the callee names the walk looked at, one per function per
distinct name. `resolved` is how many of them it could place in an indexed
file. `ambiguous` is how many had more than one file to choose from: those
are the edges `framework_map.json` writes with a trailing `?`, because the
file such an edge names is whichever the walk reached first. The three
counters live in the map under `call_graph_stats`, counted over the whole
walk rather than the 60 keys `call_graph_files` keeps, so the rate is about
the walk and not about the cap. `--json` prints the same report as JSON.

With `pip install "where-are-we[precise]"` the TypeScript, JavaScript and Go
are parsed again with tree-sitter and the two counts are printed side by
side:

```
regex vs tree-sitter, go: sites 5 vs 2 (-3), resolved 5 vs 2 (-3), rate 1.0 vs 1.0 (+0.0)
```

The pattern pass scans a function body from its signature line, so the
function's own name reads as a call and so does `if (`. The parse counts
neither, and the gap is how much of the pattern pass's confidence was
bookkeeping. Without the extra installed the line says the comparison was
not run, and the rest of the report is printed as usual.

The CI step `wawe-eval --graph: the map says how much of its call tree it
resolved` asserts the key is there, that both rates are fractions, and that
on the poly fixture, whose every callee is declared in it, `resolved` equals
`sites`.

## The agent half

The same map, asked by a model two ways: once with the map tools, once with
grep and read over the repository. Same questions, same model, same scoring,
so the only difference is what the agent had to search with.

```bash
export ANTHROPIC_API_KEY=...
pip install "where-are-we[eval-agent]"
wawe-eval --agent --repo . --out .wawe --questions 5 --model claude-sonnet-5
```

It prints one row per arm and writes every question's row to
`eval-agent.json`:

```
 arm  questions  correct  accuracy  tokens_in  tokens_out  tool_calls
 map          .        .         .          .           .           .
grep          .        .         .          .           .           .
wrote eval-agent.json
```

The cells are left empty on purpose. No numbers are quoted here because no
run has been made to quote: this half is not in CI and its result depends on
the repository, the model and the day, so the table it prints is the record,
not this page.

Without `ANTHROPIC_API_KEY` it refuses and sends nothing:

```
wawe-eval --agent calls the Claude API and found no key: set
ANTHROPIC_API_KEY in the environment and run it again. Nothing was sent.
```

(exit 2, and the same exit code with the same shape of message when the
`eval-agent` extra is not installed.)

### The questions

Four kinds, all with answers already written in `framework_map.json`, so
nothing is scored against a model's opinion:

| kind | question | answer taken from |
|---|---|---|
| `definition` | Where is `X` defined? | `definitions` |
| `caller` | Which functions call `Y`? | `call_graph_files` and `call_graph`, through `callers()` |
| `tag` | Which scenarios are tagged `@Z`? | `features[*].scenarios` and their tags |
| `route` | Which file serves route `R`? | `routes_served` |

Kinds are interleaved before sampling, so five questions on a map with many
definitions and a few routes come back as some of each rather than five
definitions. A kind the map has nothing for produces nothing.

Scoring is exact match, not similarity: every expected string has to appear
verbatim in the model's final answer. These are paths, line numbers and
identifiers, and an answer of the right shape with the wrong name is wrong.

### The two tool sets

**`map`** is the five MCP tools, read straight from `mcp.TOOLS` so their
names and descriptions are the ones a real agent sees, answered in this
process by the same functions the MCP server calls. No server, no
subprocess, no network beyond the model call itself.

**`grep`** is two tools, `grep(pattern, path)` and `read(path, start, end)`,
implemented here in Python over the repository. Read only, bounded to the
repository (an absolute path or a `..` out of the tree is refused after
symlinks are resolved, not before), and with no shell: the comparison is
about what the map saves an agent that searches files, and a shell would
make it about the sandbox instead.

### What it costs

Every question is asked twice, once per arm, and each ask is a short tool
loop. `eval-agent.json` records `tokens_in`, `tokens_out` and `tool_calls`
per question per arm, so the bill is arithmetic after the fact rather than a
guess: multiply the totals by the model's rates. Before the fact, the thing
to know is the shape of the spend. Each question is a short tool loop and
the whole conversation is re-sent on every round, so input tokens grow with
the square of the rounds, and the grep arm is the expensive one because it
puts real file contents into the conversation while the map arm puts a
bounded answer there. Price a large run by doing a five question run first
and reading its `tokens_in`. `--max-turns` (default 12) is the ceiling on
rounds per question, and it is what stops a lost grep arm from spending a
repository.

The agent half is deliberately not in CI. It costs money, it is not
deterministic, and the claim it settles is a comparison, not a contract.
