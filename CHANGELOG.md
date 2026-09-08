# Changelog

## 1.6.0

Answers the graph already holds. 1.5.0 wrote `xrefs`, `spans` and `rank` into
the map and nothing read them end to end; this release starts doing that.

- Which tests a change reaches: `affected` (MCP), `--affected FILE[,FILE]`,
  `--changed [REF]`. The walk starts at every name the changed files declare
  and follows the map's `calls` rows upward, callee to caller, with a visited
  set and a sorted frontier, to a depth of 6 by default and 12 at most. The
  answer names the scenarios whose steps reach the change, with the step that
  reaches it and how many hops away it is, the feature files those scenarios
  are in, the routes and page objects reached, and the files no `xrefs` row
  names at all, which is the answer saying what it does not cover. That last
  count is in the first line as well as in its own block, because it is the
  block a small budget gives up first and a selection that drops it quietly
  is the one way this tool can be wrong rather than short.
- A step function is identified from the map rather than from a naming
  convention: `spans` holds two declarations on one line for a behave step,
  the function and the phrase its decorator binds, and the join of those two
  is what a step function is. A scenario is reached when one of its own step
  lines holds a reached phrase, normalised and cut to 40 characters, which is
  the same substring rule `feature_links` is built with: a scenario named
  here is one the map already binds to that module, and a step phrase written
  as a regular expression that shares no literal head with its line binds in
  neither place.
- A changed feature file selects its own scenarios. A feature file is a test
  rather than something a test calls, so every scenario in it is affected, at
  no hops, and the row says "the feature file itself changed". Before this a
  commit that edited or added a scenario, which is the commonest change a
  behave suite gets, selected nothing and read as an all clear.
- A route is named when the file it is served from is reached.
  `routes_served` records the basename of that file and no handler name, so
  the granularity of that block is the file, and its head says so.
- A first line that says what a zero means. On the `suite` golden fixture a
  change to `pages/checkout.py` reaches 40 step functions and 0 of 5
  scenarios, because 3 of those 5 hold no step any module in that fixture
  binds; the answer says so rather than reading as an all clear.
- `--changed [REF]` reads `git diff --name-only REF` in the repository the map
  was built from, HEAD by default, so a pipeline passes nothing. A ref that
  reads as an option to git is refused rather than handed to it, a failed
  `git diff` is one line and exit 2, and a commit that changed nothing is
  "nothing changed since HEAD" and exit 0.
- `--affected-format behave` prints one `--name` per affected scenario,
  anchored on its name, and nothing else. `--name` is the only option behave
  unions: it is `action="append"` and it matches a scenario wherever it
  lives. `-i` is a plain store, so the last one on the line overwrites the
  rest, and it filters which feature files are collected at all, so it
  intersects with `--name` instead of adding to it; a selection using it ran
  3 of the 24 scenarios it named across 8 feature files, and none of the 3 it
  named across a wholly and a partly affected file. And no tag is ever
  printed: behave applies `--tags` per scenario, and the map records a
  feature file's tags as every `@word` anywhere in it, so a scenario level
  tag or the `@` of an email address in a step line would select the wrong
  scenarios or none at all. A scenario outline is selected too: behave
  substitutes the example values into the name it runs and appends its own
  ` -- @1.1` suffix, so the pattern allows both. Past 200 scenarios each
  feature file's names alternate inside one `--name`, because a command line
  has a length. Two scenarios of one name in one file are one argument and
  behave runs both, which over-selects rather than under-selects.
  `--affected-format pytest` prints node ids from `pytest_tests`.
  `--affected-depth N` is 1 to 12, and the flag refuses what the tool
  refuses.
- A selection is exempt from the answer budget. The budget is there because
  prose lands in a conversation and is re-read on every turn after it; a
  runner's selection is a machine artefact that goes to `xargs` or to a file,
  and half of one is a test run that quietly misses tests. So
  `--affected-format` prints its list whole, with no tail and no handle,
  however large: measured on 80 feature files of 30 scenarios, 2400 of 2400
  selected as 80 patterns and 56 KB, with behave running every one. The prose
  blocks keep the budget rules they had.
- `--affected-out FILE` writes that selection, and nothing else, to FILE, and
  prints the blocks a person reads to stdout, so a pipeline parses a file it
  asked for rather than an answer it has to cut a head off. The write is
  atomic, the flag is classed `writes-repo` because the path is the caller's,
  and `--dry-run` names the file and the directories it would create without
  writing either.
- That file is empty, zero bytes, when the change reaches nothing, and when
  `--changed` finds that nothing changed at all: an empty file means run
  nothing, and never the previous run's selection left where it lay. The
  sentence saying so in words stays on stdout, where a person reads it;
  written into the file it would be an argument behave fails on. A pipeline
  has to test for it, because `xargs` given empty input runs behave with no
  arguments, which is the whole suite:
  `[ -s sel.txt ] && xargs behave < sel.txt || echo "nothing to run"`.
- The MCP `affected` tool stays bounded, unlike the flag. A tool reply lands
  in the conversation and is re-read on every turn after it, which is why
  every tool this server declares has a ceiling and the command line does
  not: the flag has `--affected-out` to write a large selection to, and a
  tool has nowhere like that to send one. A selection that fits the 12000
  character reply comes back whole and is the same bytes the flag prints; one
  that does not comes back as its count, its first 20 selectors and the
  `--affected-out` command that writes all of it. Never a prefix that reads
  as the whole list.
- Every block is cut by the rules every other answer here is cut by: whole
  rows, a floor share of the budget with what nobody claims handed on in
  printing order, and a `more:aff:` handle under a block that could not print
  all of itself. `more` resolves it like any other handle, with the block, the
  files and the depth in the handle and nothing stored between the two calls.
  A block there is no room to print at all is not dropped silently, as it is
  in `context`: it gets one line, `… 2 rows in pages; raise the budget`, with
  the handle that fetches them, because a list of rows a reader can neither
  see nor ask for is what makes a selection wrong rather than short. Where
  even those lines do not all fit, the one for the unreachable files is the
  last to go, because it is the one that says the answer is partial.
- `context`'s three budget functions are now shared with this one, with the
  handle passed in: the cut, the floor and the two allocation passes were the
  same for both. `context` is byte for byte what it was, over 224 names at 6
  budgets.
- Which tests reach one name: `reaches` (MCP), `--reaches NAME`. The other
  direction of `affected`, over the same walk and with no depth cap, because
  the question is whether anything reaches this at all and a cap would answer
  "nothing" for a function seven hops under a step. The answer names where
  the name is declared with the members walked for a class, the scenarios
  that reach it grouped by feature file with the chain of calls under the
  first scenario of each, the pytest cases that reach it, and the routes
  reached. A class is answered by what is declared inside it: `spans` records
  the range of a class and the line of each method and links them to nothing,
  so the dotted name it writes beside a method and that method's line inside
  the class's range are the only joins the map holds, and without them
  `reaches CheckoutPage` answers nothing for a page object every step drives,
  because the constructor call sits at module level and no `calls` row is
  written for it.
- What no test reaches: `unreached` (MCP), `--unreached`, with `--limit N`
  for how many definitions are ranked (200 by default). One walk down from
  every entry point the map names, to exhaustion, and every product function
  and class it never arrives at, grouped by file and ranked by the map's own
  `rank`. An entry point is a behave step function, a pytest case
  `pytest_tests` names, or any declaration in the files another runner holds
  its cases in (`js_tests`, `api_tests`, `perf_suites`, `other_suites`,
  `more_suites`), whose cases the map records by title rather than by
  function. Product is every file that declares something and that the map
  does not name as suite, read off the keys the map already writes
  (`features`, `steps`, `page_objects`, `drivers`,
  `behave_environment_files`, `pytest_tests`, `js_tests`, `fixtures`,
  `perf_suites`, `helpers`, `api_tests`, `other_suites`, `more_suites`), so a
  product under a root of its own and a product beside its suite are answered
  the same way. A class counts as reached when anything declared inside it
  is.
- The answer says what it set aside and how it counted. The precision of the
  product split is the precision of the map's own suite heuristics, so the
  files it treated as suite are printed under a head of their own: a module
  the mapper miscalls a page object is not product, is not in the count and
  is not in the list, and now that is visible instead of silent. A `## How
  this was counted` block carries the entry point tally, the product rule,
  the kinds counted, the class rule, the exclusions and the ranking, so the
  first line stays short enough to read.
- `main`, `__main__` and `__init__`, and any file on a test path, are left
  out of `unreached`. The list is `graph.ENTRY_POINTS`, in one place, because
  `dead` asks the same question of the same graph and two answers disagreeing
  about the same definition is worse than either rule.
- Two limits of the map are stated in the answer rather than left to be
  discovered. Where a class's `end` is unknown and `spans` records no dotted
  name for a method, `reaches` says the counts are a floor instead of
  answering nothing. Where the product is checked out under a root of its
  own, no `calls` row crosses into it, because the call graph is extracted
  from the files under `--repo` and from no other root; both answers say so.
