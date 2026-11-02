#!/usr/bin/env bash
# Clone or update the agent-comms skill cache and link it into opencode.
# Never overwrite an existing path: a conflict moves to a backup directory.
set -euo pipefail

CACHE="${OPENCODE_SKILLS_CACHE:-$HOME/.cache/opencode-skills}"
REPO_URL="https://github.com/DiamonDinoia/skill-agent-comms"
CLONE="$CACHE/skill-agent-comms"
SKILLS="$HOME/.config/opencode/skills"
COMMANDS="$HOME/.config/opencode/commands"
BACKUP=""

backup() {
  if [ -e "$1" ] || [ -L "$1" ]; then
    [ -n "$BACKUP" ] || BACKUP="$(mktemp -d "${TMPDIR:-/tmp}/agent-comms-backup.XXXXXX")"
    mv "$1" "$BACKUP/"
    echo "backup: $1 -> $BACKUP/$(basename "$1")"
  fi
}

mkdir -p "$CACHE"
if [ -d "$CLONE/.git" ]; then
  git -C "$CLONE" pull --ff-only
  rev=$(git -C "$CLONE" rev-parse --short HEAD)
  echo "update: $CLONE at $rev"
else
  backup "$CLONE"
  git clone "$REPO_URL" "$CLONE"
  echo "clone: $REPO_URL -> $CLONE"
fi

if [ ! -f "$CLONE/skills/agent-comms/SKILL.md" ]; then
  echo "error: no SKILL.md at $CLONE/skills/agent-comms, refusing to link" >&2
  exit 1
fi

mkdir -p "$SKILLS" "$COMMANDS"
backup "$SKILLS/agent-comms"
ln -sTn "$CLONE/skills/agent-comms" "$SKILLS/agent-comms"
echo "link: $SKILLS/agent-comms -> $CLONE/skills/agent-comms"

if [ -e "$CLONE/.opencode/command/agent-comms.md" ]; then
  backup "$COMMANDS/agent-comms.md"
  ln -sTn "$CLONE/.opencode/command/agent-comms.md" "$COMMANDS/agent-comms.md"
  echo "link: $COMMANDS/agent-comms.md -> $CLONE/.opencode/command/agent-comms.md"
else
  echo "skip: no command file at $CLONE/.opencode/command/agent-comms.md"
fi

echo "done: restart opencode to pick the skill up"
