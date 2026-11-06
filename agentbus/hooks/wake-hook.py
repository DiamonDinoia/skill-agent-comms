#!/usr/bin/env python3
"""PostToolUse hook for Claude Code and Codex: wake-on-message as extra context.

Reads nothing from stdin; the agent name comes from AGENTBUS_AGENT. Prints one
JSON object when there are new rows, nothing when there are none, and exits 0
on every path so the tool call is never failed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from wake import wake  # noqa: E402


def main():
    block = wake()
    if block:
        # only hookSpecificOutput: the Codex post_tool_use schema is
        # additionalProperties=false, so any top-level key voids the whole JSON
        print(json.dumps({
            "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": block},
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