- Only `function` and `class` kinds are counted, and the block that says how
  the count was made says why a `const` bound to an arrow function is not one
  of them: the map records it as a constant with nothing beside it saying the
  value is callable. `reaches` has no such limit and answers for a constant
  like any other name.
- The first line of `unreached` states the graph's own resolution rate, from
  `call_graph_stats`: how many of the callee names the walk looked at some
  indexed file declares. A graph that placed half its names calls half the
  product unreached whatever the suite covers, and a list of names under a
  head that does not say so reads as a coverage report. A map with no step
  function at all says there are no steps to reach from and prints no list,
  rather than naming every definition it holds.
- How one function reaches another: `path` (MCP), `--path A,B`,
  `--path-depth N`. Breadth first over the same `calls` rows, forward this
  time, caller to callee. One hop per line with the rule that placed the edge
  and the line the call site is on, the rows out of a node sorted by callee,
  line and resolution and every frontier sorted, so the chain printed is the
  same chain on every run. A visited set carries across hops, so a graph with
  a cycle in it terminates and the first chain found is the shortest. An
  ambiguous edge is followed into every candidate rather than guessed at, and
  the hop names every file that declares the callee and says which of them
  the chain took. Each end is a name, or `FILE:NAME` where several files
  declare it. Where there is no chain the answer names the frontier the walk
  stopped at, so "no path" says how far it got, and the first line says the
  two reasons a chain can be missing: the depth, and that only cross-file
  calls are in this graph.
- The lines an edit needs: `range` (MCP), `--range NAME`. Every home of a
  name as `file:start-end kind`, the text of the shortest of them, and the
  three numbers an editor anchors on, the first line of the definition, the
  last, and the one after the last, each printed with the text of that line
  so an `Edit` can match on the text rather than trust a number. An
  insertion after the last line lands outside the definition rather than
  inside it, which is the move this exists for. A site whose end nothing
  measured cannot be the shortest and is listed with `?` and the reason,
  which says whether a read cut short is ruled out. No write path.
- What nothing calls, with the emphasis on the question mark: `dead` (MCP),
  `--dead [--limit N]`. It is a list of questions and not a list of dead
  code, and the answer's first line says so before it says anything else,
  because the flag's name does not. Only cross-file calls are in the graph,
  so a call inside the file that declares the callee leaves no row, and
  neither does a call through an imported module, which is how a package
  usually calls itself: on this repository 359 of 516 definitions are listed
  and a spot check of five found one that is genuinely dead. It is sharp on a
  test suite, where a page object is called from step modules across files,
  and blunt on a library. What it is: the definitions no `calls` row lands
  on, grouped by file, one file per row. One `def` is one
  row whatever it is spelled as: `spans` holds a class as `LoginPage` and as
  `class LoginPage` and a method as `LoginPage.sign_in` and `sign_in`, and a
  call on any spelling keeps the site off the list. Counted only in the file
  kinds this map's call graph actually reaches, read off the table rather
  than hard coded, because a `def` quoted inside a Markdown fence is
  documentation and not dead code; a row of `## How this was counted` names
  the suffixes it counted, and a declaration in any other language is not
  judged either way.
  A map whose graph holds no `calls` row at all answers `No call graph in
  this map` rather than printing a clean nothing, which is what a small
  repository used to get. `routes_served` records a basename and no path, so
  where two files share one the map cannot say which serves the route and
  both are left out, and a row of that same block counts the basenames it
  guessed on instead of dropping their rows in silence.

  The map's own "Page-object methods nothing calls" section is **not** yet a
  rendering of `dead`, which is what 1.6.0 planned. The two disagree: that
  section is `unused_api`, a count of occurrences of `.name` in the suite's
  own source, and on the `suite` golden fixture it calls 20 methods dead that
  the graph holds an incoming `calls` row for. Rebuilding `unused_api` from
  `xrefs` empties the section and moves four golden files, so it is left to a
  release that names the moved lines. A CI step measures the disagreement and
  runs `dead` against that fixture, where it returns one row, `CheckoutPage`,
  and that row is a known false positive: `build_fixtures.py` has the steps
  module do `page = CheckoutPage()` at module level, and a `calls` row's
  subject is `<file>:<func>`, so a call outside any function has no shape to
  be recorded in. Recording it needs a synthetic subject and a change to what
  an `xrefs` row means, which is a mapper change and not this release's; the
  step fails if such a row ever appears, so the caveat cannot outlive it.
- Where to look first: `hot` (MCP), `--hot [--limit N]`. The map's own `rank`
  score times the commits its most-changed-files section counted, top N with
  both numbers printed, so a reader can see which of the two put a row where
  it is. `rank` is the map's top 200, so this ranks within those, and the
  first line says so.
- A new map key, `git_commits`: how many commits named each of the forty
  busiest files in the last ninety days. `git_history` was not that number
  and reading it as one was a false statement in an answer. That key keeps at
  most five commit lines a file, so it is a sample for a reader rather than a
  count, and multiplying a rank score by the length of it made every file in
  the section weigh exactly five: `--hot`'s top twenty came back as `--rank`'s
  order verbatim, with `ask.py` printed as five commits where the history
  holds thirty-seven. `git_commits` is counted before the lists are cut, over
  the same forty keys, and the most-changed section in the brief now prints
  it too. This is the one key 1.6.0 adds, and the golden maps move by exactly
  that one line; every expected answer is byte for byte what it was.
- `hot` states both of its bounds in the first line, the way the `impact`
  answer states its own. The most-changed section is the forty busiest files,
  so a file outside it counts 1 however often it changed and the ranking is
  `rank`'s own order for those; a merge commit names no file in the log that
  section is built from and is not counted. A map built before `git_commits`
  existed can only count commit lines, and there the first line says so and
  every count at the cap prints `5+ commits`, a floor rather than a
  measurement.
- A `more:` handle chain never dead-ends on a row longer than the budget.
  Every chain in this project continues a list by offset; `fit_indices` skips
  a row that does not fit and `_first_gap` puts the handle's offset back on
  it, so the handle an answer printed landed on exactly the row nothing could
  print, the next call answered `no such handle in this map: line N ... does
  not fit`, and every row after it in that list was unreachable at that
  budget for good. Now such a row is returned cut, marked `… (row cut to fit;
  756 of 1574 characters)`, and the offset moves past it: a cut row counts as
  delivered, because the reader has its front, is told exactly how much was
  taken off, and the chain advances. Below the length of one handle the count
  of what is left is printed without it, which is the line the same corner of
  `_block_chunk` already printed. Fixed once, in `more()`, for every kind it
  serves: `rows`, `unmatched`, `defs`, `ctx`, `aff` and the four new ones. A
  `sections` handle, whose unit is a section rather than a row, steps past a
  section that will not fit and names it instead of refusing. That line is
  itself built to fit: a section name is arbitrary text and can run past a
  small budget on its own, so the forms shorten until one fits and the name
  is the first thing given up, and the note under it is offered the room the
  line left rather than the whole budget. It carries a handle only where
  there is a section after this one, the guard the ordinary path has; without
  it the last section handed out a handle one past the end of the list and
  following it was refused. Swept over 542 budgets from 60 to 3000 on this
  repository's own map: 7040 calls, 0 over budget, 0 refusals reached from a
  printed handle, 1885 replies that stepped past a section.

  The refusal is as old as handles and shared by every kind; what is new is
  the row shape that reaches it. `dead` prints one file per row with every
  name on it, and on this repository one row runs to 1574 characters, which
  at 900 stranded 25 of 39 rows. Measured after the fix, on this repository's
  own map rather than on a fixture of short rows: 39 of 39 reachable at
  12000, 1500, 900 and 800, and the 1574-character row comes back cut. The CI
  step asserts that, and asserts on the `affected` chain that across every
  budget from 202 down to 60 the call comes back, stays inside the budget,
  never refuses, and either advances the offset or says there is no room for
  a handle.
- Every one of the four prints its rules in a block rather than in its first
  line. A first line is read again on every turn of a conversation and the
  rules behind it are not, and `dead`'s had grown to about a thousand
  characters carrying both caveats, the file-kind rule, six exclusions and a
  route caveat, which also put the whole answer out of reach below its own
  length. Each first line is now the counts and the one sentence that decides
  what they mean, under two hundred characters: for `dead` that most of the
  list is calls the map could not place rather than dead code, for `hot` that
  churn covers the forty busiest files only, for `path` that only cross-file
  calls are in the graph, and for `range` that a redacted line is not the
  line on disk. Everything else is a row of `## How this was counted`, the
  same head and the same shape `unreached` prints, and the budget may cut it
  without taking a count or a caveat with it. Measured: 168, 178, 102 to 164
  and 50 to 153 characters against 988, 506, 194 to 236 and 50 to 253 before.
