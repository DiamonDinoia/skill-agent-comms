#!/usr/bin/env python3
"""Agent-messaging MCP server. Stdio transport, one SQLite file.

Env:
  AGENTBUS_DB     SQLite file path, required.
  AGENTBUS_AGENT  Fallback identity when a call passes an empty `me`, default "anon".

Identity: each call carries `me` (the caller's own name). Under the multiplex
gateway the daemon owns this server process, so per-launch env never reaches it.
"""
import asyncio
import os
import sqlite3
import sys
import time

from mcp.server.mcpserver import MCPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from busdb import resolve_db

DB = resolve_db()
AGENT = os.environ.get("AGENTBUS_AGENT", "anon")
# clamp: the per-server `timeout: 3600` in CONFIG.md ends every call before this bound
MAX_WAIT_S = 3500
# covers a model repeating the same tool call in one turn, measured in e2e-final/carol.log where the repeat came within the same turn
REUSE_ANSWER_S = 300

mcp = MCPServer("agentbus")

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents(name TEXT PRIMARY KEY, pid INT, last_seen REAL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, sender TEXT, rcpt TEXT, body TEXT, ts REAL, read_at REAL);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, sender TEXT, body TEXT, answer TEXT, created REAL, answered_ts REAL);
CREATE UNIQUE INDEX IF NOT EXISTS questions_open_uniq ON questions(sender, body) WHERE answered_ts IS NULL;
"""


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")  # before the WAL pragma below: the busy handler does not cover the journal-mode change
    for n in range(5):
        try:
            c.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError as e:
            if "database is locked" not in str(e) or n == 4:
                raise
            time.sleep(0.2)
    c.executescript(SCHEMA)  # every connect: re-creates the schema after the DB file was deleted
    if "read_at" not in [r[1] for r in c.execute("PRAGMA table_info(messages)")]:
        try:
            c.execute("ALTER TABLE messages ADD COLUMN read_at REAL")  # migrate DBs from before consume-once
        except sqlite3.OperationalError as e:
            # a racing db() added the column first; anything else is a real failure
            if "duplicate column name" not in str(e):
                raise
    return c


def init():
    with db() as c:
        c.execute("INSERT OR REPLACE INTO agents VALUES(?,?,?)", (AGENT, os.getpid(), time.time()))


@mcp.tool()
def send(to: str, body: str, me: str = "") -> str:
    """Send a message to another agent. me = your agent name, given in your brief."""
    sender = me or AGENT
    with db() as c:
        cur = c.execute("INSERT INTO messages(sender, rcpt, body, ts) VALUES(?,?,?,?)",
                        (sender, to, body, time.time()))
        return f"sent id={cur.lastrowid}"


@mcp.tool()
async def inbox(wait_s: float = 30, me: str = "") -> str:
    """Return messages addressed to you. Each message is consumed on read.

    me = your agent name, given in your brief.
    """
    who = me or AGENT
    deadline = time.monotonic() + min(wait_s, MAX_WAIT_S)
    while True:
        with db() as c:
            rows = c.execute(
                "UPDATE messages SET read_at=? WHERE rcpt=? AND read_at IS NULL"
                " RETURNING id, sender, body, ts", (time.time(), who)).fetchall()
        if rows:
            return "\n".join(f"[{i}] from={s} body={b}" for i, s, b, _ in sorted(rows))
        if time.monotonic() >= deadline:
            return "no messages"
        await asyncio.sleep(0.5)


@mcp.tool()
async def ask_parent(question: str, timeout_s: float = 600, me: str = "") -> str:
    """Ask the manager a question. Call it once per question; it blocks until the manager answers.

    A repeat call matches on me plus the exact question text. The match is exact. Case and spacing count.
    While the question is open, the repeat call waits on the same question and makes no new question.
    The answer is remembered. A repeat call on a question answered less than 300 s ago returns the same answer at once.
    When the answer is 300 s old or more, or after a timeout, the same text is a new question.
    me = your agent name, given in your brief.
    Returns the answer text, or one of three TIMEOUT forms: `TIMEOUT after Xs (question id=N, no answer)`, `TIMEOUT: question id=N expired after X.Xs`, `TIMEOUT: question id=N is gone`.
    """
    who = me or AGENT
    timeout_s = min(timeout_s, MAX_WAIT_S)
    while True:
        with db() as c:
            # dedupe on (me, question text); an expired row or an answer 300 s old or more does not count
            row = c.execute("SELECT id, answer, answered_ts, created FROM questions WHERE sender=? AND body=?"
                            " AND (answered_ts IS NULL OR answered_ts > ?)"
                            " ORDER BY id DESC LIMIT 1",
                            (who, question, time.time() - REUSE_ANSWER_S)).fetchone()
            if row and row[2] is None:  # open: wait on the same row
                qid, created = row[0], row[3]
            elif row and row[1] is not None:  # answered inside the reuse window: return at once
                return row[1]
            else:  # no row, an expired one, or a stale answer: ask fresh
                created = time.time()
                cur = c.execute("INSERT INTO questions(sender, body, created) VALUES(?,?,?)"
                                " ON CONFLICT DO NOTHING", (who, question, created))
                if cur.rowcount:
                    qid = cur.lastrowid
                else:  # a concurrent call inserted the open row first (unique index above)
                    row = c.execute("SELECT id, created FROM questions WHERE sender=? AND body=?"
                                    " AND answered_ts IS NULL", (who, question)).fetchone()
                    if row is None:
                        # that row closed in between (answered or expired): rerun the lookup above
                        continue
                    qid, created = row
            break
    start = time.monotonic()
    deadline = start + timeout_s
    # row identity: after a DB delete the ids restart at 1, so the id alone can belong to another question
    where = "WHERE id=? AND sender=? AND body=? AND created=?"
    ident = (qid, who, question, created)
    # shortcut: 2 s SQLite poll instead of notifications, fine below one
    # hundred agents; upgrade to a Unix socket push if latency matters.
    while True:
        with db() as c:
            row = c.execute(f"SELECT answer, answered_ts FROM questions {where}", ident).fetchone()
        if row is None:  # the row vanished or a new row took the id: end the wait, never a crash
            return f"TIMEOUT: question id={qid} is gone"
        if row[0] is not None:
            return row[0]
        if row[1] is not None:
            # a co-waiter expired the row: say so, do not claim the own timeout
            return f"TIMEOUT: question id={qid} expired after {time.monotonic() - start:.1f}s"
        if time.monotonic() >= deadline:
            with db() as c:
                # expire the row: closed with NULL answer, so pending drops it
                cur = c.execute(f"UPDATE questions SET answered_ts=? {where} AND answered_ts IS NULL",
                                (time.time(),) + ident)
                if cur.rowcount == 0:
                    # closed first: an answer won the race, or a co-waiter expired the row
                    row = c.execute(f"SELECT answer FROM questions {where}", ident).fetchone()
                    if row is None:  # the row vanished or a new row took the id: end the wait, never a crash
                        return f"TIMEOUT: question id={qid} is gone"
                    if row[0] is not None:  # return it like a normal answer
                        return row[0]
            break
        await asyncio.sleep(2)
    return f"TIMEOUT after {timeout_s}s (question id={qid}, no answer)"


@mcp.tool()
def answer(id: int, text: str) -> str:
    """Answer an open question by id. The manager path; the CLI does the same."""
    with db() as c:
        cur = c.execute("UPDATE questions SET answer=?, answered_ts=? WHERE id=? AND answered_ts IS NULL",
                        (text, time.time(), id))
        if cur.rowcount == 0:
            return f"no open question with id={id}"
        return f"answered id={id}"


@mcp.tool()
def list_agents() -> str:
    """List agents that have registered (process-level names)."""
    with db() as c:
        rows = c.execute("SELECT name, pid, last_seen FROM agents ORDER BY name").fetchall()
    if not rows:
        return "no agents"
    return "\n".join(f"{n} pid={p} last_seen={int(ls)}" for n, p, ls in rows)


if __name__ == "__main__":
    init()
    mcp.run(transport="stdio")
