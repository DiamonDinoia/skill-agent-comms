"""Resolve the agentbus SQLite path for the server, the CLI and the wake hook.

Rule: AGENTBUS_DB if set; else a local-disk path when $HOME sits on a network
filesystem (SQLite WAL over NFS is unsafe); else ~/.local/share/agentbus/bus.db.
"""
import os

# filesystem types where SQLite WAL is unsafe
_NET_FS = {"cifs", "smbfs", "smb", "ncpfs", "afs", "sshfs", "fuse.sshfs"}


def mount_fstype(path):
    """Best-matching mount fstype for path from /proc/mounts, or None."""
    best, best_len = None, -1
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = parts[1].replace("\\040", " ")
                if (path == mp or path.startswith(mp.rstrip("/") + "/")) and len(mp) > best_len:
                    best, best_len = parts[2], len(mp)
    except OSError:
        pass
    return best


def is_network_fs(path):
    fstype = (mount_fstype(path) or "").lower()
    return fstype.startswith("nfs") or fstype in _NET_FS


def ensure_db_dir(db):
    """Create the database's parent directory with private permissions (writers only)."""
    d = os.path.dirname(os.path.abspath(db))
    if d:
        os.makedirs(d, mode=0o700, exist_ok=True)


def resolve_db(env=None):
    """AGENTBUS_DB, else a local path when HOME is on a network fs, else the XDG data path."""
    env = os.environ if env is None else env
    explicit = env.get("AGENTBUS_DB")
    if explicit:
        return explicit
    home = env.get("HOME") or os.path.expanduser("~")
    if is_network_fs(home):
        runtime = env.get("XDG_RUNTIME_DIR")
        if runtime and not is_network_fs(runtime):
            return os.path.join(runtime, "agentbus", "bus.db")
        return os.path.join("/var/tmp", "agentbus-%d" % os.getuid(), "bus.db")
    return os.path.join(home, ".local", "share", "agentbus", "bus.db")
