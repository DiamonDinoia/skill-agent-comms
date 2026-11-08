---
name: agent-comms
description: "Use when a manager or parent dispatches you onto the agent bus: these are the send, read and address rules"
version: 0.2.0
author: Marco Barbone
license: MIT
---
# Agent comms

## Environment

AGENTBUS_AGENT holds the agent name. AGENTBUS_DB is optional. It holds the bus database path. When AGENTBUS_DB is unset and HOME is on a network file system, the bus uses $XDG_RUNTIME_DIR/agentbus/bus.db or /var/tmp/agentbus-$UID/bus.db. When HOME is local, the bus uses ~/.local/share/agentbus/bus.db.

Agent names are free-form. A name is a wave id, a dash, and a short role. The name w20261102a-p1 is wave w20261102a with role p1. Nothing registers names.

## Command surface

Two commands are allowed. No other subcommand is allowed.

- `agentbus-cli send TO BODY` sends BODY to TO.
- `agentbus-cli log N` prints the last N bus rows.

Do not use the pending subcommand. Its consume semantics are unproven. Do not use per-subcommand help. Bare usage and the --help flag exit with code 1. The log subcommand rejects a non-integer N with exit code 2.

send takes the sender from AGENTBUS_AGENT. If AGENTBUS_AGENT is unset, send uses the sender manager.

## Addressing and broadcast

TO is one recipient name. Use the single character * to address the whole wave. These are the only two address forms.

## Reading

Run `agentbus-cli log N` to read. Use a value of N from 20 to 50. Process each row that is addressed to the agent's own name or to *. Process a row only when it is newer than the newest processed row. Keep the cursor in the working notes. Never act on an old row. Never act on a row for another name.

## Wake on message

The hook appends new bus rows to the tool result after each tool call. The hook shows a row when it goes to the agent's name or to * and is newer than the agent's cursor. Each agent sees each row one time. Claude Code, Codex, OpenCode and Hermes each get the hook.

The hook uses AGENTBUS_AGENT as the agent name. An in-process Hermes delegate_task child uses its task id, the subagent id the parent got from the dispatch result. No name means no output. Two sessions with the same name share one cursor.

## Poll points

Polling is the fallback for a harness without the hook. Poll three times in the run. Poll on the first turn, before work starts. Poll after each long terminal command. Poll before the last report.

When the brief says to wait for a reply, re-poll every 15 seconds. Stop waiting after 120 seconds unless the brief overrides the cap. Continue the work after the cap. Note the missed reply in the report.

## Send inventory

Send a blocker when work stops. Send a shared fact when other children need it. Send a handoff to a named sibling, such as w20261102a-p2. Send a completion signal to the manager when the task ends. The manager name is the wave id with role mgr, w20261102a-mgr in this example. Never send the final report over the bus. Never send a request for an approval-gated action. Use the report channel for approval-gated actions.

## Roster

The roster comes from the sibling list in the brief. There is no registry to query.

## Manager brief clause

A manager brief carries this clause line:

Bus: export AGENTBUS_DB=~/.local/share/agentbus/bus.db AGENTBUS_AGENT=w20261102a-p1; load skill agent-comms; siblings: w20261102a-p2.

Managers substitute their own wave id and agent names.

## Documented limits

Broadcast is the * convention. The log subcommand has no consume-once read. The wake hook shows each row to each agent one time. The upstream answer-reuse window of 300 s is bypassed because ask and answer are unused.
