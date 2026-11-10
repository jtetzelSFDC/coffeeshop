"""The daily three: the context Claude reads, strict checks on its answer, and saving once a day (fake Claude)."""
import json
from datetime import date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from coffeeshop import daily
from coffeeshop.claude_cli import ClaudeError
from coffeeshop.cli import app as cli
from coffeeshop.sync_all import _daily_due as _real_daily_due
from coffeeshop.storage.models import DailyTask, JournalAttachment, JournalEntry, WorkItem

from helpers import fake_syncs, link, load_v2mom, open_session


TODAY = date.today()


def setup(dd, with_v2mom=True):
    with open_session(dd) as s:
        e = JournalEntry(day=(TODAY - timedelta(days=2)).isoformat(), kind="meeting", text="Release go/no-go for 4.2",
                         created_at=datetime.now(), source="calendar", status="")
        s.add(e)
        s.flush()
        s.add(JournalAttachment(entry_id=e.id, kind="notes", title="Gemini notes", body="SECRET NOTES TEXT",
                                created_at=datetime.now()))
        s.commit()
        if with_v2mom:
            load_v2mom(s)


def reply(goal_ids, n=3, minutes=5, text="Write a two-line summary of the 4.2 go/no-go"):
    return "Sure:\n" + json.dumps({"tasks": [dict(text=text, minutes=minutes, goal=goal_ids[i % len(goal_ids)],
                                                  why="Moves this goal a step.") for i in range(n)]})


def test_context_has_goals_and_recent_titles_but_never_notes(nb):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        data = daily.context(s, TODAY)
    ids = [g["id"] for g in data["goals"]]
    assert "V2MOM M1" in ids and "V2MOM M2" in ids
    assert any(i.startswith("Grade 6: ") for i in ids) and any(i.startswith("Skill: ") for i in ids)
    assert any("Release go/no-go for 4.2" in r for r in data["week"]["meetings"])
    assert "SECRET NOTES TEXT" not in json.dumps(data) and len(json.dumps(data)) <= daily.MAX_CONTEXT


def test_context_has_this_weeks_meetings_open_tasks_and_projects(nb):
    dd, *_ = nb
    setup(dd)
    day = lambda n: (TODAY - timedelta(days=n)).isoformat()
    with open_session(dd) as s:
        wi = WorkItem(title="Pine 5.1.2 release", day=day(1), started=day(3), created_at=datetime.now())
        old = WorkItem(title="Old Elm cutover", day=day(30), started=day(31), created_at=datetime.now())
        s.add_all([wi, old,
                   JournalEntry(day=day(1), kind="task", text="Update the Pine runbook", created_at=datetime.now(),
                                status="open"),
                   JournalEntry(day=day(10), kind="meeting", text="Old Elm retro", created_at=datetime.now()),
                   JournalEntry(day=day(3), kind="task", text="Merged the Pine branch", created_at=datetime.now(),
                                status="done")])
        s.commit()
        data = daily.context(s, TODAY)
    wk = data["week"]
    assert wk["projects"] == ["Pine 5.1.2 release"] and wk["open_tasks"] == [f"{day(1)}: Update the Pine runbook"]
    assert wk["meetings"] == [f"{day(2)}: Release go/no-go for 4.2"]  # last week's retro is too old
    assert any("Old Elm retro" in r for r in data["recent"])  # still inside the two weeks
    assert not any("Release go/no-go" in r or "runbook" in r for r in data["recent"])  # each title appears once
    assert any("Merged the Pine branch" in r for r in data["recent"]) and not data["few_records"]


