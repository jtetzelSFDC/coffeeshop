"""The setup steps, shared by `careeros setup` and the /setup page: choose a role and level, and check what is in
place. A check only reads (the database is opened read-only, each connector gets one cheap read) and gives up
after CHECK_TIMEOUT seconds."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass

from . import schedule
from .config import DataDir
from .guide.service import SETUP_HINT, import_guide, level, read_profile, save_level

CHECK_TIMEOUT = 60
GOOGLE_TOOL = "mcp__plugin_google-workspace_google-workspace__list_task_lists"
SLACK_TOOL = "mcp__plugin_slack_slack__slack_read_user_profile"


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    state: str  # "pass", "fail", or "skipped"
    todo: str   # what to do; empty when it passes


def find_role(guides: list[dict], text: str) -> dict | None:
    """A role of the leveling guide by its number in the list or its name."""
    a = text.strip()
    return guides[int(a) - 1] if a.isdigit() and 1 <= int(a) <= len(guides) else \
        next((g for g in guides if g["name"].lower() == a.lower()), None)


def choose_level(s, guide: dict, grade: int) -> tuple[dict, dict, dict]:
    """Save `guide`'s role at `grade` and load the role's guide (links you made are kept): (the level picked, the
    import counts, the saved level). ValueError when the role has no such grade."""
    pick = next((l for l in guide["levels"] if l["grade"] == grade), None)
    if pick is None:
        raise ValueError(f"{guide['name']} has no Grade {grade}. "
                         f"Its grades: {', '.join(str(l['grade']) for l in guide['levels'])}.")
    r = import_guide(s, guide["items"])
    save_level(s, guide["name"], grade, pick["title"])
    return pick, r, level(s)


def _database(dd: DataDir) -> tuple[str, str]:
    if dd.is_personal and dd.db.exists():
        return "pass", ""
    return "fail", "Create your notebook: uv run careeros notebook init"


def _level(dd: DataDir) -> tuple[str, str]:
    return ("pass", "") if isinstance(read_profile(dd.root).get("grade"), int) else ("fail", f"Choose them: {SETUP_HINT}")


def _guide(dd: DataDir) -> tuple[str, str]:
    try:
        with closing(sqlite3.connect(f"{dd.db.as_uri()}?mode=ro", uri=True)) as c:
            if c.execute("SELECT 1 FROM guide_item WHERE active LIMIT 1").fetchone():
                return "pass", ""
    except sqlite3.Error:
        pass
    return "fail", f"Load your role's guide by choosing your role and level: {SETUP_HINT}"


def _v2mom(dd: DataDir) -> tuple[str, str]:
    from .v2mom import connector
    src = connector.load_source(dd)
    if src and not (src["kind"] == "pdf" and not connector.newest_pdf(src["value"])):
        return "pass", ""
    return "fail", ("Your V2MOM PDF has moved. Connect it again: uv run careeros v2mom connect <path to the PDF>"
                    if src else "Connect your V2MOM PDF: uv run careeros v2mom connect <path to the PDF>")


def _read(tool: str, prompt: str, service: str) -> tuple[str, str]:
    """One cheap read through the connector; fail with the reason when it doesn't answer."""
    from .claude_cli import ClaudeError, call_tool, connector_error
    try:
        text = call_tool(prompt, tool, timeout=CHECK_TIMEOUT)
        if err := connector_error(text, service):
            raise ClaudeError(err)
    except ClaudeError as exc:
        return "fail", str(exc)
    return "pass", ""


def _google() -> tuple[str, str]:
    return _read(GOOGLE_TOOL, "Call the list_task_lists tool exactly once. When it returns, reply with only DONE.",
                 "Google")


def _slack() -> tuple[str, str]:
    return _read(SLACK_TOOL, "Call the slack_read_user_profile tool once with no arguments. When it returns, reply "
                 "with only DONE.", "Slack")


def _github() -> tuple[str, str]:
    """Optional: not installed or not signed in is skipped, never a failure."""
    if not shutil.which("gh"):
        return "skipped", "Optional. To add pull requests: brew install gh, then gh auth login"
    try:
        ok = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=CHECK_TIMEOUT).returncode == 0
    except subprocess.TimeoutExpired:
        ok = False
    return ("pass", "") if ok else ("skipped", "Optional. To add pull requests, sign in: gh auth login")


def _schedule() -> tuple[str, str]:
    if all((schedule.AGENTS_DIR / f"{label}.plist").exists() for label in (schedule.APP, schedule.SYNC, schedule.DIGEST)):
        return "pass", ""
    return "skipped", "Optional. To sync on its own twice a day: uv run careeros schedule install"


def run_checks(dd: DataDir, skip: set[str] = frozenset()) -> list[Check]:
    """Every step in order. Keys in `skip` are not run. The steps run side by side, so the two connector reads
    take as long as one."""
    steps = [("database", "Local notebook", lambda: _database(dd)),
             ("level", "Role and level saved", lambda: _level(dd)),
             ("guide", "Leveling guide loaded", lambda: _guide(dd)),
             ("v2mom", "V2MOM connected", lambda: _v2mom(dd)),
             ("google", "Google connector reachable", _google),
             ("slack", "Slack connector reachable", _slack),
             ("github", "GitHub signed in (optional)", _github),
             ("schedule", "Schedule installed (optional)", _schedule)]

    def run(step) -> Check:
        key, label, fn = step
        state, todo = ("skipped", "Skipped. Add it later by running setup again.") if key in skip else fn()
        return Check(key, label, state, todo)

    with ThreadPoolExecutor(len(steps)) as ex:
        return list(ex.map(run, steps))
