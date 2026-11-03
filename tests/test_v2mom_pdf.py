"""V2MOM from the PDF the V2MOM app exports: connect, the newest-file pick, page markers, the parse (with made-up text
and a fake Claude), measures rolled up into methods, check-ins, switching from a Doc, the page, and promo evidence."""
import json
import os

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from typer.testing import CliRunner

from careeros.claude_cli import ClaudeError
from careeros.cli import app as cli
from careeros.promo import evidence as pe
from careeros.v2mom import connector, store
from careeros.web.app import create_app

from test_slack import BASE, personal
from test_v2mom import DOC_ID, SRC, TWO, answer

# Made up, in the shape of the V2MOM app's PDF export as pypdf reads it.
PDF_TEXT = """FY27 V2MOM Pat Example
Vision
Releases so calm nobody notices them.
Values
Calm CraftDo it right once, then make it boring.Learn Out LoudShare what we find.
-- 1 of 3 --
Methods & Measures
1. Share Release Know-How Across Teams
Teach other teams how releases run.
1. Q2: Present at 2 community sessions
Status: Completed
Comments: Both sessions done, recordings posted.
2. Q3: Publish a release primer
Progress: 40%
-- 2 of 3 --
2. Build Reusable Pipeline Accelerators
Templates teams can pick up.
1. Q2: Ship one shared pipeline template
Status: On Track
Obstacles
Two Leads For Many Teams
Too few people for the number of teams.
Related methods:
- Share Release Know-How Across Teams
- Build Reusable Pipeline Accelerators
Canceled / Postponed Methods
Check-Ins
> Midyear FY27 Check-In
Manager comments: Strong half. The community sessions landed well with other teams.
-- 3 of 3 --
> Q2 FY27 Check-In
> Q1 FY27 Check-In
"""

PDF_ANSWER = json.dumps(dict(
    fiscal_year="FY27", published="", vision="Releases so calm nobody notices them.",
    values=[dict(name="Calm Craft", text="Do it right once, then make it boring."),
            dict(name="Learn Out Loud", text="Share what we find.")],
    methods=[
        dict(name=TWO[0][0], description="Teach other teams how releases run.", status="", progress=None, measures=[
            dict(text="Q2: Present at 2 community sessions", status="Completed", progress=None,
                 comments="Both sessions done, recordings posted."),
            dict(text="Q3: Publish a release primer", status="", progress=40, comments="")]),
        dict(name=TWO[1][0], description="Templates teams can pick up.", status="", progress=None, measures=[
            dict(text="Q2: Ship one shared pipeline template", status="On Track", progress=None, comments="")])],
    obstacles=[dict(name="Two Leads For Many Teams", text="Too few people for the number of teams.",
                    related_methods=[TWO[0][0], TWO[1][0]])],
    check_ins=[dict(name="Midyear FY27 Check-In",
                    manager_comments="Strong half. The community sessions landed well with other teams."),
               dict(name="Q2 FY27 Check-In", manager_comments=""), dict(name="Q1 FY27 Check-In")]))


def touch(path, mtime):
    path.write_bytes(b"%PDF-1.4 made up")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def pdf(tmp_path, monkeypatch):
    """A made-up V2MOM PDF on a fake Desktop; its text is PDF_TEXT and Claude answers `pdf.reply`."""
    desk = tmp_path / "Desktop"
    desk.mkdir()
    seen = dict(path=touch(desk / "FY27 V2MOM Pat Example.pdf", 1_700_000_000), reply=PDF_ANSWER)

    def text(path):
        seen["read"] = path
        return PDF_TEXT

    def ask(prompt, data, timeout=240):
        seen["prompt"], seen["data"] = prompt, data
        return seen["reply"]
    monkeypatch.setattr(connector, "pdf_text", text)
    monkeypatch.setattr(connector, "ask", ask)
    return seen


def test_page_markers_are_stripped():
    assert connector.strip_markers("Values\n-- 1 of 7 --\nMethods\n  -- 12 of 12 --  \nPage 3 of 7\nEnd") == \
        "Values\nMethods\nEnd"
    assert connector.strip_markers("Ship 1 of 7 templates") == "Ship 1 of 7 templates"


def test_the_newest_v2mom_pdf_in_the_folder_is_read(tmp_path):
    first = touch(tmp_path / "FY27 V2MOM Pat Example.pdf", 1_700_000_000)
    assert connector.newest_pdf(str(first)) == first
    again = touch(tmp_path / "FY27 V2MOM Pat Example (1).pdf", 1_700_000_100)
    touch(tmp_path / "Boarding pass.pdf", 1_700_000_200)  # newer, but not a V2MOM
    (tmp_path / "v2mom notes.txt").write_text("not a PDF")
    assert connector.newest_pdf(str(first)) == again
    first.unlink()
    assert connector.newest_pdf(str(first)) == again
    other = tmp_path / "other"
    other.mkdir()
    export = touch(other / "export.pdf", 1_700_000_000)  # renamed: no V2MOM in the name, so the stored file
    assert connector.newest_pdf(str(export)) == export
    assert connector.newest_pdf(str(other / "gone.pdf")) is None


