"""The KSO page: the bars (plain math from the V2MOM), the gap warning, your rating, and moving a method
to another KSO part. Made-up framework and V2MOM only."""
import json

from sqlalchemy import select

from coffeeshop.kso import map as kmap, progress
from coffeeshop.storage.models import KsoMap

from helpers import BASE, TWO, connect, form, kso_setup, load_v2mom, open_session




def test_without_ksos_the_page_says_how_to_connect(nb):
    dd, c, *_ = nb
    assert "No KSOs loaded yet" in c.get("/kso").text and 'href="/kso"' in c.get("/").text


def test_bars_average_the_v2mom_and_count_a_missing_goal_as_zero(nb):
    dd, *_ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        r = progress.build(s)
    k1, k2 = r["ksos"]
    assert [(x["key"], x["bar"], x["gap"]) for x in k1["components"]] == [("1.1", 69, False), ("1.2", None, True)]
    assert k1["bar"] == round((69 + 0) / 2) and k1["gaps"] == 1
    assert k2["bar"] == round((50 + 0) / 2)
    assert k1["components"][1]["kudos"] == 0 and k1["components"][0]["kudos"] is None  # kudos count for feedback


def test_the_page_shows_parts_examples_and_the_gap_warning(nb):
    dd, c, *_ = nb
    kso_setup(dd)
    page = c.get("/kso").text
    assert "KSO 1 &middot; Calm Releases" in page and "What the KSOs pay" not in page and "$" not in page
    assert "1 of its 2 parts has no V2MOM goal yet" in page and "No V2MOM goal yet" in page
    assert "Mark one V2MOM measure&#39;s progress" in page and "Standout plan kept" in page  # examples, rubric 5
    assert 'href="/v2mom/' in page


def test_saving_a_rating(nb):
    dd, c, token, _ = nb
    kso_setup(dd)
    assert c.post("/kso/rating", data={"fy": "FY27", "kso": "1", "rating": "4"}, follow_redirects=False).status_code == 403
    form(c, "/kso/rating", token, fy="FY27", kso="1", rating="4")
    page = c.get("/kso").text
    assert 'id="rate-1"' in page and 'value="4" selected' in page and "$" not in page
    form(c, "/kso/rating", token, fy="FY27", kso="2", rating="5")
    assert "rating" in form(c, "/kso/rating", token, fy="FY27", kso="9", rating="4").headers["location"]
    form(c, "/kso/rating", token, fy="FY27", kso="2", rating="")
    with open_session(dd) as s:
        assert progress.build(s)["ratings"] == {"1": 4}


def test_moving_a_method_makes_the_pick_yours(nb):
    dd, c, token, _ = nb
    m = kso_setup(dd)
    assert c.post("/kso/map", data={"fy": "FY27", "method_id": m["M2"], "component": "2.2"}).status_code == 403
    r = form(c, "/kso/map", token, fy="FY27", method_id=m["M2"], component="2.2")
    assert "M2 now counts toward KSO 2.2" in r.headers["location"].replace("%20", " ")
    with open_session(dd) as s:
        row = s.scalar(select(KsoMap).where(KsoMap.method_id == m["M2"]))
        assert (row.component, row.by_ai) == ("2.2", False)
    seen = []
    with open_session(dd) as s:
        kmap.suggest(s, progress.framework.get(s), redo=True,
                     reader=lambda p, d: seen.append(p + d) or json.dumps({"map": {"M1": "1.1"}}))
    assert seen and "M1" in seen[0]


def test_performance_shows_last_year_only_when_that_year_is_stored(nb):
    from coffeeshop.v2mom.report import prior_year
    assert prior_year(["FY26", "FY27"], "FY27") == "FY26"
    assert prior_year(["FY27"], "FY27") is None and prior_year(["FY26"], "") is None
    dd, c, *_ = nb
    with open_session(dd) as s:
        load_v2mom(s, fy="FY26")
        connect(s, "FY26")
    one, _, _ = c.get("/performance").text.partition("<h2>Promotion (optional)</h2>")
    assert "<p class=\"st\">V2MOM</p>" in one and "FY26" in one and "FY27" not in one and "69%" in one
    assert 'class="grid2"' not in one
    with open_session(dd) as s:
        load_v2mom(s, fy="FY27")
        connect(s, "FY27")
    both, _, _ = c.get("/performance").text.partition("<h2>Promotion (optional)</h2>")
    assert "FY26" in both and "FY27" in both and both.index("FY26") < both.index("FY27")
    assert 'class="grid2"' in both and "<p class=\"st\">KSOs</p>" in both


def test_older_years_get_a_picker(nb):
    dd, c, *_ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        connect(s, "FY26")
    page = c.get("/kso").text
    assert '<option selected>FY27</option>' in page and "<option >FY26</option>" in page
    assert "KSOs FY26" in c.get("/kso?fy=FY26").text


def test_the_practice_notebook_has_made_up_ksos(tmp_path):
    from fastapi.testclient import TestClient
    from coffeeshop.config import DataDir
    from coffeeshop.fixtures.demo import seed
    from coffeeshop.storage.db import init_db, make_engine, make_session_factory
    from coffeeshop.web.app import create_app
    dd = DataDir(tmp_path / "demo")
    dd.init_demo()
    engine = make_engine(dd.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        seed(s)
    page = TestClient(create_app(dd), base_url=BASE).get("/kso").text
    assert "KSOs FY27" in page and "Calm Releases" in page


def test_a_method_moved_to_no_part_can_be_moved_back(nb):
    dd, c, token, _ = nb
    m = kso_setup(dd)
    form(c, "/kso/map", token, fy="FY27", method_id=m["M2"], component="")
    page = c.get("/kso").text
    assert "Not counting toward any KSO part" in page and f'for="map-{m["M2"]}">Counts toward, for M2' in page
    form(c, "/kso/map", token, fy="FY27", method_id=m["M2"], component="2.2")
    assert "Not counting toward any KSO part" not in c.get("/kso").text


def test_last_years_ksos_stay_in_view_until_this_years_are_read(nb):
    dd, c, *_ = nb
    kso_setup(dd)
    with open_session(dd) as s:
        load_v2mom(s, TWO, fy="FY28")  # next year's V2MOM, before next year's KSOs are connected
    page = c.get("/kso").text
    assert "KSOs FY27" in page and "wins and records in FY27" not in page  # no counts for a year that isn't current


def test_an_older_practice_notebook_gets_the_made_up_ksos(tmp_path):
    from coffeeshop.config import DataDir
    from coffeeshop.fixtures.demo import seed
    from coffeeshop.kso import framework
    from coffeeshop.storage.db import init_db, make_engine, make_session_factory
    from coffeeshop.storage.models import KsoFramework
    dd = DataDir(tmp_path / "demo")
    dd.init_demo()
    engine = make_engine(dd.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        seed(s)
        s.query(KsoFramework).delete()
        s.commit()
        seed(s)  # records exist already, so only the KSOs are added
        seed(s)
        assert s.query(KsoFramework).count() == 1 and framework.get(s).track == "Delivery"
