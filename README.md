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

For a remote install, add `https://raw.githubusercontent.com/DiamonDinoia/skill-agent-comms/v0.1.1/skills/` to the `skills` list in the opencode config. opencode reads `index.json` from that URL and downloads the listed skill files.

The npm plugin route is unsupported for a markdown-only skill. `opencode plugin add` requires a JS entrypoint, a server or TUI module. This repo ships markdown only.

## Fork first

Fork this repo before you install, then work from a clone of your fork.

- The install links the skill folder from your fork clone into your harness.
- Pull new releases into the fork clone when you want them.

## License

MIT. See `LICENSE`.
