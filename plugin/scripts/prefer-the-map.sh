#!/bin/sh
# PreToolUse, opt-in (WAWE_STRICT=1): a search over the repository is refused
# while a map exists, and the refusal says how to ask the map instead. Off by
# default - in an interactive session a refusal is a surprise; in a headless
# agent it is the difference between forty turns of grep and one question.
set -u
[ "${WAWE_STRICT:-0}" = "1" ] || exit 0
input=$(cat 2>/dev/null || true)
python3 - "$input" <<'PY'
import json, os, re, sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
tool = d.get("tool_name", "")
args = d.get("tool_input") or {}
cwd = d.get("cwd") or os.getcwd()
if not os.path.exists(os.path.join(cwd, ".wawe", "framework_map.md")):
    sys.exit(0)
searching = tool in ("Grep", "Glob")
if tool == "Bash":
    cmd = str(args.get("command", ""))
    searching = bool(re.match(r"^\s*(?:\w+=\S*\s+)*(grep|rg|ag|find|fd|ack)\b", cmd))
if not searching:
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": (
        "This repository has a map; ask it instead of searching. Where a name "
        "is defined: where-are-we defines(name=[...]). Where a phrase lives: "
        "find(phrase=[...]). Anything else: ask(words=[...]). Lists, so ask for "
        "everything in one call. (WAWE_STRICT=1 refuses repository searches.)")}}))
PY
