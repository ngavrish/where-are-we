"""The package. `mapper` is the facade; `cli` is the command line above it.

`init_manifest` and `main` are answered on first use rather than imported
here. They live in `cli.py`, which imports this package's whole world, so
importing them at this line would make `import where_are_we` build the
command line, the MCP server and the language server before it could hand
back `build`. The names still resolve, and `from where_are_we import main`
still works: Python asks a module's `__getattr__` when an ordinary lookup
fails, which is exactly when this one runs.
"""

try:
    from .mapper import brief, build, digest
except ImportError:  # run as a plain file, with no package around it
    from mapper import brief, build, digest  # type: ignore[no-redef]

__all__ = ["build", "brief", "digest", "init_manifest", "main"]
__version__ = "1.3.0"

_FROM_CLI = frozenset(("init_manifest", "main"))


def __getattr__(name):
    if name in _FROM_CLI:
        try:
            from . import cli
        except ImportError:  # run as a plain file, with no package around it
            import cli  # type: ignore[no-redef]
        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | _FROM_CLI)