- All seven are cut by the rules every other answer here is cut by, through
  one function rather than seven: whole rows, a floor share of the budget per
  block with what nobody claims handed on in printing order, a `more:` handle
  under a block that was cut, and one "raise the budget" line with a handle
  for a block there was no room for at all. `affected`'s renderer became that
  shared one and is byte for byte what it was. The handle kinds are
  `more:aff:`, `more:rch:`, `more:unr:`, `more:pth:`, `more:rng:`,
  `more:dead:` and `more:hot:`, each carrying its own question and nothing
  stored between the call that printed it and the call that uses it: what to
  walk is in the handle, the walk runs again over the map on disk, and a
  rebuilt map answers "no such handle in this map" rather than a slice of
  some other list.
- A `find` chain advances past a hit longer than the budget. `find_text`
  refused when not even the first hit fitted whole, and the refusal was
  itself over the budget: on this repository's own map `more:find:invoice:0`
  at 150 characters returned 111 characters of "no such handle" and stranded
  all 166 hits behind one row of 152. It now prints that hit cut and marked,
  with the handle on the hit after it, through the same `_cut_row` the other
  chains were repaired with. The two CI assertions that read a refusal as an
  answer that fitted are the reason it stood for a round; both now assert the
  budget and the absence of a refusal separately.
- A map with no call graph edge says so, in `affected`, `reaches` and
  `unreached` alike. The resolution rate does not catch this on its own: a
  name the caller's own file declares is resolved without becoming an edge,
  so a JavaScript suite whose call sits in the arrow passed to `it(...)`
  reads 100 percent resolved with an empty graph, and `unreached` then lists
  the whole product under a head whose only caveat reassures the reader.
- A page object owns a selector, and the word alone is not one. The shape
  half of the rule counted the bare words XPATH, SELECTOR, LOCATOR, CSS,
  data-testid and By. anywhere in a file, which put this project's own
  `_mapper/build.py` in `page_objects`, because the words are in that file
  for the reason it finds them elsewhere. It now wants the punctuation that
  makes each word a selector: a locator constant being assigned, a
  `data-testid=` followed by the quote that opens its value, an attribute
  read off Selenium's `By`. A class with three locator constants under
  neither a `pages/` directory nor a `*_page.py` name is still found.
- `dead` says why a class only ever constructed is in its list. The resolver
  places a callee by the function declarations it indexed and keeps class
  names in a table of its own, so a construction writes no `calls` row from
  anywhere, module level or not, and `CheckoutPage` is the one row `dead`
  returns on this project's flagship fixture. That is a row of
  `## How this was counted` now rather than a fact a reader has to discover.
- `ENTRY_POINTS` and `_entry_name` are two exclusion rules on purpose, and
  the README says why. `unreached` counts a definition to say what share of
  the product the tests cover, so every name a rule drops leaves the
  denominator with it; `dead` asks what nothing calls, where a name the
  runtime or the runner calls is not an answer. Each answer's
  `## How this was counted` block prints its own list.
- A README section, "What to re-run after a change": the `--changed <base>
  --affected-format behave --affected-out sel.txt` pipeline with the guard
  that makes it right, the five things the guard is there for, and the clause
  that says what the selection cannot see. A CI step runs that pipeline
  verbatim on a git fixture in all three of its branches, and behave itself
  agrees the selection is the scenarios named and not the rest.
- `tools/list` moves from 12 to 18 and every pin in the workflow moves with
  it; the session banner the plugin prints names all eighteen, and two CI
  steps fail on a stale number: one when a tool the server declares is
  missing from the banner, and one that reads every prose count of the tool
  list in every document and checks it against `mcp.TOOLS`. That second step
  is what found ten stale counts across four documents while these five
  changes were being merged.

## 1.5.0

What the neighbours in this space do better, taken: every home of a name with
its span, one call that answers the five an agent asks on landing, a ranking of
what the repository is built around, a content-addressed parse cache, a `tags`
file, a cost report and an export, and every edge of the graph as a row that
says which rule placed it.

- Every home of a name, with the line it ends on. The map gains a key
  `spans`: `{name: [{file, start, end, kind}]}`, one row per declaration site,
  sorted by file then start. `definitions` is unchanged, so nothing reading it
  moves; what changes is that a name declared in two files no longer keeps
  whichever of them the walk reached first and says nothing about the other.
  The end line is `ast`'s own `end_lineno` for Python and a tree-sitter node's
  `end_point` where a grammar is installed; for a language the pattern table
  reads it is null and prints as `?`, because a pattern has seen the line a
  declaration starts on and nothing that says where it stops, and a guessed
  end is worse than none for anyone editing by anchor.
- What a file quotes is not what it declares. The lines inside a Python string
  literal, docstrings included, and the body of a `<<EOF` heredoc in a shell
  script or a workflow are text this file hands to something else, so they are
  no longer read for declarations. On this repository that is 40 names gone,
  measured on the 1.5.0 tree by building it twice, once with the rule off:
  29 declared inside `python - <<'EOF'` blocks in the CI workflow, 11 inside
  the string fixtures `tests/golden/build_fixtures.py` writes out and one in
  a docstring, which sums to 41 because `refund` is written in both files.
  The three worth naming: `refund`, a `def` inside a fixture string; `build`, a `def` inside a CI
  heredoc, which used to outrank the real `build` in `rank`; and `of`, from
  the phrase "the class of that command line" in a docstring. The count is a
  property of this tree rather than of the rule, and it moves with the
  workflow: the same A/B on the 1.6.0 tree gives 67. The heredoc rule
  is applied to `.sh`, `.bash`, `.zsh`, `.ksh`, `.yml` and `.yaml` and nowhere
  else, because `a << b` at the end of a line is a shift in the languages that
  have no heredocs. It is a shift in shell too, so an opener is refused where
  the line puts it inside `$(( ))` or `(( ))`, after `let`, or in an integer
  declaration, and a bare delimiter is believed only when a later line closes
  it: `let MASK=1 << bits` declares `MASK` and everything after it, as it did
  before. A redirection after the delimiter is still a heredoc, which is what
  `python - <<'EOF' > out.bin` is. An opener that is believed and never closed
  runs to the end of its own file and nothing beyond it, and that file is named
  under `## This map is incomplete` with the delimiter that was left open.
- `--defines NAME` and the MCP `defines` tool list every home:
  `charge: a.py:10-24 (function), b.py:88-91 (function)`. The flag is new; the
  tool answered with one home per name before, chosen by directory order.
- `--at FILE:LINE` and the MCP `at` tool return the whole definition enclosing
  a line, which is the move after every stack trace and was until now a read
  at a guessed offset. The innermost definition, whole lines, cut to the
  answer budget with a `more:at:` handle for the rest. A line no definition
  encloses is answered with `no definition encloses FILE:LINE` and the nearest
  declarations, rather than with the wrong function.
- Under the `precise` extra, `.ts`, `.tsx`, `.js`, `.jsx` and `.go` get real
  end lines too. The grammar is asked how far a declaration runs and nothing
  else: which names those files declare, and on which line, is the pattern
  table's answer either way, so `definitions` is the same map with the extra
  installed and without it.
- `--context NAME` and the MCP `context` tool answer in one call what five
  calls answered before: where the name is declared and how far each
  declaration runs, the rows of the map that mention it, who calls it, what it
  calls, and its blast radius one hop out. Nothing new is parsed and nothing
  new is stored; it is `defines`, `ask`, `callers`, `callees` and `impact`
  over the same map, so an agent that lands on a name pays one round trip
  rather than five. The budget is counted in characters, as `ask`'s is, and
  the first line says so: it names the five blocks, the ceiling and the
  shares, in 134 characters rather than the 181 an earlier draft spent,
  because at the MCP server's 1500 floor that line is twelve percent of the
  answer. The budget is allocated in two passes: every block is
  given the smaller of what printing all of itself would cost and its floor
  share - 15 percent for the declarations, 35 for the map's rows, 15 for the
  callers, 15 for the callees, 20 for the impact - and what nobody claimed is
  handed on in that same order to the blocks still short. So when the five
  answers together fit the budget, every one of them is printed whole; and the
  same name at the same budget is always the same answer, since the needs come
  from the map and the order is fixed. Whole rows; a block that could not
  print all of itself ends in a tail carrying a `more:ctx:` handle that `more`
  resolves like any other, and a block that could not be given room for even
  that is left out rather than printed as a count nobody can follow.
- `wawe-eval --tool context` measures the new tool with the harness that
  measures `ask`: over 100 names of the suite fixture, recall with handles is
  1.0 at 1500 and at 12000 characters, which the CI step `context returns in
  one call what five calls return` asserts, at that root and at one whose
  absolute path is 80 characters longer, since path length moves how many rows
  fit and not what a handle returns.
- What the repository is built around, ranked. The map gains a key `rank`:
  the top 200 definitions as `{name, file, line, score}`, best first, from
  PageRank over the graph the map already describes. Files are the nodes; an
  edge runs from a file that uses a name to the file that declares it,
  weighted by the square root of how often it uses it; aider's four
  multipliers apply, x10 for a long snake, kebab or camel name and x0.1 for a
  leading underscore or a name more than five files declare. A hundred
  iterations of power iteration at damping 0.85, nodes walked in sorted
  order, scores rounded to nine digits before they are sorted and ties broken
  by path, so two builds of one tree and both supported Pythons write the
  same bytes. No dependency: the iteration is forty lines of arithmetic.
