"""`careeros sync all`: back up, then run the same Slack, Google and GitHub syncs as the buttons, with a log.
Once a month it also re-reads the V2MOM and re-estimates the KSOs, and once a day (from 8 AM) it suggests the daily
three, last, so it sees the fresh work.

Run by the scheduled task at 8 AM and 6 PM and at login. A run that's already covered by an earlier one since
the latest scheduled time does nothing, so the login catch-up is cheap.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, time, timedelta
from typing import Callable

try:
    import fcntl
except ImportError:  # Windows has no fcntl; the lock uses msvcrt instead
    fcntl = None

from sqlalchemy import func, select

from .backup import make_backup, prune
from .config import DataDir
from .storage.db import init_db, make_engine, make_session_factory
from .storage.models import SyncRun
from .web import syncs
from .web.jobs import Job

TIMES = (time(8, 0), time(18, 0))
DAILY_FROM = time(8, 0)  # the daily three come with the first sync of the day from 8 AM on
SOURCES = ("slack", "calendar")  # each sync's sign of a successful pull
LOCKED = 2  # exit code when another sync holds the lock


def last_scheduled(now: datetime) -> datetime:
    today = [datetime.combine(now.date(), t) for t in TIMES if datetime.combine(now.date(), t) <= now]
    return today[-1] if today else datetime.combine(now.date() - timedelta(days=1), TIMES[-1])


def mac_notify(title: str, message: str) -> None:
    """A macOS notification (quoted for AppleScript); never fails the sync."""
    def q(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.run(["osascript", "-e", f"display notification {q(message[:220])} with title {q(title[:80])}"],
                       check=False, capture_output=True, timeout=10)
    except subprocess.SubprocessError:  # a stuck notification shouldn't fail a finished sync
        pass


# Title and body stay in the environment, so a quote in the message can't change the script.
_TOAST = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipTitle = $env:COFFEESHOP_NOTIFY_TITLE
$n.BalloonTipText = $env:COFFEESHOP_NOTIFY_BODY
$n.Visible = $true
$n.ShowBalloonTip(8000)
# The balloon is never drawn unless a window message loop is running.
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 3000
$timer.add_Tick({ $timer.Stop(); $n.Dispose(); [System.Windows.Forms.Application]::Exit() })
$timer.Start()
[System.Windows.Forms.Application]::Run()
"""


