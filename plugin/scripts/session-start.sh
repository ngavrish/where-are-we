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
# `||` and `&&` are equal precedence in sh, left to right, so an ungrouped
# "no-map || have-head && moved" parses as "(no-map || have-head) && moved":
# in a repository with no git, head and built are both empty, "" != "" is
# false, and a repository that has never been mapped is never built. The
# braces make the intended grouping explicit: no map -> build; a git repo
# whose HEAD moved since the last build -> build; otherwise skip.
if [ ! -f "$out/framework_map.md" ] || { [ -n "$head" ] && [ "$head" != "$built" ]; }; then
  # One tree walk, seconds, offline. A stale map is rebuilt on the next
  # session after a commit; edits within a session are not re-walked.
  ( cd "$cwd" && where-are-we --repo . --out .wawe --quiet >/dev/null 2>&1 ) || exit 0
  if [ -n "$head" ]; then
    # Written after the build finishes, and atomically (temp file then
    # rename): a reader of .built-at never sees a half-written HEAD, and a
    # build killed mid-way leaves the old stamp in place rather than a torn
    # one that would look like the wrong commit was mapped.
    tmp="$out/.built-at.$$.tmp"
    printf '%s' "$head" > "$tmp" && mv "$tmp" "$out/.built-at"
  fi
fi
# The map directory ignores itself, so the repository's own .gitignore is
# never touched and `git status` stays clean whether or not one exists.
[ -f "$out/.gitignore" ] || printf '*\n' > "$out/.gitignore"

ptr=$(cd "$cwd" && where-are-we --repo . --out .wawe --pointer 2>/dev/null || true)
[ -n "$ptr" ] || exit 0
emit "$ptr

The same map is on MCP in this session (server where-are-we): tools ask, find, defines, at, sections, callers, callees, impact, more. Prefer them to the CLI and to grep: one call, a list of words or names, and only the rows that mention them come back. Where an answer says it left something out it ends with a handle like (more:rows:...); pass that to more rather than asking again for a bigger answer."
