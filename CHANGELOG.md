# Changelog

## 0.3.0 - 2026-11-12

- `agentbus-cli wait [SECONDS]`: an idle agent sleeps on an inotify event of the bus database until a row for its name or `*` arrives. No deadline by default. Replaces the 15 s re-poll and the 120 s cap.
- `bin/agentbus-cli`: the Claude Code plugin puts the CLI on the Bash PATH.
- The skill tells each harness how to get the completion event: Claude Code `run_in_background`, Hermes `notify_on_complete`, Codex a blocking `write_stdin`.

## 0.2.0 - 2026-11-08

- Wake-on-message hooks for Claude Code, Codex, OpenCode and Hermes.
- Bus server and CLI moved into the repo.
- Documented limits as in the README.

## 0.1.1 - 2026-11-02

- opencode coverage via install script (`install-opencode.sh`) and URL index (`skills/index.json`).

## 0.1.0 - 2026-11-02

- Initial release.