def test_last_years_pdf_opened_again_is_not_read(tmp_path):
    this = touch(tmp_path / "FY27 V2MOM Pat Example.pdf", 1_700_000_000)
    touch(tmp_path / "FY26 V2MOM Pat Example.pdf", 1_700_000_500)  # downloaded later, to look back at
    assert connector.newest_pdf(str(this)) == this
    nxt = touch(tmp_path / "FY28 V2MOM Pat Example.pdf", 1_600_000_000)  # next year's, whatever its date
    assert connector.newest_pdf(str(this)) == nxt


def test_an_existing_notebook_gets_the_check_ins_column(tmp_path):
    from sqlalchemy import text
    from careeros.storage.db import init_db, make_engine
    engine = make_engine(tmp_path / "old.db")
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE v2mom_version (id INTEGER PRIMARY KEY, doc_id VARCHAR, fiscal_year VARCHAR, "
                          "published VARCHAR, vision TEXT, \"values\" JSON, obstacles JSON, pulled_at DATETIME)")
        c.exec_driver_sql("INSERT INTO v2mom_version VALUES (1, 'x', 'FY27', '', '', '[]', '[]', '2026-10-01')")
    init_db(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT check_ins FROM v2mom_version")).scalar() == "[]"


def test_connect_a_pdf_stores_its_absolute_path(tmp_path, pdf, monkeypatch):
    dd, _ = personal(tmp_path)
    monkeypatch.chdir(pdf["path"].parent)
    r = CliRunner().invoke(cli, ["v2mom", "connect", pdf["path"].name, "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert connector.load_source(dd) == dict(kind="pdf", value=str(pdf["path"].resolve()))
    assert oct(connector.source_file(dd).stat().st_mode)[-3:] == "600"
    r = CliRunner().invoke(cli, ["v2mom", "connect", str(tmp_path / "nope.pdf"), "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "There's no PDF at" in r.output


def test_a_pdf_pull_saves_measures_rollups_and_check_ins(tmp_path, pdf):
    dd, Session = personal(tmp_path)
    connector.save_source(dd, str(pdf["path"]))
    again = touch(pdf["path"].parent / "FY27 V2MOM Pat Example (1).pdf", 1_700_000_100)
    r = CliRunner().invoke(cli, ["v2mom", "sync", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert "2 methods, 1 obstacle, 3 check-ins" in r.output
    assert pdf["read"] == again and pdf["prompt"] == connector.PDF_PROMPT and pdf["data"] == PDF_TEXT
    with Session() as s:
        v = store.current(s)
        assert v.doc_id == str(again) and [x["name"] for x in v.values] == ["Calm Craft", "Learn Out Loud"]
        share, build = store.methods(s)
        assert share.measures[0] == dict(text="Q2: Present at 2 community sessions", status="Completed",
                                         progress=None, comments="Both sessions done, recordings posted.")
        assert share.measures[1]["progress"] == 40
        assert (share.status, share.progress) == ("On Track", 70)  # (100 for Completed + 40) / 2
        assert (build.status, build.progress) == ("On Track", None)  # an On Track measure, but no percent
        assert v.obstacles[0]["related_methods"] == [TWO[0][0], TWO[1][0]]
        assert v.check_ins == [
            dict(name="Midyear FY27 Check-In",
                 manager_comments="Strong half. The community sessions landed well with other teams."),
            dict(name="Q2 FY27 Check-In", manager_comments=""), dict(name="Q1 FY27 Check-In", manager_comments="")]


def test_rollup():
    def ms(*xs):
        return [dict(text="m", status=st, progress=p, comments="") for st, p in xs]
    assert connector.rollup([]) == ("", None)
    assert connector.rollup(ms(("Completed", None), ("Completed", 90))) == ("Completed", 95)
    assert connector.rollup(ms(("", 0), ("Not Started", None))) == ("", 0)
    assert connector.rollup(ms(("On Track", 25), ("", None))) == ("On Track", 25)
    assert connector.rollup(ms(("At Risk", None), ("", None))) == ("", None)
    parsed = connector.validate(dict(methods=[dict(name="A", status="At Risk", progress=10,
                                                   measures=[dict(text="x", status="Completed")])]))
    assert (parsed["methods"][0]["status"], parsed["methods"][0]["progress"]) == ("At Risk", 10)  # given wins


def test_a_missing_pdf_says_where_to_save_it(tmp_path, pdf):
    dd, _ = personal(tmp_path)
    connector.save_source(dd, str(pdf["path"]))
    pdf["path"].unlink()
    r = CliRunner().invoke(cli, ["v2mom", "sync", "--data-dir", str(dd.root)])
    assert r.exit_code == 1
    assert f"Download your V2MOM as a PDF from the V2MOM app and save it to {pdf['path'].parent}" in r.output


def test_real_pypdf_errors_are_plain(tmp_path):
    blank = tmp_path / "FY27 V2MOM blank.pdf"
    w = PdfWriter()
    w.add_blank_page(612, 792)
    with open(blank, "wb") as fh:
        w.write(fh)
    with pytest.raises(ClaudeError, match="has no text to read"):
        connector.pdf_text(blank)
    junk = touch(tmp_path / "FY27 V2MOM junk.pdf", 1_700_000_000)
    with pytest.raises(ClaudeError, match="Couldn't open"):
        connector.pdf_text(junk)


def test_switching_from_the_doc_to_the_pdf_keeps_method_rows(tmp_path, pdf):
    dd, Session = personal(tmp_path)
    with Session() as s:
        store.save(s, connector.validate(json.loads(answer(*TWO))), DOC_ID)
        ids = [m.id for m in store.methods(s)]
    connector.save_source(dd, str(pdf["path"]))
    with Session() as s:
        assert store.save(s, *connector.read(connector.load_source(dd)))["added"] == 0
        assert [m.id for m in store.methods(s)] == ids and len(store.current(s).check_ins) == 3


def test_page_shows_measure_progress_comments_and_check_ins(tmp_path, pdf):
    dd, Session = personal(tmp_path)
    with Session() as s:
        store.save(s, connector.validate(json.loads(PDF_ANSWER)), str(pdf["path"]))
    c = TestClient(create_app(dd), base_url=BASE)
    page = c.get("/v2mom").text
    assert "read from your PDF" in page and 'aria-label="40 percent done"' in page
    assert "<summary>Comments</summary>" in page and "Both sessions done, recordings posted." in page
    assert "<summary>Check-ins (3)</summary>" in page
    assert "Manager comments: Strong half. The community sessions landed well with other teams." in page
    assert page.count("No manager comments.") == 2
    assert page.count("Obstacle: Two Leads For Many Teams.") == 2  # under both related methods


def test_doc_pages_keep_their_look(tmp_path):
    dd, Session = personal(tmp_path)
    with Session() as s:
        store.save(s, connector.validate(json.loads(answer(*TWO))), DOC_ID)
        v = store.current(s)
        for m in store.methods(s):  # measures saved before this change: no progress or comments keys
            m.measures = [dict(text="Old measure", status="")]
        s.commit()
    page = TestClient(create_app(dd), base_url=BASE).get("/v2mom").text
    assert "read from your Doc" in page and "Old measure" in page and "Check-ins" not in page
    assert page.count('percent done"') == 2  # the methods' bars only
    assert v.check_ins == []


def test_promo_cites_check_ins_with_manager_comments_only(tmp_path):
    dd, Session = personal(tmp_path)
    with Session() as s:
        store.save(s, connector.validate(json.loads(PDF_ANSWER)), "/x/FY27 V2MOM.pdf")
        pieces, slices = pe.build(s, "2026-02-01", "2026-10-29")
        got = [p for p in pieces if p["kind"] == "checkin"]
        assert [p["text"] for p in got] == ["V2MOM check-in (Midyear FY27), manager comments: Strong half. The "
                                            "community sessions landed well with other teams."]
        assert [k for k, ns in slices.items() if got[0]["n"] in ns] == ["summary", "accomplishments", "behaviors"]
        store.save(s, connector.validate(json.loads(answer(*TWO))), DOC_ID)  # the Doc has no check-ins
        assert not any(p["kind"] == "checkin" for p in pe.build(s, "2026-02-01", "2026-10-29")[0])


def test_long_manager_comments_are_cut(tmp_path):
    dd, Session = personal(tmp_path)
    data = json.loads(PDF_ANSWER)
    data["check_ins"] = [dict(name="Midyear FY27 Check-In", manager_comments="word " * 300)]
    with Session() as s:
        store.save(s, connector.validate(data), "/x/FY27 V2MOM.pdf")
        text = next(p["text"] for p in pe.build(s, "2026-02-01", "2026-10-29")[0] if p["kind"] == "checkin")
        assert len(text.split("manager comments: ")[1]) == 600


def test_doc_mode_still_reads_through_the_connector(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(connector, "fetch", lambda doc: seen.setdefault("doc", doc) and "made-up doc text " * 5)
    monkeypatch.setattr(connector, "ask", lambda prompt, data, timeout=240: seen.setdefault("prompt", prompt)
                        and answer(*TWO))
    parsed, origin = connector.read(SRC)
    assert seen == dict(doc=DOC_ID, prompt=connector.PROMPT) and origin == DOC_ID and len(parsed["methods"]) == 2
