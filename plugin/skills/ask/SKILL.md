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
- **Names go to `defines`, phrases go to `find`, lines go to `at`.** `ask`
  ranks sections; `defines(name=[...])` answers "where is X declared" with
  every home and its span, `at(place=["f.py:147"])` answers "what is this line
  inside" with the whole definition, and `find(phrase=[...])` answers "where
  does this step / string live". Use the narrower tool when you have a name.
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
