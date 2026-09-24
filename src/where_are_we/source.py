"""The indexed files' text, read from the repository the map describes.

A map used to carry a copy of every line it indexed. It was written that way so
a phrase search would be a lookup in one parsed file rather than a walk, and it
made framework_map.json most of its own size: on one checkout indexed beside
its product repo the file came to 87 MB, of which `lines` was 20 and a nested
`also` - carrying its own copy - 35.

The copy was never worth it, because a map without its repository answers
nothing anyway. It is attached to a checkout; `--ask` names files and line
numbers in it, the `handle` fields point into it, and every answer is read by
somebody who has it. Storing the checkout inside the description of the
checkout was twenty megabytes spent on a case that does not arise.

So the map stores `files` - which paths were indexed - and the text comes from
disk when something asks for it. Reading 1,500 small files costs less than
parsing 20 MB of JSON, and the pass that wanted them was already walking all of
them.

`lines` is still read when a map has it: a map built by 1.6.2 or earlier must
keep working against 1.6.3's code, and an older map is exactly the one whose
checkout is most likely gone.
"""
from __future__ import annotations

import os

_cache: dict = {}


def paths(doc: dict) -> list:
    """Every file the map indexed, in a stable order."""
    got = doc.get("files")
    if isinstance(got, list):
        return got
    return sorted(doc.get("lines") or {})


def resolve(doc: dict, path: str) -> str:
    """Where that file is now.

    The map records the path it walked. A map built in a container and read on
    the workstation - or a checkout re-cloned somewhere else since - has the
    same tree under a different root, and the repository the map names is the
    one to ask.
    """
    if os.path.isfile(path):
        return path
    root = str(doc.get("repo") or "")
    if not root:
        return path
    for base in (doc.get("content_root"), doc.get("repo")):
        base = str(base or "")
        if base and path.startswith(base):
            moved = os.path.join(root, os.path.relpath(path, base))
            if os.path.isfile(moved):
                return moved
    return path


def body(doc: dict, path: str) -> list:
    """The lines of one indexed file, without their endings."""
    stored = doc.get("lines")
    if isinstance(stored, dict) and stored:
        return stored.get(path) or []
    real = resolve(doc, path)
    try:
        key = (real, os.path.getmtime(real), os.path.getsize(real))
    except OSError:
        return []
    hit = _cache.get(real)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(real, encoding="utf-8", errors="replace") as fh:
            rows = fh.read().splitlines()
    except OSError:
        return []
    _cache[real] = (key, rows)
    return rows


def bodies(doc: dict) -> dict:
    """Every indexed file's lines, the shape the scanning passes want.

    A dict rather than a generator because both callers index into it after
    walking it, and because a map that still carries `lines` hands its own
    dictionary straight back.
    """
    stored = doc.get("lines")
    if isinstance(stored, dict) and stored:
        return stored
    return {p: rows for p in paths(doc) if (rows := body(doc, p))}
