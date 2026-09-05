"""The package's own import graph, and the cycles in it.

A cycle between modules is not a style question here. It is what forced eleven
imports in this package to be written inside functions: `mapper` re-exported
the command line, the command line imported `ask`, `hooks`, `lsp` and `mcp`,
and each of those imported `mapper` back, so whichever module was imported
first found a half-built one on the other side and raised "cannot import name
from partially initialized module". The workaround was to defer the import to
call time, and one of those deferrals carried a fourteen-line comment
explaining itself.

So the graph is measured instead of argued about. Only imports that run at
module level are edges: those are the ones that execute while a module is
still being built, and so the only ones that can produce that error. Imports
inside a function or a method run after everything has finished loading and
are listed separately, with the module they pull in, so that a new one has to
be looked at rather than slipped in.

Run: `python tests/golden/import_graph.py` (add `--verbose` for every edge).
Exits 0 when there are no cycles, 1 and names each cycle otherwise.
"""

import argparse
import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "where_are_we"
PKG = "where_are_we"


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([PKG] + parts)


def _modules() -> dict:
    return {_module_name(p): p for p in sorted(SRC.rglob("*.py"))}


def _resolve(node, here: str, known: set) -> list:
    """The modules of this package that one import statement names.

    Both spellings count: the relative one a packaged run uses, and the plain
    one `python src/where_are_we/mapper.py` falls back to, which names the
    same file from a different root.
    """
    out = []
    if isinstance(node, ast.Import):
        candidates = [a.name for a in node.names]
    else:
        base = node.module or ""
        if node.level:
            parts = here.split(".")[:-1]
            parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
            base = ".".join(parts + ([base] if base else []))
        elif base:
            base = f"{PKG}.{base}"
        candidates = [base] + [f"{base}.{a.name}" for a in node.names if base]
    for name in candidates:
        if not name:
            continue
        if name.endswith("__init__"):
            name = name.rpartition(".")[0] or PKG
        if name != PKG and not name.startswith(PKG + "."):
            name = f"{PKG}.{name}"
        # Walk up to the nearest module this package actually has, but never
        # as far as the package itself: `import os` is not an edge to
        # `where_are_we` just because nothing called `where_are_we.os` exists.
        while name.count(".") and name not in known:
            name = name.rpartition(".")[0]
        if name in known and name != here and (name != PKG or PKG in candidates
                                               or f"{PKG}.__init__" in candidates):
            out.append(name)
    return out


def graph() -> tuple:
    """`(edges, deferred)`: module-level imports, and function-local ones."""
    mods = _modules()
    known = set(mods)
    edges: dict = {name: set() for name in mods}
    deferred = []
    for name, path in mods.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        inner = set()
        for parent in ast.walk(tree):
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(parent):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        inner.add(id(node))
                        for target in _resolve(node, name, known):
                            deferred.append((name, target, parent.name, node.lineno))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in inner:
                edges[name].update(_resolve(node, name, known))
    return edges, sorted(set(deferred))


def cycles(edges: dict) -> list:
    """Every simple cycle, each written from its alphabetically first module
    so one cycle is reported once rather than once per member.

    Every distinct loop is listed, not one per strongly connected component:
    `mapper -> cli -> ask -> mapper` and `mapper -> cli -> hooks -> mapper`
    are two different reasons an import has to be deferred, and a fix that
    removes one and leaves the other has not finished.
    """
    found = set()
    order = sorted(edges)

    def walk(start, node, path, on_path):
        for nxt in sorted(edges.get(node, ())):
            if nxt == start:
                found.add(tuple(path))
            elif nxt not in on_path and nxt > start:
                walk(start, nxt, path + [nxt], on_path | {nxt})

    for node in order:
        walk(node, node, [node], {node})
    return sorted(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true",
                    help="print every module level edge and every deferred import")
    args = ap.parse_args()
    edges, deferred = graph()
    n_edges = sum(len(v) for v in edges.values())
    if args.verbose:
        for name in sorted(edges):
            for target in sorted(edges[name]):
                print(f"edge     {name} -> {target}")
        for src, target, func, lineno in deferred:
            print(f"deferred {src} -> {target} (in {func}, line {lineno})")
    loops = cycles(edges)
    for loop in loops:
        print("cycle: " + " -> ".join(loop + (loop[0],)))
    print(f"import graph: {len(edges)} modules, {n_edges} module level edges, "
          f"{len(loops)} cycles, {len(deferred)} deferred imports")
    return 1 if loops else 0


if __name__ == "__main__":
    sys.exit(main())
