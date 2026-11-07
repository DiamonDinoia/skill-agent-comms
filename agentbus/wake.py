"""Wake-on-message: the text block a harness hook appends to a tool result.

One call returns the bus rows addressed to NAME or to * that are newer than the
name's own cursor, then advances the cursor so each row is shown once per agent.
No name means no output. Any error means no output, so the hook can never fail
the tool call it rides on. A held lock means no output this time: the unchanged
cursor delivers on the next call.
"""
import fcntl
import hashlib
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from busdb import resolve_db  # noqa: E402

MAX_ROWS = 50
# the hook rides a tool call with a 100 ms budget; the SQLite busy handler gets at
# most half of it, so a held database lock can never stall the call
BUSY_TIMEOUT_S = 0.05


def cursor_path(db, name):
    # the key derives from the exact agent name and the canonical database path,
    # so a symlink alias of one database shares one cursor and one lock;
    # a:b and a/b never share a cursor, and one name on two databases keeps
    # two cursors
    real = os.path.realpath(db)  # a missing file keeps its name under the parent realpath
    key = hashlib.sha256(
        ("%s\x00%s" % (real, name)).encode("utf-8", "surrogateescape")).hexdigest()
    return os.path.join(os.path.dirname(real) or ".", "cursors", key)


def _lock(path):
    """Nonblocking exclusive flock beside the cursor: the fd, or None when another call holds it."""
    lock = path + ".lock"
    fd = None
    try:
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        if fd is not None:
            os.close(fd)
        return None


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
    fd = None
    try:
        name = (name if name is not None else env.get("AGENTBUS_AGENT", "") or "").strip()
        if not name:
            return None
        db = db or resolve_db(env)
        if not os.path.isfile(db):
            return None
        cursor = cursor_path(db, name)
        # one nonblocking lock per (database, agent) makes read-query-update atomic,
        # so two concurrent sessions can never show one row twice
        fd = _lock(cursor)
        if fd is None:
            return None
        last = _read_cursor(cursor)
        c = sqlite3.connect(db, timeout=BUSY_TIMEOUT_S)
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
    finally:
        if fd is not None:  # close releases the flock
            try:
                os.close(fd)
            except OSError:
                pass
