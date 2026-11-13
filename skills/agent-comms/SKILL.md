---
name: agent-comms
description: "Use when a manager or parent dispatches you onto the agent bus: these are the send, read and address rules"
version: 0.3.1
author: Marco Barbone
license: MIT
---
# Agent comms

## Environment

AGENTBUS_AGENT holds the agent name. AGENTBUS_DB is optional. It holds the bus database path. When AGENTBUS_DB is unset and HOME is on a network file system, the bus uses $XDG_RUNTIME_DIR/agentbus/bus.db or /var/tmp/agentbus-$UID/bus.db. When HOME is local, the bus uses ~/.local/share/agentbus/bus.db.

Agent names are free-form. A name is a wave id, a dash, and a short role. The name w20261102a-p1 is wave w20261102a with role p1. Nothing registers names.

## Command surface

Three commands are allowed. No other subcommand is allowed.

- `agentbus-cli send TO BODY` sends BODY to TO.
- `agentbus-cli log N` prints the last N bus rows.
- `agentbus-cli wait` blocks until a new row for the agent's name or * arrives, then prints it.

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

## Waiting for a message

Never wait on a timer. Do not sleep and do not re-poll. When work cannot continue until a message comes, run `agentbus-cli wait` and stop until it exits.

The wait sleeps on a kernel file event of the bus database. It uses no CPU while it sleeps. It ends at the first row for the agent's name or *. It prints that row and every other new row, and advances the cursor. A row that came before the wait started ends the wait at once.

Start the wait the way the harness gets a completion event:

- Claude Code: run it with Bash `run_in_background: true`, then end the turn. The harness starts the next turn when the wait exits.
- Hermes: run `terminal(command="agentbus-cli wait", background=true, notify_on_complete=true)`. An in-process delegate_task child puts its task id in front: `AGENTBUS_AGENT=<task id> agentbus-cli wait`.
- Codex: run it in the foreground. When the call yields, send an empty `write_stdin`, which blocks until the wait exits.

The wait has no deadline. A brief can set one with `agentbus-cli wait SECONDS`. Read the exit status:

- 0: rows came. Process them.
- 1: the deadline passed. Continue the work and note the missed reply in the report.
- 2: a bad call or a bus failure. Do not start the wait again. Report the error.
- Killed by the harness, no output: start the wait again.

A row that the tool hook already showed does not end the wait.

The manager wakes a waiting agent with any row to its name. A manager that checks on its agents sends a check-in row. That row ends the wait of an agent that missed an earlier row.

## Send inventory

Send a blocker when work stops. Send a shared fact when other children need it. Send a handoff to a named sibling, such as w20261102a-p2. Send a completion signal to the manager when the task ends. The manager name is the wave id with role mgr, w20261102a-mgr in this example. Never send the final report over the bus. Never send a request for an approval-gated action. Use the report channel for approval-gated actions.

## Roster

The roster comes from the sibling list in the brief. There is no registry to query.

## Manager brief clause

A manager brief carries this clause line:

Bus: export AGENTBUS_DB=~/.local/share/agentbus/bus.db AGENTBUS_AGENT=w20261102a-p1; load skill agent-comms; siblings: w20261102a-p2.

Managers substitute their own wave id and agent names.

## Documented limits

Broadcast is the * convention. The log subcommand has no consume-once read. The wake hook shows each row to each agent one time. The upstream answer-reuse window of 300 s is bypassed because ask and answer are unused. The wait uses Linux inotify, so it works only on Linux. Any write to the bus ends the sleep for one read, so traffic to other agents costs the waiter one short query for each write.
