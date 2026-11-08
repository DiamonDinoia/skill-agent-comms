# skill-agent-comms

Send, read and addressing rules for subagents that talk to each other over the agentbus message bus.

## What it does

This skill gives a dispatched subagent the rules for talking to its siblings and its manager over the agentbus message bus. The brief exports `AGENTBUS_DB` and `AGENTBUS_AGENT`. The skill fixes the two allowed commands, `agentbus-cli send TO BODY` and `agentbus-cli log N`, the two address forms, one name or `*` for the whole wave, the read cursor discipline, and the three poll points of a run. It also carries the manager brief clause that starts the bus for a wave.

## Non-destructive rules

The skill only writes to the bus with `agentbus-cli send`. It never consumes a row, never deletes a row, and never registers an agent name.

- Only `send` and `log` are allowed. The `pending` subcommand is not allowed.
- Act only on rows that are new and addressed to the agent's own name or to `*`.
- Never send the final report over the bus. Never send a request for an approval-gated action. Use the report channel for those.

## Install

The bus and its CLI, `agentbus-cli`, are a prerequisite. The installer must already have them. They are a separate local package and are not published. This repository does not install them.

Fork this repository, clone your fork, and install the skill into your harness. For example, link the skill folder into the skill folder of the harness: `ln -s "$PWD/skill-agent-comms/skills/agent-comms" ~/.claude/skills/agent-comms`.

## opencode

Two routes install the skill into opencode.

For a local install, run `./install-opencode.sh`. The script clones `https://github.com/DiamonDinoia/skill-agent-comms` into `~/.cache/opencode-skills/skill-agent-comms` and symlinks `skills/agent-comms` into `~/.config/opencode/skills/agent-comms`. Set `OPENCODE_SKILLS_CACHE` to change the cache directory. Restart opencode after the script runs. The script never overwrites an existing path. It moves a conflict into a backup directory and reports the move.

For a remote install, add `https://raw.githubusercontent.com/DiamonDinoia/skill-agent-comms/v0.2.0/skills/` to the `skills` list in the opencode config. opencode reads `index.json` from that URL and downloads the listed skill files.

The npm plugin route is unsupported for a markdown-only skill. `opencode plugin add` requires a JS entrypoint, a server or TUI module. This repo ships markdown only.

## Codex

Two routes install the wake hook into Codex. Both load the same `hooks/hooks.json` that Claude Code uses. The hook output goes to `hookSpecificOutput.additionalContext`. This is the only context field that Codex accepts, because the Codex output schema rejects unknown top-level keys. Claude Code reads the same field.

The plugin route is the primary route. Add the repository as a marketplace and install the plugin:

```sh
codex plugin marketplace add https://github.com/DiamonDinoia/skill-agent-comms.git
codex plugin add agent-comms@agent-comms
```

A local clone works too. Pass the clone path to `codex plugin marketplace add`. Codex then loads `hooks/hooks.json` from the plugin root.

The hook-config route is the fallback when no plugin marketplace is available. Put the hook in `~/.codex/hooks.json`, or in the project `.codex/hooks.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"/path/to/skill-agent-comms/agentbus/hooks/wake-hook.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Codex shows a trust prompt the first time it sees each hook. A non-interactive run (`codex exec`) cannot show the prompt and skips untrusted hooks. Trust the hook once in the Codex TUI, or pass `--dangerously-bypass-hook-trust` to `codex exec` for automation that already vets the hook source.

## Documented limits

The Hermes wake plugin cannot rewrite a `tool_search`, `tool_describe` or error result in place. Those returns skip the `transform_tool_result` hook (model_tools.py:919-921 and 977-979) and the `post_tool_call` return value is discarded (model_tools.py:713). The block therefore rides the next normal tool result, else the context of the next turn. A block polled but not yet delivered is lost when the Hermes process exits. An agent that upgrades from the plain-name cursor file format has no new hash-named cursor file, so it sees its already-delivered rows once more.

## Fork first

Fork this repo before you install, then work from a clone of your fork.

- The install links the skill folder from your fork clone into your harness.
- Pull new releases into the fork clone when you want them.

## License

MIT. See `LICENSE`.
