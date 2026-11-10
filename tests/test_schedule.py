import plistlib
import subprocess
import sys
import types
from datetime import date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from careeros import config, schedule, sync_all
from careeros.cli import app as cli
from careeros.config import DataDir
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import SyncRun

from helpers import fake_syncs


@pytest.fixture
def dd(tmp_path):
    d = DataDir(tmp_path / "nb")
    d.init_personal()
    init_db(make_engine(d.db))
    return d


def test_sync_all_backs_up_runs_each_and_logs(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 0
    assert calls == ["slack", "google", "github"] and not notes
    assert list(dd.backups.glob("coffeeshop-*.db"))
    log = next((dd.root / "logs").glob("sync-*.log")).read_text()
    assert "slack synced" in log and "google synced" in log and "backup" in log.lower()


def test_failure_notifies_and_exits_nonzero(dd, monkeypatch):
    fake_syncs(monkeypatch, fail="slack")
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 1
    assert len(notes) == 1 and "Slack" in notes[0][0] and "sign in again" in notes[0][1].lower()


def test_catch_up_is_a_no_op_after_a_covered_run(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)
    with make_session_factory(make_engine(dd.db))() as s:
        for src in ("slack", "calendar"):
            s.add(SyncRun(source=src, at=datetime(2026, 10, 28, 18, 5), added=0))
        s.commit()
    assert sync_all.run(dd, now=datetime(2026, 10, 28, 21, 0), notify=lambda *a: None) == 0
    assert calls == []  # 6 PM run already happened
    assert sync_all.run(dd, now=datetime(2026, 10, 29, 9, 0), notify=lambda *a: None) == 0
    assert calls == ["slack", "google", "github"]  # 8 AM not covered yet


def test_sync_all_waits_out_a_save_in_the_running_app(dd, monkeypatch):
    import sqlite3
    import threading
    import time
    fake_syncs(monkeypatch)
    app = sqlite3.connect(dd.db, check_same_thread=False)
    app.execute("BEGIN IMMEDIATE")  # the app is in the middle of a save

    def finish_save():
        time.sleep(1)
        app.commit()
    t = threading.Thread(target=finish_save)
    t.start()
    try:
        assert sync_all.run(dd, force=True, notify=lambda *a: None) == 0
    finally:
        t.join()
        app.close()
    with make_session_factory(make_engine(dd.db))() as s:
        assert s.query(SyncRun).count() == 3


def test_last_scheduled_time():
    at = sync_all.last_scheduled
    assert at(datetime(2026, 10, 28, 7, 59)) == datetime(2026, 10, 27, 18, 0)
    assert at(datetime(2026, 10, 28, 8, 0)) == datetime(2026, 10, 28, 8, 0)
    assert at(datetime(2026, 10, 28, 17, 59)) == datetime(2026, 10, 28, 8, 0)
    assert at(datetime(2026, 10, 28, 18, 30)) == datetime(2026, 10, 28, 18, 0)


def test_notification_text_is_escaped(monkeypatch):
    seen = []
    monkeypatch.setattr(sync_all.subprocess, "run", lambda args, **kw: seen.append(args))
    sync_all.mac_notify('Slack "sync"', 'it said \\ "no"')
    assert seen[0][0] == "osascript" and '\\"sync\\"' in seen[0][2] and '\\\\' in seen[0][2]


def test_plists_have_absolute_paths_and_the_right_schedule(dd, tmp_path):
    agents = schedule.plists(dd, uv="/opt/uv", repo=Path("/repo"))
    app, sync = agents[schedule.APP], agents[schedule.SYNC]
    assert app["ProgramArguments"] == ["/opt/uv", "run", "--project", "/repo", "careeros", "serve"]
    assert app["KeepAlive"] is True and app["RunAtLoad"] is True and app["WorkingDirectory"] == "/repo"
    assert sync["ProgramArguments"][-2:] == ["sync", "all"]
    assert sync["StartCalendarInterval"] == [{"Hour": 8, "Minute": 0}, {"Hour": 18, "Minute": 0}]
    assert sync["RunAtLoad"] is True and "KeepAlive" not in sync
    assert str(dd.root / "logs") in app["StandardErrorPath"]
    assert "/.local/bin" in app["EnvironmentVariables"]["PATH"]
    assert app["EnvironmentVariables"]["COFFEESHOP_DATA_DIR"] == str(dd.root)


def test_install_and_uninstall_write_and_remove_only_their_files(dd, tmp_path, monkeypatch):
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir()
    (agents_dir / "com.other.plist").write_text("keep me")
    ran = []
    monkeypatch.setattr(schedule, "launchctl", lambda *args: ran.append(args) or 0)
    schedule.install(dd, agents_dir=agents_dir, uv="/opt/uv", repo=Path("/repo"))
    files = sorted(p.name for p in agents_dir.glob("com.careeros.*.plist"))
    assert files == ["com.careeros.app.plist", "com.careeros.digest.plist", "com.careeros.sync.plist"]
    digest = plistlib.loads((agents_dir / "com.careeros.digest.plist").read_bytes())
    assert digest["StartCalendarInterval"] == [{"Weekday": 5, "Hour": 12, "Minute": 0}] and "RunAtLoad" not in digest
    assert digest["ProgramArguments"][-2:] == ["digest", "notify"]
    assert plistlib.loads((agents_dir / "com.careeros.sync.plist").read_bytes())["Label"] == "com.careeros.sync"
    assert any(a[0] == "bootstrap" for a in ran)
    schedule.uninstall(agents_dir=agents_dir)
    assert not list(agents_dir.glob("com.careeros.*")) and (agents_dir / "com.other.plist").exists()
    assert any(a[0] == "bootout" for a in ran)


def test_a_signed_out_connector_gets_a_plain_message(monkeypatch):
    import json as _json
    from types import SimpleNamespace
    from careeros import claude_cli
    init = {"type": "system", "subtype": "init", "mcp_servers": [
        {"name": "plugin:google-workspace:google-workspace", "status": "failed"},
        {"name": "plugin:slack:slack", "status": "connected"}]}
    monkeypatch.setattr(claude_cli, "_claude", lambda: "claude")
    monkeypatch.setattr(claude_cli.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=_json.dumps(init) + "\n", stderr=""))
    with pytest.raises(claude_cli.ClaudeError, match="Google Workspace connector isn't signed in"):
        claude_cli.call_tool("x", "mcp__plugin_google-workspace_google-workspace__list_task_lists")
    with pytest.raises(claude_cli.ClaudeError, match="didn't get an answer"):  # Slack is up; a different problem
        claude_cli.call_tool("x", "mcp__plugin_slack_slack__slack_read_canvas")


