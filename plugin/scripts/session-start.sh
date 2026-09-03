#!/bin/sh
# SessionStart: the repository gets a map before the first turn, and the
# session gets the pointer - not the map. The map (100+ KB) stays on disk in
# .wawe/; the pointer (~600 bytes) says it exists, what is in it and how to
# ask. Measured on a real suite: carrying the map cost ~64k tokens a turn,
# the pointer ~200.
set -u
input=$(cat 2>/dev/null || true)
cwd=$(printf '%s' "$input" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("cwd",""))
except Exception: print("")' 2>/dev/null)
[ -n "$cwd" ] || cwd=$PWD

emit() {
  python3 -c 'import sys,json
print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.argv[1]}}))' "$1"
}

if ! command -v where-are-we >/dev/null 2>&1; then
  emit "where-are-we (the repository map) is not installed, so this session has no map and the map tools will not answer. Install it once, outside this session: pipx install where-are-we   (or: uv tool install where-are-we). Until then search the repository as usual."
  exit 0
fi

# Not a repository we should map: no files, or not writable.
[ -d "$cwd" ] && [ -w "$cwd" ] || exit 0

out="$cwd/.wawe"
head=$(git -C "$cwd" rev-parse HEAD 2>/dev/null || echo "")
built=$(cat "$out/.built-at" 2>/dev/null || echo "")
if [ ! -f "$out/framework_map.md" ] || [ -n "$head" ] && [ "$head" != "$built" ]; then
  # One tree walk, seconds, offline. A stale map is rebuilt on the next
  # session after a commit; edits within a session are not re-walked.
  ( cd "$cwd" && where-are-we --repo . --out .wawe --quiet >/dev/null 2>&1 ) || exit 0
  [ -n "$head" ] && printf '%s' "$head" > "$out/.built-at"
  # Keep the map out of the repository's own diff.
  if [ -f "$cwd/.gitignore" ] && ! grep -qx '.wawe/' "$cwd/.gitignore" 2>/dev/null; then
    printf '\n.wawe/\n' >> "$cwd/.gitignore"
  fi
fi

ptr=$(cd "$cwd" && where-are-we --out .wawe --pointer 2>/dev/null || true)
[ -n "$ptr" ] || exit 0
emit "$ptr

The same map is on MCP in this session (server where-are-we): tools ask, find, defines, sections. Prefer them to the CLI and to grep: one call, a list of words or names, and only the rows that mention them come back."
