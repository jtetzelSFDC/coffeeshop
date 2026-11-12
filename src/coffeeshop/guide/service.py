"""Leveling guide storage, links from the user's work to guide items, and how much evidence each item has."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import write_private
from ..storage.models import GuideItem, GuideLink, JournalEntry, Win
from .parse import parse_guide
from .topics import grouped, suggest

PROFILE = "profile.json"
RESPONSIBILITIES_MAX = 2_000  # optional note; longer would crowd the daily prompt
SETUP_HINT = "uv run coffeeshop setup level"
POINTS = {"entry": 1, "small": 2, "medium": 3, "large": 4}
RECOGNITION_SIZE = "medium"  # kudos from someone else count like a medium win
STATUSES = [(6, "strong", "Strong"), (3, "shown", "Shown"), (1, "started", "Started"), (0, "gap", "Not yet")]


def read_profile(root: Path) -> dict:
    try:
        return json.loads((root / PROFILE).read_text())
    except (OSError, ValueError):
        return {}


def save_profile(root: Path, **changes) -> None:
    write_private(root / PROFILE, json.dumps({**read_profile(root), **changes}))


def _root(s: Session) -> Path:
    return Path(s.get_bind().url.database).parent  # profile.json sits next to the notebook's database


def profile(s: Session) -> dict:
    return read_profile(_root(s))


def save_level(s: Session, role: str, grade: int, title: str = "") -> None:
    save_profile(_root(s), role=role, grade=grade, title=title)


def level(s: Session) -> dict | None:
    """The saved role and grade, and `targets`: the next one or two grades the loaded guide has, so DevOps Grade 9
    goes for 11. `top` when the guide has no higher grade. None until `coffeeshop setup level` has run."""
    p = profile(s)
    if not isinstance(p.get("grade"), int):
        return None
    grades = sorted(s.scalars(select(GuideItem.grade).where(GuideItem.active, GuideItem.grade.is_not(None)).distinct()))
    targets = tuple(g for g in grades if g > p["grade"])[:2]
    return dict(role=str(p.get("role", "")), grade=p["grade"], title=str(p.get("title", "")), targets=targets,
                next=targets[0] if targets else None, top=bool(grades) and not targets)


def level_note(lv: dict | None) -> str:
    """What a page says when there's no Promo map: the top of the path, or how to choose a level."""
    if lv and lv["top"]:
        return (f"Grade {lv['grade']} is the top of the {lv['role'] or 'career'} path in the leveling guide, "
                "so there's no next level to map.")
    return f"Choose your role and level to see the Promo map. In Terminal: {SETUP_HINT}"


def person(lv: dict | None) -> str:
    """Who the prompts are about, e.g. "a DevOps Engineer on the DevOps career path"."""
    if not lv:
        return "someone"
    who = f"{'an' if lv['title'][0] in 'AEIOU' else 'a'} {lv['title']}" if lv["title"] else "someone"
    return f"{who} on the {lv['role']} career path" if lv["role"] else who


def grades_text(lv: dict | None) -> str:
    """The level for the prompts, e.g. "Grade 5, going for Grade 6, with some Grade 7 work"; "" before one is
    chosen."""
    if not lv:
        return ""
    t = lv["targets"]
    return (f"Grade {lv['grade']}" + (f", going for Grade {t[0]}" if t else ", the top of the path")
            + (f", with some Grade {t[1]} work" if len(t) > 1 else ""))


def import_guide(s: Session, guide: Path | str | list[dict]) -> dict:
    """Load or update the leveling guide from a CSV, or from items already read (one role of the workbook); items
    keep their rows (and links) by key."""
    items = parse_guide(guide) if isinstance(guide, (str, Path)) else guide
    have = {g.key: g for g in s.scalars(select(GuideItem))}
    seen, added, updated = set(), 0, 0
    for pos, it in enumerate(items):
        if it["key"] in seen:
            continue
        seen.add(it["key"])
        g = have.get(it["key"])
        if g is None:
            s.add(GuideItem(**it, position=pos, active=True))
            added += 1
        else:
            changed = (g.name, g.description, g.targets, g.category, g.active) != (
                it["name"], it["description"], it["targets"], it["category"], True)
            g.name, g.description, g.targets, g.category, g.position, g.active = (
                it["name"], it["description"], it["targets"], it["category"], pos, True)
            updated += changed
    retired = 0
    for key, g in have.items():
        if key not in seen and g.active:
            g.active = False  # kept so existing links still show; it just leaves the map
            retired += 1
    s.commit()
    return dict(added=added, updated=updated, retired=retired)


