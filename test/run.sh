#!/bin/sh
# Check that every manifest and SKILL.md pin one version string.
set -eu
root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
versions=$(grep -h '"version"' "$root"/.*-plugin/*.json "$root"/gemini-extension.json | sed 's/.*"\([0-9][0-9.]*\)".*/\1/' | sort -u)
count=$(printf '%s\n' "$versions" | grep -c .)
[ "$count" -eq 1 ] || { echo "FAIL: manifest versions differ: $versions" >&2; exit 1; }
skill_version=$(sed -n 's/^version: *//p' "$root"/skills/agent-comms/SKILL.md)
[ "$skill_version" = "$versions" ] || { echo "FAIL: SKILL.md version '$skill_version' != manifest version '$versions'" >&2; exit 1; }
echo "OK: version $versions consistent in manifests and SKILL.md"
