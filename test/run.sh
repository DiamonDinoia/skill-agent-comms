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
for f in $(sed -n 's/.*"files": *\[\(.*\)\].*/\1/p' "$root/skills/index.json" | tr -d '"' | tr ',' ' '); do
  [ -e "$root/skills/$name/$f" ] || { echo "FAIL: skills/index.json lists missing file skills/$name/$f" >&2; exit 1; }
done
nice -n 19 ionice -c 3 env -u AGENTBUS_WAKE_MODULE python3 "$root/agentbus/test/test_wake.py" >/dev/null || { echo "FAIL: agentbus wake tests" >&2; exit 1; }
# The harness configs start the MCP launcher through a ~/.local/bin symlink.
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
ln -s "$root/agentbus/agentbus-mcp-launch" "$tmp/launch"
init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}'
out=$(echo "$init" | timeout 30 "$tmp/launch" 2>&1) || true
case $out in
  *serverInfo*) mcp="MCP launcher answers initialize through a symlink" ;;
  *"no Hermes venv python can import mcp"*) mcp="MCP launcher check skipped: no Hermes venv with mcp" ;;
  *) echo "FAIL: MCP launcher through a symlink: $out" >&2; exit 1 ;;
esac
echo "OK: version $versions consistent in manifests, SKILL.md and skills/index.json; wake tests pass; $mcp"
