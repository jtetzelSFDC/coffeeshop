"""The daily three: the context Claude reads, strict checks on its answer, and saving once a day (fake Claude)."""
import json
from datetime import date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from careeros import daily
from careeros.claude_cli import ClaudeError
from careeros.cli import app as cli
from careeros.sync_all import _daily_due as _real_daily_due
from careeros.storage.models import DailyTask, JournalAttachment, JournalEntry

from test_guide import nb, session  # noqa: F401
from test_v2mom_links import load_v2mom

TODAY = date.today()


def setup(dd, with_v2mom=True):
    with session(dd) as s:
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
    with session(dd) as s:
        data = daily.context(s, TODAY)
    ids = [g["id"] for g in data["goals"]]
    assert "V2MOM M1" in ids and "V2MOM M2" in ids
    assert any(i.startswith("Grade 6: ") for i in ids) and any(i.startswith("Skill: ") for i in ids)
    assert any("Release go/no-go for 4.2" in r for r in data["recent"])
    assert "SECRET NOTES TEXT" not in json.dumps(data) and len(json.dumps(data)) <= daily.MAX_CONTEXT


def test_a_good_answer_saves_three_once_a_day(nb):
    dd, *_ = nb
    setup(dd)
    seen = []
    with session(dd) as s:
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
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        with pytest.raises(ClaudeError, match="didn't fit"):
            daily.suggest(s, TODAY, reader=lambda p, d: bad(ids))
        assert s.query(DailyTask).count() == 0


def test_force_replaces_only_the_ones_not_done(nb):
    dd, *_ = nb
    setup(dd)
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        first = daily.suggest(s, TODAY, reader=lambda p, d: reply(ids, text="First idea"))
        first[1].done_at = datetime.now()
        s.commit()
        new = daily.suggest(s, TODAY, force=True, reader=lambda p, d: reply(ids, text="Second idea"))
        assert [t.text for t in new] == ["First idea", "Second idea", "Second idea"]
        assert new[0].done_at and [t.position for t in new] == [1, 2, 3]


def test_no_v2mom_still_works_from_the_guide_and_no_goals_at_all_is_a_clear_error(nb, tmp_path):
    dd, *_ = nb
    setup(dd, with_v2mom=False)
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        assert ids and not any(i.startswith("V2MOM") for i in ids)
        assert len(daily.suggest(s, TODAY, reader=lambda p, d: reply(ids))) == 3
    from careeros.config import DataDir
    from careeros.storage.db import init_db, make_engine, make_session_factory
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
    with session(dd) as s:
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
    many = [dict(id=f"Skill: {i} " + "x" * 300, what="y" * 300, state="no evidence yet") for i in range(60)]
    monkeypatch.setattr(daily, "goals", lambda s, today: many)
    with session(dd) as s:
        data = daily.context(s, TODAY)
    assert data["recent"] and len(data["goals"]) <= daily.MAX_GOALS and len(json.dumps(data)) <= daily.MAX_CONTEXT


def test_quiet_v2mom_methods_come_before_on_track_ones(nb):
    from test_v2mom_views import link
    dd, *_ = nb
    setup(dd)
    with session(dd) as s:
        from careeros.v2mom import store
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


def test_force_with_all_three_done_doesnt_ask(nb):
    dd, *_ = nb
    setup(dd)
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        for t in daily.suggest(s, TODAY, reader=lambda p, d: reply(ids)):
            t.done_at = datetime.now()
        s.commit()
        assert len(daily.suggest(s, TODAY, force=True, reader=lambda p, d: pytest.fail("asked"))) == 3


def test_two_runs_at_once_keep_one_three(nb):
    dd, *_ = nb
    setup(dd)
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]

    def racing(p, d):  # while this run waits on Claude, another run saves today's three
        with session(dd) as other:
            daily.suggest(other, TODAY, reader=lambda p2, d2: reply(ids, text="The other run"))
        return reply(ids, text="This run")
    with session(dd) as s:
        tasks = daily.suggest(s, TODAY, reader=racing)
        assert [t.text for t in tasks] == ["The other run"] * 3 and s.query(DailyTask).count() == 3


def test_a_successful_run_lights_the_daily_chip(nb):
    from careeros.storage.sync_log import status
    dd, *_ = nb
    setup(dd)
    with session(dd) as s:
        assert status(s)["daily"]["ok"] is False and "morning sync" in status(s)["daily"]["hint"]
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        daily.suggest(s, TODAY, reader=lambda p, d: reply(ids))
        st = status(s)["daily"]
        assert st["ok"] is True and st["added"] == 3


