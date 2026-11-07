#!/usr/bin/env python3
"""Unit tests for the agentbus wake hook: cursor, broadcast, no-op, corruption, latency,
and one failing-first test per review finding: held-lock latency, concurrent
once-only delivery, name/db key isolation, fresh-HOME first send, top-level vs
child naming, catalog-path delivery.

Run: python3 test_wake.py
The module under test comes from ../wake.py unless AGENTBUS_WAKE_MODULE points at
a copy (mutation checks). Always run the suite with `env -u AGENTBUS_WAKE_MODULE`.
"""
import importlib.util
import json
import multiprocessing
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTBUS_DIR = os.path.abspath(os.path.join(HERE, ".."))
WAKE_MODULE = os.environ.get("AGENTBUS_WAKE_MODULE") or os.path.join(AGENTBUS_DIR, "wake.py")
WAKE_CLI = os.path.join(AGENTBUS_DIR, "agentbus-wake")
WAKE_HOOK = os.path.join(AGENTBUS_DIR, "hooks", "wake-hook.py")
BUSCLI = os.path.join(AGENTBUS_DIR, "agentbus-cli")
AGENTBUS_PY = os.path.join(AGENTBUS_DIR, "agentbus.py")
PLUGIN = os.path.join(AGENTBUS_DIR, "..", "hermes-plugin", "agentbus-wake", "__init__.py")

spec = importlib.util.spec_from_file_location("wake_under_test", WAKE_MODULE)
assert spec is not None and spec.loader is not None
wake_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake_mod)


def make_db(tmp, rows=(), filename="bus.db"):
    db = os.path.join(tmp, filename)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, sender TEXT, rcpt TEXT, body TEXT, ts REAL)")
    for sender, rcpt, body in rows:
        c.execute("INSERT INTO messages(sender, rcpt, body, ts) VALUES(?,?,?,?)", (sender, rcpt, body, time.time()))
    c.commit()
    c.close()
    return db


class WakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agentbus-test.")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_once_only_delivery(self):
        db = make_db(self.tmp, [("a", "b", "hello")])
        first = wake_mod.wake(db=db, name="b")
        self.assertIn("hello", first)
        self.assertIsNone(wake_mod.wake(db=db, name="b"))

    def test_broadcast_each_agent_once(self):
        db = make_db(self.tmp, [("a", "*", "wave")])
        self.assertIn("wave", wake_mod.wake(db=db, name="x") or "")
        self.assertIn("wave", wake_mod.wake(db=db, name="y") or "")
        self.assertIsNone(wake_mod.wake(db=db, name="x"))
        self.assertIsNone(wake_mod.wake(db=db, name="y"))

    def test_no_name_no_output(self):
        db = make_db(self.tmp, self.db_rows())
        self.assertIsNone(wake_mod.wake(db=db, name=""))
        self.assertIsNone(wake_mod.wake(db=db, name="  ", env={}))

    def db_rows(self):
        return [("a", "*", "all"), ("a", "b", "one")]

    def test_other_name_untouched(self):
        db = make_db(self.tmp, self.db_rows())
        block = wake_mod.wake(db=db, name="c") or ""
        self.assertIn("all", block)  # broadcast row
        self.assertNotIn("one", block)  # addressed to b only
        self.assertIn("one", wake_mod.wake(db=db, name="b") or "")

    def test_missing_db_no_output(self):
        self.assertIsNone(wake_mod.wake(db=os.path.join(self.tmp, "nope.db"), name="b"))

    def test_corrupt_db_no_output(self):
        db = os.path.join(self.tmp, "bus.db")
        with open(db, "wb") as f:
            f.write(b"\x00garbage not a sqlite file" * 20)
        self.assertIsNone(wake_mod.wake(db=db, name="b"))

    def test_cli_send_log_roundtrip(self):
        db = os.path.join(self.tmp, "bus.db")
        env = dict(os.environ, AGENTBUS_DB=db, AGENTBUS_AGENT="a")
        r = subprocess.run([BUSCLI, "send", "b", "roundtrip"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([BUSCLI, "log", "5"], env=env, capture_output=True, text=True)
        self.assertIn("a->b\troundtrip", r.stdout)

    def test_hook_process_latency_under_100ms(self):
        rows = [("s", "b", "m%d" % i) for i in range(10000)]
        db = make_db(self.tmp, rows)
        env = dict(os.environ, AGENTBUS_DB=db, AGENTBUS_AGENT="b")
        for script in (WAKE_HOOK, WAKE_CLI):
            worst = 0.0
            for _ in range(5):
                # fresh cursor each run so the query covers the pending rows
                shutil.rmtree(os.path.join(self.tmp, "cursors"), ignore_errors=True)
                t0 = time.perf_counter()
                r = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True)
                worst = max(worst, time.perf_counter() - t0)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertLess(worst, 0.1, "%s took %.1f ms with 10k rows" % (script, worst * 1000))

    def test_hook_json_matches_codex_output_contract(self):
        # the Codex post_tool_use schema is additionalProperties=false, so an
        # unknown top-level key voids the whole JSON and the model sees nothing
        db = make_db(self.tmp, [("a", "b", "ctx")])
        env = dict(os.environ, AGENTBUS_DB=db, AGENTBUS_AGENT="b")
        r = subprocess.run([sys.executable, WAKE_HOOK], env=env, capture_output=True, text=True)
        out = json.loads(r.stdout)
        self.assertIn("ctx", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        allowed = {"continue", "decision", "hookSpecificOutput", "reason",
                   "stopReason", "suppressOutput", "systemMessage"}
        self.assertEqual(set(out) - allowed, set())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_held_lock_returns_under_100ms_and_delivers_next_call(self):
        # finding 4: a held database lock must not stall the hook past its budget
        db = make_db(self.tmp, [("m", "b", "AFTER_RELEASE")])
        holder = sqlite3.connect(db)
        holder.execute("BEGIN EXCLUSIVE")
        self.addCleanup(holder.close)
        result, elapsed = [], []
        def run():
            t0 = time.perf_counter()
            result.append(wake_mod.wake(db=db, name="b"))
            elapsed.append(time.perf_counter() - t0)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(0.25)
        self.assertFalse(t.is_alive(), "wake() still blocked past 250 ms with the lock held")
        self.assertIsNone(result[0])
        self.assertLess(elapsed[0], 0.1, "wake() took %.0f ms under a held lock" % (elapsed[0] * 1000))
        holder.rollback()
        holder.close()
        self.assertIn("AFTER_RELEASE", wake_mod.wake(db=db, name="b") or "")  # cursor unchanged

    def test_concurrent_sessions_deliver_exactly_once(self):
        # finding 5: read-query-update must be atomic per (database, agent)
        db = make_db(self.tmp, [("m", "b", "DELIVER_ONCE")])
        ctx = multiprocessing.get_context("fork")
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()

        def child():
            original_read = wake_mod._read_cursor
            def synchronized_read(path):
                value = original_read(path)
                try:
                    barrier.wait(timeout=1)  # both past the cursor read before either queries
                except Exception:
                    pass
                return value
            wake_mod._read_cursor = synchronized_read
            queue.put(wake_mod.wake(db=db, name="b"))

        procs = [ctx.Process(target=child) for _ in range(2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        results = [queue.get(timeout=5) for _ in procs]
        self.assertEqual(sum("DELIVER_ONCE" in (r or "") for r in results), 1,
                         "one row was delivered %d times" % sum("DELIVER_ONCE" in (r or "") for r in results))

    def test_name_and_db_key_isolation(self):
        # finding 6: a:b and a/b must not share a cursor, and one name on two
        # databases in one directory must keep two cursors
        db = make_db(self.tmp, [("m", "a/b", "FOR_SLASH"), ("m", "a:b", "FOR_COLON")])
        self.assertIn("FOR_COLON", wake_mod.wake(db=db, name="a:b") or "")
        self.assertIn("FOR_SLASH", wake_mod.wake(db=db, name="a/b") or "")
        db2 = make_db(self.tmp, [("m", "a:b", "SECOND_DB")], filename="bus2.db")
        self.assertIn("SECOND_DB", wake_mod.wake(db=db2, name="a:b") or "")

    def test_fresh_home_first_send(self):
        # finding 7: the default path under a fresh HOME has no parent directory
        home = os.path.join(self.tmp, "fresh-home")
        os.makedirs(home)
        env = dict(os.environ, HOME=home, AGENTBUS_AGENT="m", PYTHONDONTWRITEBYTECODE="1")
        env.pop("AGENTBUS_DB", None)
        r = subprocess.run([BUSCLI, "send", "b", "FIRST"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(home, ".local", "share", "agentbus", "bus.db")))

    def test_writer_creates_parent_dir_for_all_paths(self):
        # finding 7 class: the network-home fallbacks also select a missing directory
        for rel in ("run/agentbus/bus.db", "var-tmp/agentbus-1000/bus.db"):
            db = os.path.join(self.tmp, rel)
            env = dict(os.environ, AGENTBUS_DB=db, AGENTBUS_AGENT="m")
            r = subprocess.run([BUSCLI, "send", "b", "X"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "%s: %s" % (rel, r.stderr))
            self.assertTrue(os.path.isfile(db))
            self.assertEqual(os.stat(os.path.dirname(db)).st_mode & 0o777, 0o700, rel)

    def test_mcp_server_writer_creates_parent_dir(self):
        # finding 7 class: agentbus.py had the same omission as the CLI
        for name in ("mcp", "mcp.server", "mcp.server.mcpserver"):
            self.assertNotIn(name, sys.modules)
        mcp_pkg, mcp_server = types.ModuleType("mcp"), types.ModuleType("mcp.server")
        mcp_impl = types.ModuleType("mcp.server.mcpserver")
        class MCPServer:
            def __init__(self, name):
                pass
            def tool(self):
                return lambda fn: fn
            def run(self, **kw):
                pass
        mcp_impl.MCPServer = MCPServer
        mcp_server.mcpserver = mcp_impl
        mcp_pkg.server = mcp_server
        sys.modules.update({"mcp": mcp_pkg, "mcp.server": mcp_server, "mcp.server.mcpserver": mcp_impl})
        self.addCleanup(lambda: [sys.modules.pop(n, None) for n in ("mcp", "mcp.server", "mcp.server.mcpserver")])
        db = os.path.join(self.tmp, "server-home", "agentbus", "bus.db")
        os.environ["AGENTBUS_DB"] = db
        self.addCleanup(os.environ.pop, "AGENTBUS_DB", None)
        spec2 = importlib.util.spec_from_file_location("agentbus_server_under_test", AGENTBUS_PY)
        mod = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(mod)
        c = mod.db()
        c.close()
        self.assertTrue(os.path.isfile(db))
        self.assertEqual(os.stat(os.path.dirname(db)).st_mode & 0o777, 0o700)


class HermesPluginTest(unittest.TestCase):
    """Contract tests for the Hermes user plugin adapter (live run is in the evidence)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agentbus-test.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = make_db(self.tmp, [("m", "w-mgr", "FOR_PARENT"), ("m", "sa-1-deadbeef", "FOR_CHILD"),
                                     ("m", "*", "WAVE")])
        self._old_env = {k: os.environ.get(k) for k in ("AGENTBUS_DB", "AGENTBUS_AGENT")}
        os.environ["AGENTBUS_DB"] = self.db
        os.environ["AGENTBUS_AGENT"] = "w-mgr"
        # children run their tool calls under task_id == subagent_id
        # (tools/delegate_tool_registry.py:30); stub the live registry lookup
        self._old_mods = {k: sys.modules.get(k) for k in ("tools", "tools.delegate_tool_registry")}
        tools_pkg = types.ModuleType("tools")
        reg = types.ModuleType("tools.delegate_tool_registry")
        reg.get_subagent_attribution = lambda tid: {"subagent_id": tid} if tid == "sa-1-deadbeef" else None
        tools_pkg.delegate_tool_registry = reg
        sys.modules["tools"] = tools_pkg
        sys.modules["tools.delegate_tool_registry"] = reg
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for k, v in self._old_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def _hooks(self):
        spec3 = importlib.util.spec_from_file_location("agentbus_wake_plugin", os.path.abspath(PLUGIN))
        assert spec3 is not None and spec3.loader is not None
        mod = importlib.util.module_from_spec(spec3)
        spec3.loader.exec_module(mod)

        class Ctx:
            def __init__(self):
                self.hooks = {}

            def register_hook(self, name, cb, **kw):
                self.hooks[name] = cb

        ctx = Ctx()
        mod.register(ctx)
        return ctx.hooks

    def test_top_level_task_id_uses_env_name(self):
        # finding 3: a top-level turn carries a fresh uuid task_id
        # (agent/turn_context.py:589); it must not override AGENTBUS_AGENT
        hooks = self._hooks()
        out = hooks["transform_tool_result"](task_id="8f9c-turn-uuid", result="tool output")
        self.assertIn("tool output", out)
        self.assertIn("FOR_PARENT", out)  # addressed to env w-mgr
        self.assertIsNone(hooks["transform_tool_result"](task_id="8f9c-turn-uuid", result="tool output"))

    def test_child_task_id_is_the_bus_name(self):
        # finding 3: an in-process delegate_task child's name is its task id
        hooks = self._hooks()
        out = hooks["transform_tool_result"](task_id="sa-1-deadbeef", result="tool output")
        self.assertIn("FOR_CHILD", out)
        self.assertNotIn("FOR_PARENT", out)  # the child is not w-mgr

    def test_no_name_no_output(self):
        hooks = self._hooks()
        os.environ.pop("AGENTBUS_AGENT", None)
        self.assertIsNone(hooks["transform_tool_result"](task_id="", result="x"))  # broadcast row present

    def test_catalog_result_queues_for_next_result(self):
        # finding 8: tool_search/tool_describe return before the transform
        # (model_tools.py:919-921); post_tool_call still fires there (model_tools.py:913)
        hooks = self._hooks()
        hooks["post_tool_call"](task_id="", tool_name="tool_describe", result="catalog output")
        out = hooks["transform_tool_result"](task_id="", result="next tool output")
        self.assertIn("next tool output", out)
        self.assertIn("FOR_PARENT", out)
        self.assertIsNone(hooks["transform_tool_result"](task_id="", result="again"))  # once only

    def test_queued_block_rides_next_turn_context(self):
        # finding 8: an error result also skips the transform (model_tools.py:977-979);
        # pre_llm_call delivers the block in the next turn context
        hooks = self._hooks()
        hooks["post_tool_call"](task_id="", tool_name="terminal", result="boom", status="error")
        ctx = hooks["pre_llm_call"](task_id="")
        self.assertIn("FOR_PARENT", ctx["context"])
        self.assertIsNone(hooks["pre_llm_call"](task_id=""))  # once only

    def test_queued_blocks_stay_with_their_name(self):
        # in-process children share the process: a queued child block must never
        # ride the parent's result and the other way round
        hooks = self._hooks()
        hooks["post_tool_call"](task_id="sa-1-deadbeef", tool_name="tool_describe", result="catalog")
        parent_out = hooks["transform_tool_result"](task_id="8f9c-turn-uuid", result="parent output")
        self.assertNotIn("FOR_CHILD", parent_out or "parent output")
        self.assertIn("FOR_PARENT", parent_out)  # the parent still gets its own rows
        child_out = hooks["transform_tool_result"](task_id="sa-1-deadbeef", result="child output")
        self.assertIn("FOR_CHILD", child_out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
