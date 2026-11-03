"""KSOs: reading the framework (one fiscal year per row), and matching V2MOM methods to its components.
All with fake readers and the made-up framework in careeros.fixtures.kso."""
import json
from datetime import date
import stat

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from careeros.claude_cli import ClaudeError
from careeros.cli import app as cli
from careeros.fixtures.kso import reply as fw_reply
from careeros.kso import framework, map as kmap
from careeros.storage.models import KsoFramework, KsoMap

from test_guide import nb, session  # noqa: F401
from test_v2mom import TWO
from test_v2mom_links import load_v2mom

SRC = dict(decks=["1DeckDeckDeckDeckDeckDeckDeck00"], canvases=["F0MADEUP01"], track="Delivery", manager=False)


def connect(s, fy="FY27", **changes):
    return framework.save(s, framework.parse("material", reader=lambda p, d: json.dumps(fw_reply(fy, **changes))), SRC)


def picks(**m):
    return lambda p, d: json.dumps({"map": m})


def test_the_framework_is_read_and_kept_per_fiscal_year(nb):
    dd, *_ = nb
    with session(dd) as s:
        fw = connect(s)
        assert fw.fiscal_year == "FY27" and fw.track == "Delivery"
        assert [c["key"] for c in framework.components(fw)] == ["1.1", "1.2", "2.1", "2.2"]
        assert fw.data["payout"] == {"1": 0, "2": 40, "3": 70, "4": 100, "5": 120}
        connect(s, ksos=fw_reply()["ksos"][:1])  # the same year again replaces it
        connect(s, "FY28")
        rows = {r.fiscal_year: r for r in s.scalars(select(KsoFramework))}
        assert sorted(rows) == ["FY27", "FY28"] and len(rows["FY27"].data["ksos"]) == 1
        assert framework.get(s).fiscal_year == "FY28" and framework.get(s, "FY27").fiscal_year == "FY27"


@pytest.mark.parametrize("bad, why", [
    (dict(payout={"1": 0, "2": 80, "3": 70, "4": 100, "5": 120}), "rise"),
    (dict(payout={"1": 0, "2": 40, "3": 70, "4": 100}), "ratings 1 to 5"),
    (dict(ksos=[]), "no KSOs"),
    (dict(ksos=[dict(fw_reply()["ksos"][0], weight=95), fw_reply()["ksos"][1]]), "more than 100"),
    (dict(ksos=3), "isn't a list"),
    (dict(ksos=[fw_reply()["ksos"][0], dict(fw_reply()["ksos"][1], key="1")]), "appears twice"),
])
def test_a_bad_framework_answer_saves_nothing(nb, bad, why):
    dd, *_ = nb
    with session(dd) as s:
        with pytest.raises(ClaudeError, match=why):
            connect(s, **bad)
        assert s.scalar(select(KsoFramework)) is None


def test_a_component_missing_a_level_or_examples_is_refused():
    k = fw_reply()["ksos"]
    no_level = json.loads(json.dumps(k))
    del no_level[0]["components"][0]["levels"]["3"]
    one_example = json.loads(json.dumps(k))
    one_example[1]["components"][1]["examples"] = ["Only one"]
    a_string = json.loads(json.dumps(k))
    a_string[1]["components"][1]["examples"] = "Write notes; ship"
    for ksos, why in ((no_level, "rubric"), (one_example, "examples"), (a_string, "isn't a list")):
        with pytest.raises(ValueError, match=why):
            framework.validate(fw_reply(ksos=ksos))