def test_reinstall_waits_for_the_old_copy_to_stop(dd, tmp_path, monkeypatch):
    agents_dir = tmp_path / "LaunchAgents"
    tries = []

    def launchctl(*args):
        if args[0] == "bootstrap":
            tries.append(args[-1])
            return 5 if len(tries) <= 2 else 0  # macOS refuses while the old copy is still unloading
        return 0
    monkeypatch.setattr(schedule, "launchctl", launchctl)
    monkeypatch.setattr(schedule, "pause", lambda s: None)
    assert len(schedule.install(dd, agents_dir=agents_dir, uv="/opt/uv", repo=Path("/repo"))) == 3
    assert len(tries) == 5  # two refusals, then the app, sync and digest agents load
    monkeypatch.setattr(schedule, "launchctl", lambda *a: 5 if a[0] == "bootstrap" else 0)
    with pytest.raises(RuntimeError, match="wouldn't load"):
        schedule.install(dd, agents_dir=agents_dir, uv="/opt/uv", repo=Path("/repo"))


def test_cli_sync_all_refuses_practice_notebook(tmp_path):
    d = DataDir(tmp_path / "practice")
    d.init_demo()
    r = CliRunner().invoke(cli, ["sync", "all", "--data-dir", str(d.root)])
    assert r.exit_code == 1 and "personal notebook" in r.output


def test_status_shows_the_dated_sync_log_not_the_launchd_one(dd, monkeypatch):
    monkeypatch.setattr(schedule, "launchctl", lambda *a: 1)
    logs = dd.root / "logs"
    logs.mkdir()
    (logs / "sync-2026-10-28.log").write_text("18:00:09  Google: Google synced\n")
    (logs / "sync-agent.log").write_text("launchd noise\n")
    assert "Google synced" in schedule.status(dd)[-1]


def test_install_says_so_when_macos_refuses_to_load_an_agent(dd, tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "launchctl", lambda *args: 1 if args[0] == "bootstrap" else 0)
    with pytest.raises(RuntimeError, match="wouldn't load"):
        schedule.install(dd, agents_dir=tmp_path / "LaunchAgents", uv="/opt/uv", repo=Path("/repo"))


