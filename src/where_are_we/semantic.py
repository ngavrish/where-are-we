"""The semantic half of the map: local embeddings, no service, no database.

The keyword ask answers when the asker knows the words the map used. The
sessions that pay the most do not: they ask "how do I close the values
dropdown" and the section says "dismiss an open picker". A local embedding
index closes that gap - built next to the map as two flat files, a float32
matrix and a JSON of chunks, rebuilt only when the sources' content hash
moves. At this scale (thousands of chunks, 384 dims) a numpy dot product IS
the vector database; anything heavier is dependencies looking for a job.

Models are fastembed's ONNX ones, small enough for a CPU container:
  - bi-encoder  BAAI/bge-small-en-v1.5   (~130 MB)  recall
  - cross-encoder Xenova/ms-marco-MiniLM-L-6-v2 (~90 MB) precision on top
Both load lazily and only if the `fastembed` package is present; without it
every entry point degrades to "no index", and the keyword path stands alone,
which is exactly what it did before this module existed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

INDEX_MATRIX = "semantic_index.npy"
INDEX_CHUNKS = "semantic_index.json"
_BI_MODEL = os.getenv("WAWE_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
_CROSS_MODEL = os.getenv("WAWE_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")

_bi = None
_cross = None


def available() -> bool:
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def _embedder():
    global _bi
    if _bi is None:
        from fastembed import TextEmbedding
        _bi = TextEmbedding(_BI_MODEL)
    return _bi


def _reranker():
    global _cross
    if _cross is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _cross = TextCrossEncoder(_CROSS_MODEL)
    return _cross


def _split_sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) per markdown section; the preamble rides under ''."""
    out, head, body = [], "", []
    for line in text.splitlines():
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            if head or body:
                out.append((head, "\n".join(body)))
            head, body = line.strip(), []
        else:
            body.append(line)
    out.append((head, "\n".join(body)))
    return [(h, b) for h, b in out if (h + b).strip()]


