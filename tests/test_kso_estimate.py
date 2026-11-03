"""Claude's monthly KSO estimate: what it reads (never money), strict checks, the page, your rating winning, the
monthly step in the sync, the Re-estimate button, the chip, and KSO goals in the daily three. Fake readers only."""
import json
import threading
import time
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from careeros import daily
from careeros.claude_cli import ClaudeError
from careeros.kso import estimate as est, framework, progress
from careeros.storage.models import KsoEstimate
from careeros.storage.sync_log import status

from helpers import TWO, add, form, kso_setup, load_v2mom, open_session



def answer(**changes):
    ksos = [dict(key="1", rating=3, why={"1.1": "M1 is on plan", "1.2": "No feedback goal"},
                 next=["Add a feedback measure to your V2MOM", "Ask one teammate for feedback", "Save a thank-you"]),
            dict(key="2", rating=4, why={"2.1": "M2 is half done", "2.2": "Nothing matched yet"},
                 next=["Try an AI helper on one chore", "Note one prompt that saved time", "Finish one course unit"])]
    for k in ksos:
        k.update(changes.get(k["key"], {}))
    return json.dumps({"ksos": ksos})


def run(s, reply=None):
    return est.estimate(s, framework.for_current(s), reader=lambda p, d: reply or answer())


def test_the_estimate_reads_the_rubric_and_work_but_never_money(nb):
    dd, c, token, _ = nb
    kso_setup(dd)
    form(c, "/kso/target", token, fy="FY27", target="98765")
    seen = []
    with open_session(dd) as s:
        est.estimate(s, framework.for_current(s), reader=lambda p, d: seen.append(d) or answer())
    data = json.loads(seen[0])
    part = data["ksos"][0]["components"]
    assert part[0]["methods"][0]["id"] == "M1" and part[0]["levels"]["5"].startswith("Standout")
    assert "kudos" in part[1] and "kudos" not in part[0] and "98765" not in seen[0]


@pytest.mark.parametrize("bad, why", [
    ({"2": dict(key="9")}, "isn't one of yours"),
    ({"1": dict(rating=6)}, "1 to 5"),
    ({"1": dict(why={"1.1": "only one part"})}, "every part"),
    ({"2": dict(next=["Just one"])}, "short next steps"),
    ({"2": dict(next=["x" * 200, "b", "c"])}, "short next steps"),
])
def test_a_bad_estimate_saves_nothing(nb, bad, why):
    dd, *_ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        with pytest.raises(ClaudeError, match=why):
            run(s, answer(**bad))
        assert s.scalar(select(KsoEstimate)) is None


def test_the_page_shows_the_estimate_and_your_rating_wins(nb):
    dd, c, token, _ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        run(s)
    page = c.get("/kso").text
    assert "Claude's estimate: 3 &middot; Mostly there" in page and "Add a feedback measure" in page
    assert "M1 is on plan" in page and 'data-sync="kso"' in page
    form(c, "/kso/target", token, fy="FY27", target="10000")
    with open_session(dd) as s:
        rows = progress.build(s)["projection"]["rows"]
    assert [(x["rating"], x["ai"]) for x in rows] == [(3, True), (4, True)]
    form(c, "/kso/rating", token, fy="FY27", kso="1", rating="5")
    with open_session(dd) as s:
        p = progress.build(s)["projection"]
    assert [(x["rating"], x["ai"]) for x in p["rows"]] == [(5, False), (4, True)] and p["total"] == 2400 + 1000


def test_it_runs_monthly_once_ksos_are_matched(nb):
    dd, *_ = nb
    with open_session(dd) as s:
        assert not est.due(s)  # no KSOs yet
    kso_setup(dd)
    with open_session(dd) as s:
        assert est.due(s)
        run(s)
        assert not est.due(s) and est.due(s, datetime.now() + timedelta(days=31))
        assert status(s)["kso"]["ok"]


