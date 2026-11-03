"""Linking records to V2MOM methods: Claude's picks in the guide review, Looks right, removing and editing links,
the one-time backfill, and the evidence per method. All with fake readers."""
import json
from datetime import datetime

from sqlalchemy import select
from typer.testing import CliRunner

from careeros.cli import app as cli
from careeros.guide import ai_review
from careeros.storage.models import JournalEntry, V2momLink, Win
from careeros.v2mom import connector, links, store

from test_guide import form, nb, session  # noqa: F401
from test_review import add
from test_v2mom import DOC_ID, TWO, answer


def load_v2mom(s, methods=TWO, fy="FY27"):
    store.save(s, connector.validate(json.loads(answer(*methods, fy=fy))), DOC_ID)
    return {m.label: m.id for m in store.methods(s)}


def reader(picks):
    """A guide reader that also answers V2MOM picks by record text."""
    seen = []

    def read(guide, themes, records, v2mom=None):
        seen.append(v2mom)
        return {r["id"]: dict(guide=[], kind=r["kind"], win=None, v2mom=picks.get(r["text"], [])) for r in records}
    read.seen = seen
    return read


def test_the_guide_review_also_picks_v2mom_methods(nb):
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Ran a community session on release trains")
        b = add(s, "10:00 AM Standup", kind="meeting", source="calendar")
        m = load_v2mom(s)
        read = reader({"Ran a community session on release trains": ["M1", "M9", "M1"]})
        r = ai_review.review(s, reader=read)
        assert r["v2mom"] == 1 and [x["id"] for x in read.seen[0]] == ["M1", "M2"]
        assert read.seen[0][0]["measures"] == ["Q2: Present at 2 community sessions"]
        l = s.scalar(select(V2momLink))
        assert (l.method_id, l.entry_id, l.by_ai) == (m["M1"], a, True)
        assert s.get(JournalEntry, a).v2mom_read and s.get(JournalEntry, b).v2mom_read


def test_the_real_reader_asks_for_v2mom_picks_only_when_a_v2mom_is_loaded(monkeypatch):
    sent = []
    monkeypatch.setattr(ai_review, "ask", lambda p, d, timeout=0: sent.append((p, json.loads(d))) or
                        '{"results": [{"id": "r0", "guide": [], "kind": "note", "win": null, "v2mom": ["M1"]}]}')
    recs = [dict(id="r0", day="2026-10-01", kind="note", source="typed", text="Ran a community session")]
    ai_review.read_batch([], [], recs)
    got = ai_review.read_batch([], [], recs, v2mom=[dict(id="M1", name="Share know-how")])
    assert '"v2mom"' not in sent[0][0] and "v2mom" not in sent[0][1]
    assert '4. "v2mom"' in sent[1][0] and sent[1][0].endswith("covering every record.")
    assert sent[1][1]["v2mom"][0]["id"] == "M1" and got["r0"]["v2mom"] == ["M1"]


def test_without_a_v2mom_records_stay_unread_for_the_backfill(nb):
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Shipped the shared pipeline template")
        read = reader({})
        ai_review.review(s, reader=read)
        assert read.seen == [None] and not s.get(JournalEntry, a).v2mom_read
        load_v2mom(s)
        assert [e.id for e in links.pending(s)] == [a]


