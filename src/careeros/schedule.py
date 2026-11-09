"""Scheduled tasks. On macOS, three launch agents. On Windows, three Task Scheduler tasks.
One keeps the app running, one runs `careeros sync all` at 8 AM, 6 PM, and login,
and one shows the weekly digest notification on Fridays at noon."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

from .config import DATA_DIR_ENV, DataDir

APP, SYNC, DIGEST = "com.careeros.app", "com.careeros.sync", "com.careeros.digest"
DIGEST_AT = {"Weekday": 5, "Hour": 12, "Minute": 0}  # Friday 12:00 PM; a missed one runs on wake
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
REPO = Path(__file__).resolve().parents[2]
PATH = ":".join([str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"])


BOOTSTRAP_TRIES = 5
pause = time.sleep


def launchctl(*args: str) -> int:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True).returncode


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Couldn't find the `uv` command; install it or run this from a Terminal where `uv` works.")
    return str(Path(uv).resolve())


def plists(dd: DataDir, uv: str, repo: Path = REPO) -> dict[str, dict]:
    """The three launchd agents: the app (kept running), the sync (8 AM, 6 PM, login) and the Friday digest."""
    logs = dd.root / "logs"
    base = ["run", "--project", str(repo), "careeros"]
    env = {"PATH": PATH, DATA_DIR_ENV: str(dd.root)}
    return {
        APP: dict(Label=APP, ProgramArguments=[uv, *base, "serve"], WorkingDirectory=str(repo), RunAtLoad=True,
                  KeepAlive=True, EnvironmentVariables=env, StandardOutPath=str(logs / "app.log"),
                  StandardErrorPath=str(logs / "app.log")),
        SYNC: dict(Label=SYNC, ProgramArguments=[uv, *base, "sync", "all"], WorkingDirectory=str(repo),
                   RunAtLoad=True, StartCalendarInterval=[{"Hour": 8, "Minute": 0}, {"Hour": 18, "Minute": 0}],
                   EnvironmentVariables=env, StandardOutPath=str(logs / "sync-agent.log"),
                   StandardErrorPath=str(logs / "sync-agent.log")),
        DIGEST: dict(Label=DIGEST, ProgramArguments=[uv, *base, "digest", "notify"], WorkingDirectory=str(repo),
                     StartCalendarInterval=[DIGEST_AT], EnvironmentVariables=env,
                     StandardOutPath=str(logs / "digest-agent.log"), StandardErrorPath=str(logs / "digest-agent.log")),
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(dd: DataDir, agents_dir: Path = AGENTS_DIR, uv: str | None = None, repo: Path = REPO) -> list[Path]:
    """Install the three scheduled tasks (launchd on Mac, Task Scheduler on Windows). Returns the files written."""
    if sys.platform == "win32":
        return _install_windows(dd, uv or _uv(), repo)
    (dd.root / "logs").mkdir(mode=0o700, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for label, spec in plists(dd, uv or _uv(), repo).items():
        path = agents_dir / f"{label}.plist"
        launchctl("bootout", f"{_domain()}/{label}")
        path.write_bytes(plistlib.dumps(spec))
        for attempt in range(BOOTSTRAP_TRIES):  # bootout returns before the old copy has fully stopped
            if launchctl("bootstrap", _domain(), str(path)) == 0:
                break
            if attempt < BOOTSTRAP_TRIES - 1:
                pause(1)
        else:
            raise RuntimeError(f"macOS wouldn't load {path.name}. Run `launchctl print {_domain()}/{label}` for details.")
        written.append(path)
    return written


def uninstall(agents_dir: Path = AGENTS_DIR) -> list[Path]:
    """Unload and delete the scheduled tasks."""
    if sys.platform == "win32":
        return _uninstall_windows()
    removed = []
    for label in (APP, SYNC, DIGEST):
        launchctl("bootout", f"{_domain()}/{label}")
        path = agents_dir / f"{label}.plist"
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def status(dd: DataDir, agents_dir: Path = AGENTS_DIR) -> list[str]:
    """One line per task (on, installed but not loaded, or off) and the end of the latest sync log."""
    if sys.platform == "win32":
        return _status_windows(dd)
    lines = []
    for label, what in ((APP, "Keeps the app running"), (SYNC, "Syncs at 8 AM, 6 PM, and login"),
                        (DIGEST, "Weekly digest on Fridays at noon")):
        installed = (agents_dir / f"{label}.plist").exists()
        loaded = installed and launchctl("print", f"{_domain()}/{label}") == 0
        lines.append(f"{what}: {'on' if loaded else 'installed but not loaded' if installed else 'off'}")
    if (line := _sync_log_line(dd)):
        lines.append(line)
    return lines


def _sync_log_line(dd: DataDir) -> str | None:
    logs = sorted((dd.root / "logs").glob("sync-2*.log"))
    if not logs:
        return None
    last = [l for l in logs[-1].read_text().splitlines() if l.strip()]
    return f"Last sync log ({logs[-1].name}): {last[-1] if last else 'empty'}"


def schtasks(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["schtasks", *args], capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"Couldn't run schtasks ({exc}).") from exc


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _powershell() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _task_script(data: Path, uv: str, repo: Path, args: list[str], log: Path) -> str:
    """Set the notebook folder, then run uv the same way the Mac agents do. Exit with uv's code so a crash counts."""
    return "\n".join([
        f"$env:{DATA_DIR_ENV} = {_ps_quote(str(data))}",
        f"& {_ps_quote(uv)} run --project {_ps_quote(str(repo))} careeros {' '.join(args)} *>> {_ps_quote(str(log))}",
        "exit $LASTEXITCODE",
        "",
    ])