def test_a_crashing_sync_does_not_stop_the_other_and_notifies(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)

    def crash(job, Session_, lock, *rest):
        raise ValueError("canvas exploded")
    monkeypatch.setattr(sync_all.syncs, "run_slack", crash)
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 1
    assert calls == ["google", "github"] and len(notes) == 1 and "Slack" in notes[0][0]


def test_a_second_sync_exits_while_one_is_running(dd, monkeypatch):
    import fcntl
    calls = fake_syncs(monkeypatch)
    (dd.root / "logs").mkdir()
    with (dd.root / "logs" / "sync.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert sync_all.run(dd, force=True, notify=lambda *a: None) == sync_all.LOCKED
    assert calls == []


def test_a_stuck_notification_is_ignored(monkeypatch):
    def hang(*a, **k):
        raise sync_all.subprocess.TimeoutExpired("osascript", 10)
    monkeypatch.setattr(sync_all.subprocess, "run", hang)
    sync_all.mac_notify("t", "m")


def test_cli_install_prints_the_error_instead_of_a_traceback(dd, monkeypatch):
    def refuse(*a, **k):
        raise RuntimeError("macOS wouldn't load it")
    monkeypatch.setattr(schedule, "install", refuse)
    r = CliRunner().invoke(cli, ["schedule", "install", "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "wouldn't load" in r.output and "Traceback" not in r.output


def test_mac_data_dir_is_unchanged(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(config.Path, "home", lambda: Path("/Users/jordan"))
    assert config.support_dir("coffeeshop") == Path("/Users/jordan/Library/Application Support/coffeeshop")
    assert config.support_dir("coffeeshop-demo") == Path("/Users/jordan/Library/Application Support/coffeeshop-demo")
    assert config.notebook_default_help() == "Default: ~/Library/Application Support/coffeeshop"


def test_windows_data_dir_uses_localappdata(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\steve\AppData\Local")
    assert config.support_dir("coffeeshop") == Path(r"C:\Users\steve\AppData\Local") / "coffeeshop"
    assert config.support_dir("coffeeshop-demo") == Path(r"C:\Users\steve\AppData\Local") / "coffeeshop-demo"
    assert config.notebook_default_help() == r"Default: %LOCALAPPDATA%\coffeeshop"


def test_windows_data_dir_falls_back_when_localappdata_is_missing(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(config.Path, "home", lambda: Path(r"C:\Users\steve"))
    assert config.support_dir("coffeeshop") == Path(r"C:\Users\steve") / "AppData" / "Local" / "coffeeshop"


def _schtasks(monkeypatch, code=0, stdout="", stderr=""):
    ran = []

    def fake(*args):
        ran.append(args)
        return subprocess.CompletedProcess(["schtasks", *args], code, stdout, stderr)
    monkeypatch.setattr(schedule, "schtasks", fake)
    return ran


def test_windows_schedule_builds_schtasks_commands(dd, monkeypatch):
    monkeypatch.setattr(schedule.sys, "platform", "win32")
    ran = _schtasks(monkeypatch)
    uv, repo = r"C:\Tools\uv.exe", Path("C:/repo")
    written = schedule.install(dd, uv=uv, repo=repo)
    assert [p.name for p in written] == ["com.careeros.app.ps1", "com.careeros.sync.ps1", "com.careeros.digest.ps1"]
    creates = [a for a in ran if a[0] == "/Create"]
    assert [a[2] for a in creates] == [schedule.APP, schedule.SYNC, schedule.DIGEST]
    assert all(a[1] == "/TN" and a[3] == "/XML" and a[-1] == "/F" for a in creates)
    assert [a[2] for a in ran if a[0] == "/Run"] == [schedule.APP, schedule.SYNC]
    sync = (dd.root / "tasks" / "com.careeros.sync.ps1").read_text(encoding="utf-8-sig")
    assert f"& '{uv}' run --project '{repo}' careeros sync all" in sync
    assert "$ErrorActionPreference = 'Stop'" in sync
    assert f"$env:COFFEESHOP_DATA_DIR = '{dd.root}'" in sync and "exit $LASTEXITCODE" in sync
    xml = (dd.root / "tasks" / "com.careeros.sync.xml").read_text(encoding="utf-16")
    assert "T08:00:00" in xml and "T18:00:00" in xml and "LogonTrigger" in xml
    assert "powershell.exe" in xml and "com.careeros.sync.ps1" in xml
    app = (dd.root / "tasks" / "com.careeros.app.xml").read_text(encoding="utf-16")
    assert "RestartOnFailure" in app and "<Count>255</Count>" in app and "T08:00:00" not in app
    digest_xml = (dd.root / "tasks" / "com.careeros.digest.xml").read_text(encoding="utf-16")
    digest = (dd.root / "tasks" / "com.careeros.digest.ps1").read_text(encoding="utf-8-sig")
    assert "Friday" in digest_xml and "T12:00:00" in digest_xml and "LogonTrigger" not in digest_xml
    boundary = digest_xml.split("<StartBoundary>")[1].split("T")[0]
    assert date.fromisoformat(boundary) >= date.today() and date.fromisoformat(boundary).weekday() == 4
    assert "careeros digest notify" in digest
    removed = schedule.uninstall()
    deletes = [a for a in ran if a[0] == "/Delete"]
    assert [a[2] for a in deletes] == [schedule.APP, schedule.SYNC, schedule.DIGEST]
    assert all("/F" in a for a in deletes) and [str(p) for p in removed] == list(deletes[i][2] for i in range(3))


def test_windows_install_reports_a_schtasks_error(dd, monkeypatch):
    monkeypatch.setattr(schedule.sys, "platform", "win32")

    def fake(*args):
        if args[0] == "/Create":
            return subprocess.CompletedProcess(args, 1, "", "Access is denied.")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(schedule, "schtasks", fake)
    with pytest.raises(RuntimeError, match="wouldn't schedule"):
        schedule.install(dd, uv=r"C:\Tools\uv.exe", repo=Path("C:/repo"))


def _queried(enabled: str, trigger: str = "true") -> str:
    return (f'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            f"<Triggers><LogonTrigger><Enabled>{trigger}</Enabled></LogonTrigger></Triggers>"
            f"<Settings><Enabled>{enabled}</Enabled></Settings></Task>")


def test_windows_status_reads_schtasks_not_the_real_scheduler(dd, monkeypatch):
    monkeypatch.setattr(schedule.sys, "platform", "win32")
    seen = []

    def fake(*args):
        seen.append(args)
        label = args[2]
        if label == schedule.APP:  # a disabled trigger does not mean the task is off
            return subprocess.CompletedProcess(args, 0, _queried("true", "false"), "")
        if label == schedule.SYNC:
            return subprocess.CompletedProcess(args, 0, _queried("false"), "")
        return subprocess.CompletedProcess(args, 1, "", "not found")
    monkeypatch.setattr(schedule, "schtasks", fake)
    (dd.root / "logs").mkdir(exist_ok=True)
    (dd.root / "logs" / "sync-2026-10-28.log").write_text("18:00:09  Google: Google synced\n")
    lines = schedule.status(dd)
    assert lines[:3] == ["Keeps the app running: on", "Syncs at 8 AM, 6 PM, and login: installed but not loaded",
                         "Weekly digest on Fridays at noon: off"]
    assert "Google synced" in lines[-1]
    assert seen == [("/Query", "/TN", label, "/XML") for label in (schedule.APP, schedule.SYNC, schedule.DIGEST)]


def test_windows_paths_are_quoted_for_powershell_and_xml():
    script = schedule._task_script(Path(r"C:\O'Hare\nb"), r"C:\O'Hare\uv.exe", Path(r"C:\repo"),
                                   ["sync", "all"], Path(r"C:\O'Hare\nb\logs\sync-agent.log"))
    assert "O''Hare" in script and "O'Hare" not in script.replace("O''Hare", "")
    xml = schedule._task_xml(r"C:\Windows\powershell.exe", "arg", r"C:\repo & co", "<x/>", restart=False)
    assert "repo &amp; co" in xml and "repo & co" not in xml


def test_windows_run_retries_then_gives_up(dd, monkeypatch):
    monkeypatch.setattr(schedule.sys, "platform", "win32")
    monkeypatch.setattr(schedule, "pause", lambda s: None)
    app_runs = []

    def fake(*args):
        if args[0] == "/Run" and args[2] == schedule.APP:
            app_runs.append(1)
            return subprocess.CompletedProcess(args, 0 if len(app_runs) == 2 else 1, "", "not ready")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(schedule, "schtasks", fake)
    schedule.install(dd, uv=r"C:\Tools\uv.exe", repo=Path("C:/repo"))
    assert len(app_runs) == 2
    app_runs.clear()

    def always(*args):
        if args[0] == "/Run":
            app_runs.append(args[2])
            return subprocess.CompletedProcess(args, 1, "", "not ready")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(schedule, "schtasks", always)
    with pytest.raises(RuntimeError, match="wouldn't start"):
        schedule.install(dd, uv=r"C:\Tools\uv.exe", repo=Path("C:/repo"))
    assert app_runs == [schedule.APP] * 5  # gives up before starting the sync task


def test_friday_trigger_is_the_next_friday_not_a_past_one():
    coming = schedule._friday_trigger(datetime(2026, 11, 9, 15, 56))  # Monday
    assert "2026-11-13T12:00:00" in coming
    later = schedule._friday_trigger(datetime(2026, 11, 13, 12, 0))  # Friday just at noon
    assert "2026-11-20T12:00:00" in later
    morning = schedule._friday_trigger(datetime(2026, 11, 13, 11, 59))
    assert "2026-11-13T12:00:00" in morning


def test_mac_install_does_not_call_schtasks(dd, tmp_path, monkeypatch):
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    called = []
    monkeypatch.setattr(schedule, "schtasks", lambda *a: called.append(a))
    monkeypatch.setattr(schedule, "launchctl", lambda *a: 0)
    schedule.install(dd, agents_dir=tmp_path / "LaunchAgents", uv="/opt/uv", repo=Path("/repo"))
    assert called == []


def test_desktop_notify_on_mac_is_osascript(monkeypatch):
    monkeypatch.setattr(sync_all.sys, "platform", "darwin")
    seen = []
    monkeypatch.setattr(sync_all.subprocess, "run", lambda args, **kw: seen.append(args))
    assert sync_all.desktop_notify("t", "m") is None and seen[0][0] == "osascript"


def test_windows_toast_uses_powershell_and_keeps_the_message_out_of_the_script(monkeypatch):
    monkeypatch.setattr(sync_all.sys, "platform", "win32")
    seen = {}

    def record(args, **kw):
        seen["args"] = args
        seen["env"] = kw["env"]
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(sync_all.subprocess, "run", record)
    assert sync_all.desktop_notify('Say "hi"', "the body") is None
    assert seen["args"][0].endswith("powershell.exe") and "osascript" not in seen["args"]
    assert seen["env"]["COFFEESHOP_NOTIFY_TITLE"] == 'Say "hi"'
    assert seen["env"]["COFFEESHOP_NOTIFY_BODY"] == "the body"
    assert 'Say "hi"' not in " ".join(seen["args"][1:])


def test_windows_toast_failure_is_a_log_line_and_does_not_fail_the_sync(dd, monkeypatch):
    monkeypatch.setattr(sync_all.sys, "platform", "win32")
    fake_syncs(monkeypatch, fail="slack")

    def boom(*a, **k):
        raise OSError("blocked")
    monkeypatch.setattr(sync_all.subprocess, "run", boom)
    assert sync_all.desktop_notify("t", "m") == "Notification skipped: blocked"
    assert sync_all.run(dd, force=True) == 1
    log = next((dd.root / "logs").glob("sync-*.log")).read_text()
    assert "Notification skipped: blocked" in log


def _windows_lock(monkeypatch, exc: OSError):
    monkeypatch.setattr(sync_all, "fcntl", None)
    fake = types.ModuleType("msvcrt")
    fake.LK_NBLCK = 2
    fake.locking = lambda fd, mode, n: (_ for _ in ()).throw(exc)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)


def test_a_windows_lock_held_by_another_sync_exits(dd, monkeypatch):
    _windows_lock(monkeypatch, OSError(13, "locked"))
    calls = fake_syncs(monkeypatch)
    assert sync_all.run(dd, force=True, notify=lambda *a: None) == sync_all.LOCKED
    assert calls == []


def test_a_windows_lock_io_error_is_not_called_another_sync(dd, monkeypatch):
    _windows_lock(monkeypatch, OSError(5, "I/O error"))
    fake_syncs(monkeypatch)
    with pytest.raises(OSError, match="I/O error"):
        sync_all.run(dd, force=True, notify=lambda *a: None)


def test_a_failed_backup_notifies_and_the_syncs_still_run(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)
    monkeypatch.setattr(sync_all, "make_backup", lambda dd: (_ for _ in ()).throw(OSError("No space left on device")))
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 1
    assert calls == ["slack", "google", "github"]
    assert len(notes) == 1 and "Backup" in notes[0][0] and "No space left" in notes[0][1]
