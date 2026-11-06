"""Hermes user plugin: wake-on-message after every tool call.

Bus name rule: the call's task_id when set, else AGENTBUS_AGENT. For in-process
delegate_task children task_id is the subagent_id the parent got from the
dispatch result (tools/delegate_tool_registry.py). No name means no output.
"""
import importlib.util
import os
import sys
from pathlib import Path


def _load_wake():
    # repo layout first (works through a symlinked plugin dir), deployed copy second
    here = Path(__file__).resolve().parent
    for cand in (here.parent.parent / "agentbus" / "wake.py",
                 Path.home() / ".local" / "share" / "agentbus" / "wake.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("agentbus_wake", cand)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def register(ctx):
    wake_mod = _load_wake()
    if wake_mod is None:
        return

    def on_transform_tool_result(task_id="", result=None, **kwargs):
        try:
            name = (task_id or "").strip() or os.environ.get("AGENTBUS_AGENT", "")
            block = wake_mod.wake(name=name)
            if block and isinstance(result, str):
                return result + "\n" + block
        except Exception:
            pass  # any error means no output: never fail the tool call
        return None

    ctx.register_hook("transform_tool_result", on_transform_tool_result)
