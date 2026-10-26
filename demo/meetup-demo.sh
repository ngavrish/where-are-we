#!/bin/sh
# The meetup demo is the A/B one: it shows the same question answered by hand
# (grep) and by where-are-we, side by side, on a real sample suite.
exec "$(dirname "$0")/ab-demo.sh" "$@"