- `--rank [FILE,...]` and the MCP `rank` tool answer the same question with
  the walk personalised on the files you name, which is the one worth asking:
  what should I read given that I am editing these. `--ask WORDS` alongside
  it, or the tool's `words`, weighs the identifiers in the question ten
  times. `--limit N` says how many rows; with no files and no words the
  answer is the stored key, which is what the CI step compares.
- `--files a.py,b.py` on `--ask`, and `files` on the MCP `ask` tool: inside
  every section the rows naming one of those files come first and the rest
  follow with the tail they had. A directory prefix counts and stops at a
  separator, so `--files bill` is not `billing.py`; paths are read relative to
  the repository root; a row that names only a basename is resolved through
  the files the map indexed, so `--files billing/` reaches
  `refund.py:refund` in the call graph; and a path nothing indexed matches is
  named on stderr rather than silently answered as the whole repository.
  `--files -` reads a newline separated list on stdin, which is where
  `git diff --name-only` goes. Without it no answer moves: every golden
  expected file was recorded before this and none of them changed.
- A scoped answer's `more:` handle carries the scope, as one more
  percent-encoded field: `more:rows:<section>:<words>:<offset>:<files>`. The
  offset counts rows in the order the scoped answer printed, so a handle
  without it would slice the unscoped order at that number, skipping every row
  `--files` demoted past the cut and repeating every row it promoted. `more()`
  rebuilds the scope from the field and reorders the section before it
  continues, so following a scoped answer's handles reaches every row an
  unscoped answer holds. An unscoped answer carries no fifth field and its
  handles are character for character what they were.
- `--rank` reads `--files` too, so the flag that means "the files I am working
  in" means it on both tools. `--limit` is refused below 1 rather than sliced
  from the end, which is what the MCP tool already did.
- The parse cache is keyed on content. An entry is now `(path, kind, sha256 of
  the file's bytes)` rather than `(path, kind, mtime, size)`, so a rewrite that
  kept its byte count and had its timestamp put back (rsync --times, cp -p,
  tar -p, a restore from a build cache, a `git checkout` of a line the same
  length) is re-parsed without `--force`. That was the one staleness hole the
  README named out loud, and it is closed.
- Hashing stays affordable because it is pre-filtered: a file whose mtime,
  size and inode change time are what they were when its hash was last taken
  is not read at all. A rebuild of a tree nobody touched hashes nothing and
  parses nothing, and `WAWE_DEBUG_PARSES=1` now prints `hashed N files` beside
  `parsed N files` so both halves of that claim can be checked. `parsed N
  files` counts files: one file is asked for its declarations, its symbols,
  its call graph, its step phrases and its redaction diff, so the count of
  computations is about three and a half times larger and it was that count
  the line used to print. The computation count is still `PARSE_COUNT`, which
  the `mapper` facade exposes. The inode
  change time is in the pre-filter because the mtime and the size alone are
  exactly the case content addressing exists to catch, and nothing in
  userland can put a ctime back.
- A tree whose timestamps all moved while its content did not now re-parses
  nothing, where it used to re-parse everything: a CI cache restored over a
  fresh checkout, a `cp -r`, a `tar x`, a container rebuild. Measured on this
  repository, 667 parses before and 0 after.
- The parse cache schema is 4, and no 1.4 cache is read. Three things changed
  its shape over this release, and one number says so: an entry is validated
  by the sha256 of the file's bytes rather than by its mtime and size;
  `ts:<lang>` stored a list of names and now stores `[name, start, end, kind]`
  rows, which an old entry read under the new code would index a character out
  of; and a key and a hash now name their file relative to the directory the
  cache file is in rather than absolutely, so the same path is not written out
  in full once per kind per file. An entry whose value is the empty list is
  written to a new `empty` section as its sha alone, which is most of the
  redaction diffs, since most files hold nothing that looks like a credential.
  Measured on this repository, 260 indexed files, the last two of those
  changes take `.wawe-cache.json` from 590,653 to 501,718 bytes, 15 percent:
  the entries from 516,359 to 449,253 across the two sections and the hashes
  from 74,236 to 52,396. Against 1.4.1 the file is larger, not smaller, since
  1.4.1 kept no hashes and fewer kinds at all. A file written by an earlier schema is read for its
  hashes, since a sha means the same thing in every release, and dropped for
  its entries, so the build after an upgrade re-parses the tree once and every
  build after that is warm.
- `HASHES_ADDED` and `HASHES_GONE` are on the `mapper` facade beside
  `HASHES_MOVED`, so a library caller reading what a build found through the
  facade gets all three lists rather than a third of the answer.
- New map key `content_root`: one sha256 over the sorted `(path relative to
  the repository, hash)` pairs of every indexed file. `fingerprint` keeps its
  documented `<commit>:<newest mtime in nanoseconds>` format and its meaning;
  the root is the sibling that says what the tree holds rather than when it
  was last written to. A build is now skipped only when both agree, and
  `--watch` asks both questions on every tick rather than only the first.
  Two limits worth knowing: the root is compared only when the map already in
  `--out` has one, so the first build after upgrading an existing `--out` from
  1.4.x still decides on the fingerprint alone and can serve one more stale
  answer; and where `st_ctime` is a creation time rather than an inode change
  time (Windows), the pre-filter cannot see a same-size rewrite that put its
  mtime back, and neither can the root.
- `--force` distrusts the content hashes as well as the parses, so there is
  one command that recomputes a content root from the bytes. It still reads
  each file once, not twice.
- `--diff` names the files whose content moved, were added or are gone before
  it names the map keys that moved with them. It reads the parse cache and no
  longer writes it: everything it prints is measured against the map already
  in `--out`, and a `--diff` that rewrote the cache moved its own baseline and
  answered differently the second time it was run over the same tree.
- `build()` returns redacted lines. The map on disk has always been redacted;
  what changes is that the value `build()` hands a library caller is now the
  same text, so anything computed inside the build over `lines` and anything
  a reader asks the map for agree. Redaction runs once per file as the lines
  are recorded and what it changed is cached under the file's hash, so a
  rebuild of a tree nobody touched redacts nothing. The whole-map pass the
  writers run now passes `lines` through rather than sweeping them a second
  time, because that is where they were redacted: the pass over 36,000 lines
  of this repository provably changed none of them and cost 0.46 s of every
  build, warm ones included. It still sweeps every other key, and it still
  sweeps `lines` for a map whose build said `redact_lines=False` or for a map
  handed to it by a process that never built one, so a map written to disk is
  redacted whatever produced it. The published map is byte for byte what it
  was. `build(redact_lines=False)` is for a caller that wants the raw lines,
  which is the golden fixture builder and nothing else.
- `--ctags` writes `<out>/tags` beside the map: every declaration site the
  `spans` key holds, in universal-ctags format, with the line number as the EX
  command, `kind:`, `line:` and, where a parser knew it, `end:`. The map was
  already a tags file with the fields renamed; writing one costs a sort and a
  format string and buys vim, emacs, helix, kakoune, `readtags` and everything
  else that has read the format for thirty years, with no server running, over
  a checkout mounted read only, in a language whose server is not installed on
  the machine. Rows are sorted as bytes over the whole row, which is what
  `LC_ALL=C sort` checks and what the file's own `!_TAG_FILE_SORTED 1` promises
  a reader doing a binary search; a name or a path holding a tab or a newline
  is left out rather than rewritten, since a name spelled differently from the
  source is worse than a name the editor cannot jump to. Written atomically
  like every other artefact, and named by `--dry-run` before it exists.
- `--cost [THRESHOLD]` says what each section of the map costs to carry: rows,
  bytes and tokens, heaviest first, with a total, and with every section under
  THRESHOLD bytes hidden. `--cost --json` prints the same table as
  `where-are-we-cost/1`. The sections are the ones a reader carries: every one
  in `framework_map.md`, then every one in the brief beside it whose heading
  the map does not already have, which is the rule every read composes the two
  files by. Each is measured on its own file rather than on the two joined
  together, so a byte count is the one `wc -c` gives for those lines, and the
  report ends with a `measured:` line per file whose header plus sections is
  exactly that file's size. The token column is `bytes / 4` and says
  `estimate`: no extra this project has carries a tokenizer that can be
  reached without downloading a model, and a precise count from the wrong
  tokenizer would be worse than an honest division.
  `semantic.token_counter()` is the one place that has to learn about a
  tokenizer if one ever arrives.
- `--export FILE` writes the map as one self-contained file: the incompleteness
  notice, the `indexed:` counts, every section with its byte and row count,
  then the brief. For the case where a map has to travel through something
  with no filesystem, a PR comment or a paste, and the pointer, which is a
  path and an invitation to ask, is no use. `--export -` writes it to stdout,
  which is where a paste usually comes from; an empty path is refused rather
  than falling through to a build, and `--dry-run` names every directory the
  write would have to create as well as the file. Not the whole map: the big
  file is the one the pointer exists to keep out of a prompt. The internal
  renderer named `digest` keeps its name; the flag is `--export` because the
  two would otherwise be one word for two different things.