def _windows_toast(title: str, message: str) -> None:
    """A Windows balloon. Raises if PowerShell can't show it."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    powershell = root + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    env = os.environ.copy()
    env["COFFEESHOP_NOTIFY_TITLE"] = title[:80]
    env["COFFEESHOP_NOTIFY_BODY"] = message[:220]
    proc = subprocess.run(
        [powershell, "-NoProfile", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", _TOAST],
        check=False, capture_output=True, timeout=15, text=True, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        raise OSError((proc.stderr or proc.stdout or "toast failed").strip())


def desktop_notify(title: str, message: str) -> str | None:
    """A notification. On Windows a blocked toast returns a log line and does not raise."""
    if sys.platform != "win32":
        mac_notify(title, message)
        return None
    try:
        _windows_toast(title, message)
    except (OSError, subprocess.SubprocessError) as exc:
        line = f"Notification skipped: {exc}"
        logging.getLogger(__name__).warning("%s", line)
        return line
    return None


def _lock_windows(lock_file) -> None:
    """Exclusive non-blocking lock. Raises BlockingIOError when another sync holds it."""
    import msvcrt
    lock_file.seek(0, 2)
    if lock_file.tell() == 0:
        lock_file.write(b" ")  # msvcrt.locking needs a byte, and the file opened in binary mode
        lock_file.flush()
    lock_file.seek(0)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno not in (13, 16, 36):  # EACCES, EBUSY, EDEADLK: someone else holds the byte
            raise
        raise BlockingIOError(exc.errno or 0, "sync already running") from exc


def _covered(Session_, since: datetime) -> bool:
    with Session_() as s:
        return all((s.scalar(select(func.max(SyncRun.at)).where(SyncRun.source == src)) or datetime.min) >= since
                   for src in SOURCES)


def _daily_due(Session_, now: datetime) -> bool:
    """From the 8 AM sync on, until today's three exist, and only with goals to aim at (a guide or a V2MOM). The
    login and 6 PM runs catch a morning the computer was off."""
    from . import daily
    if now.time() < DAILY_FROM:
        return False
    with Session_() as s:
        return not daily.today_tasks(s, now.date()) and bool(daily.goals(s, now.date()))


def _kso_due(Session_, now: datetime) -> bool:
    from .kso import estimate
    with Session_() as s:
        return estimate.due(s, now)


def _v2mom_due(dd: DataDir, Session_, now: datetime) -> bool:
    """Monthly, and only once a V2MOM PDF or Doc is connected."""
    from .v2mom import connector, store
    if not connector.load_source(dd):
        return False
    with Session_() as s:
        return store.due(s, now)


def run(dd: DataDir, *, force: bool = False, now: datetime | None = None,
        notify: Callable[..., object] = desktop_notify) -> int:
    """0 if everything synced (or nothing was due), 1 if any step failed."""
    now = now or datetime.now()
    logs = dd.root / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    engine = make_engine(dd.db)
    init_db(engine)
    Session_ = make_session_factory(engine)
    lock_file = (logs / "sync.lock").open("w" if fcntl is not None else "a+b")
    try:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            _lock_windows(lock_file)
    except BlockingIOError:  # another sync (login catch-up, or the 6 PM run) is still going
        lock_file.close()
        return LOCKED
    except Exception:
        lock_file.close()
        raise
    log = (logs / f"sync-{now:%Y-%m-%d}.log").open("a")

    def say(line: str) -> None:
        log.write(f"{datetime.now():%H:%M:%S}  {line}\n")
        log.flush()

    try:
        if not force and _covered(Session_, last_scheduled(now)):
            say("Already synced since the last scheduled time; nothing to do.")
            return 0
        failed = []
        try:
            say(f"Backup: {make_backup(dd).name} ({prune(dd)} old copies removed)")
        except (OSError, sqlite3.Error) as exc:  # a full disk shouldn't stop the syncs, but it must be noticed
            say(f"Backup failed: {exc}")
            failed.append(("Backup", f"The backup failed ({exc}). Check the disk has space."))
        lock = threading.Lock()
        runs = [("Slack", syncs.SLACK_STEPS, lambda j: syncs.run_slack(j, Session_, lock, dd)),
                ("Google", syncs.GOOGLE_STEPS, lambda j: syncs.run_google(j, Session_, lock)),
                ("GitHub", syncs.GITHUB_STEPS, lambda j: syncs.run_github(j, Session_, lock))]
        if _v2mom_due(dd, Session_, now):
            runs.append(("V2MOM", syncs.V2MOM_STEPS, lambda j: syncs.run_v2mom(j, Session_, lock, dd)))
        if _kso_due(Session_, now):  # after the V2MOM, so it reads this month's progress
            runs.append(("KSO estimate", syncs.KSO_STEPS, lambda j: syncs.run_kso(j, Session_, lock)))
        if _daily_due(Session_, now):  # last, so the three see the work just synced
            runs.append(("Daily three", syncs.DAILY_STEPS, lambda j: syncs.run_daily(j, Session_, lock)))
        for name, steps, fn in runs:
            job = Job(steps)
            try:
                fn(job)
            except Exception as exc:  # one broken sync shouldn't stop the other
                job.finish(f"{name} sync stopped early: {exc}")
                job.state = "error"
            for st in job.steps:
                say(f"{name}: {st['label']}: {st['state']}" + (f" ({st['detail']})" if st["detail"] else ""))
            say(f"{name}: {job.message}")
            if job.state in ("error", "partial"):
                reason = next((st["detail"] for st in job.steps if st["state"] == "error"), job.message)
                failed.append((name, reason))
        for name, reason in failed:
            note = notify(f"Coffee Shop: {name} sync needs a look", reason)
            if isinstance(note, str):
                say(note)
        return 1 if failed else 0
    finally:
        log.close()
        lock_file.close()