def test_a_new_user_with_almost_no_records_still_gets_a_valid_prompt(nb):
    dd, *_ = nb
    with open_session(dd) as s:
        load_v2mom(s)
        data = daily.context(s, TODAY)
        assert data["week"] == dict(meetings=[], open_tasks=[], projects=[]) and data["recent"] == []
        assert data["few_records"] and data["goals"]
        ids = [g["id"] for g in data["goals"]]
        seen = []
        tasks = daily.suggest(s, TODAY, reader=lambda p, d: seen.append(p) or reply(ids))
    assert len(tasks) == 3 and tasks[0].goal in ids
    assert "Never invent" in seen[0] and "few_records" in seen[0] and "lean on the goals themselves" in seen[0]


def test_a_good_answer_saves_three_once_a_day(nb):
    dd, *_ = nb
    setup(dd)
    seen = []
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        tasks = daily.suggest(s, TODAY, reader=lambda p, d: seen.append(d) or reply(ids))
        assert [t.position for t in tasks] == [1, 2, 3] and tasks[0].goal == ids[0] and tasks[0].minutes == 5
        again = daily.suggest(s, TODAY, reader=lambda p, d: pytest.fail("asked twice"))
        assert [t.id for t in again] == [t.id for t in tasks] and len(seen) == 1


@pytest.mark.parametrize("bad", [
    lambda ids: reply(ids, n=2),
    lambda ids: reply(ids, minutes=15),
    lambda ids: reply(ids, text="x" * 200),
    lambda ids: reply(["Not a goal we offered"]),
    lambda ids: "I can't do that",
])
def test_a_bad_answer_raises_and_saves_nothing(nb, bad):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        with pytest.raises(ClaudeError, match="didn't fit"):
            daily.suggest(s, TODAY, reader=lambda p, d: bad(ids))
        assert s.query(DailyTask).count() == 0


def test_force_replaces_every_task_and_keeps_the_logged_one(nb):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        first = daily.suggest(s, TODAY, reader=lambda p, d: reply(ids, text="First idea"))
        e = daily.check(s, first[1])
        eid = e.id
        new = daily.suggest(s, TODAY, force=True, reader=lambda p, d: reply(ids, text="Second idea"))
        assert [t.text for t in new] == ["Second idea"] * 3 and all(t.done_at is None for t in new)
        assert [t.position for t in new] == [1, 2, 3] and s.get(JournalEntry, eid) is not None


