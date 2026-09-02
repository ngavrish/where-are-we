#!/bin/sh
# Live demo for a testers' meetup: map a real behave suite, then ask it the
# questions a tester actually asks. Everything here runs offline in seconds,
# on your machine, at zero token cost.
#
#   docs/demo/meetup-demo.sh /path/to/a/behave-or-pytest/suite
#
# Falls back to the bundled example suite if no path is given.
set -eu

SUITE="${1:-$(cd "$(dirname "$0")/../.." && pwd)/docs/examples/behave-suite}"
OUT="$(mktemp -d)/map"

pause() { printf "\n\033[2m--- press enter ---\033[0m"; read -r _; }
say()   { printf "\n\033[1;36m# %s\033[0m\n" "$1"; }

say "1. Map the whole suite. Offline, one command."
echo "\$ where-are-we --repo $SUITE --out \$OUT"
time where-are-we --repo "$SUITE" --out "$OUT" --quiet
head -1 "$OUT/framework_map_brief.md"
pause

say "2. What lands in an agent's prompt is a pointer, not the map."
echo "\$ where-are-we --out \$OUT --pointer | wc -c"
POINTER=$(where-are-we --out "$OUT" --pointer --quiet | wc -c | tr -d ' ')
MAP=$(wc -c < "$OUT/framework_map.md" | tr -d ' ')
printf "pointer in the prompt: %s bytes\nfull map on disk:      %s bytes (grep this, never carry it)\n" "$POINTER" "$MAP"
pause

say "3. Where is this step defined? (the daily grep, answered instantly)"
echo "\$ where-are-we --ask \"warm up\" --out \$OUT"
where-are-we --ask "warm up" --out "$OUT" | head -8
pause

say "4. Which step phrases overlap? (find the duplicate/dead steps)"
echo "\$ where-are-we --ask \"overlap\" --out \$OUT"
where-are-we --ask "overlap" --out "$OUT" | head -8
pause

say "5. Drop the pointer into AGENTS.md so every session starts oriented."
echo "\$ where-are-we --repo $SUITE --agent-file AGENTS.md --out \$OUT"
where-are-we --repo "$SUITE" --agent-file "$OUT/AGENTS.md" --out "$OUT" --quiet >/dev/null
printf "AGENTS.md pointer: %s bytes\n" "$(wc -c < "$OUT/AGENTS.md" | tr -d ' ')"

say "Done. The map is on disk at $OUT - grep it, ask it, or serve it over MCP with --mcp."
