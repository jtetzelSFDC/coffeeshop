"""Saves Slack canvas items as notebook entries, tagged as coming from Slack, once each."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DataDir, write_private
from ..storage.models import JournalAttachment, JournalEntry
from .parse import TRACKER, SlackItem, link_key

SOURCE = "slack"
NOTES_TITLE = "From Slack (AI-written)"
IMPACT_LINE = re.compile(r"^Why it mattered: (.+)$", re.M)


def new_items(s: Session, items: list[SlackItem]) -> list[SlackItem]:
    from ..storage.removal import removed_ids
    have = set(s.scalars(select(JournalEntry.external_id).where(JournalEntry.source == SOURCE))) | removed_ids(s, SOURCE)
    return [i for i in items if i.key not in have]


def _base(external_id: str) -> str:
    """A message record's id is slack:C/p…:YYYY-MM-DD; the canvas id is the part before the day."""
    head, _, tail = (external_id or "").rpartition(":")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tail) and head.startswith("slack:"):
        return head
    return external_id or ""


def linked_entry(s: Session, link: str, day: str | None = None) -> JournalEntry | None:
    """The Slack record whose link is this message, if one is already saved.

    A thread that spans days shares an id prefix. The record with this message's own link wins; a shared prefix
    matches only when one record has it, or `day` names which one.
    """
    msg = link_key(link)
    if not msg:
        return None
    rows = list(s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE)))
    if not rows:
        return None
    bodies: dict[int, list[str]] = {}
    for a in s.scalars(select(JournalAttachment).where(
            JournalAttachment.entry_id.in_([e.id for e in rows]), JournalAttachment.kind == "link")):
        bodies.setdefault(a.entry_id, []).append(a.body)
    exact, shared = [], []
    for e in rows:
        if msg in {link_key(b) for b in bodies.get(e.id, [])}:
            exact.append(e)
        elif msg == _base(e.external_id or ""):
            shared.append(e)
    if exact:
        return exact[0]
    if day and (same := [e for e in shared if e.day == day]):
        return same[0]
    return shared[0] if len(shared) == 1 else None


def link_removed(s: Session, link: str) -> bool:
    from ..storage.removal import removed_ids
    msg = link_key(link)
    return bool(msg) and any(_base(i) == msg for i in removed_ids(s, SOURCE))


def add_canvas_note(s: Session, entry: JournalEntry, it: SlackItem) -> None:
    """Add the canvas summary to a record. The record's day is left as it is: the message's date wins."""
    body = (it.body or "").strip()
    if not body:
        return
    have = list(s.scalars(select(JournalAttachment).where(
        JournalAttachment.entry_id == entry.id, JournalAttachment.kind == "notes")))
    if any(body in (a.body or "") for a in have):
        return
    s.add(JournalAttachment(entry_id=entry.id, kind="notes", title=f"{NOTES_TITLE}, {it.origin}", body=body,
                            created_at=datetime.now()))
    if not entry.reviewed:
        entry.ai_read = False


def import_items(s: Session, items: list[SlackItem], classify: Callable[[list[SlackItem]], dict[str, str]]) -> dict:
    """Save new tracker items as records, sorted by Claude into kinds; returns counts per kind.

    An item that links to a message already saved adds its summary to that record instead. An item with a link
    and no matching message is still saved, marked as from the canvas. Items with no link are saved as before.
    """
    fresh = []
    for it in items:
        if it.link and link_removed(s, it.link):
            continue
        if it.link and (e := linked_entry(s, it.link, it.day)):
            add_canvas_note(s, e, it)
            continue
        fresh.append(it)
    todo = new_items(s, fresh)
    kinds = classify(todo) if todo else {}
    todo = new_items(s, todo)  # classify takes minutes; another sync may have saved some of these meanwhile
    counts = {k: 0 for k in ("meeting", "conversation", "document", "task", "note")}
    for it in todo:
        kind = kinds.get(it.key, "note")
        kind = kind if kind in counts else "note"
        body = ("From the canvas.\n" + it.body) if it.link else it.body
        e = JournalEntry(day=it.day, kind=kind, text=it.text, created_at=datetime.now(), source=SOURCE,
                         external_id=it.key, status="done" if kind == "task" else "")
        s.add(e)
        s.flush()
        s.add(JournalAttachment(entry_id=e.id, kind="notes", title=f"{NOTES_TITLE}, {it.origin}", body=body,
                                created_at=datetime.now()))
        if it.link:
            s.add(JournalAttachment(entry_id=e.id, kind="link", title="Slack thread", body=it.link,
                                    created_at=datetime.now()))
        counts[kind] += 1
    if any(i.origin == TRACKER for i in items):  # old promo canvases don't say anything about the daily log
        from ..storage.sync_log import record
        record(s, SOURCE, len(todo))
    s.commit()
    return dict(added=len(todo), skipped=len(items) - len(todo), **counts)


def impact_of(body: str) -> str:
    m = IMPACT_LINE.search(body)
    return m.group(1).strip() if m else ""


def canvas_file(dd: DataDir):
    return dd.root / "slack.canvas"


def save_canvas_id(dd: DataDir, value: str) -> str:
    m = re.search(r"\b(F[A-Z0-9]{8,})\b", value.strip())
    if not m:
        raise ValueError("That doesn't look like a canvas link or ID (it starts with F, like F0EXAMPLE01).")
    write_private(canvas_file(dd), m.group(1) + "\n")
    return m.group(1)


def load_canvas_id(dd: DataDir) -> str | None:
    f = canvas_file(dd)
    return f.read_text().strip() if f.exists() else None
