"""The numbered evidence a promotion case is written from: built from the notebook only, nothing else.

Each piece has a number the draft cites, a plain-text line Claude reads, and refs back to the records or wins it
came from. Each section of the case gets its own slice of the pieces.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..guide.activities import LABEL, counts_between
from ..guide.service import level, promo_map
from ..guide.topics import grouped, short_name
from ..storage.models import GuideItem, GuideLink, JournalEntry, Win, WorkItem
from ..v2mom import links as v2mom_links, store as v2mom_store

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEMPLATE = Path(__file__).resolve().parents[3] / "data" / "pat" / "pat-template.docx"
# Headings the bundled template must contain. Promotion Readiness introduces the last two; it is not its own draft.
PAT_HEADINGS = (
    "Project Highlights",
    "Business Contributions",
    "Professional Development",
    "Feedback",
    "Promotion Readiness",
    "Strategic Business Need",
    "Talent Readiness",
)
PAT_KEYS = (
    ("highlights", "Project Highlights"),
    ("contributions", "Business Contributions"),
    ("development", "Professional Development"),
    ("feedback", "Feedback"),
    ("business_need", "Strategic Business Need"),
    ("talent", "Talent Readiness"),
)
# shortcut: form labels in the template are shorter than the instructions; raise this if a real instruction is shorter
_MIN_GUIDANCE = 80


def _norm(text: str) -> str:
    return text.casefold().strip().rstrip(":")


def docx_paragraphs(path: Path) -> list[str]:
    """Paragraphs of a docx, in order. A docx is a zip; the words live in word/document.xml."""
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    out = []
    for para in root.iter(_W + "p"):
        parts = []
        for node in para.iter():
            if node.tag == _W + "t" and node.text:
                parts.append(node.text)
            elif node.tag in (_W + "tab", _W + "br"):
                parts.append(" ")
        text = " ".join("".join(parts).split())
        if text:
            out.append(text)
    return out


def _between(paras: list[str], start: str, stops: set[str]) -> list[str]:
    """Paragraphs after `start` until the next label in `stops`."""
    try:
        i = next(n for n, para in enumerate(paras) if _norm(para) == _norm(start))
    except StopIteration:
        raise ValueError(f"The performance template has no heading {start!r}") from None
    body = []
    for para in paras[i + 1:]:
        if _norm(para) in stops:
            break
        body.append(para)
    return body


def _guidance(paras: list[str]) -> str:
    kept, seen = [], set()
    for para in paras:
        if len(para) < _MIN_GUIDANCE or para in seen:
            continue
        seen.add(para)
        kept.append(para)
    if not kept:
        raise ValueError("The performance template section has no guidance")
    return "\n".join(kept)


def _length(text: str) -> str:
    if m := re.search(r"minimum word count (\d+)", text, re.I):
        return f"at least {m.group(1)} words"
    if m := re.search(r"(\d+) word limit", text, re.I):
        return f"at most {m.group(1)} words"
    return "a concise section"


def read_template(path: Path | None = None) -> dict:
    """Section guidance, plus the preamble's valued and avoid lists, from the bundled blank template."""
    paras = docx_paragraphs(path or TEMPLATE)
    stops = {_norm(h) for h in (*PAT_HEADINGS, "Employee Information", "What is Valued", "What to Avoid")}
    valued = _between(paras, "What is Valued", stops)
    avoid = _between(paras, "What to Avoid", stops)
    if not valued or not avoid:
        raise ValueError("The performance template is missing What is valued or What to avoid")
    parent = _guidance(_between(paras, "Promotion Readiness", stops))
    sections = {}
    for heading in PAT_HEADINGS:
        if heading == "Promotion Readiness":
            continue
        own = _guidance(_between(paras, heading, stops))
        if heading in ("Strategic Business Need", "Talent Readiness"):
            own = parent + "\n" + own
        sections[heading] = dict(guidance=own, length=_length(own))
    return dict(valued="\n".join(valued), avoid="\n".join(avoid), sections=sections)


