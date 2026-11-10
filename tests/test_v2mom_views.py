"""The V2MOM page, the Home strip, and the digest nudge: counts per quarter and fiscal year, active/quiet/none, and
links that resolve. All made-up data."""
import re
from datetime import date, datetime, timedelta

from coffeeshop import digest
from coffeeshop.storage.models import JournalEntry, Win
from coffeeshop.v2mom import report

from helpers import TWO, add, link, load_v2mom, open_session


FOUR = TWO + [("Grow The Next Release Leads", "Completed", 100), ("Write Down The Runbooks", "At Risk", None)]
NOV_2 = date(2026, 11, 2)


def fixture(s, today):
    """M1 has work this quarter, M2 went quiet, M3 (Completed) has nothing linked, M4 only an open task."""
    m = load_v2mom(s, methods=FOUR)
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    recent = add(s, "Ran a community session on release trains", day=d(0))
    for eid in (recent, add(s, "Wrote the release primer outline", day=d(240))):
        link(s, m["M1"], entry_id=eid)
    link(s, m["M1"], entry_id=add(s, "Planned next month's session", day=d(-10)))  # dated later: left out
    link(s, m["M2"], entry_id=add(s, "Drafted the pipeline template", day=d(100)))
    todo = add(s, "Write the refresh runbook", kind="task", source="tasks", day=d(0))
    s.get(JournalEntry, todo).status = "open"  # not done yet: not evidence
    link(s, m["M4"], entry_id=todo)
    s.add(Win(day=d(0), title="Ran the community session", entry_id=recent, created_at=datetime.now()))
    s.commit()
    return m


def test_fiscal_year_and_quarter():
    assert report.fiscal_year("FY27", NOV_2) == ("FY27", date(2026, 2, 1), date(2027, 1, 31))
    assert report.fiscal_year("", date(2026, 1, 31))[0] == "FY26"
    assert report.fiscal_year("", date(2026, 2, 1)) == ("FY27", date(2026, 2, 1), date(2027, 1, 31))
    assert report.quarter(NOV_2) == (date(2026, 10, 1), date(2026, 12, 31))
    assert report.quarter(date(2026, 2, 1)) == (date(2026, 1, 1), date(2026, 3, 31))
    assert report.status_class("Completed") == "done" and report.status_class("At Risk") == "late"
    assert report.status_class("On Track") == ""


def test_counts_and_states_on_a_fixture(nb):
    dd, *_ = nb
    with open_session(dd) as s:
        m = fixture(s, NOV_2)  # 240 days before Nov 2 is Mar 7: in FY27, not this quarter; 100 days is Jul 25
        r = report.build(s, NOV_2)
        rows = {x["m"].label: x for x in r["methods"]}
        assert (r["fy"], r["active"], len(r["methods"])) == ("FY27", 1, 4)
        assert {k: (x["quarter"], x["year"], x["entries"], x["wins"], x["state"]) for k, x in rows.items()} == {
            "M1": (2, 3, 2, 1, "active"), "M2": (0, 1, 1, 0, "quiet"), "M3": (0, 0, 0, 0, "none"),
            "M4": (0, 0, 0, 0, "none")}
        assert rows["M1"]["last"] == "2026-11-02" and rows["M2"]["last"] == "2026-07-25"
        assert [o["name"] for o in rows["M1"]["obstacles"]] == ["Two Leads For Many Teams"] and r["loose"] == []
        assert rows["M1"]["pct"] == 100 and rows["M2"]["pct"] == 0
        assert m["M1"] == rows["M1"]["m"].id


def test_home_strip_numbers(nb):
    dd, c, *_ = nb
    assert "methods active this quarter" not in c.get("/").text  # hidden with no V2MOM
    with open_session(dd) as s:
        m = fixture(s, date.today())
    page = c.get("/").text
    assert "V2MOM: <b>1 of 4</b> methods active this quarter" in page
    assert f'href="/v2mom#m{m["M1"]}"' in page and 'aria-label="M1: 2 this quarter"' in page
    assert 'aria-label="M2: 0 this quarter"' in page


def test_digest_nudges_only_quiet_methods(nb):
    dd, *_ = nb
    with open_session(dd) as s:
        assert not any("V2MOM" in n["text"] for n in digest.build(s, NOV_2)["nudges"])  # no V2MOM yet
        fixture(s, NOV_2)
        got = [n for n in digest.build(s, NOV_2)["nudges"] if "V2MOM" in n["text"]]
        before_fy27 = digest.build(s, date(2026, 1, 20))["nudges"]
    assert not any("V2MOM" in n["text"] for n in before_fy27)  # the methods didn't exist yet
    assert [n["text"] for n in got] == [
        "Nothing new for V2MOM M2 (Build Reusable Pipeline Accelerators) in 30 days (last: 2026-07-25).",
        "Nothing linked to V2MOM M4 (Write Down The Runbooks) yet."]
    assert {n["link"] for n in got} == {"/v2mom"}


def test_the_page_renders_with_and_without_a_v2mom(nb):
    dd, c, *_ = nb
    page = c.get("/v2mom").text
    assert "No V2MOM loaded yet" in page and 'href="/v2mom" class="on"' in page
    with open_session(dd) as s:
        m = fixture(s, date.today())
    page = c.get("/v2mom").text
    assert "V2MOM FY27" in page and "1 of 4 methods active this quarter" in page
    assert "Vision and values" in page and "Releases so calm nobody notices them." in page
    assert "M1 Share Release Know-How Across Teams" in page and '<span class="chip done">Completed</span>' in page
    assert '<span class="chip late">At Risk</span>' in page and "Q2: Present at 2 community sessions" in page
    assert "Obstacle: Two Leads For Many Teams." in page and page.count("nothing linked yet") == 2
    assert f'href="/v2mom/{m["M1"]}"' in page and f'href="/v2mom/{m["M3"]}"' not in page
    detail = c.get(f"/v2mom/{m['M1']}").text
    assert "Wins (1)" in detail and "Records (3)" in detail and "Ran the community session" in detail
    assert "Planned next month" in detail  # the method's full list, including what's dated ahead
    assert c.get("/v2mom/9999").status_code == 404


def test_every_link_resolves(nb):
    dd, c, *_ = nb
    with open_session(dd) as s:
        m = fixture(s, date.today())
    pages = ["/", "/v2mom", f"/v2mom/{m['M1']}", "/digest"]
    hrefs = {h.split("#")[0] for p in pages for h in re.findall(r'href="(/[^"]*)"', c.get(p).text)}
    assert {"/v2mom", f"/v2mom/{m['M1']}"} <= hrefs
    for h in sorted(hrefs - {""}):
        assert c.get(h.replace("&amp;", "&")).status_code == 200, h
