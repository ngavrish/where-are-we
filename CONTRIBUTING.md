# Contributing

## The shape of a change

A new section is a function of the tree and nothing else: no model, no network,
no guessing. If it cannot be derived from files, it does not belong in the map.

Sections are added, not renamed: `framework_map.json` is a contract
([SCHEMA.md](SCHEMA.md)) and something depends on every key in it.

An empty section means the repository has none of that. Do not invent a
placeholder.

## Where things are

`src/where_are_we/mapper.py` is a facade: the docstring, the re-exports, and
the module subclass that forwards the shared state. Everything it exports lives
in `src/where_are_we/_mapper/`, seven jobs in seven places:

- `state.py`: the indexes and caches that live for the length of a process.
  Nothing else keeps module-level state, so there is one place to reset.
- `walk.py`: which files are in this repository, what they say, whether they
  changed since the last build. The ignore rules, the file and walk caches, the
  parse cache, `.wawe.toml`, the manifest, redaction.
- `declare.py`: what a file declares and on which line, by regex table or by
  tree-sitter where a grammar is installed. The line index and the phrase
  search over it.
- `extract/`: the map topics that are a function of the file list alone. An
  extractor is one file, one topic, one `(ctx) -> dict`: it gets the repository
  root, the code files and a reader, hands back the sections it owns keyed the
  way `framework_map.json` names them, and can reach nothing else. A new topic
  of that shape goes here, not into `build()`.
- `build.py`: the one walk that assembles the map dict, and every topic that is
  not the shape above. It is long on purpose: its sections share more than a
  hundred locals, and several extend a value an earlier section built.
- `render.py`: map dict to Markdown, and the lookups (`pointer`, `ask`'s
  definitions, `changed_since`) that read a map somebody already wrote.
- `cli.py`: argv, stdout, and the two things the tool writes into a repository.

Import from `where_are_we.mapper`, never from `where_are_we._mapper`: the
facade is the interface, and the underscore says the layout behind it may move.

## Adding support for a framework

1. Detect by shape first, by convention second, by directory name last.
2. Answer the same three questions the others do: where the cases live, what
   they are called, what binds a phrase to code.
3. Add a case in `tests/` that builds a small repository and asserts the map
   names what is in it.

## Running it

```bash
pip install -e . pytest
pytest tests -q
where-are-we --repo . --out /tmp/self && head -40 /tmp/self/framework_map_brief.md
```

## Pull requests

CI runs the tests, maps the tool with itself, maps a polyglot fixture, and
checks that a second run reports the map unchanged. Keep all four green.
