# Contributing

## The shape of a change

A new section is a function of the tree and nothing else: no model, no network,
no guessing. If it cannot be derived from files, it does not belong in the map.

Sections are added, not renamed: `framework_map.json` is a contract
([SCHEMA.md](SCHEMA.md)) and something depends on every key in it.

An empty section means the repository has none of that. Do not invent a
placeholder.

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
