"""Tables: notebook entries and what hangs off them, wins, the leveling guide, and sync bookkeeping."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JournalEntry(Base):
    """The user's own day-to-day notes (meetings, conversations, documents). Not evidence, no approvals."""
    __tablename__ = "journal_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    kind: Mapped[str] = mapped_column(String)  # meeting | conversation | document | note
    text: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String, default="")  # "" = typed by the user | calendar
    external_id: Mapped[str | None] = mapped_column(String, index=True, default=None)
    status: Mapped[str] = mapped_column(String, default="")  # tasks only: open | done
    kind_was: Mapped[str] = mapped_column(String, default="")  # the kind before Claude changed it, else ""
    ai_read: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has read it against the guide
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user checked it in the Intake Review Queue
    work_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_item.id"), nullable=True, default=None)
    grouped: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has decided which work item it belongs to
    work_fixed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user grouped or split it; Claude leaves it
    activity: Mapped[str] = mapped_column(String, default="")  # one key from guide/activities.py, or "" for none
    activity_read: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has tagged it
    activity_fixed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user set it; Claude leaves it
    v2mom_read: Mapped[bool] = mapped_column(Boolean, default=False)  # Claude has read it against the V2MOM
    v2mom_fixed: Mapped[bool] = mapped_column(Boolean, default=False)  # the user set its methods; Claude leaves them


class WorkItem(Base):
    """One piece of work (a release, a refresh, a runbook) that several records can describe. Counted once."""
    __tablename__ = "work_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD of its latest record
    started: Mapped[str] = mapped_column(String, default="")  # YYYY-MM-DD of its first record
    by_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RemovedEntry(Base):
    """A journal entry the user removed. Syncs skip its external id so it doesn't come back; Restore re-adds it."""
    __tablename__ = "removed_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="")
    external_id: Mapped[str | None] = mapped_column(String, index=True, default=None)
    status: Mapped[str] = mapped_column(String, default="")
    removed_at: Mapped[datetime] = mapped_column(DateTime)


class SyncRun(Base):
    """One pull from a source (Slack tracker, Google Calendar, Google Tasks), even when nothing new came in."""
    __tablename__ = "sync_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    added: Mapped[int] = mapped_column(Integer, default=0)


class SkipRule(Base):
    """Calendar events whose title contains this text (any case) are never brought into the notebook."""
    __tablename__ = "skip_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, default="calendar")
    pattern: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class JournalAttachment(Base):
    """Something pasted under a journal entry: a link, meeting notes, a transcript, a canvas, a prompt."""
    __tablename__ = "journal_attachment"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entry.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # link | notes | transcript | canvas | prompt | other
    title: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Win(Base):
    """An accomplishment the user chose to keep for reviews, promotion cases, and resumes. Written by the user."""
    __tablename__ = "win"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    title: Mapped[str] = mapped_column(String)  # what I did
    impact: Mapped[str] = mapped_column(Text, default="")  # why it mattered, in the user's words
    size: Mapped[str] = mapped_column(String, default="small")  # small | medium | large
    theme: Mapped[str] = mapped_column(String, default="")
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)  # drafted by Claude, not yet edited or confirmed


class PromoVersion(Base):
    """One drafted promotion case. It keeps the numbered evidence it was written from, so its sources still make
    sense after the notebook changes."""
    __tablename__ = "promo_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    window_start: Mapped[str] = mapped_column(String)
    window_end: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    voice: Mapped[str] = mapped_column(String, default="third")
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{n, kind, text, day, refs}]
    slices: Mapped[dict] = mapped_column(JSON, default=dict)  # section key -> evidence numbers it was written from
    note: Mapped[str] = mapped_column(String, default="")  # how this draft came about, e.g. "Edited Impact"
    google_doc_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)  # the copy with sources
    google_doc_clean_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)  # for sharing


class PromoSection(Base):
    """One heading of a draft. `sentences` is [{text, sources: [n], valid, reason}]."""
    __tablename__ = "promo_section"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("promo_version.id"), index=True)
    key: Mapped[str] = mapped_column(String)
    heading: Mapped[str] = mapped_column(String)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sentences: Mapped[list] = mapped_column(JSON, default=list)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String, default="")


class GuideItem(Base):
    """One line of the leveling guide: a grade's role summary, a key experience, or a rated skill."""
    __tablename__ = "guide_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)  # stable across re-imports, e.g. exp:6:<slug>
    kind: Mapped[str] = mapped_column(String)  # summary | experience | skill
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None for skills
    category: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    targets: Mapped[dict] = mapped_column(JSON, default=dict)  # skills: {"6": 3, "7": 4}
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(default=True)  # False once a re-import no longer has it