def has_guide(s: Session) -> bool:
    return s.scalar(select(GuideItem.id).where(GuideItem.active).limit(1)) is not None


def experiences(s: Session, grades: tuple[int, ...] | None = None) -> list[GuideItem]:
    """Key experiences of `grades` (default: the grades the saved level is going for)."""
    if grades is None:
        grades = (level(s) or {}).get("targets", ())
    return list(s.scalars(select(GuideItem).where(
        GuideItem.kind == "experience", GuideItem.active, GuideItem.grade.in_(grades)).order_by(GuideItem.position)))


def skills(s: Session) -> list[GuideItem]:
    return list(s.scalars(select(GuideItem).where(GuideItem.kind == "skill", GuideItem.active)
                          .order_by(GuideItem.position)))


def summaries(s: Session) -> dict[int, str]:
    return {g.grade: g.name for g in s.scalars(select(GuideItem).where(GuideItem.kind == "summary", GuideItem.active))}


def status(points: float) -> tuple[str, str]:
    return next((key, label) for floor, key, label in STATUSES if points >= floor)


def work_key(entry: JournalEntry | None, win: Win | None = None) -> str:
    """What counts once: a whole piece of work when the record is grouped, else the record (or a lone win) itself."""
    if entry is not None:
        return f"w{entry.work_item_id}" if entry.work_item_id else f"e{entry.id}"
    return f"win{win.id}"


def evidence(s: Session) -> dict[int, dict]:
    """item id -> {points, wins, entries}. Points count once per piece of work, at its strongest evidence,
    so a deployment seen in a meeting, a Slack thread, and a task (or an entry and the win made from it) scores once."""
    links = list(s.scalars(select(GuideLink)))
    wins = {w.id: w for w in s.scalars(select(Win).where(Win.id.in_({l.win_id for l in links if l.win_id})))}
    want = {l.entry_id for l in links if l.entry_id} | {w.entry_id for w in wins.values() if w.entry_id}
    entries = {e.id: e for e in s.scalars(select(JournalEntry).where(JournalEntry.id.in_(want)))}
    out: dict[int, dict] = {}
    for l in links:
        ev = out.setdefault(l.item_id, dict(points=0, wins=[], entries=[]))
        if l.win_id in wins:
            ev["wins"].append(wins[l.win_id])
    for l in links:
        ev = out[l.item_id]
        if l.entry_id in entries and all(w.entry_id != l.entry_id for w in ev["wins"]):
            ev["entries"].append(entries[l.entry_id])
    for ev in out.values():
        ev["wins"].sort(key=lambda w: w.day, reverse=True)
        ev["entries"].sort(key=lambda e: e.day, reverse=True)
        groups: dict[str, int] = {}
        for w in ev["wins"]:
            k = work_key(entries.get(w.entry_id), w)
            groups[k] = max(groups.get(k, 0), POINTS.get(w.size, 2))
        for e in ev["entries"]:
            k = work_key(e)
            groups[k] = max(groups.get(k, 0), POINTS[RECOGNITION_SIZE if e.kind == "recognition" else "entry"])
        ev["points"] = sum(groups.values())
    return out


