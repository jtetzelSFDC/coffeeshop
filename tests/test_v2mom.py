"""V2MOM from a Google Doc: connect, read (with a fake connector and a fake Claude), save, and the monthly rule."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from careeros import sync_all
from careeros.claude_cli import ClaudeError
from careeros.cli import app as cli
from careeros.storage.models import SyncRun, V2momMethod, V2momVersion
from careeros.storage.sync_log import status
from careeros.v2mom import connector, store
from careeros.web.app import create_app

from test_slack import BASE, personal, run_sync

DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcd"
SRC = dict(kind="doc", value=DOC_ID)
# Made up, in the shape of a page copied from the V2MOM app.
DOC = """## My V2MOM Progress (FY27)
**Published on** Mar 25, 2026 **Last updated** Oct 2, 2026
## V2MOM
**Published: Mar 25, 2026**
## Check-Ins **Check-In Available**
### V2MOM
###### Vision
Releases so calm nobody notices them.
###### Values
**Calm Craft**
Do it right once.
**Learn Out Loud**
Share what we find.
Method and Measures
**Measure Filters**
###### Share Release Know-How Across Teams
**On Track69%**
Teach other teams how releases run.
Q2: Present at 2 community sessions **Completed**
Q3: Publish a release primer **Not Started**
###### Build Reusable Pipeline Accelerators
**A measure below requires your review.**
**On Track50%**
Templates teams can pick up.
Q2: Ship one shared pipeline template **On Track**
###### Obstacles
## Two Leads For Many Teams
**Related Method: Share Release Know-How Across Teams**
Too few people for the number of teams.
### Helpful Resources
Learn more about the V2MOM | Technical Support | Send feedback
"""


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


@pytest.fixture
def fake(monkeypatch):
    """The connector returns DOC; Claude answers with whatever `fake.reply` holds."""
    seen = {}

    def call_tool(prompt, tool, timeout=240):
        seen["tool"] = (prompt, tool)
        return json.dumps({"markdown_content": DOC})

    def ask(prompt, data, timeout=240):
        seen["data"] = data
        return "Here you go:\n" + seen["reply"]
    monkeypatch.setattr(connector, "call_tool", call_tool)
    monkeypatch.setattr(connector, "ask", ask)
    seen["reply"] = answer(*TWO)
    return seen


def pull(Session):
    with Session() as s:
        return store.save(s, *connector.read(SRC))


def test_connect_saves_the_doc_id_owner_only(tmp_path):
    dd, _ = personal(tmp_path)
    r = CliRunner().invoke(cli, ["v2mom", "connect", f"https://docs.google.com/document/d/{DOC_ID}/edit",
                                 "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert connector.load_source(dd) == SRC and oct(connector.source_file(dd).stat().st_mode)[-3:] == "600"
    with pytest.raises(ValueError):
        connector.save_source(dd, "not a doc")


def test_a_doc_connected_before_pdfs_still_counts(tmp_path):
    dd, _ = personal(tmp_path)
    (dd.root / connector.DOC_FILE).write_text(DOC_ID + "\n")
    assert connector.load_source(dd) == SRC
    connector.save_source(dd, f"https://docs.google.com/document/d/{DOC_ID}/edit")
    assert not (dd.root / connector.DOC_FILE).exists() and connector.load_source(dd) == SRC


def test_a_pull_saves_the_version_methods_measures_and_obstacles(tmp_path, fake):
    dd, Session = personal(tmp_path)
    assert pull(Session) == dict(methods=2, added=2, retired=0, obstacles=1)
    assert DOC_ID in fake["tool"][0] and fake["tool"][1] == connector.TOOL
    assert fake["data"] == DOC  # the markdown inside the connector's JSON is what Claude reads
    with Session() as s:
        v = store.current(s)
        assert (v.fiscal_year, v.published, v.vision) == ("FY27", "Mar 25, 2026", "Releases so calm nobody notices them.")
        assert [x["name"] for x in v.values] == ["Calm Craft", "Learn Out Loud"]
        assert v.obstacles[0]["related_method"] == "Share Release Know-How Across Teams"
        ms = store.methods(s)
        assert [(m.label, m.name, m.status, m.progress) for m in ms] == [
            ("M1", "Share Release Know-How Across Teams", "On Track", 69),
            ("M2", "Build Reusable Pipeline Accelerators", "On Track", 50)]
        assert ms[0].measures == [dict(text="Q2: Present at 2 community sessions", status="Completed", progress=None,
                                       comments="")]
        assert status(s)["v2mom"]["ok"] is True


def test_a_second_pull_does_not_duplicate(tmp_path, fake):
    dd, Session = personal(tmp_path)
    pull(Session)
    fake["reply"] = answer(("Share Release Know-How Across Teams", "Completed", 100), TWO[1])
    assert pull(Session) == dict(methods=2, added=0, retired=0, obstacles=1)
    with Session() as s:
        assert s.query(V2momVersion).count() == 1 and s.query(V2momMethod).count() == 2
        assert (store.methods(s)[0].status, store.methods(s)[0].progress) == ("Completed", 100)


def test_reordered_and_renamed_methods_keep_their_rows(tmp_path, fake):
    dd, Session = personal(tmp_path)
    pull(Session)
    with Session() as s:
        share, build = (m.id for m in store.methods(s))
    fake["reply"] = answer(TWO[1], TWO[0])  # swapped
    pull(Session)
    with Session() as s:
        assert [(m.id, m.label) for m in store.methods(s)] == [(build, "M1"), (share, "M2")]
    fake["reply"] = answer(("Build reusable pipeline accelerators!", "At Risk", 40),  # same name, new punctuation
                           ("Share Release Know-How Across Every Team", "On Track", 70))  # renamed in place
    assert pull(Session)["added"] == 0
    with Session() as s:
        assert [m.id for m in store.methods(s)] == [build, share]
        assert store.methods(s)[1].name == "Share Release Know-How Across Every Team"


def test_a_removed_method_is_kept_inactive_and_comes_back(tmp_path, fake):
    dd, Session = personal(tmp_path)
    pull(Session)
    fake["reply"] = answer(TWO[1])
    assert pull(Session) == dict(methods=1, added=0, retired=1, obstacles=1)
    with Session() as s:
        gone = s.scalar(select(V2momMethod).where(V2momMethod.name == TWO[0][0]))
        assert gone.active is False and [m.name for m in store.methods(s)] == [TWO[1][0]]
    fake["reply"] = answer(*TWO)
    assert pull(Session)["added"] == 0
    with Session() as s:
        assert s.get(V2momMethod, gone.id).active is True


def test_a_new_fiscal_year_starts_a_new_version(tmp_path, fake):
    dd, Session = personal(tmp_path)
    pull(Session)
    fake["reply"] = answer(*TWO, fy="FY28")
    assert pull(Session)["added"] == 2
    with Session() as s:
        assert s.query(V2momVersion).count() == 2 and store.current(s).fiscal_year == "FY28"
        assert len(store.methods(s)) == 2 and s.query(V2momMethod).filter(V2momMethod.active).count() == 4


@pytest.mark.parametrize("reply, why", [
    ("I can't find a V2MOM here.", "isn't a JSON object"),
    (json.dumps(dict(methods=[])), "no methods"),
    (json.dumps(dict(methods=[dict(name=" ")])), "no name"),
    (json.dumps(dict(methods=[dict(name="A", progress="69%")])), "percent"),
    (json.dumps(dict(methods=[dict(name="A", measures="lots")])), "measures"),
])
def test_an_unreadable_answer_is_a_plain_error(tmp_path, fake, reply, why):
    fake["reply"] = reply
    with pytest.raises(ClaudeError, match=why):
        connector.read(SRC)


def test_connector_failures_say_what_to_do(monkeypatch):
    monkeypatch.setattr(connector, "call_tool", lambda *a, **k: 'MCP tool call failed: status 401 {"error": "invalid_token"}')
    with pytest.raises(ClaudeError, match="sign-in has expired"):
        connector.read(SRC)
    monkeypatch.setattr(connector, "call_tool", lambda *a, **k: json.dumps({"markdown_content": ""}))
    with pytest.raises(ClaudeError, match="looks empty"):
        connector.read(SRC)


def test_monthly_rule(tmp_path):
    dd, Session = personal(tmp_path)
    now = datetime(2026, 11, 2, 9, 0)
    with Session() as s:
        assert store.due(s, now) and status(s, now)["v2mom"]["ok"] is False
        s.add(SyncRun(source="v2mom", at=now - timedelta(days=29), added=0))
        s.commit()
        assert not store.due(s, now) and status(s, now)["v2mom"]["ok"] is True
        assert store.due(s, now + timedelta(days=2)) and status(s, now + timedelta(days=2))["v2mom"]["ok"] is True
        assert status(s, now + timedelta(days=3))["v2mom"]["ok"] is False


def test_sync_all_pulls_the_v2mom_only_when_connected_and_due(tmp_path, monkeypatch):
    from test_schedule import fake_syncs
    dd, Session = personal(tmp_path)
    calls = fake_syncs(monkeypatch)
    pulled = []
    monkeypatch.setattr(sync_all.syncs, "run_v2mom", lambda job, *a: (pulled.append(1), job.finish("ok")))
    assert sync_all.run(dd, force=True, notify=lambda *a: None) == 0 and not pulled  # not connected
    connector.save_source(dd, DOC_ID)
    sync_all.run(dd, force=True, notify=lambda *a: None)
    assert pulled == [1]
    with Session() as s:
        s.add(SyncRun(source="v2mom", at=datetime.now() - timedelta(days=3), added=0))
        s.commit()
    sync_all.run(dd, force=True, notify=lambda *a: None)
    assert pulled == [1] and calls.count("slack") == 3


def test_web_button_and_chips(tmp_path, fake):
    dd, Session = personal(tmp_path)
    app = create_app(dd)
    c, token = TestClient(app, base_url=BASE), app.state.csrf_token
    home = c.get("/").text
    assert "v2mom connect" in home and 'action="/sync/v2mom"' in home and "V2MOM" in c.get("/sheet").text
    job = run_sync(c, token, "v2mom")
    assert job["state"] == "error" and "No V2MOM connected" in job["steps"][0]["detail"]
    connector.save_source(dd, DOC_ID)
    job = run_sync(c, token, "v2mom")
    assert job["message"] == "V2MOM synced: FY27, 2 methods." and [st["state"] for st in job["steps"]] == ["done", "done"]
    home = c.get("/").text
    assert "v2mom connect" not in home and 'chip-sync ok" title="V2MOM: last pulled today' in home


def test_cli_sync(tmp_path, fake):
    dd, Session = personal(tmp_path)
    connector.save_source(dd, DOC_ID)
    r = CliRunner().invoke(cli, ["v2mom", "sync", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert "2 methods, 1 obstacle" in r.output and "V2MOM synced: FY27, 2 methods." in r.output