class V2momVersion(Base):
    """The user's V2MOM for one fiscal year, as last read from its PDF or Google Doc."""
    __tablename__ = "v2mom_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String)  # the Google Doc's id, or the PDF's path
    fiscal_year: Mapped[str] = mapped_column(String, default="")  # e.g. FY27, or "" when the Doc doesn't say
    published: Mapped[str] = mapped_column(String, default="")  # as the Doc writes it, e.g. "Mar 25, 2026"
    vision: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[list] = mapped_column(JSON, default=list)  # [{name, text}]
    obstacles: Mapped[list] = mapped_column(JSON, default=list)  # [{name, text, related_method, related_methods}]
    check_ins: Mapped[list] = mapped_column(JSON, default=list)  # [{name, manager_comments}]
    pulled_at: Mapped[datetime] = mapped_column(DateTime)


class V2momMethod(Base):
    """One method of a V2MOM. Rows are kept across pulls (matched by name, then position) so links survive edits."""
    __tablename__ = "v2mom_method"
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("v2mom_version.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # 1-based order in the Doc; shown as M1, M2, …
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="")  # as the Doc says: On Track, At Risk, Completed, …
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)  # percent, when shown
    measures: Mapped[list] = mapped_column(JSON, default=list)  # [{text, status, progress, comments}]
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # False once a pull no longer has it

    @property
    def label(self) -> str:
        return f"M{self.position}"


class DailyTask(Base):
    """One of the day's three suggested tasks. Checking it off logs a done record (entry_id)."""
    __tablename__ = "daily_task"
    __table_args__ = (UniqueConstraint("day", "position"),)  # two runs at once can't save six
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    position: Mapped[int] = mapped_column(Integer)  # 1 to 3
    text: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(String, default="")  # e.g. "V2MOM M4" or "Grade 6: Leads sandbox strategy"
    minutes: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)  # the record it logged


class KsoFramework(Base):
    """One fiscal year's KSOs as read from the KSO deck and guides: weights, components, rubric, payout per rating.
    Internal material, so it stays in the notebook."""
    __tablename__ = "kso_framework"
    id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year: Mapped[str] = mapped_column(String, unique=True)  # e.g. FY27
    track: Mapped[str] = mapped_column(String, default="")  # e.g. Delivery
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # see kso.framework.validate
    sources: Mapped[dict] = mapped_column(JSON, default=dict)  # {decks, canvases, track, manager}
    pulled_at: Mapped[datetime] = mapped_column(DateTime)


class KsoMap(Base):
    """Which KSO component a V2MOM method serves ("" for none). Claude's pick until you set it."""
    __tablename__ = "kso_map"
    __table_args__ = (UniqueConstraint("fiscal_year", "method_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year: Mapped[str] = mapped_column(String, index=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("v2mom_method.id"), index=True)
    component: Mapped[str] = mapped_column(String, default="")  # e.g. "2.2"
    by_ai: Mapped[bool] = mapped_column(Boolean, default=True)


class KsoYear(Base):
    """What you enter for a fiscal year: your target incentive (dollars, never sent anywhere) and your own 1-5
    rating per KSO (a guess, or the final one once your manager has rated you)."""
    __tablename__ = "kso_year"
    id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year: Mapped[str] = mapped_column(String, unique=True)
    target_incentive: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    ratings: Mapped[dict] = mapped_column(JSON, default=dict)  # {"1": 4, "2": 5}


class KsoEstimate(Base):
    """Claude's monthly guess at your 1-5 per KSO, with a reason per part and next steps. Marked AI on the page."""
    __tablename__ = "kso_estimate"
    id: Mapped[int] = mapped_column(primary_key=True)
    fiscal_year: Mapped[str] = mapped_column(String, index=True)
    made_at: Mapped[datetime] = mapped_column(DateTime)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # {"ksos": [{key, rating, why: {part: text}, next: [...]}]}


class V2momLink(Base):
    """A win or a notebook entry that advances a V2MOM method. Goes away with the win or entry."""
    __tablename__ = "v2mom_link"
    __table_args__ = (UniqueConstraint("method_id", "win_id", "entry_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("v2mom_method.id"), index=True)
    win_id: Mapped[int | None] = mapped_column(ForeignKey("win.id", ondelete="CASCADE"), nullable=True, index=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id", ondelete="CASCADE"), nullable=True,
                                                 index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)  # picked by Claude, not yet confirmed


class GuideLink(Base):
    """The user's statement that a win or a notebook entry shows a guide item."""
    __tablename__ = "guide_link"
    __table_args__ = (UniqueConstraint("item_id", "win_id", "entry_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("guide_item.id"), index=True)
    win_id: Mapped[int | None] = mapped_column(ForeignKey("win.id"), nullable=True, index=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)  # picked by Claude, not yet confirmed
