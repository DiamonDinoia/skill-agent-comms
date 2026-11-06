#!/usr/bin/env python3
"""Unit tests for the agentbus wake hook: cursor, broadcast, no-op, corruption, latency.

Run: python3 test_wake.py
The module under test comes from ../wake.py unless AGENTBUS_WAKE_MODULE points at
a copy (mutation checks). Always run the suite with `env -u AGENTBUS_WAKE_MODULE`.
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTBUS_DIR = os.path.abspath(os.path.join(HERE, ".."))
WAKE_MODULE = os.environ.get("AGENTBUS_WAKE_MODULE") or os.path.join(AGENTBUS_DIR, "wake.py")
WAKE_CLI = os.path.join(AGENTBUS_DIR, "agentbus-wake")
WAKE_HOOK = os.path.join(AGENTBUS_DIR, "hooks", "wake-hook.py")
BUSCLI = os.path.join(AGENTBUS_DIR, "agentbus-cli")

spec = importlib.util.spec_from_file_location("wake_under_test", WAKE_MODULE)
assert spec is not None and spec.loader is not None
wake_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake_mod)


def make_db(tmp, rows=()):
    db = os.path.join(tmp, "bus.db")
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


class HermesPluginTest(unittest.TestCase):
    """Contract test for the Hermes user plugin adapter (live run is UNRUN, see evidence)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agentbus-test.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = make_db(self.tmp, [("m", "b1", "hello-from-mgr"), ("m", "*", "wave")])
        self._old = {k: os.environ.get(k) for k in ("AGENTBUS_DB", "AGENTBUS_AGENT")}
        os.environ["AGENTBUS_DB"] = self.db
        os.environ["AGENTBUS_AGENT"] = "w-mgr"
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _hook(self):
        path = os.path.join(AGENTBUS_DIR, "..", "hermes-plugin", "agentbus-wake", "__init__.py")
        spec = importlib.util.spec_from_file_location("agentbus_wake_plugin", os.path.abspath(path))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        class Ctx:
            def __init__(self):
                self.hooks = {}

            def register_hook(self, name, cb, **kw):
                self.hooks[name] = cb

        ctx = Ctx()
        mod.register(ctx)
        return ctx.hooks["transform_tool_result"]

    def test_task_id_wins_over_env_and_rows_append_once(self):
        cb = self._hook()
        out = cb(task_id="b1", result="tool output")
        self.assertIn("tool output", out)
        self.assertIn("hello-from-mgr", out)  # addressed to task_id b1, not to env w-mgr
        self.assertIsNone(cb(task_id="b1", result="tool output"))  # once only

    def test_no_name_no_output(self):
        cb = self._hook()
        os.environ.pop("AGENTBUS_AGENT", None)
        self.assertIsNone(cb(task_id="", result="x"))  # broadcast row is present, no name means no output


if __name__ == "__main__":
    unittest.main(verbosity=2)
