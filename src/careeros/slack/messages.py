"""Your own Slack messages, from public and private channels, saved as notebook records.

DMs and group DMs are never searched. One thread's messages on one day become one record, dated from the message
timestamp in local time. Very short replies, emoji-only messages, and bots are dropped before Claude sees anything.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import JournalAttachment, JournalEntry, SyncRun
from . import search
from .kudos import _norm
from .parse import SlackItem, link_key

SOURCE = "slack"
CURSOR = "slack-messages"  # not the canvas row: that already has history, and the first search still looks back
FIRST_LOOKBACK = timedelta(days=90)
MIN_LEN = 8  # shorter than "done, merged", so "ok", "thanks", and "lgtm" stay out
THREAD_TOOL = "mcp__plugin_slack_slack__slack_read_thread"
THREAD_CAP = 20  # one tool call each; the rest of a busy sync keeps the reply without the thread's first message
KINDS = ("meeting", "conversation", "document", "task", "note")
_EMOJI = re.compile("[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "\u200d\ufe0f" "]+")
_CODE = re.compile(r":[a-z0-9_+'-]+:", re.I)


def since(s: Session) -> date:
    """Two days before the last message search, or FIRST_LOOKBACK ago the first time."""
    last = s.scalars(select(SyncRun).where(SyncRun.source == CURSOR).order_by(SyncRun.at.desc()).limit(1)).first()
    return (last.at - timedelta(days=2)).date() if last else date.today() - FIRST_LOOKBACK


def local_day(ts: str, shown: date, zone=None) -> date:
    """The calendar day of a Slack timestamp in `zone` (the machine's zone when omitted)."""
    zone = zone or datetime.now().astimezone().tzinfo
    try:
        return datetime.fromtimestamp(float(ts), zone).date()
    except (TypeError, ValueError, OSError):
        return shown


def plain(text: str) -> str:
    return " ".join(_CODE.sub("", _EMOJI.sub("", _norm(text))).split())


def noisy(hit: search.Hit) -> bool:
    """Bots, DMs, emoji-only messages, and very short replies. Dropped before Claude sees them."""
    if hit.bot or not hit.channel.startswith("#") or hit.channel_id.startswith("D"):
        return True
    return len(plain(hit.text)) < MIN_LEN


def p_digits(ts: str) -> str:
    """Slack's permalink id for a timestamp: the dot removed, the fraction padded to 6 digits."""
    whole, dot, frac = (ts or "").partition(".")
    if not whole.isdigit():
        return ""
    return whole + ((frac + "000000")[:6] if dot else "000000")


def _thread_ts(hit: search.Hit) -> str:
    m = re.search(r"[?&]thread_ts=([\d.]+)", hit.link)
    return m.group(1) if m else hit.ts


@dataclass
class Group:
    channel: str
    channel_id: str
    thread_ts: str
    day: date
    messages: list[search.Hit]
    context: str = ""
    canvas: list[SlackItem] = field(default_factory=list)

    @property
    def ext_id(self) -> str:
        digits = p_digits(self.thread_ts) or "0"
        return f"slack:{self.channel_id or 'channel'}/p{digits}:{self.day.isoformat()}"

    @property
    def links(self) -> list[str]:
        return [m.link for m in self.messages]

    @property
    def needs_parent(self) -> bool:
        """A reply in someone else's thread: the first message isn't one of yours."""
        parent = p_digits(self.thread_ts)
        return bool(parent and self.channel_id and not self.channel_id.startswith("D")
                    and all(p_digits(m.ts) != parent for m in self.messages))

    def full_text(self) -> str:
        lines = []
        if self.context:
            lines.append("In reply to: " + " ".join(self.context.split())[:400])
        lines.extend(plain(m.text) for m in self.messages)
        return "\n".join(lines)

    def item(self) -> SlackItem:
        text = self.full_text()
        extra = "\n".join(c.body for c in self.canvas if c.body)
        body = f"{text}\n{extra}".strip() if extra else text
        return SlackItem(self.ext_id, self.day.isoformat(), text[:500], body, "", self.links[0], "messages")


def group(hits: list[search.Hit], zone=None) -> list[Group]:
    """One group per thread per local day. Messages in the group stay in time order."""
    buckets: dict[tuple, list[search.Hit]] = {}
    for hit in hits:
        day = local_day(hit.ts, hit.day, zone)
        buckets.setdefault((hit.channel_id or hit.channel, _thread_ts(hit), day), []).append(hit)
    out = []
    for (cid, ts, day), msgs in buckets.items():
        msgs.sort(key=lambda m: m.ts)
        out.append(Group(msgs[0].channel, cid, ts, day, msgs))
    return out


def parent_text(raw: str) -> str:
    """The first message of a slack_read_thread answer, or "" when the shape isn't one we know."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        msgs = data.get("messages")
        if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
            return str(msgs[0].get("text") or "")
        if isinstance(data.get("text"), str):
            return data["text"]
    if "\nText: \n" in raw:
        return raw.split("\nText: \n", 1)[1].split("\n---", 1)[0].strip()
    return ""


def add_context(groups: list[Group]) -> None:
    """For threads you replied in, read the first message. Capped. A failed read leaves the reply as it is."""
    from ..claude_cli import ClaudeError, call_tools, connector_error
    need = [g for g in groups if g.needs_parent][:THREAD_CAP]
    if not need:
        return
    lines = [f"{i + 1}. channel_id={g.channel_id!r}, message_ts={g.thread_ts!r}" for i, g in enumerate(need)]
    prompt = ("Call the slack_read_thread tool once for each line below, each with limit=1, "
              "response_format=concise, and the channel_id and message_ts on that line, and nothing else. "
              "These are channel ids, never direct messages. When they have all returned, reply with only DONE.\n"
              + "\n".join(lines))
    try:
        answers = call_tools(prompt, [THREAD_TOOL], timeout=600, max_turns=len(need) + 6)
    except ClaudeError:
        return
    by = {(g.channel_id, g.thread_ts): g for g in need}
    for _tool, args, raw in answers:
        cid = str(args.get("channel_id") or "")
        if cid.startswith("D") or connector_error(raw, "Slack"):
            continue
        g = by.get((cid, str(args.get("message_ts") or "")))
        if g is not None:
            g.context = parent_text(raw)[:500]


def fetch(uid: str, since_day: date, today: date | None = None, progress=None) -> tuple[list[Group], int]:
    """Your messages since `since_day`, grouped. (groups, windows not fully read)."""
    today = today or date.today()

    def accept(hit: search.Hit) -> bool:
        return (not noisy(hit) and (not hit.who_id or hit.who_id == uid)
                and local_day(hit.ts, hit.day) >= since_day)

    hits, short = search.fetch([], f"from:<@{uid}>", since_day, today, search.CHUNK, accept, progress)
    groups = group(hits)
    add_context(groups)
    return groups, short


def _live(s: Session, g: Group):
    """The record this group already is, "removed" when you deleted it, or None."""
    from .importer import link_removed, linked_entry
    for link in g.links:
        if e := linked_entry(s, link, g.day.isoformat()):
            return e
    from ..storage.removal import removed_ids
    if g.ext_id in removed_ids(s, SOURCE) or any(link_removed(s, link) for link in g.links):
        return "removed"
    return None


def attach(s: Session, groups: list[Group], items: list[SlackItem]) -> list[SlackItem]:
    """Canvas items that link to a message we're about to add ride on that group. The rest are returned."""
    creating = {id(g) for g in groups if _live(s, g) is None}
    rest = []
    for it in items:
        g = _group_for(groups, it)
        if g is not None and id(g) in creating:
            g.canvas.append(it)
        else:
            rest.append(it)
    return rest


def _group_for(groups: list[Group], it: SlackItem) -> Group | None:
    """The group this canvas link belongs to: the message's own link, or the same thread on the canvas's day."""
    msg = link_key(it.link)
    if not msg:
        return None
    exact = [g for g in groups if msg in {link_key(link) for link in g.links}]
    if exact:
        same = [g for g in exact if g.day.isoformat() == it.day]
        return (same or exact)[0]
    same = [g for g in groups if g.ext_id.rsplit(":", 1)[0] == msg and g.day.isoformat() == it.day]
    return same[0] if len(same) == 1 else None


def _insert(s: Session, groups: list[Group], kinds: dict[str, str]) -> int:
    from .importer import add_canvas_note
    for g in groups:
        kind = kinds.get(g.ext_id, "note")
        kind = kind if kind in KINDS else "note"
        text = g.full_text()
        e = JournalEntry(day=g.day.isoformat(), kind=kind, text=text[:500], created_at=datetime.now(),
                         source=SOURCE, external_id=g.ext_id, status="done" if kind == "task" else "")
        s.add(e)
        s.flush()
        for link in g.links:
            s.add(JournalAttachment(entry_id=e.id, kind="link", title=f"Slack message in {g.channel}", body=link,
                                    created_at=datetime.now()))
        if len(text) > 500:
            s.add(JournalAttachment(entry_id=e.id, kind="notes", title="From Slack", body=text[:4000],
                                    created_at=datetime.now()))
        for it in g.canvas:
            add_canvas_note(s, e, it)
    return len(groups)


def save(s: Session, groups: list[Group], items: list[SlackItem], classify) -> tuple[int, dict]:
    """Save new message records, fold canvas items into them or import the ones left, and log the pull.

    When a message and a canvas item disagree on the day, the message's day is the one kept.
    """
    from ..storage.sync_log import record
    from .importer import add_canvas_note, import_items, link_removed, linked_entry, new_items
    for g in groups:
        hit = _live(s, g)
        if hit not in (None, "removed") and hit.day != g.day.isoformat() and not hit.reviewed:
            hit.day = g.day.isoformat()
    new_groups = [g for g in groups if _live(s, g) is None]
    create = []
    for it in items:
        if it.link and link_removed(s, it.link):
            continue
        if it.link and (e := linked_entry(s, it.link, it.day)):
            add_canvas_note(s, e, it)
            continue
        create.append(it)
    create = new_items(s, create)
    todo = [g.item() for g in new_groups] + create
    kinds = classify(todo) if todo else {}
    before = s.scalar(select(SyncRun.id).order_by(SyncRun.id.desc()).limit(1)) or 0
    n = _insert(s, new_groups, kinds)
    r = import_items(s, create, lambda t: {i.key: kinds.get(i.key, "note") for i in t})
    for g in new_groups:
        kind = kinds.get(g.ext_id, "note")
        r[kind if kind in KINDS else "note"] += 1
    latest = s.scalars(select(SyncRun).where(SyncRun.source == SOURCE, SyncRun.id > before)).first()
    if latest:  # the canvas import logged its own count; the chip should include the messages too
        latest.added += n
    else:
        record(s, SOURCE, n + r["added"])
    s.add(SyncRun(source=CURSOR, at=datetime.now(), added=n))
    s.commit()
    return n, r
