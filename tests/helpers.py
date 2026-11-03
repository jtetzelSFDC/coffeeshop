"""Builders and fake answers shared by the tests: a made-up notebook, leveling guide, V2MOM, KSOs and promo
evidence. Fixtures (like `nb`) live in conftest.py; these are plain functions and constants. Made-up data only."""
import csv
import json
from datetime import datetime

from careeros.config import DataDir
from careeros.fixtures.kso import reply as fw_reply
from careeros.guide.service import experiences
from careeros.kso import framework, map as kmap
from careeros.promo import write as pw
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros import sync_all
from careeros.storage.models import GuideLink, JournalEntry, SyncRun, V2momLink, Win
from careeros.v2mom import connector, store

BASE = "http://127.0.0.1"


G6 = ["Builds CI/CD pipelines for a project.", "Plans sandbox refresh strategies.", "Mentors newer engineers."]


G7 = ["Owns CI/CD pipelines for an engagement.", "Owns the sandbox strategy.", "Runs demos for customers."]


def write_guide(path, g6=G6, g7=G7):
    blank = [""] * 7
    rows = [["Group: Example", *[""] * 6], ["Career Path: Example", *[""] * 6],
            ["", "Grade", "", "Grade 5", "Grade 6", "Grade 7", ""],
            ["Job Profile", "Role Summary", "", "Grade five summary.", "Senior summary.", "Architect summary.", ""],
            ["", "Key Experiences", "", "- Helps with pipelines", "- " + "\n- ".join(g6), "- " + "\n- ".join(g7), ""],
            ["Skills ", *[""] * 6], blank,
            ["Transferable Skills", "Communicate Effectively", "Conveys information clearly.", "2", "3", "4", ""],
            ["", "Learning Mindset", "Keeps learning.", "2", "3", "3", ""],
            ["Path-Specific Skills", "Environment/Sandbox Management", "Manages sandboxes.", "2", "3", "4", ""],
            ["", "*Agentforce", "Guides customers on Agentforce.", "2", "3", "3", ""]]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


def open_session(dd):
    return make_session_factory(make_engine(dd.db))()


def form(c, path, token, **data):
    return c.post(path, data={"csrf": token, **data}, follow_redirects=False)


def personal(tmp_path):
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    engine = make_engine(dd.db)
    init_db(engine)
    return dd, make_session_factory(engine)


def run_sync(c, token, name):
    import time
    path = {"slack": "/slack/sync", "google": "/sync/google", "v2mom": "/sync/v2mom"}[name]
    assert c.post(path, data={"csrf": token}, headers={"X-Sync": "1"}).json()["started"]
    for _ in range(200):
        job = c.get("/sync/status").json().get(name)
        if job and job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("sync never finished")


def add(s, text, day="2026-10-20", kind="note", source="slack", **fields):
    """A saved record (from Slack by default); returns its id."""
    e = JournalEntry(day=day, kind=kind, text=text, created_at=datetime.now(), source=source, **fields)
    s.add(e)
    s.commit()
    return e.id


DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcd"


SRC = dict(kind="doc", value=DOC_ID)


def answer(*methods, fy="FY27"):
    """What Claude would reply for the Doc, with the given methods (name, status, progress)."""
    return json.dumps(dict(
        fiscal_year=fy, published="Mar 25, 2026", vision="Releases so calm nobody notices them.",
        values=[dict(name="Calm Craft", text="Do it right once."), dict(name="Learn Out Loud", text="Share what we find.")],
        methods=[dict(name=n, description=f"About {n}.", status=st, progress=p,
                      measures=[dict(text="Q2: Present at 2 community sessions", status="Completed")])
                 for n, st, p in methods],
        obstacles=[dict(name="Two Leads For Many Teams", text="Too few people for the number of teams.",
                        related_method="Share Release Know-How Across Teams")]))


TWO = [("Share Release Know-How Across Teams", "On Track", 69), ("Build Reusable Pipeline Accelerators", "On Track", 50)]


def load_v2mom(s, methods=TWO, fy="FY27"):
    store.save(s, connector.validate(json.loads(answer(*methods, fy=fy))), DOC_ID)
    return {m.label: m.id for m in store.methods(s)}


KSO_SRC = dict(decks=["1DeckDeckDeckDeckDeckDeckDeck00"], canvases=["F0MADEUP01"], track="Delivery", manager=False)


def connect(s, fy="FY27", **changes):
    return framework.save(s, framework.parse("material", reader=lambda p, d: json.dumps(fw_reply(fy, **changes))), KSO_SRC)


def picks(**m):
    return lambda p, d: json.dumps({"map": m})


def kso_setup(dd):
    """FY27 made-up KSOs; M1 (69%) counts toward 1.1 and M2 (50%) toward 2.1."""
    with open_session(dd) as s:
        m = load_v2mom(s)
        kmap.suggest(s, connect(s), reader=picks(M1="1.1", M2="2.1"))
        return m


def promo_seed(s):
    item = experiences(s)[0].id
    e = JournalEntry(day="2026-10-20", kind="task", text="Ran the full sandbox refresh", created_at=datetime.now(),
                     source="slack", activity="sandbox_refresh")
    old = JournalEntry(day="2024-01-05", kind="task", text="Ancient deploy", created_at=datetime.now(), source="slack")
    s.add_all([e, old])
    s.flush()
    w = Win(day="2026-10-20", title="Planned and ran a full sandbox refresh for four teams", impact="No team lost data.",
            size="large", entry_id=e.id, created_at=datetime.now())
    s.add(w)
    s.flush()
    s.add_all([GuideLink(item_id=item, win_id=w.id, created_at=datetime.now()),
               GuideLink(item_id=item, entry_id=old.id, created_at=datetime.now())])
    s.commit()
    return w


def by_key(answers):
    def reader(name, key, evidence):
        assert all(set(p) == {"n", "kind", "text", "day", "refs"} for p in evidence)
        return answers(key, evidence)
    return reader


def draft(s):
    promo_seed(s)
    return pw.write_case(s, start="2025-10-29", end="2026-10-29", name="Jordan", reader=by_key(
        lambda key, ev: [dict(text=f"Jordan's {key} one.", sources=[ev[0]["n"]]),
                         dict(text=f"Jordan's {key} two.", sources=[ev[-1]["n"]])]))


def link(s, method_id, *, entry_id=None, win_id=None):
    s.add(V2momLink(method_id=method_id, entry_id=entry_id, win_id=win_id, created_at=datetime.now()))


def fake_syncs(monkeypatch, fail=None):
    """Replace the Slack, Google and GitHub syncs with ones that log a SyncRun, or fail one step."""
    calls = []

    def runner(name, source):
        def run(job, Session_, lock, *rest):
            calls.append(name)
            if fail == name:
                job.fail(0, "Claude Code's Slack sign-in has expired. Sign in again.")
                for i in range(1, len(job.steps)):
                    job.skip(i)
                job.finish("Slack sync couldn't read the tracker, so nothing changed.")
                return
            with Session_() as s:
                s.add(SyncRun(source=source, at=datetime.now(), added=1))
                s.commit()
            for i in range(len(job.steps)):
                job.done(i, "ok")
            job.finish(f"{name} synced")
        return run
    monkeypatch.setattr(sync_all.syncs, "run_slack", runner("slack", "slack"))
    monkeypatch.setattr(sync_all.syncs, "run_google", runner("google", "calendar"))
    monkeypatch.setattr(sync_all.syncs, "run_github", runner("github", "github"))
    monkeypatch.setattr(sync_all, "_daily_due", lambda Session_, now: False)  # covered in test_daily
    return calls
