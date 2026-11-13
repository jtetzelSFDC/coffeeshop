"""Ask Claude: the slice cites a real record number, and the notebook is not written (fake Claude)."""
import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from coffeeshop import ask
from coffeeshop.storage.models import Base, JournalAttachment, JournalEntry, Win

from helpers import add, link, load_v2mom, open_session


def _counts(s):
    return {name: s.scalar(select(func.count()).select_from(table)) for name, table in Base.metadata.tables.items()}


def test_answer_cites_a_sent_record_and_writes_nothing(nb):
    dd, *_ = nb
    today = date.today().isoformat()
    outside = (date.today() - timedelta(days=40)).isoformat()
    with open_session(dd) as s:
        s.add(JournalEntry(day=outside, kind="note", text="OUTSIDE WINDOW MARKER", created_at=datetime.now(),
                           source="slack"))
        for i in range(50):
            s.add(JournalEntry(day=today, kind="note", text=f"filler work {i} " + ("x" * 300),
                               created_at=datetime.now(), source="slack"))
        cited = JournalEntry(day=today, kind="task", text="Ran the Pine release", created_at=datetime.now(),
                             source="slack")
        s.add(cited)
        s.flush()
        s.add(JournalAttachment(entry_id=cited.id, kind="notes", title="Notes", body="SECRET NOTES TEXT",
                                created_at=datetime.now()))
        s.commit()
        eid = cited.id
        before = _counts(s)
        seen = []

        def reader(_prompt, data):
            seen.append(json.loads(data))
            return f"The Pine release [{seen[-1]['records'][0]['n']}] mattered most."

        text = ask.answer(s, "What was most impactful last week?", "week", reader=reader)
    payload, raw = seen[0], json.dumps(seen[0])
    cited_n = int(re.search(r"\[(\d+)\]", text).group(1))
    sent = {r["n"] for r in payload["records"]}
    assert cited_n == eid and cited_n in sent
    assert len(sent) < 50 and len(raw) <= ask.MAX_CONTEXT
    assert "SECRET NOTES TEXT" not in raw and "OUTSIDE WINDOW MARKER" not in raw
    assert payload["records"][0]["text"] == "Ran the Pine release" and payload["records"][0]["methods"] == []
    assert payload["values"] and payload["topics"]
    with open_session(dd) as s:
        assert _counts(s) == before
        assert s.get(JournalEntry, eid).text == "Ran the Pine release"
        assert s.scalar(select(JournalAttachment.body).where(JournalAttachment.entry_id == eid)) == "SECRET NOTES TEXT"


def test_a_method_linked_only_on_the_win_still_counts(nb):
    dd, *_ = nb
    today = date.today()
    with open_session(dd) as s:
        ids = load_v2mom(s)
        eid = add(s, "Pine release notes", day=today.isoformat())
        w = Win(day=today.isoformat(), title="Shipped Pine", size="small", entry_id=eid, created_at=datetime.now())
        s.add(w)
        s.flush()
        link(s, ids["M1"], win_id=w.id)
        s.commit()
        seen = []

        def reader(_prompt, data):
            seen.append(json.loads(data))
            return "M1 already covers it."

        ask.answer(s, "Work with no V2MOM method: suggest methods to add", "week", reader=reader, today=today)
    assert seen[0]["records"][0]["n"] == eid
    assert seen[0]["records"][0]["methods"] == ["M1"]
