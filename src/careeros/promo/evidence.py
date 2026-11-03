"""The numbered evidence a promotion case is written from: built from the notebook only, nothing else.

Each piece has a number the draft cites, a plain-text line Claude reads, and refs back to the records or wins it
came from. Each section of the case gets its own slice of the pieces.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..guide.activities import LABEL, counts_between
from ..guide.service import promo_map
from ..guide.topics import topic_of
from ..storage.models import GuideItem, GuideLink, JournalEntry, Win, WorkItem
from ..v2mom import links as v2mom_links, store as v2mom_store

SECTIONS = [  # key, heading, what goes in it (for Claude), how long
    ("summary", "Summary", "where the candidate stands: ready for Grade 6, the areas where the work already reaches "
     "Grade 7, and the scale of the work", "3 to 4 sentences"),
    ("accomplishments", "Key accomplishments", "the most significant accomplishments, most significant first, one "
     "per sentence, saying what was done and how big it was", "5 to 8 sentences"),
    ("impact", "Impact", "what changed because of the work: outcomes, who it helped, and the activity counts",
     "3 to 6 sentences"),
    ("behaviors", "Behaviors & values", "how the candidate works: communication, mentoring, ownership, improving "
     "process, helping other teams", "3 to 5 sentences"),
    ("growth", "Growth areas", "an honest account of the Grade 6 and Grade 7 experiences not shown yet, and the "
     "concrete next steps; do not spin gaps as strengths", "3 to 5 sentences"),
]
SIZE_ORDER = {"large": 0, "medium": 1, "small": 2}
CAPS = dict(summary=40, accomplishments=50, impact=40, behaviors=40, growth=40)
SUMMARY_WINS = 15  # leaves room in the summary for the counts and the Promo map progress
SKILL_ACTIVITIES = {"mentoring", "process_change", "document", "demo"}


def _label(g: GuideItem) -> str:
    return f"{topic_of(g.name).name} (Grade {g.grade})" if g.kind == "experience" else g.name


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _advances(labels) -> str:
    return f" Advances V2MOM {', '.join(sorted(labels, key=lambda x: int(x[1:])))}." if labels else ""


def build(s: Session, start: str, end: str) -> tuple[list[dict], dict[str, list[int]]]:
    """(pieces, section key -> piece numbers). Only records and wins dated inside the window count."""
    items = {g.id: g for g in s.scalars(select(GuideItem))}
    shows: dict[tuple[str, int], list[GuideItem]] = {}
    for l in s.scalars(select(GuideLink)):
        if l.item_id in items:
            shows.setdefault(("win", l.win_id) if l.win_id else ("entry", l.entry_id), []).append(items[l.item_id])
    entries = {e.id: e for e in s.scalars(select(JournalEntry).where(
        JournalEntry.day >= start, JournalEntry.day <= end, JournalEntry.status != "open"))}
    wins = sorted(s.scalars(select(Win).where(Win.day >= start, Win.day <= end)), key=lambda w: w.day, reverse=True)
    wins.sort(key=lambda w: SIZE_ORDER.get(w.size, 3))  # biggest first, newest first within a size
    # the current V2MOM's methods, and the wins and records in the window that advance each
    methods = v2mom_store.methods(s)
    linked = v2mom_links.evidence(s) if methods else {}
    win_ids = {w.id for w in wins}
    advancing: dict[int, tuple[list[Win], list[JournalEntry]]] = {}
    advances: dict[tuple[str, int], set[str]] = {}
    for m in methods:
        ev = linked.get(m.id, dict(entries=[], wins=[]))
        advancing[m.id] = ([w for w in ev["wins"] if w.id in win_ids], [e for e in ev["entries"] if e.id in entries])
        for key in [("win", w.id) for w in advancing[m.id][0]] + [("entry", e.id) for e in advancing[m.id][1]]:
            advances.setdefault(key, set()).add(m.label)
    pieces: list[dict] = []
    slices: dict[str, list[int]] = {k: [] for k, *_ in SECTIONS}

    def add(kind: str, text: str, day: str, refs: list[dict], into: list[str]) -> None:
        n = len(pieces) + 1
        pieces.append(dict(n=n, kind=kind, text=text, day=day, refs=refs))
        for key in into:
            if len(slices[key]) < CAPS[key]:
                slices[key].append(n)

    # one piece per V2MOM method with work in the window: how much, and a few examples. First, so a window full of
    # wins can't push them out of the capped sections
    for m in methods:
        mw, me = advancing[m.id]
        if not mw and not me:
            continue
        about = ", ".join([m.name] + ([m.status] if m.status else [])
                          + ([f"{m.progress}% progress"] if m.progress is not None else []))
        made = {w.entry_id for w in mw}
        examples = [w.title for w in mw] + [e.text for e in me if e.id not in made]
        text = (f"V2MOM {m.label} ({about}): {_plural(len(mw), 'win')} and {_plural(len(me), 'record')} between "
                f"{start} and {end}, for example: " + "; ".join(" ".join(x.split())[:80] for x in examples[:3]) + ".")
        add("v2mom", text, max([w.day for w in mw] + [e.day for e in me]),
            [dict(v2mom=m.id), *(dict(win=w.id) for w in mw), *(dict(entry=e.id) for e in me)], ["summary", "impact"])

    # the manager's own words from the current V2MOM's check-ins
    v = v2mom_store.current(s)
    for c in (v.check_ins or []) if v else []:
        if c.get("manager_comments"):
            name = re.sub(r"\s*check-?in\s*$", "", c["name"], flags=re.I) or c["name"]
            add("checkin", f"V2MOM check-in ({name}), manager comments: {' '.join(c['manager_comments'].split())[:600]}",
                end, [], ["summary", "accomplishments", "behaviors"])

    # then wins: the strongest evidence
    won_entries = set()
    for i, w in enumerate(wins):
        g = shows.get(("win", w.id), [])
        text = f"Win ({w.size}, {w.day}): {w.title}." + (f" Why it mattered: {w.impact}" if w.impact else "") \
            + (f" Shows: {', '.join(_label(x) for x in g)}." if g else "") + _advances(advances.get(("win", w.id)))
        into = ["accomplishments"] + (["impact"] if w.impact else []) \
            + (["summary"] if w.size != "small" and i < SUMMARY_WINS else []) \
            + (["behaviors"] if any(x.kind == "skill" for x in g) else [])
        add("win", text, w.day, [dict(win=w.id), *([dict(entry=w.entry_id)] if w.entry_id else [])], into)
        if w.entry_id:
            won_entries.add(w.entry_id)

    # pieces of work with guide links or an activity, unless a win already covers them
    members: dict[int, list[JournalEntry]] = {}
    for e in entries.values():
        if e.work_item_id:
            members.setdefault(e.work_item_id, []).append(e)
    for w in sorted(s.scalars(select(WorkItem).where(WorkItem.id.in_(members))), key=lambda w: w.day, reverse=True):
        recs = sorted(members[w.id], key=lambda e: e.day)
        if any(e.id in won_entries for e in recs):
            continue
        g = {x.id: x for e in recs for x in shows.get(("entry", e.id), [])}.values()
        acts = sorted({LABEL[e.activity] for e in recs if e.activity})
        if not g and not acts:
            continue
        text = (f"Piece of work: {w.title} ({recs[0].day} to {recs[-1].day}, {len(recs)} records): "
                + "; ".join(e.text[:120] for e in recs[:4]) + "."
                + (f" Shows: {', '.join(_label(x) for x in g)}." if g else "")
                + (f" Activity: {', '.join(acts)}." if acts else "")
                + _advances(set().union(*(advances.get(("entry", e.id), set()) for e in recs))))
        into = ["accomplishments"] + (["impact"] if acts else []) \
            + (["behaviors"] if any(x.kind == "skill" for x in g) or {e.activity for e in recs} & SKILL_ACTIVITIES else [])
        add("work", text, recs[-1].day, [dict(entry=e.id) for e in recs], into)

    # recognition from other people, quoted as stored
    praised = [e for e in sorted(entries.values(), key=lambda e: e.day, reverse=True)
               if e.kind == "recognition" and e.id not in won_entries]
    for e in praised[:20]:
        g = shows.get(("entry", e.id), [])
        add("recognition", f"Recognition ({e.day}), quoted exactly: {e.text[:400]}"
            + (f" Shows: {', '.join(_label(x) for x in g)}." if g else ""), e.day, [dict(entry=e.id)],
            ["summary", "impact", "behaviors"])
    won_entries |= {e.id for e in praised}

    # single linked records that aren't part of a piece of work or a win
    singles = [e for e in sorted(entries.values(), key=lambda e: e.day, reverse=True)
               if not e.work_item_id and e.id not in won_entries and (shows.get(("entry", e.id)) or e.activity)]
    for e in singles[:60]:
        g = shows.get(("entry", e.id), [])
        text = f"Record ({e.day}): {e.text[:200]}." + (f" Shows: {', '.join(_label(x) for x in g)}." if g else "") \
            + (f" Activity: {LABEL[e.activity]}." if e.activity else "")
        into = ["accomplishments"] + (["behaviors"] if any(x.kind == "skill" for x in g) or e.activity in SKILL_ACTIVITIES
                                      else [])
        add("record", text, e.day, [dict(entry=e.id)], into)

    # activity counts over the window
    for c in counts_between(s, start, end):
        add("count", f"Count: {c['n']} {c['label']} between {start} and {end}.", end, [dict(activity=c["key"])],
            ["summary", "impact"])

    # where the Promo map stands today, and what's still missing
    pm = promo_map(s)
    for gr in pm["grades"]:
        p = pm["progress"][gr]
        add("progress", f"Promo map, Grade {gr}: {p['shown'] + p['strong']} of {p['total']} key experiences shown "
            f"({p['strong']} strong), {p['started']} started, {p['gap']} not shown yet.", end, [],
            ["summary", "growth"])
    for row in pm["rows"]:
        for gr in pm["grades"]:
            for x in row["cells"][gr]:
                if x["status"] in ("gap", "started"):
                    what = "not shown yet" if x["status"] == "gap" else "started, needs more evidence"
                    add("gap", f"Grade {gr} key experience {what}: {x['item'].name}", end, [], ["growth"])
    for nxt in pm["next"]:
        add("next", f"Next step idea for {nxt['topic'].name} (Grade {nxt['grade']}): {nxt['idea']}", end, [], ["growth"])
    return pieces, slices
