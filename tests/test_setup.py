"""Setup: the checks (stubbed connector reads), `setup check`, and the /setup and /settings pages. Made-up data only."""
import hashlib
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from careeros import claude_cli, schedule, setup
from careeros.cli import app as cli
from careeros.config import DataDir
from careeros.guide.service import save_profile
from careeros.v2mom import connector
from careeros.web.app import create_app

from helpers import BASE, form, personal
from test_leveling import workbook  # noqa: F401  (fixture: the repo's workbook swapped for a made-up one)

REAL_CALL_TOOL = claude_cli.call_tool
GOOD = "Task lists:\n- Inbox (ID: abc)\n  Updated: 2026-10-20T10:00:00Z"
ROLE = "Widget Release Engineering"


@pytest.fixture(autouse=True)
def quiet_machine(tmp_path, monkeypatch):
    """No real gh, no real launch agents, and both connectors answering."""
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(schedule, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(claude_cli, "call_tool", lambda prompt, tool, timeout=240, stdin=None: GOOD)


def states(checks):
    return {c.key: c.state for c in checks}


def snapshot(root):
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def test_local_steps_fail_until_done_and_pass_after(tmp_path, workbook):
    dd, _ = personal(tmp_path)
    got = states(setup.run_checks(dd))
    assert [got[k] for k in ("database", "level", "guide", "v2mom")] == ["pass", "fail", "fail", "fail"]
    r = CliRunner().invoke(cli, ["setup", "level", "--role", ROLE, "--grade", "5", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    pdf = tmp_path / "v2mom.pdf"
    pdf.write_bytes(b"%PDF")
    connector.save_source(dd, str(pdf))
    got = states(setup.run_checks(dd))
    assert [got[k] for k in ("database", "level", "guide", "v2mom")] == ["pass"] * 4
    pdf.unlink()
    assert states(setup.run_checks(dd))["v2mom"] == "fail"  # the PDF moved
    assert states(setup.run_checks(DataDir(tmp_path / "nothing")))["database"] == "fail"


def test_checks_work_from_a_relative_notebook_folder(tmp_path, workbook, monkeypatch):
    dd, _ = personal(tmp_path)
    CliRunner().invoke(cli, ["setup", "level", "--role", ROLE, "--grade", "5", "--data-dir", str(dd.root)])
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(cli, ["setup", "check", "--skip", "google", "--skip", "slack", "--data-dir", "nb"])
    assert "pass    Leveling guide loaded" in r.output and "skipped Google connector reachable\n" in r.output


def test_checks_write_nothing(tmp_path, workbook):
    dd, _ = personal(tmp_path)
    CliRunner().invoke(cli, ["setup", "level", "--role", ROLE, "--grade", "5", "--data-dir", str(dd.root)])
    before = snapshot(dd.root)
    setup.run_checks(dd)
    assert snapshot(dd.root) == before and not (tmp_path / "agents").exists()


def test_connector_reads_pass_fail_and_time_out(tmp_path, monkeypatch):
    dd, _ = personal(tmp_path)
    tools = []
    monkeypatch.setattr(claude_cli, "call_tool", lambda prompt, tool, timeout=240, stdin=None:
                        tools.append((tool, timeout)) or (GOOD if "slack" in tool else "Needs authentication"))
    got = {c.key: c for c in setup.run_checks(dd)}
    assert (got["slack"].state, got["google"].state) == ("pass", "fail")
    assert "sign-in has expired" in got["google"].todo and "connector settings" in got["google"].todo
    assert sorted(t for t, _ in tools) == [setup.GOOGLE_TOOL, setup.SLACK_TOOL]
    assert all(t <= 60 for _, t in tools)  # a short timeout, not the 240 seconds a sync waits

    def hang(cmd, **kw):
        assert kw["timeout"] <= 60
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(claude_cli, "call_tool", REAL_CALL_TOOL)  # the real helper, with its subprocess stubbed
    monkeypatch.setattr(claude_cli, "_claude", lambda: "claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", hang)
    got = {c.key: c for c in setup.run_checks(dd, {"github"})}
    assert got["google"].state == got["slack"].state == "fail" and "too long" in got["slack"].todo


def test_optional_steps_skip_instead_of_failing_and_skip_leaves_a_step_out(tmp_path, monkeypatch):
    dd, _ = personal(tmp_path)
    calls = []
    monkeypatch.setattr(claude_cli, "call_tool", lambda *a, **k: calls.append(a) or GOOD)
    got = setup.run_checks(dd, {"google", "slack"})
    assert states(got) == {"database": "pass", "level": "fail", "guide": "fail", "v2mom": "fail", "google": "skipped",
                           "slack": "skipped", "github": "skipped", "schedule": "skipped"} and not calls
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    for label in (schedule.APP, schedule.SYNC, schedule.DIGEST):
        (tmp_path / "agents").mkdir(exist_ok=True)
        (tmp_path / "agents" / f"{label}.plist").write_text("")
    assert states(setup.run_checks(dd, {"google", "slack"}))["github"] == "pass"
    assert states(setup.run_checks(dd, {"google", "slack"}))["schedule"] == "pass"


def test_setup_check_prints_each_step_and_fails_when_one_does(tmp_path, workbook):
    dd, _ = personal(tmp_path)
    r = CliRunner().invoke(cli, ["setup", "check", "--skip", "google", "--data-dir", str(dd.root)])
    assert r.exit_code == 1
    assert "pass    Local notebook" in r.output and "fail    Role and level saved\n        What to do: Choose them" in r.output
    assert "skipped Google connector reachable" in r.output and "pass    Slack connector reachable" in r.output


def client(dd):
    app = create_app(dd)
    return TestClient(app, base_url=BASE), app.state.csrf_token


def test_setup_page_saves_role_and_level_through_the_shared_code(tmp_path, workbook):
    dd, _ = personal(tmp_path)
    c, tok = client(dd)
    html = c.get("/setup").text
    assert f"<option value=\"{ROLE}\"" in html and "Save my level" not in html  # pick a role to see its levels
    html = c.get("/setup", params={"role": ROLE}).text
    assert "Grade 5, Widget Engineer" in html and "Grade 7, Widget Architect" in html
    r = form(c, "/setup/level", tok, role=ROLE, grade="5")
    assert r.status_code == 303 and "Saved%3A%20Widget%20Release%20Engineering%2C%20Grade%205" in r.headers["location"]
    assert json.loads((dd.root / "profile.json").read_text())["grade"] == 5
    assert states(setup.run_checks(dd, {"google", "slack"}))["guide"] == "pass"  # the role's guide was loaded too
    assert "Saved now: Widget Release Engineering, Grade 5" in c.get("/setup").text
    r = form(c, "/setup/level", tok, role=ROLE, grade="6")  # this role has no Grade 6
    assert r.status_code == 303 and "no%20Grade%206" in r.headers["location"]
    assert json.loads((dd.root / "profile.json").read_text())["grade"] == 5


def test_setup_posts_need_the_csrf_token_and_a_personal_notebook(tmp_path, workbook):
    dd, _ = personal(tmp_path)
    c, tok = client(dd)
    assert c.post("/setup/level", data={"role": ROLE, "grade": "5"}).status_code == 403
    assert c.post("/setup/level", data={"csrf": "wrong", "role": ROLE, "grade": "5"}).status_code == 403
    assert c.post("/setup/check", data={}).status_code == 403
    assert not (dd.root / "profile.json").exists()
    practice = DataDir(tmp_path / "practice")
    practice.init_demo()
    c, tok = client(practice)
    for r in (form(c, "/setup/level", tok, role=ROLE, grade="5"), form(c, "/setup/check", tok), c.get("/setup", follow_redirects=False),
              c.get("/settings", follow_redirects=False)):
        assert r.status_code == 303 and "personal%20notebook" in r.headers["location"]
    assert not (practice.root / "profile.json").exists() and "Setup" not in c.get("/").text.split("</nav>")[0]


def test_check_button_shows_pass_fail_and_what_to_do_and_skips_what_is_unticked(tmp_path, workbook, monkeypatch):
    dd, _ = personal(tmp_path)
    c, tok = client(dd)
    monkeypatch.setattr(claude_cli, "call_tool", lambda prompt, tool, timeout=240, stdin=None:
                        GOOD if "slack" in tool else "Needs authentication")
    r = c.post("/setup/check", data={"csrf": tok, "on": ["google", "slack"]})
    html = r.text
    assert r.status_code == 200
    assert 'class="chip done">pass</span> Slack connector reachable' in html
    assert 'class="chip late">fail</span> Google connector reachable' in html and "sign-in has expired" in html
    assert "skipped</span> GitHub signed in (optional)" in html
    assert 'value="github" ' in html and 'value="github" checked' not in html  # unticked stays unticked


def test_home_banner_shows_until_a_level_is_saved_and_settings_shows_it(tmp_path, workbook):
    dd, _ = personal(tmp_path)
    c, tok = client(dd)
    assert 'href="/setup">Finish setup</a>' in c.get("/").text
    assert "Not chosen yet" in c.get("/settings").text
    form(c, "/setup/level", tok, role=ROLE, grade="5")
    assert "Finish setup" not in c.get("/").text
    html = c.get("/settings").text
    assert f"{ROLE}, Grade 5 (Widget Engineer)" in html and 'href="/setup#level">Change' in html and "Run setup again" in html
    assert 'href="/setup"' in html and 'href="/settings"' in html  # both are in the Menu
    save_profile(dd.root, grade=None)
    assert "Finish setup" in c.get("/").text