def _daily_trigger(hour: int) -> str:
    # The date only anchors the clock time; 08:00 and 18:00 are local, every day.
    return (
        "    <CalendarTrigger>\n"
        f"      <StartBoundary>2026-01-01T{hour:02d}:00:00</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>\n"
        "    </CalendarTrigger>\n"
    )


_LOGON = "    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>\n"
# 2026-01-02 is a Friday, so the boundary matches the weekday Windows uses.
_FRIDAY = (
    "    <CalendarTrigger>\n"
    "      <StartBoundary>2026-01-02T12:00:00</StartBoundary>\n"
    "      <Enabled>true</Enabled>\n"
    "      <ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Friday/></DaysOfWeek></ScheduleByWeek>\n"
    "    </CalendarTrigger>\n"
)


def _task_xml(command: str, arguments: str, workdir: str, triggers: str, *, restart: bool) -> str:
    # Count is an unsigned byte, so 255 is the most times Task Scheduler will restart the app after a crash.
    # USERNAME is the Windows account. Without it, schtasks may refuse the task XML.
    user = os.environ.get("USERNAME") or ""
    user_xml = f"      <UserId>{escape(user)}</UserId>\n" if user else ""
    restart_xml = ("    <RestartOnFailure><Interval>PT1M</Interval><Count>255</Count></RestartOnFailure>\n"
                   if restart else "")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
{triggers}  </Triggers>
  <Principals>
    <Principal id="Author">
{user_xml}      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
{restart_xml}  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _windows_tasks(dd: DataDir, uv: str, repo: Path) -> list[tuple[str, str, str, bool]]:
    """(label, script, xml, start now). The app restarts after a crash; a clean exit waits for the next logon."""
    logs = dd.root / "logs"
    ps = _powershell()
    jobs = (
        (APP, ["serve"], logs / "app.log", _LOGON, True, True),
        (SYNC, ["sync", "all"], logs / "sync-agent.log", _LOGON + _daily_trigger(8) + _daily_trigger(18), False, True),
        (DIGEST, ["digest", "notify"], logs / "digest-agent.log", _FRIDAY, False, False),
    )
    out = []
    for label, args, log, triggers, restart, run_now in jobs:
        script = _task_script(dd.root, uv, repo, args, log)
        script_path = dd.root / "tasks" / f"{label}.ps1"
        arguments = f'-NoProfile -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "{script_path}"'
        xml = _task_xml(ps, arguments, str(repo), triggers, restart=restart)
        out.append((label, script, xml, run_now))
    return out


def _schtasks_failed(result: subprocess.CompletedProcess, label: str, what: str) -> RuntimeError:
    detail = (result.stderr or result.stdout or "schtasks failed").strip()
    return RuntimeError(f"Windows wouldn't {what} {label}. {detail}")


def _install_windows(dd: DataDir, uv: str, repo: Path) -> list[Path]:
    (dd.root / "logs").mkdir(mode=0o700, exist_ok=True)
    tasks = dd.root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    written = []
    for label, script, xml, run_now in _windows_tasks(dd, uv, repo):
        script_path = tasks / f"{label}.ps1"
        xml_path = tasks / f"{label}.xml"
        script_path.write_text(script, encoding="utf-8-sig")  # PowerShell 5.1 reads a BOM
        xml_path.write_text(xml, encoding="utf-16")  # schtasks rejects UTF-8 task XML
        schtasks("/End", "/TN", label)  # stop a copy from the previous install; missing is fine
        created = schtasks("/Create", "/TN", label, "/XML", str(xml_path), "/F")
        if created.returncode != 0:
            raise _schtasks_failed(created, label, "schedule")
        if run_now:
            for attempt in range(BOOTSTRAP_TRIES):
                started = schtasks("/Run", "/TN", label)
                if started.returncode == 0:
                    break
                if attempt < BOOTSTRAP_TRIES - 1:
                    pause(1)
            else:
                raise _schtasks_failed(started, label, "start")
        written.append(script_path)
    return written


def _uninstall_windows() -> list[Path]:
    removed = []
    for label in (APP, SYNC, DIGEST):
        schtasks("/End", "/TN", label)
        deleted = schtasks("/Delete", "/TN", label, "/F")
        if deleted.returncode == 0:
            removed.append(Path(label))
    return removed


def _status_windows(dd: DataDir) -> list[str]:
    lines = []
    for label, what in ((APP, "Keeps the app running"), (SYNC, "Syncs at 8 AM, 6 PM, and login"),
                        (DIGEST, "Weekly digest on Fridays at noon")):
        result = schtasks("/Query", "/TN", label, "/XML")
        # <Enabled> is not translated; "Disabled" in /FO LIST is, so a French PC would look on.
        if result.returncode != 0:
            state = "off"
        elif "<Enabled>false</Enabled>" in (result.stdout or ""):
            state = "installed but not loaded"
        else:
            state = "on"
        lines.append(f"{what}: {state}")
    if (line := _sync_log_line(dd)):
        lines.append(line)
    return lines