def promo_map(s: Session) -> dict | None:
    """Topics as rows with each target grade's experiences, plus per-grade progress, skills, and impact counts.
    None with no level chosen, or at the top of the path where there's no next grade to map."""
    from .activities import counts
    from .topics import OTHER, PLAIN, TOPICS, topic_of
    lv = level(s)
    if not lv or not lv["targets"]:
        return None
    grades = lv["targets"]
    ev = evidence(s)
    empty = dict(points=0, wins=[], entries=[])

    def view(g: GuideItem) -> dict:
        e = ev.get(g.id, empty)
        key, label = status(e["points"])
        return dict(item=g, status=key, status_label=label, **e)

    exps = [view(g) for g in experiences(s, grades)]
    devops = grouped(lv["role"])
    rows = []
    for t in [*TOPICS, OTHER] if devops else [PLAIN]:
        cells = {gr: [x for x in exps if x["item"].grade == gr and (not devops or topic_of(x["item"].name) == t)]
                 for gr in grades}
        if any(cells.values()):
            rows.append(dict(topic=t, cells=cells))
    progress = {}
    for gr in grades:
        mine = [x for x in exps if x["item"].grade == gr]
        progress[gr] = dict(total=len(mine), **{k: sum(1 for x in mine if x["status"] == k)
                                                for _f, k, _l in STATUSES})
    skill_views = [dict(view(g), now=g.targets.get(str(lv["grade"])),
                        **{f"g{gr}": g.targets.get(str(gr)) for gr in grades}) for g in skills(s)]
    hi, lo = grades[-1], grades[0]
    rising = [x for x in skill_views if (x[f"g{hi}"] or 0) > (x[f"g{lo}"] or 0)]
    nxt = []  # one step per topic: finish the lower grade first, then step up
    for row in rows:
        t = row["topic"]
        for i, gr in enumerate(grades):
            todo = [x for x in row["cells"][gr] if x["status"] in ("gap", "started")]
            if todo and t.ideas:
                started = any(x["status"] != "gap" for gr2 in grades for x in row["cells"][gr2])
                nxt.append(dict(topic=t, grade=gr, item=todo[0]["item"], started=started,
                                idea=t.ideas[0] if i == 0 else t.ideas[-1]))
                break
    nxt.sort(key=lambda n: (not n["started"], n["grade"]))
    return dict(rows=rows, progress=progress, rising=rising, next=nxt,
                steady=[x for x in skill_views if x not in rising], summaries=summaries(s), grades=grades,
                current=lv["grade"], level=lv, impact=counts(s))


def suggested_ids(s: Session, text: str) -> set[int]:
    from .topics import topic_of
    topics, skill_names = suggest(text)
    keys = {t.key for t in topics}
    lv = level(s)
    ids = ({g.id for g in experiences(s, lv["targets"]) if topic_of(g.name).key in keys}
           if lv and grouped(lv["role"]) else set())
    return ids | {g.id for g in skills(s) if g.name in skill_names}


def linked_ids(s: Session, *, win_id: int | None = None, entry_id: int | None = None) -> set[int]:
    return set(s.scalars(select(GuideLink.item_id).where(GuideLink.win_id == win_id, GuideLink.entry_id == entry_id)))


def shown_ids(s: Session) -> set[int]:
    """The items the link page offers: the target grades' experiences and the skills, or none without a Promo map."""
    lv = level(s)
    if not lv or not lv["targets"]:
        return set()
    return {g.id for g in experiences(s, lv["targets"])} | {g.id for g in skills(s)}


def set_links(s: Session, ids: set[int], shown: set[int], *, win_id: int | None = None,
              entry_id: int | None = None) -> None:
    """The user's choice among the `shown` items; links to items not shown (an earlier grade's) stay."""
    ids &= shown
    s.execute(delete(GuideLink).where(GuideLink.win_id == win_id, GuideLink.entry_id == entry_id,
                                      GuideLink.item_id.in_(shown)))
    s.add_all(GuideLink(item_id=i, win_id=win_id, entry_id=entry_id, created_at=datetime.now()) for i in sorted(ids))
    s.commit()


def confirm(s: Session, entry_id: int) -> None:
    """The user checked this row: Claude's picks for it (links, V2MOM methods, type, drafted win) become the user's own."""
    e = s.get(JournalEntry, entry_id)
    if e is None:
        return
    e.reviewed = True
    e.work_fixed = True  # accepting the row accepts its grouping (or lack of one), so a regroup run leaves it alone
    wins = list(s.scalars(select(Win).where(Win.entry_id == entry_id)))
    for w in wins:
        w.by_ai = False
    for l in s.scalars(select(GuideLink).where(
            (GuideLink.entry_id == entry_id) | GuideLink.win_id.in_([w.id for w in wins]))):
        l.by_ai = False
    from ..v2mom.links import confirm as confirm_v2mom
    confirm_v2mom(s, entry_id, [w.id for w in wins])
    s.commit()


def ai_counts(s: Session) -> dict[str, int]:
    from sqlalchemy import func
    return dict(links=s.scalar(select(func.count()).select_from(GuideLink).where(
        GuideLink.by_ai, GuideLink.entry_id.is_not(None))) or 0,
                wins=s.scalar(select(func.count()).select_from(Win).where(Win.by_ai)) or 0)


def drop_links(s: Session, *, win_id: int) -> None:
    """A win's guide links, before it's deleted or relinked."""
    s.execute(delete(GuideLink).where(GuideLink.win_id == win_id))
