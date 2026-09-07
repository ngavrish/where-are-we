---
name: rank
description: Use at the start of work in an unfamiliar repository, or before deciding what to read next while editing a set of files - the map ranks its own definitions by how much of the codebase reaches them, and takes the files you are in so the answer is about your change rather than about the repository in general.
---

# What matters here, and what matters given these files

`ask` and `find` answer "where is this word". They cannot answer "what should I
read", because importance is a property of the call graph rather than of the
text, and a name nothing calls reads exactly like a name everything calls.

`rank()` answers it. Files are nodes; an edge runs from a file that uses a name
to the file that declares it, weighted by how often; PageRank over that graph
puts the definitions the repository is built around at the top.

    rank(limit=10)

returns one line per definition, best first:

    0.043907032 build /repo/src/where_are_we/_mapper/build.py:243
    0.043129010 build /repo/.github/workflows/ci.yml:1280
    0.040425929 find_text /repo/src/where_are_we/_mapper/declare.py:97

## Use it two ways

- **Opening an unfamiliar repository.** `rank(limit=10)` before anything else.
  Those ten files are what the rest of the tree points at; read them and the
  next answer means something. This is the same list the map stores under its
  `rank` key, so it costs one call and no build.
- **Deciding what to read next.** `rank(files=["billing/refund.py"])`
  personalises the walk on the files you are editing: the ranking becomes what
  is worth reading *given that change*, which is a different list and the one
  you actually want. A directory prefix works: `files=["billing/"]`.

`words=[...]` weighs the identifiers in your question ten times, so
`rank(files=["billing/"], words=["refund"])` asks both halves at once.

## Read it right

- **A score of 0 means nothing in the map reaches that definition.** That is an
  answer - a dead entry point, or a name the graph could not resolve - not a
  gap in the ranking.
- **The same name in six files ranks low on purpose.** A name more than five
  files declare is weighted down by ten: `run`, `main` and `setup` are words,
  not definitions. So is a leading underscore.
- **It is a ranking, not a search.** Do not use it to find a name you can
  already spell; `defines(name=...)` is one lookup and this is two hundred
  rows. Use it when you do not yet know what to ask for.
- **A row can be a declaration the map got wrong.** The second row above is a
  `def build` inside a heredoc in a CI workflow. The ranking reports what the
  declaration index holds; check the file and line before you believe a row
  that reads oddly.
- **The graph is the map's graph.** It sees the files the walk indexed and the
  names it declared, so `## This map is incomplete` bounds this answer too.

Pair it with `ask(words=[...], files=[...])`, which takes the same file list
and prints the rows about those files first inside every section.