- The effects table gains all three. `--ctags` is `writes-map-dir`, `--cost` is
  `read` and appends to the answer log like every other read, and `--export` is
  `writes-repo`, the class `--agent-file` and `--docs` already carry for the
  same reason: the path is the caller's and the flag cannot say in advance
  where it lands.
- `--context` joins the set of flags that answer without building, so
  `where-are-we --context Foo` is classified `read` rather than picking up the
  build floor a command line with no read flag on it carries. It answers out
  of a map on disk and returns before any build, and has since it shipped;
  only the classification was wrong. `effects.json` does not move, since the
  set is not part of the manifest. The README's copy of that list gains
  `--defines`, `--at` and `--rank` as well, which have been in the set since
  they shipped, and a CI step now compares the sentence with the set so it
  cannot drift a third time.
- Every edge, with the rule that placed it. The map gains a key `xrefs`:
  one row per edge, `{subject, edge, object, file, candidates, line,
  resolution}`, sorted by subject, object and line and capped by nothing.
  `edge` is `calls` (a cross-file call), `declares` (a `spans` site) or
  `imports` (one import line, with the file it is in and the line it is on,
  for the package pairs `import_graph` summarises). Every path in every row
  is absolute, which is the spelling `definitions` and most of `spans` use,
  so the table joins to itself: the file a `calls` row settled on is the
  subject of the `declares` rows for that file. A `declares` row's
  `candidates` is empty, because a declaration is not a choice between
  files, and a site the page object and step tables recorded relative to the
  root being walked is named under the root it exists under, so an `--also`
  map of two checkouts names each file where it really is. `call_graph_files` is derived
  from the `calls` rows by the renderer that writes it, and holds less than
  they do: it is cut to 8 callees a key and 60 keys, and its keys are
  basenames, so where two files of one basename declare one function name
  they share a key and the file the walk read last owns it while both keep
  their rows. A consumer that parses the pipes and the `?` back out of
  `charge (a.py|b.py)?` can now read the same fact as data instead.
- `resolution` says how sure the map is about each edge, not only about the
  ambiguous ones. Eight values, each written by the rule that placed the
  edge: `sole_declarer` (one indexed file declares the name), `import_line`
  (the caller's own import line named the file), `receiver_import` (the
  module the receiver was bound to named it), `re_export` (a facade's own
  import lines were followed to the file with the `def`), `base_class` (a
  `self.name(...)` call reached the one base that declares it),
  `declaration` (the row is the declaration site), `import_statement` (the
  row is the import line) and `ambiguous` (several files declare the name and
  nothing said which, which is the `?` the rendering carries). An unmarked
  edge used to cover two different degrees of certainty; now it says which.
  There is no `local` value and no `overrides` edge: a call inside the file
  that declares the callee never becomes an edge at all, and no rule computes
  an override.
- `impact` prints a `how:` line under each hop, naming in the same order the
  rule that placed each of that hop's edges, and `step_graph` for a hop
  through the behave step graph, which records a bare name and no rule. The
  `depth N:` lines are unchanged. A map with no `xrefs` key gets no `how:`
  line and no promise of one.
- `call_graph_stats` is unchanged and now checkable: `marked` is the count of
  `ambiguous` rows per language, and `edges` the count of the placed ones.
- The Python parse record's cache kind is `func_edges_3`: it carries the
  first line each name is called on, which is the line an `xrefs` row holds.
  A `func_edges_2` record is not read, so the first build after upgrading
  reparses the Python files, and it is dropped rather than carried: a record
  under any kind this release no longer computes is left out when the cache
  is written, which used to leave half an upgraded checkout's cache file
  unreadable until someone ran `--force`.
- Under `--also` the `declares` rows are rebuilt from the merged `spans`, so
  a map of two roots holds the rows of both. The `calls` and `imports` rows
  are the first root's, as `call_graph_files` and `import_graph` are, and the
  second root's map is under `also`.
- Every `spans` site is an absolute path. The page object and public API
  tables used to record one relative to whichever root was being walked, and
  `spans` does not say which root that was, so the two things written from the
  key had to put a root back on and did it in opposite directions: `xrefs`
  joined a relative site onto the first root it existed under, which under
  `--also` could name a file that is not there, and the `tags` file took a
  root off an absolute one. One spelling in the key, one rule per consumer:
  `xrefs` copies the path through, and `tags` relativises every row against the
  directory the tags file is written into, which is where every ctags reader
  resolves it from. With the usual `--out .` at the repository root that is
  the path it always was; with the plugin's `--out .wawe` it is `../src/a.py`,
  which is the file the row means and which used to be a path that opened
  nothing.
- Upgrading does not add `spans` to a map that is already on disk. A build
  skips a tree that has not moved, so run `where-are-we --repo . --out ...
  --force` once after upgrading, or wait for the next commit. Until then
  `--defines` answers in the old `- \`name\` - file:line` shape from the old
  map, and `--at` says the map has no spans index and names the fix.

## 1.4.1

- Receivers the syntax settles. A call written `NAME.callee(...)` used to be
  placed by the callee's name alone, so every file with a `def add` was a
  candidate for `out.add(key)`. Three shapes of receiver are now read, none
  of them needing a type checker. A receiver that resolves to one indexed
  file which does not declare the name is a facade, and that file's own
  `from M import name` line is followed, three steps at most, to the file
  with the `def`: `mapper.build(...)` in `hooks.py` is `_mapper/build.py`'s
  `build`, not a choice between two files. A receiver the function itself
  bound to a builtin (a literal, a comprehension, an f-string, one of the
  builtin constructors, or `defaultdict`, `Counter`, `deque` and
  `OrderedDict` through an import from outside the tree) is not a
  first-party object, so `out = set()` followed by `out.add(key)` is
  `set.add` and no edge at all. A parameter's default counts as what the
  function bound and `None` does not, `*args` and `**kwargs` are a tuple and
  a dict, a name a nested function never binds is the one written around it,
  and `d.setdefault(k, set())` is a set whatever `d` is; a name the function
  also bound to something else, and a receiver that is not a name such as
  `d[k]`, keep the candidate list. And `self.name(...)` and `cls.name(...)`
  go to the class the method is in: declared there or by a base in the same
  file, the call is local and no cross-file edge; declared by exactly one
  base in another file, the edge names that file. A base is followed only
  where the file says where it came from, so `class D(Base)` with no import
  of `Base` and `class D(other.Base)` where nothing binds `other` keep the
  mark rather than matching a class name anywhere in the tree.
- A directory named after an imported module no longer speaks for it on its
  own. `_module_is_here` counts a directory whose last path part matches the
  module, at any depth, which made `tests/fixtures/logging/` enough for
  `logging.info(...)` to reach a first-party `info`. The directory now has to
  hold one of the callee's candidate homes. A vendored
  `requests/__init__.py` that declares `get` is a file and still answers for
  `requests.get(...)`.
- The numbers after those rules. On this repository the marks under the same
  60 keys go from 20 to 1, and the one that stays is `pool[kind].add(word)`,
  a call on a subscript. Mapping the previous release's own checkout with
  both releases, the marks under the same 60 keys go from 20 to 1 as well.
  `call_graph_stats` for this repository is now 0.2431 over 2308 Python
  sites, with 156 edges and 4 of them marked, against 145 and 36 before.
  Only the names something was actually called on are kept in the parse
  cache, so this costs `.wawe-cache.json` 241 KB against 159 KB and a full
  build of this tree 2.11s against 1.97s. The cache record these rules read
  is stored under its own kind, so upgrading re-parses the call graph rather
  than serving 1.4.0 answers from a warm cache.

- An effects manifest, so a command guard can tell this tool's reads from
  its writes. `src/where_are_we/effects.py` holds one table: every flag the
  command line parser knows against one of `read`, `writes-map-dir`,
  `writes-repo`, `writes-config` and `network`, in that order, and a
  command's class is the highest class any of its flags carries.
  `where-are-we --effects` prints the table, `--effects --json` prints
  `{"schema": "where-are-we-effects/1", "flags": ..., "order": ...}`, and the
  same JSON ships beside the code as `effects.json`. `--effects --
  <command line>` classifies one command line with this tool's own parser
  and runs nothing: `--out /tmp/m --ask x` is `writes-map-dir`,
  `--install-hook git` is `writes-config`, `--mcp` is `read`. Flags are
  resolved the way argparse resolves them, abbreviations and all, and the
  dispatch of `--effects` itself goes through the same resolution, so
  `--eff` cannot be classified as one thing and run as another. A line
  naming none of the flags that answer from an existing map builds one into
  `--out`, so its floor is `writes-map-dir` whatever else it says; `--specs`
  is one of the exceptions, since it writes `spec_map.*` and returns. The
  JSON carries a `notes` object as well, saying per class what it touches,
  so a guard reading the file is told what a `read` may still append to.
  The table cannot drift: a CI step fails when the parser knows a flag the
  table does not, when the table names one the parser does not, when a named
  flag's class is not the one documented, or when `effects.json` in the
  checkout differs from what the table prints or from the copy installed
  beside the code.
