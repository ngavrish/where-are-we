"""Give every directory a README, written from what is actually in it.

The framework map reads a directory's README as that directory explaining
itself, which beats anything inferred — but only where a README exists, and in
this suite twenty content directories had none. Rather than let an agent guess
what `Base/Misc` or `steps/data_steps` is for, each directory gets a stub built
from its own contents: how many step phrases it declares and a sample, which
classes it defines, what its scripts say their usage is, the first line of each
module docstring.

Nothing here is invented: every line is derived from the files in the directory.
A human can then correct the one sentence at the top, which is the sentence
worth a human's time.
"""

import ast
import os
import re
import sys

SKIP = {".git", ".venv", "node_modules", "__pycache__", ".runs", ".pytest_cache"}
CODE = (".py", ".feature", ".sh", ".sql")


def _steps(path: str) -> list[str]:
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except (OSError, SyntaxError):
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and dec.args:
                name = getattr(dec.func, "id", "") or getattr(dec.func, "attr", "")
                if name.lower() in {"step", "given", "when", "then"}:
                    a = dec.args[0]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        out.append(a.value)
    return out


def describe(d: str) -> str | None:
    files = sorted(f for f in os.listdir(d)
                   if os.path.isfile(os.path.join(d, f)) and f.endswith(CODE))
    if not files:
        return None
    title = os.path.basename(d) or "."
    lines = [f"# `{title}`", "",
             "<!-- Written from the contents of this directory. Replace the line",
             "     below with one sentence a newcomer needs; the rest is derived. -->",
             "", "TODO: one sentence on what this directory is for.", ""]

    phrases, classes, docs, usages, scenarios = [], [], [], [], []
    for f in files:
        p = os.path.join(d, f)
        if f.endswith(".py"):
            phrases += [(f, t) for t in _steps(p)]
            try:
                tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
                doc = ast.get_docstring(tree)
                if doc:
                    docs.append((f, doc.strip().splitlines()[0][:160]))
                classes += [(f, n.name) for n in tree.body if isinstance(n, ast.ClassDef)]
            except (OSError, SyntaxError):
                pass
        elif f.endswith(".feature"):
            try:
                body = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            scenarios.append((f, len(re.findall(r"^\s*Scenario(?: Outline)?:", body, re.M))))
        elif f.endswith(".sh"):
            try:
                head = open(p, encoding="utf-8", errors="replace").read(1200)
            except OSError:
                continue
            u = [l.lstrip("# ").rstrip() for l in head.splitlines()[:16]
                 if l.startswith("#") and ("usage" in l.lower() or ".sh " in l)]
            if u:
                usages.append((f, u[0][:140]))

    lines += [f"Contents: {len(files)} files "
              f"({', '.join(sorted({os.path.splitext(f)[1] for f in files}))}).", ""]
    if phrases:
        lines += [f"## Step phrases ({len(phrases)})", ""]
        for f, t in phrases[:12]:
            lines.append(f"- `{f}` — {t}")
        if len(phrases) > 12:
            lines.append(f"- … {len(phrases) - 12} more")
        lines.append("")
    if scenarios:
        lines += ["## Feature files", ""]
        for f, n in scenarios[:20]:
            lines.append(f"- `{f}` — {n} scenarios")
        lines.append("")
    if classes:
        lines += ["## Classes", ""]
        for f, c in classes[:20]:
            lines.append(f"- `{c}` in `{f}`")
        lines.append("")
    if usages:
        lines += ["## Scripts", ""]
        for f, u in usages[:20]:
            lines.append(f"- `{f}` — {u}")
        lines.append("")
    if docs:
        lines += ["## Module docstrings, first line", ""]
        for f, doc in docs[:20]:
            lines.append(f"- `{f}` — {doc}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    repo = os.getenv("AGENT_REPO", "/work")
    written = 0
    for base, dirs, _ in os.walk(repo):
        dirs[:] = [x for x in dirs if x not in SKIP]
        target = os.path.join(base, "README.md")
        if os.path.exists(target):
            continue
        text = describe(base)
        if not text:
            continue
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
        written += 1
        print("wrote", os.path.relpath(target, repo))
    print(f"{written} README files written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
