# 1.4.1: receivers the map can resolve without types

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. No `tests/test_*.py` files (a global hook forbids the model writing tests): every behaviour is proven by a live command in the report and a step in `.github/workflows/ci.yml`; the golden suite (`tests/golden/check.py`) stays byte-identical in `expected/` unless the commit message explains the moved lines.

**Goal:** After 1.4.0 the surviving `?` marks on this repository are 20 of 60 keys: 15 `x.add(...)` calls whose receiver is a set built in the same function, and 5 `mapper.build(...)` / `mapper.digest(...)` calls whose receiver is a first-party module that re-exports the name from another file. Neither needs a type checker. This release resolves both, plus `self.x()` inside a class, and closes the two minors from the 1.4.0 re-review.

**Architecture:** all changes sit in the Python resolving pass of `src/where_are_we/_mapper/build.py` (the `aliases` / `mods` / `_module_target` / `_module_is_here` helpers built in 1.4.0) and, for the re-export chain, one pass over the target module's own `from X import name` / `from .x import name` lines. Nothing changes in the ts/js/go regex pass. Schema `where-are-we/1` unchanged; `call_graph_stats` keys unchanged.

**Global constraints:** stdlib only; deterministic output; Python 3.12+; no em dashes or en dashes in new prose; CI negations as `if cmd; then exit 1; fi`; commit trailers `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01Qt2xWwtUxwkeWyJt5hHgi7`; comments say what is there, not what changed.

---

### Task 1: re-export chains

`hooks.py:_ensure_map` calls `mapper.build(...)`. `mapper` is bound by `from . import mapper` (or `import where_are_we.mapper`), resolves to `src/where_are_we/mapper.py`, an indexed file that does not declare `build` but has `from ._mapper.build import build`. Today the edge is the candidate list `build (ask.py|build.py)?`.

Rule: when the receiver resolves to exactly one indexed file F and F does not declare `name`, look at F's import lines once (cached per file for the build): a `from M import name` or `from M import name as alias` whose M resolves (relative to F) to one indexed file G that declares `name` gives the edge `name (G)` unmarked. Follow at most 3 hops (F -> G -> H) so a chain of facades resolves; a cycle or a hop that resolves to nothing falls back to the candidate list as today. `__init__.py` files are files like any other, so `from pkg import mod` + `mod.f()` where `pkg/mod.py` is a facade works the same way.

Proofs (report + CI step "a re-export resolves to the file that declares the name"): fixture `facade.py: from impl import build`, `impl.py: def build`, `other.py: def build`, `caller.py: import facade; facade.build()` gives `build (impl.py)` unmarked; a two-hop chain resolves; a cycle (`a.py: from b import f`, `b.py: from a import f`) with `f` declared in `c.py` and `d.py` gives `f (c.py|d.py)?`; on this repository `hooks.py:_ensure_map -> build (build.py)` and `digest (render.py)` are unmarked and `--callers build` lists `hooks.py:_ensure_map`.

### Task 2: receivers bound in the same function, and `self`

Two more receiver shapes the AST settles without types:

- A receiver name assigned in the same function (or as a parameter default) to a builtin constructor call or literal: `x = set()`, `x = {}`, `x = []`, `x = dict()`, `x = list(...)`, `x = ""`, `x = f"..."`, `x = 0`, a set/list/dict comprehension, `x = collections.defaultdict(...)` / `Counter(...)` / `deque(...)` when that name is bound by a stdlib import. The call `x.add(...)` then goes to a builtin type, not to the first-party `add`: no edge, not marked. If the same name is assigned more than once in the function and any assignment is not one of those shapes, keep today's behaviour (the mark).
- `self.name(...)` and `cls.name(...)` inside a method of class C: if C (or a base named in the same file, one hop) declares `name`, the call is local: no edge. If C's bases are all in other indexed files and exactly one of them declares `name`, edge `name (that file)` unmarked. Otherwise the mark as today.