- `--dry-run` prints every path a command can write, `would write` when
  nothing is there and `would replace` when a file is, and exits without
  writing any of them. The hook paths come from `hooks.paths()`, the one
  computation the installers themselves use, so a preview names the files
  the real run touches. It covers every command line and not only the three
  that write into a repository: `--docs write` is previewed from a map built
  with no cache, `--specs` names `spec_map.json` and `spec_map.md` without
  running the tracker command, a line that only reads says `nothing to
  write: --ask only read` rather than answering and appending to the answer
  log, and `--install-hook claude` with `HOME` unset gives the refusal the
  real install gives instead of naming the home directory of whoever the
  passwd entry belongs to. A CI step lists the files of the tree and their
  hashes before and after a dry run of `--init`, `--agent-file`,
  `--install-hook git` and `--install-hook claude`, and then runs those
  commands for real to prove every path the preview named is a path the run
  creates.

## 1.4.0

- Honest edges. A cross-file call graph edge is written `charge (a.ts)` when
  one indexed file declares the callee, and `charge (a.ts|c.ts)?` when
  several do: the edge names every file that declares the name, sorted, and
  the question mark says the map is choosing between them rather than letting
  the reader take one file for a fact. Three calls that used to produce an
  edge no longer do or no longer guess: a plain call to a name the calling
  file declares itself is a local call and is left out of a cross-file
  graph; a call through a module this tree does not declare, which is what
  `ast.walk(...)` is, and what `from os import path` followed by
  `path.join(...)` is, is not in the tree at all and is left out too; and a
  call the caller's own `from MOD import name` (or
  `import { name } from "./mod"`) settles is written plain. `callers`,
  `callees` and `impact` match on the name alone, so a marked edge is found
  exactly as an unmarked one is, and print the mark as they find it. Every
  `impact` reply now ends its rules line with "an edge ending in ? names
  every file that declares the callee, because more than one does". Mapping
  the previous release's checkout with both releases, the marks under the
  same 60 keys go from 40 to 17, and `cli.py:main -> build (ask.py)?`, which
  pointed at the wrong `build`, is now `build (build.py)`. `--callers walk`
  on this repository's own map used to answer with eleven callers of
  `ast.walk` and `os.walk` and not one caller of a `walk` this tree
  declares.
- Numbers for the call graph, and for the tree it was read from. The build
  records `call_graph_stats` in `framework_map.json`: per language group
  (`python`, `ts_js`, `go`) how many callee names the walk looked at
  (`sites`), how many of those names some indexed file declares
  (`resolved`), how many several files declare (`ambiguous`), and then the
  graph itself, the cross-file edges written (`edges`) and how many carry the
  mark (`marked`). `resolution_rate` is `resolved / sites`, which says how
  first-party a tree's calls are: builtins, methods and standard library
  names are in its denominator and a same-file call is in its numerator, so
  it is a fact about the code rather than a score for the graph. On this
  repository it is 0.239 over 2230 Python sites, with 145 edges and 36 of
  them marked. `wawe-eval --map OUT --graph` prints all of it, and `--json`
  carries it. With the `precise` extra installed it parses the TypeScript,
  JavaScript and Go again with tree-sitter and prints the delta, which is
  where the pattern pass admits what it over-counted: on the poly fixture the
  regex sees 5 Go sites to tree-sitter's 2.

## 1.3.0

- `callees` (MCP), `--callees NAME`: what a function calls, the other
  direction of `callers`, from the two call graphs the map already holds.
- `impact` (MCP), `--impact NAME [--impact-depth N]`: every `file:func` that
  reaches a name within N hops, grouped by hop, cycles walked once, capped at
  200 entries. Every reply opens with the rules it was built under: hops are
  followed by name, only cross-file calls are in the graph, and the map keeps
  a bounded number of graph keys, so the radius is a floor.

## 1.2.0

Two ideas taken from Headroom (headroomlabs-ai/headroom), rebuilt for a map
that lives on disk.

