"""The leveling guide workbook, the saved role and level, and `setup level` / `guide update`.

Uses a tiny made-up workbook built here with openpyxl; made-up roles and text only.
"""
import json
from datetime import datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from careeros.cli import app as cli
from careeros.guide import parse
from careeros.guide.ai_review import prompt_for
from careeros.guide.parse import GuideFormatError, read_workbook
from careeros.guide.service import import_guide, level, promo_map, save_level
from careeros.storage.models import GuideItem, GuideLink, Win
from careeros.web.app import create_app

from helpers import BASE, form, open_session, personal


def label_b_tab(ws):
    """Labels in column B, a grade gap (no 6), skill cells as 1.0 and as "2\\n\\nShadows ...", a tab name with a
    trailing space."""
    ws.append(["Group: Made Up"])
    ws.append(["Career Path: Widget Release Engineering"])
    ws.append([None, "Grade", None, "Grade 4", "Grade 5 ", "Grade 7 (1234)"])
    ws.append([None, "Associated Job Titles", None, "Associate Widget Engineer", "Widget Engineer", "Widget Architect\n"])
    ws.append(["Job Profile", "Role Summary", None, "Learns widgets.", "Ships widgets.", "Designs widgets."])
    ws.append([None, "Key Experiences", None, "- Helps ship widgets", "- Ships widgets\n- Fixes widget builds",
               "- Leads widget design across teams"])
    ws.append(["Transferable Skills", "Communicate Effectively", "Says things clearly.", 1.0, "2\n\nShadows seniors", 3])
    ws.append(["Path-Specific Skills", "*Widget Tuning", "Tunes widgets.", 1.0, 2.0, 4.0])


def label_a_tab(ws):
    """Labels in column A, and Grade 7 and 8 each twice: a manager and an architect column."""
    ws.append(["Group: Made Up"])
    ws.append(["Career Path: Gadget Quality "])
    ws.append(["Grade", None, None, "Grade 6", "Grade 7", "Grade 7", "Grade 8", "Grade 8"])
    ws.append(["Associated Job Titles", None, None, "Gadget Tester", "Manager, Gadget Tests", "Gadget Test Architect",
               "Sr. Manager, Gadget Tests", "Sr. Gadget Test Architect"])
    ws.append(["Job Profile", "Role Summary", None, "Tests.", "Manages testers.", "Designs tests.", "Runs a practice.",
               "Sets test strategy."])
    ws.append([None, "Key Experiences", None, "- Tests gadgets", "- Manages a test team", "- Designs a test suite",
               "- Runs the test practice", "- Sets test strategy"])
    ws.append(["Transferable Skills", "Learning Mindset", "Keeps learning.", 2, 3, 3, 4, 4])


def write_workbook(path, *tabs):
    wb = openpyxl.Workbook()
    wb.active.title = "Welcome"
    wb.active.append(["Welcome to the made-up leveling guides"])
    for title, fill in tabs or (("Widget Release Engineeri ", label_b_tab), ("Gadget Quality", label_a_tab)):
        fill(wb.create_sheet(title))
    wb.save(path)
    return path


@pytest.fixture
def workbook(tmp_path, monkeypatch):
    """The repo's workbook, swapped for a made-up one."""
    (tmp_path / "repo").mkdir()
    path = write_workbook(tmp_path / "repo" / "leveling-guides.xlsx")
    monkeypatch.setattr(parse, "WORKBOOK", path)
    return path


