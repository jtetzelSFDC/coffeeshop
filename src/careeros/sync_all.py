"""`careeros sync all`: back up, then run the same Slack and Google syncs as the buttons, then GitHub, with a log.
Once a month it also re-reads the V2MOM.

Run by the scheduled task at 8 AM and 6 PM and at login. A run that's already covered by an earlier one since
the latest scheduled time does nothing, so the login catch-up is cheap.
"""
from __future__ import annotations

import fcntl
import subprocess
import sqlite3
import threading
from datetime import datetime, time, timedelta
from typing import Callable

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
    def q(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.run(["osascript", "-e", f"display notification {q(message[:220])} with title {q(title[:80])}"],
                       check=False, capture_output=True, timeout=10)
    except subprocess.SubprocessError:  # a stuck notification shouldn't fail a finished sync
        pass


def _covered(Session_, since: datetime) -> bool:
    with Session_() as s:
        return all((s.scalar(select(func.max(SyncRun.at)).where(SyncRun.source == src)) or datetime.min) >= since
                   for src in SOURCES)


def _daily_due(Session_, now: datetime) -> bool:
    """From the 8 AM sync on, until today's three exist, and only with goals to aim at (a guide or a V2MOM). The
    login and 6 PM runs catch a morning the Mac was off."""
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
        notify: Callable[[str, str], None] = mac_notify) -> int:
    """0 if everything synced (or nothing was due), 1 if any step failed."""
    now = now or datetime.now()
    logs = dd.root / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    engine = make_engine(dd.db)
    init_db(engine)
    Session_ = make_session_factory(engine)
    lock_file = (logs / "sync.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:  # another sync (login catch-up, or the 6 PM run) is still going
        lock_file.close()
        return LOCKED
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
            notify(f"Career OS: {name} sync needs a look", reason)
        return 1 if failed else 0
    finally:
        log.close()
        lock_file.close()
