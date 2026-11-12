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
import select
import sqlite3
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from busdb import ensure_db_dir, resolve_db  # noqa: E402

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


def wake(db=None, name=None, env=None, strict=False):
    """Rows block for NAME, or None. Advances the cursor past every row shown.

    strict=True raises every error except the ones a concurrent writer causes.
    """
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
    except Exception as e:
        # a writer that locks the database or is creating its tables writes next,
        # and that write wakes a waiter, so only these errors may pass in strict mode
        if strict and not (isinstance(e, sqlite3.OperationalError)
                           and ("locked" in str(e) or "no such table" in str(e))):
            raise
        return None
    finally:
        if fd is not None:  # close releases the flock
            try:
                os.close(fd)
            except OSError:
                pass


IN_MODIFY, IN_Q_OVERFLOW, IN_IGNORED = 0x2, 0x4000, 0x8000
_EVENT = struct.Struct("iIII")  # struct inotify_event: wd, mask, cookie, len, then name[len]


def _inotify(directory):
    """inotify fd that reports IN_MODIFY on the files of directory. Linux only."""
    import ctypes  # here, not at the top: the PostToolUse hook imports this module on every tool call

    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, "inotify_init1"):
        raise OSError("agentbus wait needs Linux inotify")
    fd = libc.inotify_init1(os.O_CLOEXEC)
    if fd < 0 or libc.inotify_add_watch(fd, os.fsencode(directory), IN_MODIFY) < 0:
        err = ctypes.get_errno()
        if fd >= 0:
            os.close(fd)
        raise OSError(err, "inotify on %s: %s" % (directory, os.strerror(err)))
    return fd


def _bus_written(buf, names):
    """True when an event in buf is a write to one of names, or lost events may hide one."""
    off = 0
    while off < len(buf):
        _, mask, _, n = _EVENT.unpack_from(buf, off)
        off += _EVENT.size
        if mask & IN_IGNORED:
            raise OSError("the bus directory was removed")
        if mask & IN_Q_OVERFLOW or buf[off:off + n].rstrip(b"\0") in names:
            return True
        off += n
    return False


def wait(timeout_s=None, db=None, name=None, env=None):
    """Block until wake() has rows for NAME, then return the block.

    timeout_s None waits with no deadline; otherwise None comes back at the deadline.

    The wait sleeps on an inotify write event of the database or its WAL, never on a
    timer. Only the main file, -wal and -journal count: a reader writes the -shm file,
    so a -shm event would wake the waiter on its own read.
    """
    env = os.environ if env is None else env
    db = os.path.realpath(db or resolve_db(env))
    ensure_db_dir(db)
    base = os.fsencode(os.path.basename(db))
    names = {base, base + b"-wal", base + b"-journal"}
    fd = _inotify(os.path.dirname(db))
    try:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            # the watch exists before this read, so a row sent after the read wakes select
            block = wake(db=db, name=name, env=env, strict=True)
            if block:
                return block
            while True:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return None
                if select.select([fd], [], [], left)[0] and _bus_written(os.read(fd, 65536), names):
                    break
    finally:
        os.close(fd)