def test_sources_come_from_links_and_stay_private(nb):
    dd, *_ = nb
    src = framework.sources(["https://docs.google.com/presentation/d/1DeckDeckDeckDeckDeckDeckDeck00/edit"],
                            ["https://example.slack.com/docs/T0TEAM/F0MADEUP01"], "Delivery", False)
    assert src == SRC and framework.load_sources(dd) is None
    framework.save_sources(dd, src)
    assert framework.load_sources(dd) == SRC and stat.S_IMODE(framework.source_file(dd).stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        framework.sources([], [], "Delivery", False)


def test_fiscal_years_are_named_one_way(nb):
    from careeros.v2mom.report import fiscal_year, fy_name
    assert [fy_name(x) for x in ("FY2027", "fy 27", "FY27 Q4", "2027", "FY27_V2MOM.pdf", "FY275")] == \
        ["FY27", "FY27", "FY27", "", "FY27", ""]
    assert fiscal_year("FY2027", date(2027, 3, 1))[0] == "FY27"  # not this year's FY28
    dd, *_ = nb
    with session(dd) as s:
        assert connect(s, "FY2027").fiscal_year == "FY27"


def test_methods_are_matched_once_and_your_picks_stay(nb):
    dd, *_ = nb
    with session(dd) as s:
        m = load_v2mom(s)
        fw = connect(s)
        assert kmap.suggest(s, fw, reader=picks(M1="1.1", M2="")) == dict(mapped=1, none=1)
        assert kmap.suggest(s, fw, reader=lambda p, d: pytest.fail("nothing left to ask")) == dict(mapped=0, none=0)
        kmap.set_pick(s, "FY27", m["M2"], "2.2")
        kmap.suggest(s, fw, redo=True, reader=picks(M1="1.2"))  # only Claude's pick is asked again
        rows = {r.method_id: (r.component, r.by_ai) for r in s.scalars(select(KsoMap))}
        assert rows == {m["M1"]: ("1.2", True), m["M2"]: ("2.2", False)}
        by = kmap.by_component(s, fw)
        assert [x.label for x, _ in by["2.2"]] == ["M2"] and by["2.1"] == []


def test_a_renamed_component_gets_its_methods_matched_again(nb):
    dd, *_ = nb
    with session(dd) as s:
        m = load_v2mom(s)
        fw = connect(s)
        kmap.suggest(s, fw, reader=picks(M1="1.1", M2=""))
        kmap.set_pick(s, "FY27", m["M2"], "2.2")
        ksos = fw_reply()["ksos"]
        ksos[0]["components"][0]["key"] = "1.3"  # the new material renames 1.1, and drops nothing else
        fw = connect(s, ksos=ksos)
        assert [x.label for x in kmap.pending(s, fw)] == ["M1"]
        kmap.suggest(s, fw, reader=picks(M1="1.3"))
        assert [x.label for x, _ in kmap.by_component(s, fw)["1.3"]] == ["M1"]


def test_methods_wait_for_their_own_years_ksos(nb):
    dd, *_ = nb
    with session(dd) as s:
        load_v2mom(s)  # an FY27 V2MOM
        fw28 = connect(s, "FY28")
        assert kmap.pending(s, fw28) == [] and framework.for_current(s) is None
        assert [x.label for x in kmap.pending(s, connect(s))] == ["M1", "M2"]
        assert framework.for_current(s).fiscal_year == "FY27"


@pytest.mark.parametrize("answer", ['{"map": {"M1": "9.9", "M2": ""}}', '{"map": {"M1": "1.1"}}', "no JSON"])
def test_a_bad_match_answer_changes_nothing(nb, answer):
    dd, *_ = nb
    with session(dd) as s:
        load_v2mom(s)
        fw = connect(s)
        kmap.suggest(s, fw, reader=picks(M1="1.1", M2=""))
        with pytest.raises(ClaudeError, match="Nothing was changed"):
            kmap.suggest(s, fw, redo=True, reader=lambda p, d: answer)
        assert len(s.scalars(select(KsoMap)).all()) == 2


def test_connect_and_show_from_the_command_line(nb, monkeypatch):
    dd, *_ = nb
    with session(dd) as s:
        load_v2mom(s, TWO)
    seen = {}
    monkeypatch.setattr(framework, "fetch", lambda src: seen.setdefault("src", src) and "material")
    monkeypatch.setattr(framework, "ask", lambda p, d, timeout=0: json.dumps(fw_reply()))
    monkeypatch.setattr(kmap, "ask", lambda p, d, timeout=0: json.dumps({"map": {"M1": "1.1", "M2": "2.2"}}))
    r = CliRunner().invoke(cli, ["kso", "connect", "--deck", "1DeckDeckDeckDeckDeckDeckDeck00", "--canvas",
                                 "F0MADEUP01", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert "FY27 Delivery: KSO 1 Calm Releases (20%, 2 parts)" in r.output and "Matched 2 V2MOM methods" in r.output
    assert seen["src"] == SRC
    r = CliRunner().invoke(cli, ["kso", "show", "--data-dir", str(dd.root)])
    assert "1.1 Plan Kept: M1 (AI)" in r.output and "1.2 Kind Feedback: no V2MOM goal yet" in r.output
    monkeypatch.setattr(framework, "ask", lambda p, d, timeout=0: "not JSON")
    r = CliRunner().invoke(cli, ["kso", "connect", "--data-dir", str(dd.root)])  # re-reads the saved sources
    assert r.exit_code == 1 and "Nothing was changed" in r.output


def test_the_v2mom_sync_matches_new_methods_once_ksos_are_connected(nb, monkeypatch):
    from careeros.web import syncs
    import threading
    dd, *_ = nb
    with session(dd) as s:
        load_v2mom(s)
        assert syncs._kso_matches(s, threading.Lock()) == ""  # no KSOs yet: nothing asked
        connect(s)
        monkeypatch.setattr(kmap, "ask", lambda p, d, timeout=0: json.dumps({"map": {"M1": "2.1", "M2": "1.2"}}))
        assert "2 new methods matched to KSOs" in syncs._kso_matches(s, threading.Lock())
        assert syncs._kso_matches(s, threading.Lock()) == ""


def test_a_bad_link_never_replaces_the_saved_ones(nb, monkeypatch):
    dd, *_ = nb
    framework.save_sources(dd, SRC)
    monkeypatch.setattr(framework, "fetch", lambda src: (_ for _ in ()).throw(ClaudeError("The canvas wasn't found.")))
    r = CliRunner().invoke(cli, ["kso", "connect", "--canvas", "F0TYPO0000", "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and framework.load_sources(dd) == SRC
