---
name: agent-comms
description: "Use when a manager or parent dispatches you onto the agent bus: these are the send, read and address rules"
version: 0.1.0
author: Marco Barbone
license: MIT
---
# Agent comms

## Environment

The brief exports AGENTBUS_DB=~/.local/share/agentbus/bus.db and AGENTBUS_AGENT. AGENTBUS_AGENT holds the agent name.

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

## Poll points

Poll at three points in the run. Poll on the first turn, before any work starts. Poll after each long terminal command. Poll before the final report.

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

Broadcast is the * convention. There is no consume-once read. The upstream answer-reuse window of 300 s is bypassed because ask and answer are unused.
