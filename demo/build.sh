#!/usr/bin/env bash
# Rebuilds docs/demo/fastapi/index.html: the map of a well-known repository
# (FastAPI, at a pinned tag) as a public example of what this tool writes,
# with nothing to install and nothing to trust but the page itself.
set -euo pipefail

TAG=0.115.0
REPO_URL=https://github.com/fastapi/fastapi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEMO_DIR="$HERE/docs/demo/fastapi"

CLONE_DIR="$(mktemp -d)"
OUT_DIR="$(mktemp -d)"
trap 'rm -rf "$CLONE_DIR" "$OUT_DIR"' EXIT

git clone -q --depth 1 --branch "$TAG" "$REPO_URL" "$CLONE_DIR"

uv run --python 3.12 --with-editable "$HERE" where-are-we \
    --repo "$CLONE_DIR" --out "$OUT_DIR" --html --force

mkdir -p "$DEMO_DIR"
# The map is built from a local clone in a machine-specific temp directory;
# nothing in a public page should name that path, so it is replaced with a
# stand-in before the page is committed.
sed "s#$CLONE_DIR#<fastapi clone>#g" "$OUT_DIR/framework_map.html" > "$DEMO_DIR/index.html"

cat > "$DEMO_DIR/README.md" <<EOF
# FastAPI demo

The map of [FastAPI]($REPO_URL) $TAG, built by this repository's own tool
as a public example of what it writes.

- Repository: $REPO_URL
- Tag: $TAG
- Generated: $(date -u +%Y-%m-%d)
- Command: \`where-are-we --repo <fastapi clone> --out <tmp> --html --force\`

Regenerate with \`docs/demo/build.sh\`.
EOF

echo "wrote $DEMO_DIR/index.html and $DEMO_DIR/README.md"
