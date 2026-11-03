"""The daily three: the context Claude reads, strict checks on its answer, and saving once a day (fake Claude)."""
import json
from datetime import date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from careeros import daily
from careeros.claude_cli import ClaudeError
from careeros.cli import app as cli
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