def _load() -> tuple[list[tuple[str, str, str, str]], str, str]:
    doc = read_template()
    sections = []
    for key, heading in PAT_KEYS:
        g = doc["sections"][heading]
        sections.append((key, heading, g["guidance"], g["length"]))
    return sections, doc["valued"], doc["avoid"]


SECTIONS, VALUED, AVOID = _load()  # key, heading, template guidance, how long

# Saved drafts from before the PAT headings still rewrite. New drafts use SECTIONS only.
LEGACY = [
    ("summary", "Summary", "where the candidate stands: {ready}, and the scale of the work", "3 to 4 sentences"),
    ("accomplishments", "Key accomplishments", "the most significant accomplishments, most significant first, one "
     "per sentence, saying what was done and how big it was", "5 to 8 sentences"),
    ("impact", "Impact", "what changed because of the work: outcomes, who it helped, and the activity counts",
     "3 to 6 sentences"),
    ("behaviors", "Behaviors & values", "how the candidate works: communication, mentoring, ownership, improving "
     "process, helping other teams", "3 to 5 sentences"),
    ("growth", "Growth areas", "an honest account of the {aims} experiences not shown yet, and the "
     "concrete next steps; do not spin gaps as strengths", "3 to 5 sentences"),
]


def section_words(lv: dict) -> dict[str, str]:
    """{ready} and {aims} in SECTIONS, e.g. "ready for Grade 6, the areas where the work already reaches Grade 7"
    and "Grade 6 and Grade 7"."""
    t = lv["targets"]
    if not t:
        return dict(ready=f"how the work measures up to Grade {lv['grade']}", aims=f"Grade {lv['grade']}")
    return dict(ready=f"ready for Grade {t[0]}" + (f", the areas where the work already reaches Grade {t[1]}"
                                                  if len(t) > 1 else ""),
                aims=" and ".join(f"Grade {g}" for g in t))
SIZE_ORDER = {"large": 0, "medium": 1, "small": 2}
CAPS = dict(highlights=50, contributions=40, development=40, feedback=40, business_need=40, talent=40)
SUMMARY_WINS = 15  # leaves room in Talent Readiness for the counts and the Performance map
SKILL_ACTIVITIES = {"mentoring", "process_change", "document", "demo", "training"}


def _label(g: GuideItem, devops: bool) -> str:
    return f"{short_name(g.name, devops)} (Grade {g.grade})" if g.kind == "experience" else g.name


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _advances(labels) -> str:
    return f" Advances V2MOM {', '.join(sorted(labels, key=lambda x: int(x[1:])))}." if labels else ""


