"""Wake-on-message: the text block a harness hook appends to a tool result.

One call returns the bus rows addressed to NAME or to * that are newer than the
name's own cursor, then advances the cursor so each row is shown once per agent.
No name means no output. Any error means no output, so the hook can never fail
the tool call it rides on.
"""
import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from busdb import resolve_db  # noqa: E402

MAX_ROWS = 50


def cursor_path(db, name):
    return os.path.join(os.path.dirname(os.path.abspath(db)) or ".", "cursors", re.sub(r"[^A-Za-z0-9._-]", "_", name))


def _read_cursor(path):
    try:
        with open(path) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _write_cursor(path, last_id):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        f.write(str(last_id))
    os.replace(tmp, path)


def wake(db=None, name=None, env=None):
    """Rows block for NAME, or None. Advances the cursor past every row shown."""
    env = os.environ if env is None else env
    try:
        name = (name if name is not None else env.get("AGENTBUS_AGENT", "") or "").strip()
        if not name:
            return None
        db = db or resolve_db(env)
        if not os.path.isfile(db):
            return None
        cursor = cursor_path(db, name)
        last = _read_cursor(cursor)
        c = sqlite3.connect(db, timeout=30)
        try:
            rows = c.execute(
                "SELECT id, sender, rcpt, body, ts FROM messages"
                " WHERE id > ? AND (rcpt = ? OR rcpt = '*') ORDER BY id LIMIT ?",
                (last, name, MAX_ROWS)).fetchall()
        finally:
            c.close()
        if not rows:
            return None
        out = "\n".join(
            "[bus %d] %s %s->%s: %s" % (i, time.strftime("%H:%M:%S", time.localtime(ts)), s, r, b)
            for i, s, r, b, ts in rows)
        # advance before returning: a failed cursor write must not show rows twice
        _write_cursor(cursor, rows[-1][0])
        return "[agentbus: new messages]\n" + out
    except Exception:
        return None
