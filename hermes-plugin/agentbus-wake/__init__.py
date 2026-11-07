"""Hermes user plugin: wake-on-message on tool calls and at turn start.

Bus name rule: the call's task_id only for in-process delegate_task children,
else AGENTBUS_AGENT. A child runs its tool calls under task_id == subagent_id
(tools/delegate_tool_registry.py:30) and the live registry recognises that id
(tools/delegate_tool_registry.py:28); a top-level turn instead gets a fresh
uuid task_id (agent/turn_context.py:589). No name means no output.

Delivery: transform_tool_result rewrites the normal tool result
(model_tools.py:973). Catalog results (tool_search, tool_describe) and error
results return before that transform (model_tools.py:919-921, 931-932 and
977-979) and post_tool_call cannot rewrite them either (its return value is
discarded at model_tools.py:713). So post_tool_call polls the bus on every
result path and the block rides the next transformable result, else the
context of the next turn (pre_llm_call, agent/turn_context.py:1236).
shortcut: a block polled but not yet delivered is lost when the process exits,
upgrade when Hermes routes every result through transform_tool_result.
"""
import importlib.util
import os
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
    queued = {}  # bus name -> blocks: in-process children share this process with the parent

    def _bus_name(task_id):
        task_id = (task_id or "").strip()
        if task_id:
            try:
                from tools.delegate_tool_registry import get_subagent_attribution
                if get_subagent_attribution(task_id) is not None:
                    return task_id  # in-process delegate_task child: the name is its task id
            except Exception:
                pass
        return os.environ.get("AGENTBUS_AGENT", "") or ""

    def _poll(task_id):
        # any error means no output: never fail the tool call
        try:
            name = _bus_name(task_id)
            block = wake_mod.wake(name=name)
            if block:
                queued.setdefault(name, []).append(block)
        except Exception:
            pass

    def _drain(name):
        blocks = queued.pop(name, None)
        return "\n".join(blocks) if blocks else None

    def on_post_tool_call(task_id="", **kwargs):
        # fires on every result path, including catalog and error results
        _poll(task_id)

    def on_transform_tool_result(task_id="", result=None, **kwargs):
        _poll(task_id)  # also covers calls whose post_tool_call was suppressed
        block = _drain(_bus_name(task_id))
        if block and isinstance(result, str):
            return result + "\n" + block
        return None

    def on_pre_llm_call(task_id="", **kwargs):
        # turn start: delivers blocks no tool result could carry
        _poll(task_id)
        block = _drain(_bus_name(task_id))
        return {"context": block} if block else None

    ctx.register_hook("transform_tool_result", on_transform_tool_result)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
