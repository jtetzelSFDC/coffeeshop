"""Refuse staged files that look like personal data.

The pre-commit hook is a thin shell wrapper because Git for Windows runs hooks
with its own sh. This file is the check, so the same rules run on Mac and Windows.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import PurePosixPath

SUFFIXES = (
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".sqlite3",
    ".sqlite",
    ".db",
    ".pdf",
    ".csv",
    ".zip",
)
CONNECTORS = frozenset({
    ".secret",
    ".personal",
    ".demo",
    "profile.json",
    "slack_user.json",
    "slack.canvas",
    "calendar.url",
    "v2mom.json",
    "kso.json",
})
PRIVATE_DIRS = frozenset({"backups", "logs", "exports"})
LEVELING = "data/leveling/"


def refuse(path: str) -> str | None:
    """Why this path must not be committed, or None when it is fine.

    Names are compared case-insensitively: Windows (and a typical Mac volume)
    treats Notebook.DB and notebook.db as the same file. Git paths use forward
    slashes; a backslash is accepted so a Windows path still matches.
    """
    rel = path.replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    parts = tuple(part.lower() for part in PurePosixPath(rel.lstrip("/")).parts)
    if not parts:
        return None
    if any(part in PRIVATE_DIRS for part in parts[:-1]):
        return "under backups/, logs/, or exports/"
    name = parts[-1]
    if name in CONNECTORS:
        return "connector file"
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return f"*{suffix} file"
    if name.endswith(".xlsx") and not "/".join(parts).startswith(LEVELING):
        return "*.xlsx outside data/leveling/"
    return None


def staged() -> list[str]:
    """Staged paths. Deletions are kept out: removing a data file is the fix."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "-z", "--name-only", "--diff-filter=ACMR"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.buffer.write(proc.stderr or b"git diff --cached failed\n")
        raise SystemExit(proc.returncode or 1)
    return [item.decode("utf-8", "surrogateescape") for item in proc.stdout.split(b"\0") if item]


def unstage_command(paths: list[str], *, has_head: bool) -> str:
    """A command that takes these paths out of the index and leaves them on disk.

    `git restore --staged` needs a commit to reset to. With no commit yet, that
    fails, so the index entries are removed instead. `git rm --cached` on a file
    that is already tracked would stage a deletion, so it is only used then.
    """
    quoted = " ".join(shlex.quote(path) for path in paths)
    if has_head:
        return f"git restore --staged -- {quoted}"
    return f"git rm --cached -- {quoted}"


def unstage_line(paths: list[str]) -> str:
    head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], capture_output=True)
    return unstage_command(paths, has_head=head.returncode == 0)


def main() -> int:
    bad = []
    for path in staged():
        why = refuse(path)
        if why:
            bad.append((path, why))
    if not bad:
        return 0
    lines = ["These staged files look like personal data, so the commit was refused:"]
    for path, why in bad:
        lines.append(f"  {path} ({why})")
    lines.append("")
    lines.append("Unstage them with:")
    lines.append(f"  {unstage_line([path for path, _ in bad])}")
    sys.stderr.write("\n".join(lines) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