def _chunks_of(name: str, path: str, piece: int = 2400) -> list[dict]:
    """One source file into chunks: markdown by section, anything else whole,
    and any body over `piece` characters split on blank lines."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    sections = (_split_sections(text) if path.endswith((".md", ".mdc"))
                else [("", text)])
    out = []
    for head, body in sections:
        parts, buf = [], ""
        for para in body.split("\n\n"):
            if buf and len(buf) + len(para) > piece:
                parts.append(buf)
                buf = para
            else:
                buf = (buf + "\n\n" + para) if buf else para
        if buf.strip():
            parts.append(buf)
        for i, part in enumerate(parts):
            title = head or os.path.basename(path)
            if len(parts) > 1:
                title = f"{title} ({i + 1}/{len(parts)})"
            out.append({"source": name, "path": path, "title": title,
                        "text": part.strip()})
    return out


# What a corpus may hold. Docs, and source: a product tree handed over as a
# corpus is code, and "which component renders the values dropdown" is the
# question a UI session pays twenty Reads to answer without it. Chunking by
# blank lines works on source the way it works on prose - functions and
# blocks separate on empty lines - and the size cap keeps a bundled artifact
# or a lockfile from flooding the index.
_CORPUS_EXTS = (".md", ".mdc", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx",
                ".go", ".java", ".sh", ".feature")
_CORPUS_FILE_CAP = 200_000
_CORPUS_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__",
                     ".venv", "coverage"}


def _walk(name: str, root: str) -> list[dict]:
    """A corpus argument is a file or a directory of doc and source files."""
    if os.path.isfile(root):
        return _chunks_of(name, root)
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _CORPUS_SKIP_DIRS]
        for f in sorted(files):
            path = os.path.join(base, f)
            if not f.endswith(_CORPUS_EXTS):
                continue
            try:
                if os.path.getsize(path) > _CORPUS_FILE_CAP:
                    continue
            except OSError:
                continue
            out.append(path)
    chunks = []
    for path in sorted(out):
        chunks.extend(_chunks_of(name, path))
    return chunks


def build_index(out_dir: str, corpora: list[tuple[str, str]]) -> str:
    """Embed every corpus into out_dir; a content hash makes rebuilds free.

    Returns a one-line summary for the build log.
    """
    if not available():
        return "semantic index skipped: fastembed is not installed"
    chunks = []
    for name, root in corpora:
        chunks.extend(_walk(name, root))
    if not chunks:
        return "semantic index skipped: nothing to embed"
    fingerprint = hashlib.sha256(
        json.dumps([(c["source"], c["title"], c["text"]) for c in chunks],
                   ensure_ascii=False).encode()).hexdigest()
    meta_path = os.path.join(out_dir, INDEX_CHUNKS)
    try:
        with open(meta_path, encoding="utf-8") as fh:
            if (json.load(fh) or {}).get("fingerprint") == fingerprint:
                return f"semantic index current ({len(chunks)} chunks)"
    except (OSError, ValueError):
        pass
    import numpy as np
    os.makedirs(out_dir, exist_ok=True)
    texts = [f"{c['title']}\n{c['text']}" for c in chunks]
    matrix = np.array(list(_embedder().embed(texts)), dtype="float32")
    matrix /= (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    np.save(os.path.join(out_dir, INDEX_MATRIX), matrix)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump({"fingerprint": fingerprint, "model": _BI_MODEL,
                   "chunks": chunks}, fh, ensure_ascii=False)
    return f"semantic index built: {len(chunks)} chunks from " \
           f"{len(corpora)} corpus(es)"


def search(out_dir: str, query: str, k: int = 6,
           rerank: bool = True) -> list[dict]:
    """Top-k chunks for the query: bi-encoder recall, cross-encoder precision.

    Returns [] when there is no index or no library - the caller's keyword
    path is the fallback, not an error.
    """
    if not available():
        return []
    try:
        import numpy as np
        matrix = np.load(os.path.join(out_dir, INDEX_MATRIX))
        with open(os.path.join(out_dir, INDEX_CHUNKS), encoding="utf-8") as fh:
            chunks = (json.load(fh) or {}).get("chunks") or []
    except (OSError, ValueError):
        return []
    if len(chunks) != len(matrix):
        return []
    q = np.array(list(_embedder().embed([query])), dtype="float32")[0]
    q /= (np.linalg.norm(q) + 1e-9)
    sims = matrix @ q
    wide = min(len(chunks), max(k * 5, 30))
    order = np.argsort(-sims)[:wide]
    picked = [dict(chunks[i], score=float(sims[i])) for i in order]
    if rerank and len(picked) > k:
        try:
            texts = [f"{c['title']}\n{c['text']}"[:2000] for c in picked]
            scores = list(_reranker().rerank(query, texts))
            for c, s in zip(picked, scores):
                c["score"] = float(s)
            picked.sort(key=lambda c: -c["score"])
        except Exception:  # noqa: BLE001 - recall order stands when precision is unavailable
            pass
    return picked[:k]


def cluster(texts: list[str], threshold: float = 0.82) -> list[list[int]]:
    """Greedy cosine clustering, for the triage prefilter: one embedding per
    text, first-fit against cluster centroids. Hundreds of failure messages
    become a handful of groups a session can read whole.
    """
    if not available() or not texts:
        return [[i] for i in range(len(texts))]
    import numpy as np
    m = np.array(list(_embedder().embed(texts)), dtype="float32")
    m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    groups: list[list[int]] = []
    centroids: list = []
    for i in range(len(texts)):
        best, best_sim = -1, threshold
        for g, c in enumerate(centroids):
            sim = float(m[i] @ c)
            if sim >= best_sim:
                best, best_sim = g, sim
        if best < 0:
            groups.append([i])
            centroids.append(m[i].copy())
        else:
            groups[best].append(i)
            n = len(groups[best])
            centroids[best] = (centroids[best] * (n - 1) + m[i]) / n
            centroids[best] /= (np.linalg.norm(centroids[best]) + 1e-9)
    return groups