def test_the_morning_sync_suggests_the_three_last_once_a_day(nb, monkeypatch):
    from careeros import sync_all
    from test_schedule import fake_syncs
    dd, *_ = nb
    setup(dd)
    calls = fake_syncs(monkeypatch)
    monkeypatch.setattr(sync_all, "_daily_due", _real_daily_due)  # fake sources, but the real daily step
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
    order = []
    monkeypatch.setattr(daily, "ask", lambda p, d, timeout=0: order.append("daily") or reply(ids))
    notes = []
    at = datetime.combine(TODAY, datetime.min.time()).replace(hour=8, minute=1)
    assert sync_all.run(dd, force=True, now=at, notify=lambda *a: notes.append(a)) == 0 and not notes
    assert calls[-1] == "github" and order == ["daily"]  # after every source
    with session(dd) as s:
        assert len(daily.today_tasks(s, TODAY)) == 3
    sync_all.run(dd, force=True, now=at.replace(hour=18), notify=lambda *a: notes.append(a))
    assert order == ["daily"]  # already done today
    log = next((dd.root / "logs").glob("sync-*.log")).read_text()
    assert "Daily three: Suggest today's three tasks: done (3 tasks for today)" in log


def test_no_daily_three_before_8_and_a_failure_notifies(nb, monkeypatch):
    from careeros import sync_all
    from test_schedule import fake_syncs
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
    with session(dd) as s:
        assert s.query(DailyTask).count() == 0


def test_a_notebook_without_goals_never_runs_the_daily_step(tmp_path):
    from careeros.config import DataDir
    from careeros.storage.db import init_db, make_engine, make_session_factory
    dd = DataDir(tmp_path / "empty")
    dd.init_personal()
    engine = make_engine(dd.db)
    init_db(engine)
    nine = datetime.combine(TODAY, datetime.min.time()).replace(hour=9)
    assert _real_daily_due(make_session_factory(engine), nine) is False


def _web(nb):
    from careeros.web.app import create_app
    from starlette.testclient import TestClient
    dd, *_ = nb
    app = create_app(dd)
    return TestClient(app, base_url="http://127.0.0.1"), app.state.csrf_token


def _three(dd):
    with session(dd) as s:
        ids = [g["id"] for g in daily.context(s, TODAY)["goals"]]
        return [t.id for t in daily.suggest(s, TODAY, reader=lambda p, d: reply(ids))]


def test_home_card_shows_three_ticks_and_the_empty_state(nb):
    dd, *_ = nb
    setup(dd)
    c, _ = _web(nb)
    home = c.get("/").text
    assert "Today's three" in home and "No three yet today" in home and 'data-label="Suggest now"' in home
    _three(dd)
    home = c.get("/").text
    assert home.count('aria-label="Mark done: Write a two-line summary') == 3 and "~5 min" in home
    assert 'data-label="New three"' in home and home.index("Today's three") < home.index('aria-label="Progress"')


def test_done_logs_a_record_with_details_and_undo_takes_it_back(nb):
    from careeros.web.app import create_app  # noqa: F401
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    tid = _three(dd)[0]
    assert c.post(f"/daily/{tid}/done", data={"details": "x"}).status_code == 403  # CSRF
    r = c.post(f"/daily/{tid}/done", data={"csrf": tok, "details": "Sent it to the team channel."},
               follow_redirects=False)
    assert r.status_code == 303
    with session(dd) as s:
        t = s.get(DailyTask, tid)
        e = s.get(JournalEntry, t.entry_id)
        assert t.done_at and (e.kind, e.status, e.source, e.text) == ("task", "done", "daily", t.text)
        assert s.query(JournalAttachment).filter_by(entry_id=e.id, body="Sent it to the team channel.").count() == 1
        eid = e.id
    home = c.get("/").text
    assert 'aria-label="Mark not done: Write a two-line summary' in home
    c.post(f"/daily/{tid}/undo", data={"csrf": tok})
    with session(dd) as s:
        assert s.get(DailyTask, tid).done_at is None and s.get(JournalEntry, eid) is None


def test_undo_keeps_a_record_you_already_checked(nb):
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    tid = _three(dd)[0]
    c.post(f"/daily/{tid}/done", data={"csrf": tok})
    with session(dd) as s:
        e = s.get(JournalEntry, s.get(DailyTask, tid).entry_id)
        e.reviewed = True
        s.commit()
        eid = e.id
    c.post(f"/daily/{tid}/undo", data={"csrf": tok})
    with session(dd) as s:
        assert s.get(DailyTask, tid).done_at is None and s.get(JournalEntry, eid) is not None


def test_all_three_done_and_the_suggest_button_starts_a_job(nb, monkeypatch):
    dd, *_ = nb
    setup(dd)
    c, tok = _web(nb)
    for tid in _three(dd):
        c.post(f"/daily/{tid}/done", data={"csrf": tok})
    assert "All three done. Nice." in c.get("/").text
    started = []
    monkeypatch.setattr("careeros.web.syncs.run_daily",
                        lambda job, S, lock, force=False: (started.append(force), job.finish("ok")))
    assert c.post("/daily/suggest", data={"csrf": tok, "force": "1"}, headers={"X-Sync": "1"}).json() == {"started": True}
    import time
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started == [True]