def test_workbook_reads_both_label_columns_number_formats_gaps_and_repeated_grades(workbook):
    guides = {g["name"]: g for g in read_workbook()}
    assert list(guides) == ["Widget Release Engineering", "Gadget Quality", "Gadget Quality (Gadget Test Architect)"]
    w = guides["Widget Release Engineering"]
    assert w["levels"] == [dict(grade=4, title="Associate Widget Engineer"), dict(grade=5, title="Widget Engineer"),
                           dict(grade=7, title="Widget Architect")]
    skills = {i["name"]: i for i in w["items"] if i["kind"] == "skill"}
    assert skills["Communicate Effectively"]["targets"] == {"4": 1, "5": 2, "7": 3}
    assert skills["Widget Tuning"]["targets"] == {"4": 1, "5": 2, "7": 4}
    assert [i["name"] for i in w["items"] if i["kind"] == "experience" and i["grade"] == 5] == [
        "Ships widgets", "Fixes widget builds"]
    manager, architect = guides["Gadget Quality"], guides["Gadget Quality (Gadget Test Architect)"]
    assert [l["title"] for l in manager["levels"]] == ["Gadget Tester", "Manager, Gadget Tests",
                                                       "Sr. Manager, Gadget Tests"]
    assert [l["title"] for l in architect["levels"]] == ["Gadget Tester", "Gadget Test Architect",
                                                         "Sr. Gadget Test Architect"]
    assert {i["grade"]: i["name"] for i in architect["items"] if i["kind"] == "summary"} == {
        6: "Tests.", 7: "Designs tests.", 8: "Sets test strategy."}
    assert {i["name"]: i["targets"] for i in architect["items"] if i["kind"] == "skill"} == {
        "Learning Mindset": {"6": 2, "7": 3, "8": 4}}


def test_a_tab_that_does_not_read_is_named(tmp_path):
    path = write_workbook(tmp_path / "bad.xlsx", ("Good", label_b_tab), ("Notes", lambda ws: ws.append(["Just notes"])))
    with pytest.raises(GuideFormatError, match="Tab 'Notes'"):
        read_workbook(path)
    (tmp_path / "not.xlsx").write_text("not a workbook")
    with pytest.raises(GuideFormatError):
        read_workbook(tmp_path / "not.xlsx")


def test_next_level_is_the_next_grade_the_role_has_and_none_at_the_top(session, workbook):
    w = read_workbook()[0]
    import_guide(session, w["items"])
    assert level(session) is None and promo_map(session) is None  # nothing chosen yet
    save_level(session, w["name"], 5, "Widget Engineer")
    lv = level(session)
    assert (lv["next"], lv["targets"], lv["top"]) == (7, (7,), False)  # no Grade 6 in this role
    pm = promo_map(session)
    assert pm["grades"] == (7,) and [r["topic"].name for r in pm["rows"]] == ["Key experiences"]  # not DevOps: one list
    save_level(session, w["name"], 4)
    assert level(session)["targets"] == (5, 7)
    save_level(session, w["name"], 7, "Widget Architect")
    lv = level(session)
    assert (lv["next"], lv["targets"], lv["top"]) == (None, (), True) and promo_map(session) is None


def test_prompts_name_the_saved_role_and_grades():
    p = prompt_for(dict(role="Widget Release Engineering", grade=4, title="Associate Widget Engineer", targets=(5, 7)))
    assert p.startswith("You help an Associate Widget Engineer on the Widget Release Engineering career path "
                        "(Grade 4, going for Grade 5, with some Grade 7 work)")
    assert "Pick the Grade 7 experience only when" in p and "DevOps" not in p
    top = prompt_for(dict(role="Widget Release Engineering", grade=7, title="Widget Architect", targets=()))
    assert "Grade 7, the top of the path" in top and "Pick the Grade" not in top


def test_pages_work_before_a_level_is_chosen_and_at_the_top(tmp_path, workbook):
    dd, Session_ = personal(tmp_path)
    with Session_() as s:
        import_guide(s, read_workbook()[0]["items"])
        s.add(Win(day="2026-10-20", title="Shipped the widget", size="medium", created_at=datetime.now()))
        s.commit()
        wid = s.scalar(select(Win.id))
        item = s.scalar(select(GuideItem.id).where(GuideItem.kind == "skill"))
        s.add(GuideLink(item_id=item, win_id=wid, created_at=datetime.now()))
        s.commit()
    app = create_app(dd)
    c, tok = TestClient(app, base_url=BASE), app.state.csrf_token
    for page in ("/", "/promo"):
        assert "careeros setup level" in c.get(page).text
    assert "Choose your role and level" in c.get(f"/guide/link?win={wid}").text
    form(c, "/guide/link", tok, win=wid, next="/wins")  # saving the page without a Promo map keeps the links
    with open_session(dd) as s:
        assert s.scalar(select(GuideLink.item_id)) == item
        save_level(s, "Widget Release Engineering", 7, "Widget Architect")
    for page in ("/", "/promo", "/wins", "/sheet", "/promo/case"):
        assert c.get(page).status_code == 200
    for page in ("/", "/promo"):
        assert "Grade 7 is the top of the Widget Release Engineering path" in c.get(page).text