def test_looks_right_makes_the_picks_yours(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        a = add(s, "Ran a community session on release trains")
        load_v2mom(s)
        ai_review.review(s, reader=reader({"Ran a community session on release trains": ["M2"]}))
    row = c.get("/sheet").text
    assert "AI: V2MOM M2" in row and "/sheet/v2mom/" in row
    assert form(c, f"/sheet/{a}/ok", token).status_code == 303
    with session(dd) as s:
        assert s.scalar(select(V2momLink)).by_ai is False and s.get(JournalEntry, a).v2mom_fixed


def test_removing_a_link_sticks(nb):
    dd, c, token, _ = nb
    text = "Ran a community session on release trains"
    with session(dd) as s:
        a = add(s, text)
        load_v2mom(s)
        ai_review.review(s, reader=reader({text: ["M1"]}))
        lid = s.scalar(select(V2momLink.id))
    assert form(c, f"/sheet/v2mom/{lid}/delete", token).status_code == 303
    with session(dd) as s:
        assert s.scalar(select(V2momLink)) is None and s.get(JournalEntry, a).v2mom_fixed
        ai_review.review(s, redo=True, reader=reader({text: ["M1"]}))
        assert s.scalar(select(V2momLink)) is None and links.pending(s) == []


def test_the_backfill_reads_only_records_not_yet_read_against_the_v2mom(nb):
    dd, *_ = nb
    with session(dd) as s:
        read_before = add(s, "Published the release primer")
        checked = add(s, "Presented at the community session")
        done = add(s, "Already read against the V2MOM")
        unread = add(s, "Not read by Claude at all yet")
        for eid in (read_before, done):
            s.get(JournalEntry, eid).ai_read = True
        s.get(JournalEntry, checked).reviewed = True
        s.get(JournalEntry, done).v2mom_read = True
        s.commit()
        load_v2mom(s)
        assert {e.id for e in links.pending(s)} == {read_before, checked}
        sent = []

        def read(methods, records):
            sent.extend(r["text"] for r in records)
            return {r["id"]: ["M1"] if "primer" in r["text"] else ["M2", "M1", "M2"] for r in records}
        assert links.tag(s, links.pending(s), reader=read) == dict(read=2, links=3, failed=0)
        assert sorted(sent) == ["Presented at the community session", "Published the release primer"]
        assert links.pending(s) == [] and s.get(JournalEntry, unread).v2mom_read is False
        assert all(l.by_ai for l in s.scalars(select(V2momLink)))


def test_edit_page_sets_your_methods_and_keeps_old_ones(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        a = add(s, "Ran a community session on release trains")
        old = load_v2mom(s, fy="FY26")
        s.add(V2momLink(method_id=old["M2"], entry_id=a, created_at=datetime.now()))
        s.commit()
        new = load_v2mom(s, methods=[("Grow The Next Release Leads", "On Track", 10)])
    page = c.get("/guide/link", params={"entry": a, "next": "/sheet"}).text
    assert "Which V2MOM methods does this move forward?" in page and "M1: Grow The Next Release Leads" in page
    assert form(c, "/guide/link", token, entry=a, method=[new["M1"]], next="/sheet").status_code == 303
    with session(dd) as s:
        assert {(l.method_id, l.by_ai) for l in s.scalars(select(V2momLink))} == {(old["M2"], False), (new["M1"], False)}
        assert s.get(JournalEntry, a).v2mom_fixed
    assert "V2MOM old" in c.get("/sheet", params={"show": "all"}).text


def test_evidence_counts_wins_made_from_linked_records_and_removal_cleans_up(nb):
    dd, c, token, _ = nb
    with session(dd) as s:
        a = add(s, "Ran a community session on release trains", day="2026-10-01")
        b = add(s, "Wrote the release primer", day="2026-10-05")
        m = load_v2mom(s)
        s.add_all([V2momLink(method_id=m["M1"], entry_id=a, created_at=datetime.now()),
                   V2momLink(method_id=m["M1"], entry_id=b, created_at=datetime.now())])
        w = Win(day="2026-10-01", title="Ran the community session", entry_id=a, created_at=datetime.now())
        solo = Win(day="2026-10-09", title="Coached a new release lead", created_at=datetime.now())
        s.add_all([w, solo])
        s.flush()
        s.add(V2momLink(method_id=m["M2"], win_id=solo.id, created_at=datetime.now()))
        s.commit()
        ev = links.evidence(s)
        assert [e.id for e in ev[m["M1"]]["entries"]] == [b, a] and [x.title for x in ev[m["M1"]]["wins"]] == [w.title]
        assert (len(ev[m["M2"]]["entries"]), [x.title for x in ev[m["M2"]]["wins"]]) == (0, [solo.title])
        wid = solo.id
    assert form(c, f"/sheet/{a}/remove", token).status_code == 303
    assert form(c, f"/wins/{wid}/delete", token).status_code == 303
    with session(dd) as s:
        assert [(l.method_id, l.entry_id) for l in s.scalars(select(V2momLink))] == [(m["M1"], b)]


def test_cli_tag(nb, monkeypatch):
    dd, *_ = nb
    with session(dd) as s:
        a = add(s, "Published the release primer", day="2020-01-01")
        s.get(JournalEntry, a).ai_read = True
        s.commit()
        load_v2mom(s)
    monkeypatch.setattr(links, "ask", lambda p, d, timeout=0: json.dumps({"results": [{"id": "r0", "v2mom": ["M2"]}]}))
    r = CliRunner().invoke(cli, ["v2mom", "tag", "--data-dir", str(dd.root)])
    assert "Nothing to read" in r.output  # older than 90 days
    r = CliRunner().invoke(cli, ["v2mom", "tag", "--all", "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert "Read 1 records: 1 V2MOM links" in r.output
