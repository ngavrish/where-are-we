"""The parts of `mapper.py`.

Every public name lives on `where_are_we.mapper`, which is the module callers
import and the only one documented outside this package. This is where its
implementation is kept, one file per job:

- `state.py`: the indexes and caches that live for the length of a process.
- `walk.py`: finding files, reading them, the parse cache, the manifest.
- `declare.py`: what a file declares and on which line.
- `extract/`: map topics that are a function of the file list alone.
- `build.py`: the one walk that assembles the map dict.
- `render.py`: map dict to Markdown, and lookups over a written map.
- `cli.py`: argv, stdout, and what the tool writes into a repository.

An extractor is one file, one topic, one `(ctx) -> dict`.
"""
