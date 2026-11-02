#!/bin/sh
# Check that every manifest, SKILL.md and skills/index.json pin one version string,
# and that every file listed in skills/index.json exists in the tree.
set -eu
root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
versions=$(grep -h '"version"' "$root"/.*-plugin/*.json "$root"/gemini-extension.json "$root"/skills/index.json | sed 's/.*"\([0-9][0-9.]*\)".*/\1/' | sort -u)
count=$(printf '%s\n' "$versions" | grep -c .)
[ "$count" -eq 1 ] || { echo "FAIL: manifest versions differ: $versions" >&2; exit 1; }
skill_version=$(sed -n 's/^version: *//p' "$root"/skills/agent-comms/SKILL.md)
[ "$skill_version" = "$versions" ] || { echo "FAIL: SKILL.md version '$skill_version' != manifest version '$versions'" >&2; exit 1; }
name=$(sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' "$root"/skills/index.json | head -n 1)
for f in $(sed -n 's/.*"files": *\[\(.*\)\].*/\1/p' "$root"/skills/index.json | tr -d '"' | tr ',' ' '); do
  [ -e "$root/skills/$name/$f" ] || { echo "FAIL: skills/index.json lists missing file skills/$name/$f" >&2; exit 1; }
done
echo "OK: version $versions consistent in manifests, SKILL.md and skills/index.json"