def build(s: Session, start: str, end: str) -> tuple[list[dict], dict[str, list[int]]]:
    """(pieces, section key -> piece numbers). Only records and wins dated inside the window count."""
    items = {g.id: g for g in s.scalars(select(GuideItem))}
    devops = grouped((level(s) or {}).get("role", ""))
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

    shown: dict[int, set[str]] = {}  # piece number -> activities of its own records, for the counts below

    def add(kind: str, text: str, day: str, refs: list[dict], into: list[str]) -> None:
        n = len(pieces) + 1
        pieces.append(dict(n=n, kind=kind, text=text, day=day, refs=refs))
        if kind in ("win", "work", "record"):
            shown[n] = {entries[r["entry"]].activity for r in refs if r.get("entry") in entries} - {""}
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
            [dict(v2mom=m.id), *(dict(win=w.id) for w in mw), *(dict(entry=e.id) for e in me)],
            ["highlights", "contributions", "business_need", "talent"])

    # the manager's own words from the current V2MOM's check-ins
    v = v2mom_store.current(s)
    for c in (v.check_ins or []) if v else []:
        if c.get("manager_comments"):
            name = re.sub(r"\s*check-?in\s*$", "", c["name"], flags=re.I) or c["name"]
            add("checkin", f"V2MOM check-in ({name}), manager comments: {' '.join(c['manager_comments'].split())[:600]}",
                end, [], ["feedback"])

    # then wins: the strongest evidence
    won_entries = set()
    for i, w in enumerate(wins):
        g = shows.get(("win", w.id), [])
        text = f"Win ({w.size}, {w.day}): {w.title}." + (f" Why it mattered: {w.impact}" if w.impact else "") \
            + (f" Shows: {', '.join(_label(x, devops) for x in g)}." if g else "") + _advances(advances.get(("win", w.id)))
        into = ["highlights"] + (["contributions"] if w.impact else []) \
            + (["talent"] if w.size != "small" and i < SUMMARY_WINS else []) \
            + (["development"] if any(x.kind == "skill" for x in g) else [])
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
                + (f" Shows: {', '.join(_label(x, devops) for x in g)}." if g else "")
                + (f" Activity: {', '.join(acts)}." if acts else "")
                + _advances(set().union(*(advances.get(("entry", e.id), set()) for e in recs))))
        into = ["highlights"] + (["contributions"] if acts else []) \
            + (["development"] if any(x.kind == "skill" for x in g) or {e.activity for e in recs} & SKILL_ACTIVITIES else [])
        add("work", text, recs[-1].day, [dict(entry=e.id) for e in recs], into)

    # recognition from other people, quoted as stored
    praised = [e for e in sorted(entries.values(), key=lambda e: e.day, reverse=True)
               if e.kind == "recognition" and e.id not in won_entries]
    for e in praised[:20]:
        g = shows.get(("entry", e.id), [])
        add("recognition", f"Recognition ({e.day}), quoted exactly: {e.text[:400]}"
            + (f" Shows: {', '.join(_label(x, devops) for x in g)}." if g else ""), e.day, [dict(entry=e.id)],
            ["feedback"])
    won_entries |= {e.id for e in praised}

    # single linked records that aren't part of a piece of work or a win
    singles = [e for e in sorted(entries.values(), key=lambda e: e.day, reverse=True)
               if not e.work_item_id and e.id not in won_entries and (shows.get(("entry", e.id)) or e.activity)]
    for e in singles[:60]:
        g = shows.get(("entry", e.id), [])
        text = f"Record ({e.day}): {e.text[:200]}." + (f" Shows: {', '.join(_label(x, devops) for x in g)}." if g else "") \
            + (f" Activity: {LABEL[e.activity]}." if e.activity else "")
        into = ["highlights"] + (["development"] if any(x.kind == "skill" for x in g) or e.activity in SKILL_ACTIVITIES
                                 else [])
        add("record", text, e.day, [dict(entry=e.id)], into)

    # activity counts over the window, each only in a section that also cites work of that activity, so a number
    # never shows up in a section with nothing behind it (a count with no such section is left out)
    for c in counts_between(s, start, end):
        into = [k for k in ("talent", "contributions") if any(c["key"] in shown.get(n, ()) for n in slices[k])]
        if into:
            add("count", f"Count: {c['n']} {c['label']} between {start} and {end}.", end, [dict(activity=c["key"])], into)

    # where the Promo map stands today, and what's still missing (no map at the top of the path)
    pm = promo_map(s)
    for gr in pm["grades"] if pm else ():
        p = pm["progress"][gr]
        add("progress", f"Performance map, Grade {gr}: {p['shown'] + p['strong']} of {p['total']} key experiences shown "
            f"({p['strong']} strong), {p['started']} started, {p['gap']} not shown yet.", end, [],
            ["talent", "development"])
    for row in pm["rows"] if pm else ():
        for gr in pm["grades"]:
            for x in row["cells"][gr]:
                if x["status"] in ("gap", "started"):
                    what = "not shown yet" if x["status"] == "gap" else "started, needs more evidence"
                    add("gap", f"Grade {gr} key experience {what}: {x['item'].name}", end, [], ["development"])
    for nxt in pm["next"] if pm else ():
        add("next", f"Next step idea for {nxt['topic'].name} (Grade {nxt['grade']}): {nxt['idea']}", end, [], ["development"])
    return pieces, slices
