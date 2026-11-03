"""The KSO page: the bars (plain math from the V2MOM), the gap warning, your rating and target, the bonus
projection, and moving a method to another KSO part. Made-up framework and V2MOM only."""
import json

from sqlalchemy import select

from careeros.kso import map as kmap, progress
from careeros.storage.models import KsoMap

from test_guide import form, nb, session  # noqa: F401
from test_kso import connect, picks
from test_v2mom_links import load_v2mom


def setup(dd):
    """FY27 made-up KSOs; M1 (69%) counts toward 1.1 and M2 (50%) toward 2.1."""
    with session(dd) as s:
        m = load_v2mom(s)
        kmap.suggest(s, connect(s), reader=picks(M1="1.1", M2="2.1"))
        return m


def test_without_ksos_the_page_says_how_to_connect(nb):
    dd, c, *_ = nb
    assert "No KSOs loaded yet" in c.get("/kso").text and 'href="/kso"' in c.get("/").text


def test_bars_average_the_v2mom_and_count_a_missing_goal_as_zero(nb):
    dd, *_ = nb
    setup(dd)
    with session(dd) as s:
        r = progress.build(s)
    k1, k2 = r["ksos"]
    assert [(x["key"], x["bar"], x["gap"]) for x in k1["components"]] == [("1.1", 69, False), ("1.2", None, True)]
    assert k1["bar"] == round((69 + 0) / 2) and k1["gaps"] == 1
    assert k2["bar"] == round((50 + 0) / 2)
    assert k1["components"][1]["kudos"] == 0 and k1["components"][0]["kudos"] is None  # kudos count for feedback
    assert r["projection"] is None


def test_the_page_shows_parts_examples_and_the_gap_warning(nb):
    dd, c, *_ = nb
    setup(dd)
    page = c.get("/kso").text
    assert "KSO 1 &middot; Calm Releases" in page and "20% of your bonus" in page
    assert "1 of its 2 parts has no V2MOM goal yet" in page and "No V2MOM goal yet" in page
    assert "Mark one V2MOM measure&#39;s progress" in page and "Standout plan kept" in page  # examples, rubric 5
    assert 'href="/v2mom/' in page


def test_target_rating_and_projection(nb):
    dd, c, token, _ = nb
    setup(dd)
    assert c.post("/kso/target", data={"fy": "FY27", "target": "1"}, follow_redirects=False).status_code == 403
    assert "like%2012000" in form(c, "/kso/target", token, fy="FY27", target="lots").headers["location"]
    form(c, "/kso/target", token, fy="FY27", target="$10,000")
    form(c, "/kso/rating", token, fy="FY27", kso="1", rating="4")
    page = c.get("/kso").text
    assert "If every KSO were rated 3: $2,100" in page and "5: $3,600" in page and "KSO part of your bonus" not in page
    form(c, "/kso/rating", token, fy="FY27", kso="2", rating="5")
    with session(dd) as s:
        p = progress.build(s)["projection"]
    assert [(x["share"], x["pays"]) for x in p["rows"]] == [(2000, 2000), (1000, 1200)] and p["total"] == 3200
    page = c.get("/kso").text
    assert "KSO part of your bonus: $3,200</b> of $3,000" in page and "The other 70% of your bonus" in page
    assert "rating" in form(c, "/kso/rating", token, fy="FY27", kso="9", rating="4").headers["location"]
    form(c, "/kso/rating", token, fy="FY27", kso="2", rating="")
    with session(dd) as s:
        assert progress.build(s)["ratings"] == {"1": 4}


def test_moving_a_method_makes_the_pick_yours_and_the_target_never_reaches_claude(nb):
    dd, c, token, _ = nb
    m = setup(dd)
    assert c.post("/kso/map", data={"fy": "FY27", "method_id": m["M2"], "component": "2.2"}).status_code == 403
    r = form(c, "/kso/map", token, fy="FY27", method_id=m["M2"], component="2.2")
    assert "M2 now counts toward KSO 2.2" in r.headers["location"].replace("%20", " ")
    with session(dd) as s:
        row = s.scalar(select(KsoMap).where(KsoMap.method_id == m["M2"]))
        assert (row.component, row.by_ai) == ("2.2", False)
    form(c, "/kso/target", token, fy="FY27", target="98765")
    seen = []
    with session(dd) as s:
        kmap.suggest(s, progress.framework.get(s), redo=True,
                     reader=lambda p, d: seen.append(p + d) or json.dumps({"map": {"M1": "1.1"}}))
    assert seen and "98765" not in seen[0]


def test_older_years_get_a_picker(nb):
    dd, c, *_ = nb
    setup(dd)
    with session(dd) as s:
        connect(s, "FY26")
    page = c.get("/kso").text
    assert '<option selected>FY27</option>' in page and "<option >FY26</option>" in page
    assert "KSOs FY26" in c.get("/kso?fy=FY26").text


def test_the_practice_notebook_has_made_up_ksos(tmp_path):
    from fastapi.testclient import TestClient
    from careeros.config import DataDir
    from careeros.fixtures.demo import seed
    from careeros.storage.db import init_db, make_engine, make_session_factory
    from careeros.web.app import create_app
    from test_guide import BASE
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
    m = setup(dd)
    form(c, "/kso/map", token, fy="FY27", method_id=m["M2"], component="")
    page = c.get("/kso").text
    assert "Not counting toward any KSO part" in page and f'for="map-{m["M2"]}">Counts toward, for M2' in page
    form(c, "/kso/map", token, fy="FY27", method_id=m["M2"], component="2.2")
    assert "Not counting toward any KSO part" not in c.get("/kso").text


def test_last_years_ksos_stay_in_view_until_this_years_are_read(nb):
    from test_v2mom import TWO
    dd, c, *_ = nb
    setup(dd)
    with session(dd) as s:
        load_v2mom(s, TWO, fy="FY28")  # next year's V2MOM, before next year's KSOs are connected
    page = c.get("/kso").text
    assert "KSOs FY27" in page and "wins and records in FY27" not in page  # no counts for a year that isn't current


def test_a_target_pasted_with_cents_is_kept_in_dollars(nb):
    dd, c, token, _ = nb
    setup(dd)
    form(c, "/kso/target", token, fy="FY27", target="$12,000.50")
    with session(dd) as s:
        assert progress.build(s)["target"] == 12000
    assert "like%2012000" in form(c, "/kso/target", token, fy="FY27", target="12.000.5").headers["location"]


def test_an_older_practice_notebook_gets_the_made_up_ksos(tmp_path):
    from careeros.config import DataDir
    from careeros.fixtures.demo import seed
    from careeros.kso import framework
    from careeros.storage.db import init_db, make_engine, make_session_factory
    from careeros.storage.models import KsoFramework
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