def test_the_sync_step_and_the_button(nb, monkeypatch):
    from careeros.web import syncs
    from careeros.web.jobs import Job
    from careeros.storage.db import make_engine, make_session_factory
    dd, c, token, _ = nb
    kso_setup(dd)
    monkeypatch.setattr(est, "ask", lambda p, d, timeout=0: answer())
    job = Job(syncs.KSO_STEPS)
    syncs.run_kso(job, make_session_factory(make_engine(dd.db)), threading.Lock())
    assert job.steps[0]["state"] == "done" and "KSO 1: 3, KSO 2: 4" in job.steps[0]["detail"]
    monkeypatch.setattr(est, "ask", lambda p, d, timeout=0: "no")
    job = Job(syncs.KSO_STEPS)
    syncs.run_kso(job, make_session_factory(make_engine(dd.db)), threading.Lock())
    assert job.steps[0]["state"] == "error" and "Nothing was changed" in job.steps[0]["detail"]
    assert c.post("/kso/estimate", headers={"X-Sync": "1"}).status_code == 403
    started = []
    monkeypatch.setattr(syncs, "run_kso", lambda j, S, lock: (started.append(1), j.finish("ok")))
    assert c.post("/kso/estimate", data={"csrf": token}, headers={"X-Sync": "1"}).json() == {"started": True}
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started


def test_the_morning_sync_estimates_after_the_v2mom(nb, monkeypatch):
    from careeros import sync_all
    from careeros.web import syncs
    dd, *_ = nb
    order = []

    def ok(name):
        def run(j, *a):
            order.append(name)
            for i in range(len(j.steps)):
                j.done(i)
            j.finish("ok")
        return run
    for name in ("run_slack", "run_google", "run_github", "run_kso"):
        monkeypatch.setattr(syncs, name, ok(name))
    monkeypatch.setattr(sync_all, "_v2mom_due", lambda *a: False)
    monkeypatch.setattr(sync_all, "_daily_due", lambda *a: False)
    monkeypatch.setattr(sync_all, "_kso_due", lambda *a: True)
    assert sync_all.run(dd, force=True, notify=lambda *a: None) == 0
    assert order[-1] == "run_kso"


def test_kso_parts_without_a_goal_become_daily_goals(nb):
    dd, *_ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        ids = [g["id"] for g in daily.goals(s, date.today())]
    assert "KSO 1.2: Kind Feedback" in ids and "KSO 2.1: New Skills" in ids  # a gap, and the one furthest behind
    assert "KSO 1.1: Plan Kept" not in ids  # 69% isn't the furthest behind


def test_a_busy_part_leaves_room_for_the_others(nb):
    from careeros.storage.models import V2momLink
    dd, *_ = nb
    m = kso_setup(dd)
    with open_session(dd) as s:
        for i in range(400):
            s.add(V2momLink(method_id=m["M1"], entry_id=add(s, f"Shipped release step number {i} of many"),
                            created_at=datetime.now()))
        s.add(V2momLink(method_id=m["M2"], entry_id=add(s, "Finished one course unit"), created_at=datetime.now()))
        s.commit()
        data = est.context(s, framework.for_current(s))
    work = {c["key"]: c["work"] for k in data["ksos"] for c in k["components"]}
    assert work["1.1"] and len("".join(work["1.1"])) <= est.MAX_EVIDENCE // 4
    assert any("Finished one course unit" in x for x in work["2.1"])


def test_numbers_as_keys_are_fine_and_the_prompt_asks_for_less_than_it_checks(nb):
    dd, *_ = nb
    kso_setup(dd)
    a = json.loads(answer())
    a["ksos"][0]["key"] = 1
    with open_session(dd) as s:
        assert run(s, json.dumps(a)).data["ksos"][0]["key"] == "1"
    assert est.ASK_STEP < est.MAX_STEP and est.ASK_WHY < est.MAX_WHY


def test_the_daily_three_skips_last_years_ksos(nb):
    dd, *_ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        load_v2mom(s, TWO, fy="FY28")  # the new year's V2MOM, before its KSOs are read
        assert not [g for g in daily.goals(s, date.today()) if g["id"].startswith("KSO")]
