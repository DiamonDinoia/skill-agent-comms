// agentbus wake — append new bus messages to every tool result.
//
// Loaded from opencode.json: { "plugins": ["file:///.../opencode-plugin"] }.
// The hook spawns the shared wake CLI and appends its block as a text part in
// the tool content. Any error means no append, so a tool call never fails here.
//
// Runtime shape (opencode 2.0.25, proven live): ctx.tool.hook("execute.after",
// cb) gives one event object {tool, sessionID, agent, messageID, id, input,
// status, result: {output, content, metadata}}; the hook mutates it in place.
// The text the model sees and the transcript stores is result.content, so the
// wake block goes there, not in the tool-specific result.output.

import { spawnSync } from "child_process"
import fs from "fs"
import os from "os"
import path from "path"
import { fileURLToPath } from "url"

const TIMEOUT_MS = 90 // cap the hook under 100 ms total

// ../agentbus/agentbus-wake next to the plugin, else the deployed copy.
function wakeCli() {
  const local = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "agentbus", "agentbus-wake")
  return fs.existsSync(local) ? local : path.join(os.homedir(), ".local", "share", "agentbus", "agentbus-wake")
}

// The wake block for this tool call, or "" on any failure.
export function wakeBlock(env) {
  try {
    env = env || process.env
    if (!env.AGENTBUS_AGENT) return ""
    const r = spawnSync(wakeCli(), [], { encoding: "utf8", timeout: TIMEOUT_MS, env })
    return r.status === 0 ? String(r.stdout || "").trimEnd() : ""
  } catch {
    return ""
  }
}

export default {
  id: "agentbus-wake",
  async setup(ctx) {
    ctx.tool.hook("execute.after", (event) => {
      try {
        const block = wakeBlock()
        if (block && event.result) {
          if (!Array.isArray(event.result.content)) event.result.content = []
          event.result.content.push({ type: "text", text: block })
        }
      } catch {}
    })
  },
}
