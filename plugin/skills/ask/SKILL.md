---
name: ask
description: Use when you have a question about this repository - where something is, what calls what, which scenarios cover a feature, what is slow or duplicated - and are about to grep for it; ask the map with words and read the tail that says what was left out.
---

# Ask the map

`ask(words=[...])` on the `where-are-we` MCP server (or `where-are-we --out
.wawe --ask "words"` on the command line) returns, for each section of the map
that mentions your words, the rows that mention them - whole rows, never cut
in the middle - and ends each section with what it left out:

    … 3 more matching rows; 41 rows in this section do not mention these words

## Ask well

- **Words, not sentences.** The map matches words. `refund settled invoice`
  finds more than "how is a settled invoice refunded".
- **One call, several questions.** `words` is a list: `["refund", "invoice
  settled", "MAX_RETRIES"]` is one round trip, three answers.
- **Names go to `defines`, phrases go to `find`.** `ask` ranks sections;
  `defines(name=[...])` answers "where is X declared" with a line, and
  `find(phrase=[...])` answers "where does this step / string live". Use the
  narrower tool when you have a name.
- **Read the tail.** "12 more matching rows" means ask again with more words
  or open the section in `.wawe/framework_map.md`; "did not match" rows are
  the section's other content, not misses.
- **An answer with `## Defined here`** is the definitive location; go there.
- **"no match for … indexed: …"** says what was searched. It is not a claim
  that the thing does not exist - the walk has bounds.

## Do not

- Do not `Read` the whole map to "get an overview": the pointer already lists
  the sections, and `sections()` repeats them.
- Do not fall back to `grep -r` over the repository when the map answered
  little; ask with other words first, then grep the map file, then the
  repository - in that order.
