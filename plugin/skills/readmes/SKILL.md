---
name: readmes
description: Use when a repository's directories have no README or a stale one and the next reader (human or agent) would have to infer what each directory is for - the map already knows, and wawe-readmes drafts the docs it is missing.
---

# Offer the repository the docs it is missing

`wawe-readmes` reads the map and writes, per directory that lacks one, a draft
README saying what the directory holds, what its public surface is, and how it
is entered - from the map's facts, not from guesses.

    where-are-we --repo . --out .wawe --docs plan     # list what would be written, nothing changes
    where-are-we --repo . --out .wawe --docs write    # write the drafts

(The `wawe-readmes` command exists but takes no arguments and writes into
`$AGENT_REPO` at once; prefer the two lines above.)

- Run `--plan` first and read the list; a directory that is deliberately
  undocumented (vendored code, generated output) should be excluded with
  `.wawe-ignore` before `--write`.
- Every draft carries a `TODO:` line for the one sentence only a human knows -
  the purpose. Fill those in; the rest is measured.
- Drafts are ordinary files: review them in the diff like any other change.