def test_setup_level_saves_the_choice_and_loads_the_guide_keeping_links(tmp_path, workbook):
    dd, Session_ = personal(tmp_path)
    r = CliRunner().invoke(cli, ["setup", "level", "--data-dir", str(dd.root)], input="1\n5\n")
    assert r.exit_code == 0, r.output
    assert "  1. Widget Release Engineering" in r.output and "Grade 5, Widget Engineer" in r.output
    assert "Saved: Widget Release Engineering, Grade 5 (Widget Engineer). Next level: Grade 7." in r.output
    assert json.loads((dd.root / "profile.json").read_text())["role"] == "Widget Release Engineering"
    with Session_() as s:
        item = s.scalar(select(GuideItem).where(GuideItem.name == "Leads widget design across teams")).id
        s.add(Win(day="2026-10-20", title="Led the widget design", size="large", created_at=datetime.now()))
        s.flush()
        s.add(GuideLink(item_id=item, win_id=s.scalar(select(Win.id)), created_at=datetime.now()))
        s.commit()
    r = CliRunner().invoke(cli, ["setup", "level", "--role", "widget release engineering", "--grade", "7",
                                 "--data-dir", str(dd.root)])
    assert r.exit_code == 0 and "That's the top of this path" in r.output and "0 new, 0 changed" in r.output
    with Session_() as s:
        assert s.scalar(select(GuideLink.item_id)) == item
    r = CliRunner().invoke(cli, ["setup", "level", "--role", "Gadget Quality", "--grade", "5",
                                 "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "has no Grade 5. Its grades: 6, 7, 8." in r.output
    r = CliRunner().invoke(cli, ["setup", "level", "--role", "Nope", "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "no role called \"Nope\"" in r.output


def test_saving_links_after_a_promotion_keeps_links_to_the_old_grade(tmp_path, workbook):
    dd, Session_ = personal(tmp_path)
    run = lambda grade: CliRunner().invoke(cli, ["setup", "level", "--role", "1", "--grade", grade,
                                                 "--data-dir", str(dd.root)])
    assert run("4").exit_code == 0
    with Session_() as s:
        five = s.scalar(select(GuideItem.id).where(GuideItem.name == "Ships widgets"))
        seven = s.scalar(select(GuideItem.id).where(GuideItem.name == "Leads widget design across teams"))
        s.add(Win(day="2026-10-20", title="Shipped the widget", size="medium", created_at=datetime.now()))
        s.commit()
        wid = s.scalar(select(Win.id))
    app = create_app(dd)
    c, tok = TestClient(app, base_url=BASE), app.state.csrf_token
    form(c, "/guide/link", tok, win=wid, item=[five], next="/wins")
    assert run("5").exit_code == 0  # promoted: the page now offers Grade 7 only
    assert "Ships widgets" not in c.get(f"/guide/link?win={wid}").text
    form(c, "/guide/link", tok, win=wid, item=[seven], next="/wins")
    with open_session(dd) as s:
        assert set(s.scalars(select(GuideLink.item_id))) == {five, seven}


def test_guide_update_checks_then_copies_and_says_what_changed(tmp_path, workbook):
    def renamed(ws):
        label_b_tab(ws)
        ws["A2"] = "Career Path: Widget Ops"
    new = write_workbook(tmp_path / "new.xlsx", ("Widget Ops", renamed), ("Gadget Quality", label_a_tab))
    bad = write_workbook(tmp_path / "bad.xlsx", ("Notes", lambda ws: ws.append(["Just notes"])))
    before = workbook.read_bytes()
    r = CliRunner().invoke(cli, ["guide", "update", str(bad)])
    assert r.exit_code == 1 and "Nothing was changed" in r.output and workbook.read_bytes() == before
    r = CliRunner().invoke(cli, ["guide", "update", str(new)])
    assert r.exit_code == 0, r.output
    assert "Added: Widget Ops" in r.output and "Removed: Widget Release Engineering" in r.output
    assert "Changed: none" in r.output and workbook.read_bytes() == new.read_bytes()
    workbook.write_text("damaged")  # a repo copy that no longer reads doesn't block a good download
    r = CliRunner().invoke(cli, ["guide", "update", str(new)])
    assert r.exit_code == 0 and "doesn't read" in r.output and workbook.read_bytes() == new.read_bytes()
