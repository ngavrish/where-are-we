---
name: orient
description: Use at the start of work in an unfamiliar repository, or when you catch yourself running ls/find/grep to learn where things are - the map already knows; build or refresh it, read the pointer, and ask it instead of exploring.
---

# Orient with the map

A session in a repository it has not seen spends its first turns rediscovering
it: `ls`, `find`, `grep`, `cat conftest.py`. Measured on a real suite, that was
forty turns before the first line of work. The map replaces those turns with
one question.

## What exists

`.wawe/framework_map.md` is a generated map of this repository: layers, entry
points, routes, data model, step phrases, scenarios, fixtures, CI, duplicates,
dead code, and every declared name with its line. It is built at session start
by this plugin and rebuilt after a commit. It is on disk on purpose: **read from
it, never carry it** - the whole file is 100+ KB and would ride along in every
message after you open it.

## How to use it

1. The pointer in your context says which sections the map has. Trust it over
   your instinct to look around.
2. Ask before you search. Every question about the repository goes to the map
   first, through the MCP tools of the `where-are-we` server:
   - `ask(words=[...])` - the rows that mention those words, whole, section by
     section, with a count of what was left out.
   - `defines(name=[...])` - where a name is declared, with the line.
   - `find(phrase=[...])` - where a phrase (a step, a string) lives.
   - `sections()` - the section headings.
   All take lists: ask for everything you need in one call.
3. `grep` on `.wawe/framework_map.md` is fine; `Read` of the whole file is not.
4. If the map says `## This map is incomplete`, believe it: a bound was hit
   (file count, depth), and what is below the bound is not mapped. Raise
   `WAWE_MAX_FILES` or add a `.wawe-ignore` before concluding something is
   absent.

## When to rebuild by hand

The hook rebuilds when HEAD moved since the last build. After large uncommitted
changes, rebuild yourself - one tree walk, seconds, offline:

    where-are-we --repo . --out .wawe --quiet

## What the map is not

It is not the code. A row gives you the file and line; open that, not the map.
And an absence in an answer means "not indexed", which the answer says, not
"does not exist".
