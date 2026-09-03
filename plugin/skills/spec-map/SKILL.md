---
name: spec-map
description: Use when the work is about a ticket - its acceptance criteria, its parent, what it links to or mentions - and you would otherwise fetch the tracker page by page; build the specification map once and ask it like the code map.
---

# The other map: the specifications

A codebase is not the only thing an agent gropes around in; the tracker is the
other, and it gropes there the same way: no map, so it asks, and asks again.
`where-are-we` builds a second map from a ticket and writes `spec_map.md`
beside the code map; `ask` then answers from both.

## Build it

The tool knows nothing about any tracker. You hand it a command that turns a
ticket key into JSON, and it walks the links two hops out:

    where-are-we --repo . --out .wawe \
      --specs APF-1934 \
      --spec-cmd 'my-tracker-cli issue get {key} --json'

`{key}` is substituted per ticket. `--spec-depth` (default 2) bounds the walk,
`--spec-limit` bounds the count. What the bound cut is named at the top of the
map under `## This map is incomplete`.

Any source works: Jira, Linear, GitHub Issues (`gh issue view {key} --json
title,body,comments`), a directory of text files.

## Ask it

Once built, the same `ask(words=[...])` answers from the code map and the spec
map together, because a question about a piece of work is as likely to be
about what was asked for as about where the code is. Ask with the ticket's own
words - the feature name, the field, the error message the reporter quoted.

## Keep it fresh

The spec map is not rebuilt by the session hook (it needs your tracker
command). Rebuild it when the ticket changes.
