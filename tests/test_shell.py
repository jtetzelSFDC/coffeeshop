import re
from datetime import date

from coffeeshop.web.app import TABS, short_day

from helpers import open_session


PAGES = ["/", "/wins", "/performance", "/sheet", "/digest", "/ask", "/search?q=refresh", "/performance/case", "/impact/deployment", *TABS]


def test_every_page_has_the_app_name_and_no_greeting(nb):
    _, c, *_ = nb
    for path in PAGES:
        html = c.get(path).text
        assert '<a class="brand" href="/">coffee shop</a>' in html, path
        assert re.search(r"<title>Coffee Shop( · [^<]+)?</title>", html), path
        assert not re.search(r"Good (morning|afternoon|evening)|Fresh cup, fresh page", html), path
    assert "<title>Coffee Shop · Wins</title>" in c.get("/wins").text


def test_explanations_are_folded(nb):
    _, c, *_ = nb
    folded = {"/performance": "Each key experience from the leveling guide", "/wins": "starting with a verb works well",
              "/performance/case": "Claude writes each section", "/impact/deployment": "counts once per day it was done"}
    for path, text in folded.items():
        html = c.get(path).text
        before, sep, _ = html.partition(text)
        assert sep and before.rfind('<details class="howto">') > before.rfind("</details>"), path


def test_get_promo_redirects_to_performance(nb):
    _, c, *_ = nb
    r = c.get("/promo", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/performance"
    r = c.get("/promo/compare?a=1&b=2", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/performance/compare?a=1&b=2"


def test_short_day():
    this_year = date.today().year
    assert short_day(f"{this_year}-10-29") == "Oct 29"
    assert short_day(date(this_year - 1, 3, 5)) == f"Mar 5, {this_year - 1}"


def test_promo_map_is_compact(nb):
    from datetime import datetime
    from coffeeshop.storage.models import JournalEntry
    dd, c, *_ = nb
    with open_session(dd) as s:
        s.add(JournalEntry(day="2026-10-20", kind="meeting", text="Demo of the pipeline to the customer",
                           created_at=datetime.now()))
        s.commit()
    html = c.get("/performance").text
    assert 'href="/sheet?show=unlinked"' in html and "records might show guide items" in html
    assert "Start with what you've already done" not in html
    assert 'class="ready-row"' in html and html.count('<span class="st" title=') >= 6
