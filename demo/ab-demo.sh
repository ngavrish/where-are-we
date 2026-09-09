#!/bin/sh
# A/B demo for a meetup: one question a tester asks about an unfamiliar suite,
# answered first by hand (grep), then by where-are-we. Watch the difference in
# what you have to sift through.
#
#   docs/demo/ab-demo.sh            # uses the bundled sample suite
#   docs/demo/ab-demo.sh <path>     # or your own behave/pytest suite
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
SUITE="${1:-$HERE/sample-suite}"
OUT="$(mktemp -d)/map"

b()  { printf "\033[1m%s\033[0m\n" "$1"; }
dim(){ printf "\033[2m%s\033[0m\n" "$1"; }
amb(){ printf "\033[38;5;179m%s\033[0m\n" "$1"; }
rule(){ printf "\033[2m----------------------------------------------------------------------\033[0m\n"; }
pause(){ printf "\n"; dim "  (enter)"; read -r _; }
strip(){ sed "s|$SUITE/|  |g"; }

clear 2>/dev/null || true
b "The suite under test:"; dim "  $SUITE"
find "$SUITE" -type f | sed "s|$SUITE/|    |" | sort
echo
b "The task, on a suite you have never seen:"
echo "    Reuse the precondition \"the payment has been captured\" in a new"
echo "    scenario. Where is it defined — and has someone already written it"
echo "    twice under slightly different wording?"
pause

# ---------------------------------------------------------------- WITHOUT
clear 2>/dev/null || true
amb "WITHOUT where-are-we  —  grep the tree, read every hit"
rule
b "\$ grep -rn \"payment has been\" $SUITE"
grep -rn "payment has been" "$SUITE" | strip
HITS=$(grep -rn "payment has been" "$SUITE" | wc -l | tr -d ' ')
FILES=$(grep -rln "payment has been" "$SUITE" | wc -l | tr -d ' ')
echo
dim "  $HITS hits in $FILES files. Two of them are @given definitions in two"
dim "  different modules — but grep will not tell you they are the same"
dim "  precondition. You reuse one, the other stays a silent duplicate, and the"
dim "  suite now asserts the payment is captured two different ways."
pause

# ---------------------------------------------------------------- WITH
clear 2>/dev/null || true
amb "WITH where-are-we  —  build the map once, then ask"
rule
b "\$ where-are-we --repo $SUITE --out \$OUT --quiet"
where-are-we --repo "$SUITE" --out "$OUT" --quiet
head -1 "$OUT/framework_map_brief.md"
echo
b "\$ where-are-we --ask \"the payment has been captured\" --out \$OUT"
where-are-we --ask "the payment has been captured" --out "$OUT" | strip | head -6
pause

clear 2>/dev/null || true
amb "The duplicate it caught for you"
rule
dim "  The map's brief carries a 'Steps that overlap' section — the review"
dim "  comment nobody has time to hunt on a 1800-scenario suite:"
echo
b "\$ awk '/Steps that overlap/,/^## /' \$OUT/framework_map_brief.md"
awk '/## Steps that overlap/{f=1} f{if(/^## /&&!/overlap/){exit} print}' "$OUT/framework_map_brief.md" | strip
pause

# ---------------------------------------------------------------- SCORE
clear 2>/dev/null || true
amb "Side by side"
rule
printf "  %-24s %s\n" "" "answer to where + duplicate?"
printf "  %-24s %s\n" "by hand"      "$HITS grep hits in $FILES files to read and judge"
printf "  %-24s %s\n" "where-are-we" "file:line, plus the overlap pair with a score"
echo
dim "  The map is at $OUT — grep it, ask it, or serve it over MCP with --mcp."
dim "  On a real 184-feature suite the same build takes about ten seconds."