- A cut answer carries a handle. Every tail line that says what was left
  out (`... 37 more matching rows`, `... 15 more definitions`, `... more
  sections match`, `find`'s "these are the 40 that rank highest") now ends
  with `(more:<kind>:<payload>)`, and a sixth tool, `more`, returns the next
  slice under the same whole-row, ceiling and tail rules, with its own
  handle when there is still more. `--more HANDLE` on the command line. A
  handle is a query, not a cursor: it is recomputed from the map on disk,
  carries the question percent-encoded so `pre-commit`, `page.click` and
  non-Latin words survive it whole, and answers `no such handle in this
  map` when the map has changed under it. A question longer than about
  forty percent of the budget cannot carry per-section handles; the note
  line still points at the section.
- `wawe-eval` measures what the budget loses, from the map itself: 100
  questions built from declared names, step words and heading words, each
  asked at no budget and at 350, 1500 and 12000 bytes; first-answer recall
  (macro), pooled recall, top-5 recall, rows over budget, and recall with
  handles after every `more` has been followed. At 1500 bytes and up, the
  MCP server's floor, recall with handles is 1.0 on every fixture; CI
  asserts it. `wawe-eval --agent` asks the same questions through the Claude
  API with the map tools and with grep, scores against `framework_map.json`,
  needs `ANTHROPIC_API_KEY` and the `eval-agent` extra, and is not run in CI.
- Six new golden cases with punctuated questions; 156 pinned answers.

## 1.1.3

- `--install-hook` installs as one unit. Every target is checked before
  anything is written, so a refused hook, rule file or settings file leaves
  nothing behind and the message names the cause; a rerun after the cause
  is fixed installs the rest. Until now `git` could stop after
  `post-checkout` and report `installed: post-checkout; ...`, which read as
  success while the map went stale on the first commit, and the cursor,
  gemini and codex pairs could leave their first file behind.
- A symlinked `mcp.json` or `settings.json` is refused as a symlink, not as
  "not valid JSON".

## 1.1.2

Three audits (concurrency, robustness, design) ran against 1.1.1; every
finding below was reproduced with a command before it was fixed and has a
live CI step that fails on the old code.

Maps that are never torn:

- Every artefact (`framework_map.{md,json}`, the brief, the HTML, the agent
  file, `spec_map.*`, `.wawe-cache.json`, `.pointer-head`, the semantic index)
  is written to a temporary and renamed into place; a reader never sees a
  zero-byte or half-written file, and a build killed mid-way leaves the
  previous map intact. Dead temporaries are swept at the next build.
- `build()` starts from nothing: module state is reset per build, so two
  repositories mapped in one process no longer share names, and `--watch`
  reports a constant `indexed` count on an unchanged tree.
- The fingerprint keeps sub-second mtimes and watches exactly the files the
  map indexes (an edited `.go` or `.rs` file no longer reads as "unchanged").
- `--force` reads nothing from the parse cache and rewrites it.
- `--watch` rebuilds whole every iteration, writes every artefact including
  `framework_map.md`, and survives an exception in one iteration.

Reads that are bounded:

- Every whole-file read goes through one bounded reader; a 198 MB source
  costs about 40 MB of memory instead of four copies of itself. A module
  larger than the parser cap is parsed on whole lines and named in
  `## This map is incomplete`.
- A symlink that resolves outside the repository is not read; a FIFO or
  device is skipped; a tree walk honours `WAWE_MAX_FILES` before any other
  pass, so `--repo /` terminates.
- Ignore rules never drop a path git tracks (`.gitignore` semantics), while
  `.wawe-ignore` always prunes.

Servers that stay up:

- MCP and LSP reply with a JSON-RPC error to malformed `params`,
  `arguments` or `limit` and keep serving; both exit quietly when stdout
  closes; a corrupt semantic index degrades to an answer without the tail;
  the embed cache uses WAL and degrades to "no cache".
- `file://` URIs are percent-encoded; `changed_since` reads git NUL
  separated so a path with a space or a rename comes back verbatim.

What goes into the map:

- Secrets are redacted by what a line says, not by six prefixes: PEM blocks
  as a whole, Stripe, OpenAI, Slack, GitHub, AWS, JWT and URL passwords by
  shape, and any value under a key naming a secret, password, token, key or
  credential. A commit sha, a Java path and a counter such as
  `max_tokens = 1000000` survive.
- `--html` escapes repository content.
- UTF-16 sources with a byte order mark are decoded and indexed; a binary
  that merely starts with one is not.

The command line:

- A missing map, an unwritable `--out`, `--agent-file` or `--init` target and
  a non-directory `--repo` say so in one line with a non-zero exit code.
- A narrow stdout encoding replaces characters instead of crashing.
- `--ask` answers from a spec map alone when that is all there is.

Hooks and the plugin:

- `--install-hook` refuses to write through a symlink and refuses cleanly
  when `HOME` is unset or unwritable.
- `--spec-source` keys are validated and quoted; a timed-out fetch kills its
  whole process group. `SPEC_ROOTS` cannot smuggle shell syntax.
- The plugin's SessionStart hook maps a repository that has no git, and
  `prefer-the-map.sh` no longer refuses a destructive `find`.
- `wawe-measure` skips a `tool_use` block without a usable name.

Layout (no map bytes change; import paths do):

- `where_are_we._mapper.cli` is now `where_are_we.cli`, with no stub at the
  old path. `where_are_we.mapper:main`, `python -m where_are_we.mapper`,
  running `mapper.py` by path, and `from where_are_we.mapper import main,
  init_manifest, install_hook, propose_docs` all keep working.
- `_definitions_for` lives in `where_are_we.ask` as `definitions_for`;
  `fingerprint` is the public name of `walk._fingerprint`. Both underscore
  names stay as aliases for one release.
- `from where_are_we.mapper import *` now exports the eleven shared-state
  names and `definitions_for`/`fingerprint`, and no longer exports `main`,
  `init_manifest`, `install_hook`, `propose_docs` (import those by name).
- `WAWE_NO_CACHE`, `WAWE_DEBUG_PARSES`, `WAWE_VOCAB`, `WAWE_ASK_LOG` and
  `WAWE_EMBED_CACHE` are read once at import; a process that sets one after
  importing keeps the value it started with.
- `extract.Ctx.code_files` is a tuple and `Ctx` is hashable; `Ctx.read` is
  the `extract.Read` protocol; a new extractor is registered in
  `extract.EXTRACTORS`.
- The import graph has no cycles and no deferred import that existed only
  to dodge one (`tests/golden/import_graph.py` proves it in CI). Extractors
  are registered in one list and assembled in one loop. `SCHEMA.md`
  documents every top-level key the map emits. Every environment variable
  the code reads is in one README table.
- CI: every negative assertion is an `if ...; exit 1` (a `! cmd` under
  `bash -e` never fails a step; 24 of them were inert).

## 1.1.1

- `--mcp`, `--ask`, `--pointer` and `--callers` started by a hook or the
  plugin (no `--repo`, the map under `<repo>/.wawe`) now resolve the
  repository from that directory, so a project's `.wawe.toml` `[synonyms]`
  reaches its MCP answers. Until now they fell back to `$AGENT_REPO` or
  `/work` and read another tree's config, or none.
- The Claude Code plugin's SessionStart hook passes `--repo`, so the pointer
  it hands the session names what changed since the last one; it also lists
  the fifth MCP tool, `callers`.
- The deb install check runs on Debian 13; Debian 12 carries Python 3.11,
  below the 3.12 floor.

## 1.1.0

- `wawe-measure` reads Claude Code's own transcripts and reports, per session,
  how many turns, searches, map calls and orientation turns it took, as a
  table or as `--json`.
- Every map answer is logged to `.wawe-ask.log` (`ask`, `find`, `defines`,
  `sections`, `callers`, from both the CLI and MCP); `wawe-measure --ask-log`
  summarises median, p95 and max tokens per answer.
- `--pointer` now names what changed since the last session: `changed_since`
  diffs the repository's git HEAD against the one recorded on the previous
  build.
- Unchanged files are no longer re-parsed on rebuild: a parse cache keyed by
  path, kind, mtime and size, bypassed with `WAWE_NO_CACHE=1`;
  `WAWE_JUNIT_DIRS` names where a project's JUnit history lives.
- Declarations for Rust, Kotlin, C# and Ruby, joining Python, TypeScript,
  JavaScript and Go; wired into the tree-sitter parse where installed, and
  the `## Defined here` section is now capped.
- The cross-file call graph covers TypeScript, JavaScript and Go, not only
  Python.
- `--callers NAME`, the MCP `callers` tool, and a `## Called by` block in
  `--ask`, answer who calls a name, cross-file only: a call from within the
  same file it is defined in is not counted.
- `--ask` expands synonyms and stems terms before matching; `.wawe.toml`'s
  `[synonyms]` table adds a project's own words to the built-in groups.
- `--install-hook` gained `cursor`, `codex` and `gemini`, each idempotent and
  each wiring its own MCP configuration.
- `--spec-source github|linear` reads tickets straight from GitHub issues or
  a Linear GraphQL query, instead of a custom `--spec-cmd` only.
- `--lsp` serves go-to-definition and workspace symbols from the map over the
  Language Server Protocol.
- A public demo page, built against FastAPI 0.115.0, under `docs/demo/`.
- A golden suite of 150 `ask` cases runs in CI (`tests/golden/check.py`),
  alongside a determinism check that two builds of the same tree produce
  byte-identical maps.
- No behaviour change; `mapper` is a package behind a facade.
- Python 3.12 or newer; 3.10 and 3.11 dropped.

## 1.0.0

The contract is fixed. What 0.12.3 does, 1.0.0 does, and every 1.x will:

- `framework_map.json` is schema `where-are-we/1`: sections may be added, a
  section that exists keeps its shape and meaning, a key is never renamed or
  removed (SCHEMA.md, "Stability").
- The CLI flags and the four MCP tools (`ask`, `find`, `defines`, `sections`)
  keep their names and meanings through 1.x; anything that must break bumps
  to 2.0.0.
- The pointer, the brief and the map files keep their names and places:
  `framework_map.md`, `framework_map_brief.md`, `framework_map.json`,
  `spec_map.md`, `spec_map.json` under `--out` (`.wawe/` for the plugin and the
  pre-commit hook).
- The README lists every feature with what it is measured to save, and says
  "not measured" where it is not.

No code changed between 0.12.3 and 1.0.0.

## 0.12.3

- `wawe-readmes` is a command: `--help`, `--repo` (default `$AGENT_REPO` or
  the current directory), `--write`. Until now it parsed no arguments - `--help`
  ran it, and with `AGENT_REPO` set it wrote READMEs into that tree without a
  word. The default is now to list what would be written; nothing is written
  without `--write`.

## 0.12.2

Plugin fixes from the first install through the marketplace.

- `.wawe/` ignores itself: the hook writes `.wawe/.gitignore` instead of
  editing the repository's `.gitignore`, and a repository without one stays
  clean in `git status` too.
- The pointer says what it is a map of - "this repository" unless the map has
  step modules and feature files - and its size counts the brief, so a code
  repository no longer reads "(0 KB) map of this suite".
- The `v1` tag the GitHub Action example pins to now exists and moves with
  each release; the pre-commit example pins the current version.

## 0.12.1

A code repository gets a real map, and Claude Code gets a plugin.

- `--ask`, `--sections`, `--pointer` and the MCP `sections` read the brief's
  sections as well as the map's. For a behave suite nothing changes; for a
  plain code repository the map file was a three-section skeleton and the
  seventy sections that matter - entry points, routes, data model, public
  surface - sat in `framework_map_brief.md` where no question reached them.
- The product under test is guessed from sibling directories only when the
  repository is a test suite (a steps directory or a feature file). A code
  repository mapped from a directory of other projects had indexed its
  neighbours as the product. `--product none` switches the guess off.

- A Claude Code plugin in `plugin/`: a SessionStart hook that builds the map
  and hands the session its pointer, the map's tools over MCP, five skills
  (`orient`, `ask`, `where-defined`, `spec-map`, `readmes`), and an opt-in
  strict mode (`WAWE_STRICT=1`) that refuses repository searches while a map
  exists. Install: `/plugin marketplace add ngavrish/where-are-we`.

## 0.12.0

Answers end on whole rows and say what they left out.

- `--ask` and the MCP `ask` no longer slice a section at a character count:
  rows are whole, and a section that did not fit ends with how many matching
  rows were dropped and how many rows did not match at all.
- In an answer, consecutive rows under one directory are printed under it
  once. Rendering only; the map on disk keeps full paths.
- `--max-lines` caps the brief per section — every section keeps its head and
  up to its share of rows (none, under a cap too small to hold them), then
  says how many more are in `framework_map.md` — instead of dropping
  whatever came after line N.
- Bold `**…**` lines in a section are structure, not rows: they are neither
  shown in an answer nor counted as rows that did not match; a
  `- **label**: value` row matches only if it mentions the words.
- Internal: answering moved to `where_are_we/ask.py`; `mapper.ask` is a re-export.

## 0.11.2

Packaging only. The rpm job's "attach to the release" step ran `gh` inside a
fedora container whose checkout git cannot discover, so it died on "not a git
repository". Every `gh release` call now names the repo with `-R`, needing no
local git; the deb job matches for symmetry.

## 0.11.1

Packaging only, no code change to the tool.

- The deb now ships every module. It packaged only `mapper`, `readmes` and
  `__init__`, but `__init__` imports `mapper` and `mapper` imports `specs`,
  `semantic` and `mcp`, so the deb smoke test died on a missing-module import
  on every release since these modules were added.
- The rpm "attach to the release" step marks the container checkout as a safe
  git directory, fixing "not a git repository" when `gh` runs as root in the
  fedora image.
- `__version__` catches up to the packaged version.

## 0.11.0

A vector never changes for the same text and model, yet every run rebuilt its
index from scratch: five and a half of the six minutes of a full five-corpus
build were recomputing vectors computed the run before.

- `WAWE_EMBED_CACHE` names a sqlite file (stdlib, one file, its own locking)
  where embeddings are cached across runs, keyed by model and text hash. Unset
  keeps the old behavior byte for byte.
- `build_index` creates its out_dir instead of crashing on `np.save`.
- Running `mapper.py` by path works again: the local imports added since 0.8
  (`readmes`, `semantic`, `mcp`) now carry the same try-relative-then-plain
  fallback the top of the file always had.

## 0.10.0

A product tree handed over as `--corpus` is code, and "which component renders
the values dropdown" is the question a UI session pays twenty Reads to answer
without it.

- The corpus walk takes doc AND source extensions, skips dependency and build
  directories, and caps file size so a bundle or lockfile cannot flood the
  index. Chunking by blank lines works on source the way it works on prose.
- The "Related by meaning" tail moved into a shared helper: the MCP `ask` now
  appends it too, not only the CLI `--ask` branch.

## 0.9.0

The keyword ask answers when the asker knows the words the map used; the
sessions that pay the most only know their own words.

- A local embedding index closes the gap: fastembed's ONNX models on CPU
  (bge-small for recall, a MiniLM cross-encoder for precision on top), the
  index two flat files beside the map - at thousands of chunks a numpy dot
  product IS the vector database. Built after every map write, skipped by
  content hash, absent without complaint when the `[semantic]` extra is not
  installed.
- `--corpus NAME=PATH` indexes external corpora (a rules directory, a runbook)
  into the same answers; `--ask` grows a "Related by meaning" tail
  deduplicated against the keyword hits.
- `--ask` takes every question at once instead of one call per turn, a batch
  shares one budget, and sections are ranked by BM25 rather than raw word
  counts.
- `cluster()` greedy-folds failure messages for triage prefilters.

## 0.8.0

Half of what an agent searches for is text, not a name. Watched over one run: a
hundred and sixty-six searches by hand, of which eighty-six were names — which
the declaration index answers — and seventy were phrases like `"second Portal
tab"` or a label `"A 15"`, which it could not answer at all.

- `find(phrase)` returns every line holding that text, with file and line. The
  walk already opens every file; keeping the lines turns a repository-wide grep
  into a lookup.
- The line index lives in `framework_map.json` and never in the Markdown, so it
  is read by the tool and cannot end up in a prompt: 1.7 MB of lines beside
  178 KB of map.

## 0.7.0

Asking the map through a shell puts the question and the whole answer into the
conversation, where they are re-read on every turn after — and the agent has to
remember what the command is called, which one of them did not: it spent a turn
on `which where-are-us where-are-we`.

- `--mcp` serves the same index over MCP on stdin/stdout: `ask`, `defines`,
  `sections`. The question is an argument, the answer is a tool result. Same
  regexes, same JSON, no model and no network — JSON-RPC on a pipe, written on
  the standard library like the rest of this.

## 0.6.0

The map indexed the language of the test suite and nothing else, and said so in
the worst possible way. Asked where a constant was defined — line 31 of the
product, plainly there — it answered that this was "a real absence rather than a
search that missed". The agent believed it, rephrased three times, and spent the
next forty turns grepping by hand. It was right to.

- Every name in every file, with the line it is declared on: a table of
  declaration shapes per language, and a general shape for the rest, applied to
  whatever the walk finds. On a real product: 2343 names from 137 files, where
  the previous version had none.
- The map records what it indexed, and a "not found" now says where it looked.
  A map that overstates its reach turns "I did not look" into "it is not there",
  and the reader stops looking too.

## 0.5.1

A limit that stops quietly produces a map that looks complete and is not, and an
absence in a silent map reads as a fact about the codebase.

- Both walks name what they left out, at the top of the map: the tracker walk
  already did, the file walk did not and silently stopped at 40000 files.
- `--spec-limit` is a flag rather than a constant, beside `--spec-depth`.

## 0.5.0

A codebase is not the only thing an agent gropes around in. The other is the
tracker, and it gropes there for the same reason: no map, so it asks, and asks
again. On one run of a real pipeline sixteen tickets were fetched over and over —
one agent pulled fourteen neighbours, the next pulled the same fourteen again,
three were fetched three times inside a single session — and every answer then
sat in a context for ever, paid for on every later turn.

- `--specs KEY[,KEY]` with `--spec-cmd 'your-fetcher {key}'` walks the tracker
  once, two hops out, into `spec_map.json` and `spec_map.md`. This tool learns
  nothing about any tracker: it is handed a command that turns a key into JSON.
- Links are read out of the whole document rather than out of a schema's link
  fields — a key mentioned in a comment is a link somebody made on purpose.
- `--ask` answers from both maps: a question about a piece of work is as likely
  to be about what was asked for as about where the code is.

## 0.4.1

- `--for author|coder`. The vocabulary is what a scenario is written in, so the
  author writing scenarios gets all of it (64k tokens here) and the coder
  changing what it runs against does not (30k) — that context is worth more to
  them as room to work than as fourteen hundred phrases.
- The vocabulary is no longer capped by default: whole-map arithmetic favours
  carrying it, since one turn spent grepping for a phrase re-reads the entire
  context twice.

## 0.4.0

- The brief carries the vocabulary, not a count of it. It used to say "this
  module declares 211 steps" and leave the 211 in a file beside it, so the
  agents writing scenarios spent a hundred and forty-nine turns grepping for
  words they were entitled to be handed. Now: behave phrases, cucumber glue in
  any language, Robot keywords, pytest fixtures and page-object methods, in one
  section, capped by WAWE_VOCAB (700 by default) with the rest in the full map.

## 0.3.1

- An hour to nine seconds. The "interesting line" sections matched with patterns
  shaped `.*(?:a|b|c).*`, which makes the engine try every position of every
  line of every file; a substring test gives the same answer. On the repository
  this was written for the map had been running for an hour and the run it was
  meant to help never started.

## 0.3.0

- Lock files (what is actually installed), the status codes each file returns,
  the services this code calls out to, Kubernetes probes, resources and
  replicas, the asset inventory, which schema belongs to which topic, where
  feature flags are branched on, assumptions about time and locale, the
  functions carrying the complexity, and blocks of code that appear more than
  once.

## 0.2.0

- Every remaining ecosystem: Elixir, Dart, Groovy, Clojure, Haskell, Lua, Perl,
  Julia, Objective-C, Solidity; Vue, Svelte, Angular, Storybook; dbt, Airflow,
  Spark, notebooks; AsyncAPI, JSON Schema, Avro, Thrift, SOAP, tRPC, Pact;
  CloudFormation, Pulumi, Bicep, Ansible, Chef, Puppet; Jenkins, CircleCI, Azure
  Pipelines, Travis, Buildkite, Drone; Gradle, Maven, Bazel, sbt, CMake, Rake;
  MongoDB, Elasticsearch, DynamoDB, Cassandra, ClickHouse, NATS, Pulsar, MQTT;
  Prometheus rules, Grafana dashboards, OpenTelemetry, OPA, flag platforms;
  JMeter, Locust, Artillery; test data factories.
- Indexes and constraints, generated code, declared types, environment per
  service, retries/timeouts/breakers/limits, transactions and idempotency,
  logging levels, contribution templates, license headers.
- `.wawe.toml` for defaults, `--also` to fold several repositories into one map,
  `--watch`, `--html`, `--only`, `--skip`, `--max-lines`, `--diff`.
- A parse cache that survives between runs, and redaction of anything shaped
  like a credential before it reaches a file.

## 0.1.0

First release.

- Indexes any codebase into `framework_map.{json,md}` and a brief for a prompt:
  languages, entry points, HTTP routes, data model, public surface, import and
  cross-file call graphs, queues, gRPC, schedules, Kubernetes, Terraform, cache
  keys, permissions, observability, error types, CLI, frontend, contracts
  (OpenAPI, GraphQL, migrations, mocks, flags, i18n), ADRs, coverage, hotspots,
  licenses, git history, blame owners, deprecations and documentation drift.
- Test suites across behave, pytest, jest, playwright, cypress, robot, JUnit,
  TestNG, Cucumber in Java, Kotlin, Scala, TypeScript, JavaScript and Ruby,
  rspec, go test, xUnit, NUnit, SpecFlow, PHPUnit, Behat, Rust, XCTest, karate,
  gauge, k6 — plus the suite's own state: overlapping phrases, unused steps,
  dead page-object methods, admitted debts, quarantine and past-run timings.
- `--init` writes a manifest a repository can correct; what it states wins.
- `--install-hook git|agent`, `--agent-file`, `--only`, `--skip`, `--max-lines`,
  `--diff`, `--force`, `.wawe-ignore`.
- Rebuilds only when the tree has moved; JSON contract versioned as
  `where-are-we/1` and documented in `SCHEMA.md`.