Proofs (report + CI step "a receiver the function itself built is not a first-party call"): fixture with `def g(): out = set(); out.add(1)` and `def add` declared in two files gives no edge and `marked 0`; `out = make(); out.add(1)` still gives `add (a.py|b.py)?`; `class C: def add(self): ...; def g(self): self.add()` with `add` in two other files gives no edge; `class D(Base)` with `Base.add` in `base.py` gives `add (base.py)`; on this repository the marked count reaches 0 of 60 keys or the report lists each survivor with its receiver and why it stays; `call_graph_stats.python.marked` and the README numbers are re-measured and dated 2026-09-07.

### Task 3: the two minors from the 1.4.0 re-review, and the release

- `_module_is_here`'s directory fallback matches on basename at any depth, so `tests/fixtures/logging/` with any `.py` in it makes `import logging; logging.info()` keep a marked edge to a first-party `info`. Tighten: when only the fallback matched, require that a candidate home of the callee lies under that directory; otherwise refuse. Proof: fixture `tests/fixtures/logging/x.py` (declares nothing named `info`) + `import logging; logging.info()` + `info` declared in two first-party files: no edge; vendored `requests/__init__.py` declaring `get` + `requests.get()` still resolves to the vendored file unmarked.
- CHANGELOG lines wrapped at 77 like the rest of the file.
- Version 1.4.1 in `pyproject.toml`, `src/where_are_we/__init__.py`, `plugin/.claude-plugin/plugin.json`; CHANGELOG 1.4.1 entry; README honesty rows and the graph section updated with the re-measured numbers; SCHEMA.md `call_graph_files` row names the three receiver rules; plugin skill `where-defined/SKILL.md` unchanged unless an example moved.
- Gates: `python3 tests/golden/regen.py` then `check.py` (expected byte-identical; maps regenerated only if stats moved), `python3 -m pytest tests -q`, `python3 tests/golden/import_graph.py`, the SCHEMA coverage script from CI, every new and existing graph CI step under `bash -e -o pipefail`, dash gate on added lines.

### Task 4: an effects manifest, so a guard can tell a read from a write

A user asked for HOL Guard support (an open-source pre-execution check for agent commands). Guards classify commands by argv; today they would have to guess which of this tool's flags write. Ship the answer with the tool.

- `src/where_are_we/effects.py` holds one table, `EFFECTS`: every command line flag (from `cli.py`'s parser, checked by a CI step that every flag the parser knows is in the table and nothing else is) mapped to one effect class: `read` (`--ask`, `--sections`, `--callers`, `--callees`, `--impact`, `--more`, `--mcp`, `--lsp`, `--pointer`, `--watch` reads plus the build), `writes-map-dir` (`--out`, `--html`, `--force`, `--watch`), `writes-repo` (`--agent-file`, `--init`), `writes-config` (`--install-hook`, per target: git writes `.git/hooks`, claude writes `~/.claude`), `network` (`--spec-source`). A command's class is the highest class any of its flags carries, in the order read < writes-map-dir < writes-repo < writes-config < network.
- `where-are-we --effects` prints the table as text; `--effects --json` prints `{"schema": "where-are-we-effects/1", "flags": {...}, "order": [...]}`; `--effects -- <argv...>` classifies one command line and exits 0, printing the class and the flags that gave it. The same JSON is installed as package data `effects.json` (built from the table at packaging time or checked identical in CI).
- `--dry-run` with `--agent-file`, `--init` or `--install-hook` prints every path the command would create or replace and exits 0 without writing (hooks: the three hook files and the settings file; `--init`: the manifest path; `--agent-file`: the file). A CI step proves the tree is byte-identical after a dry run (hash before and after).
- README: one section "What writes and what only reads", the table, the `--dry-run` line; SCHEMA.md untouched (not a map key). CHANGELOG 1.4.1.
- Proofs: `--effects -- where-are-we --out /tmp/m --ask x` prints `writes-map-dir`; `... --install-hook git` prints `writes-config`; `... --mcp` prints `read`; the parser/table cross-check step fails when a flag is added to one and not the other (prove by a temporary edit in the report, then revert).