def test_no_v2mom_still_works_from_the_guide_and_no_goals_at_all_is_a_clear_error(nb, tmp_path):
    dd, *_ = nb
    setup(dd, with_v2mom=False)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        assert ids and not any(i.startswith("V2MOM") for i in ids)
        assert len(daily.suggest(s, TODAY, reader=lambda p, d: reply(ids))) == 3
    from coffeeshop.config import DataDir
    from coffeeshop.storage.db import init_db, make_engine, make_session_factory
    empty = DataDir(tmp_path / "empty")
    empty.init_personal()
    engine = make_engine(empty.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        with pytest.raises(ClaudeError, match="no goals"):
            daily.suggest(s, TODAY, reader=lambda p, d: pytest.fail("shouldn't ask"))


def test_cli_suggest_and_show(nb, monkeypatch):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
    monkeypatch.setattr(daily, "ask", lambda p, d, timeout=0: reply(ids))
    r = CliRunner().invoke(cli, ["daily", "suggest", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert r.output.count("[ ] Write a two-line summary") == 3 and "~5 min" in r.output
    shown = CliRunner().invoke(cli, ["daily", "show", "--data-dir", str(dd.root)]).output
    assert shown.count("[ ]") == 3
    monkeypatch.setattr(daily, "ask", lambda p, d, timeout=0: "nope")
    r = CliRunner().invoke(cli, ["daily", "suggest", "--force", "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "No new tasks today" in r.output


def test_context_keeps_recent_work_even_when_goals_are_many(nb, monkeypatch):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        s.add(JournalEntry(day=TODAY.isoformat(), kind="task", text="Shared a template", created_at=datetime.now(),
                           status="done"))
        s.commit()
    many = [dict(id=f"Skill: {i} " + "x" * 300, what="y" * 300, state="no evidence yet") for i in range(60)]
    monkeypatch.setattr(daily, "goals", lambda s, today: many)
    with open_session(dd) as s:
        data = daily.context(s, TODAY)
    assert data["recent"] and len(data["goals"]) <= daily.MAX_GOALS and len(json.dumps(data)) <= daily.MAX_CONTEXT


def test_quiet_v2mom_methods_come_before_on_track_ones(nb):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        from coffeeshop.v2mom import store
        m1, m2 = store.methods(s)
        m2.measures = [dict(text="Ship one template", status="On Track", progress=None, comments="")]
        e = JournalEntry(day=TODAY.isoformat(), kind="task", text="Shared a template", created_at=datetime.now(),
                         status="done")
        s.add(e)
        s.flush()
        link(s, m2.id, entry_id=e.id)  # M2 is active (work today); M1 has nothing linked
        s.commit()
        ids = [g["id"] for g in daily.goals(s, TODAY)]
    assert ids.index("V2MOM M1") < ids.index("V2MOM M2")
    aim = next(i for i, g in enumerate(ids) if g.startswith("Grade "))
    assert ids.index("V2MOM M1") < aim < ids.index("V2MOM M2")


def test_force_with_all_three_done_asks_for_a_new_three(nb):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        for t in daily.suggest(s, TODAY, reader=lambda p, d: reply(ids)):
            t.done_at = datetime.now()
        s.commit()
        new = daily.suggest(s, TODAY, force=True, reader=lambda p, d: reply(ids, text="Next idea"))
        assert [t.text for t in new] == ["Next idea"] * 3 and all(t.done_at is None for t in new)


def test_two_runs_at_once_keep_one_three(nb):
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]

    def racing(p, d):  # while this run waits on Claude, another run saves today's three
        with open_session(dd) as other:
            daily.suggest(other, TODAY, reader=lambda p2, d2: reply(ids, text="The other run"))
        return reply(ids, text="This run")
    with open_session(dd) as s:
        tasks = daily.suggest(s, TODAY, reader=racing)
        assert [t.text for t in tasks] == ["The other run"] * 3 and s.query(DailyTask).count() == 3


def test_a_successful_run_lights_the_daily_chip(nb):
    from coffeeshop.storage.sync_log import status
    dd, *_ = nb
    setup(dd)
    with open_session(dd) as s:
        assert status(s)["daily"]["ok"] is False and "morning sync" in status(s)["daily"]["hint"]
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        daily.suggest(s, TODAY, reader=lambda p, d: reply(ids))
        st = status(s)["daily"]
        assert st["ok"] is True and st["added"] == 3


def test_the_morning_sync_suggests_the_three_last_once_a_day(nb, monkeypatch):
    from coffeeshop import sync_all
    dd, *_ = nb
    setup(dd)
    calls = fake_syncs(monkeypatch)
    monkeypatch.setattr(sync_all, "_daily_due", _real_daily_due)  # fake sources, but the real daily step
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
    order = []
    monkeypatch.setattr(daily, "ask", lambda p, d, timeout=0: order.append("daily") or reply(ids))
    notes = []
    at = datetime.combine(TODAY, datetime.min.time()).replace(hour=8, minute=1)
    assert sync_all.run(dd, force=True, now=at, notify=lambda *a: notes.append(a)) == 0 and not notes
    assert calls[-1] == "github" and order == ["daily"]  # after every source
    with open_session(dd) as s:
        assert len(daily.today_tasks(s, TODAY)) == 3
    sync_all.run(dd, force=True, now=at.replace(hour=18), notify=lambda *a: notes.append(a))
    assert order == ["daily"]  # already done today
    log = next((dd.root / "logs").glob("sync-*.log")).read_text()
    assert "Daily three: Suggest today's three tasks: done (3 tasks for today)" in log


def test_no_daily_three_before_8_and_a_failure_notifies(nb, monkeypatch):
    from coffeeshop import sync_all
    dd, *_ = nb
    setup(dd)
    fake_syncs(monkeypatch)
    monkeypatch.setattr(sync_all, "_daily_due", _real_daily_due)
    monkeypatch.setattr(daily, "ask", lambda p, d, timeout=0: "not json")
    notes = []
    early = datetime.combine(TODAY, datetime.min.time()).replace(hour=7, minute=30)
    sync_all.run(dd, force=True, now=early, notify=lambda *a: notes.append(a))
    assert not notes
    assert sync_all.run(dd, force=True, now=early.replace(hour=8), notify=lambda *a: notes.append(a)) == 1
    assert len(notes) == 1 and "Daily three" in notes[0][0] and "didn't fit" in notes[0][1]
    with open_session(dd) as s:
        assert s.query(DailyTask).count() == 0


def test_a_notebook_without_goals_never_runs_the_daily_step(tmp_path):
    from coffeeshop.config import DataDir
    from coffeeshop.storage.db import init_db, make_engine, make_session_factory
    dd = DataDir(tmp_path / "empty")
    dd.init_personal()
    engine = make_engine(dd.db)
    init_db(engine)
    nine = datetime.combine(TODAY, datetime.min.time()).replace(hour=9)
    assert _real_daily_due(make_session_factory(engine), nine) is False


def _web(nb):
    from coffeeshop.web.app import create_app
    from starlette.testclient import TestClient
    dd, *_ = nb
    app = create_app(dd)
    return TestClient(app, base_url="http://127.0.0.1"), app.state.csrf_token


def _three(dd):
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        return [t.id for t in daily.suggest(s, TODAY, reader=lambda p, d: reply(ids))]


def test_home_card_shows_three_ticks_and_the_empty_state(nb):
    dd, *_ = nb
    setup(dd)
    c, _ = _web(nb)
    home = c.get("/").text
    assert "Today's Three" in home and "No three yet today" in home and 'data-label="Suggest now"' in home
    _three(dd)
    home = c.get("/").text
    assert home.count('aria-label="Mark done: Write a two-line summary') == 3 and "~5 min" in home
    assert 'data-label="New three"' in home and home.index('aria-label="Progress"') < home.index("Today's Three")


def test_checking_off_a_task_starts_claude_reading_it(nb, monkeypatch):
    import time
    from coffeeshop.web import syncs
    dd, *_ = nb
    setup(dd)
    ran = []
    monkeypatch.setattr(syncs, "run_review", lambda j, S: (ran.append(1), j.finish("ok")))
    c, tok = _web(nb)
    c.post(f"/daily/{_three(dd)[0]}/done", data={"csrf": tok})
    for _ in range(50):
        if ran:
            break
        time.sleep(0.02)
    assert ran


def test_done_logs_a_record_with_details_and_undo_keeps_your_note(nb):
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    tid = _three(dd)[0]
    assert c.post(f"/daily/{tid}/done", data={"details": "x"}).status_code == 403  # CSRF
    r = c.post(f"/daily/{tid}/done", data={"csrf": tok, "details": "Sent it to the team channel."},
               follow_redirects=False)
    assert r.status_code == 303
    with open_session(dd) as s:
        t = s.get(DailyTask, tid)
        e = s.get(JournalEntry, t.entry_id)
        assert t.done_at and (e.kind, e.status, e.source, e.text) == ("task", "done", "daily", t.text)
        assert s.query(JournalAttachment).filter_by(entry_id=e.id, body="Sent it to the team channel.").count() == 1
        eid = e.id
    home = c.get("/").text
    assert 'aria-label="Mark not done: Write a two-line summary' in home
    c.post(f"/daily/{tid}/done", data={"csrf": tok})  # a double press
    c.post(f"/daily/{tid}/undo", data={"csrf": tok})
    with open_session(dd) as s:
        assert s.get(DailyTask, tid).done_at is None and s.get(JournalEntry, eid) is not None  # it has your note
    c.post(f"/daily/{tid}/done", data={"csrf": tok})
    with open_session(dd) as s:
        assert s.query(JournalEntry).filter_by(source="daily").count() == 1 and s.get(DailyTask, tid).entry_id == eid


def test_undo_without_a_note_takes_the_record_back(nb):
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    tid = _three(dd)[0]
    c.post(f"/daily/{tid}/done", data={"csrf": tok})
    with open_session(dd) as s:
        eid = s.get(DailyTask, tid).entry_id
    c.post(f"/daily/{tid}/undo", data={"csrf": tok})
    with open_session(dd) as s:
        assert s.get(DailyTask, tid).done_at is None and s.get(JournalEntry, eid) is None


def test_removing_its_record_unlinks_the_task_so_undo_cant_hit_a_reused_id(nb):
    from coffeeshop.storage.removal import remove_entry
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    tid = _three(dd)[0]
    c.post(f"/daily/{tid}/done", data={"csrf": tok})
    with open_session(dd) as s:
        eid = s.get(DailyTask, tid).entry_id
        remove_entry(s, eid)
        s.add(JournalEntry(id=eid, day=TODAY.isoformat(), kind="meeting", text="Planning", created_at=datetime.now()))
        s.commit()
    c.post(f"/daily/{tid}/undo", data={"csrf": tok})
    with open_session(dd) as s:
        assert s.get(JournalEntry, eid).text == "Planning" and s.get(DailyTask, tid).entry_id is None


def test_undo_keeps_a_record_you_already_checked(nb):
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    tid = _three(dd)[0]
    c.post(f"/daily/{tid}/done", data={"csrf": tok})
    with open_session(dd) as s:
        e = s.get(JournalEntry, s.get(DailyTask, tid).entry_id)
        e.reviewed = True
        s.commit()
        eid = e.id
    c.post(f"/daily/{tid}/undo", data={"csrf": tok})
    with open_session(dd) as s:
        assert s.get(DailyTask, tid).done_at is None and s.get(JournalEntry, eid) is not None


def test_all_three_done_and_the_suggest_button_starts_a_job(nb, monkeypatch):
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    for tid in _three(dd):
        c.post(f"/daily/{tid}/done", data={"csrf": tok})
    home = c.get("/").text
    assert "All three done. Nice." in home and 'data-label="New three"' in home
    started = []
    monkeypatch.setattr("coffeeshop.web.syncs.run_daily",
                        lambda job, S, lock, force=False: (started.append(force), job.finish("ok")))
    assert c.post("/daily/suggest", data={"csrf": tok, "force": "1"}, headers={"X-Sync": "1"}).json() == {"started": True}
    import time
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started == [True]


def test_the_prompt_asks_for_shorter_lines_than_validate_allows():
    import re
    text, why = map(int, re.findall(r"at most (\d+) characters", daily.PROMPT))
    assert text < daily.MAX_TEXT and why < daily.MAX_WHY


def test_untick_keeps_a_record_you_linked_yourself(nb):
    from sqlalchemy import select
    from coffeeshop.storage.models import GuideItem, GuideLink
    dd, *_ = nb
    setup(dd)
    tid = _three(dd)[0]
    with open_session(dd) as s:
        t = s.get(DailyTask, tid)
        e = daily.check(s, t)
        item = s.scalar(select(GuideItem).limit(1))
        s.add(GuideLink(item_id=item.id, entry_id=e.id, created_at=datetime.now(), by_ai=False))
        s.commit()
        daily.uncheck(s, t)
        assert s.get(JournalEntry, e.id) is not None and t.done_at is None


def test_new_three_reloads_when_done_unless_a_box_has_text():
    """Runs sync.js against a fake page: done reloads once and Today's three opens; text in a box does not."""
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    assert node, "node is required to run sync.js"
    r = subprocess.run([node, str(Path(__file__).with_name("sync_reload.js"))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
