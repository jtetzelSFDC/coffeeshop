"""Saving a pulled V2MOM, and when the next monthly pull is due."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..storage.models import SyncRun, V2momMethod, V2momVersion

SOURCE = "v2mom"
PULL_EVERY = timedelta(days=30)


def _norm(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def current(s: Session) -> V2momVersion | None:
    return s.scalar(select(V2momVersion).order_by(V2momVersion.pulled_at.desc(), V2momVersion.id.desc()).limit(1))


def methods(s: Session, version: V2momVersion | None = None) -> list[V2momMethod]:
    """The active methods of the current V2MOM (or `version`), in the Doc's order."""
    v = version or current(s)
    if v is None:
        return []
    return list(s.scalars(select(V2momMethod).where(V2momMethod.version_id == v.id, V2momMethod.active)
                          .order_by(V2momMethod.position)))


def _version_for(s: Session, fy: str, doc_id: str) -> V2momVersion:
    latest = current(s)
    same = s.scalar(select(V2momVersion).where(V2momVersion.fiscal_year == fy).limit(1)) if fy else None
    v = same or (latest if latest and (not fy or not latest.fiscal_year) else None)
    if v is None:  # a new fiscal year starts a new V2MOM; last year's methods and links stay as they were
        v = V2momVersion(doc_id=doc_id, pulled_at=datetime.now())
        s.add(v)
        s.flush()
    return v


def save(s: Session, parsed: dict, doc_id: str) -> dict[str, int]:
    """Updates the V2MOM in place. A method keeps its row when its name matches (any order), or when it sits in
    the same place under a new name; a method the Doc no longer has is kept but marked inactive."""
    v = _version_for(s, parsed["fiscal_year"], doc_id)
    v.doc_id, v.pulled_at = doc_id, datetime.now()
    v.fiscal_year = parsed["fiscal_year"] or v.fiscal_year
    v.published, v.vision, v.values, v.obstacles = (parsed["published"], parsed["vision"], parsed["values"],
                                                    parsed["obstacles"])
    have = list(s.scalars(select(V2momMethod).where(V2momMethod.version_id == v.id).order_by(V2momMethod.id)))
    by_name = {}
    for m in have:
        by_name.setdefault(_norm(m.name), m)
    rows: list[V2momMethod | None] = []
    claimed: set[int] = set()
    for new in parsed["methods"]:
        m = by_name.get(_norm(new["name"]))
        m = m if m and m.id not in claimed else None
        rows.append(m)
        if m:
            claimed.add(m.id)
    for pos, new in enumerate(parsed["methods"], 1):
        if rows[pos - 1] is None:
            rows[pos - 1] = next((m for m in have if m.id not in claimed and m.active and m.position == pos), None)
            if rows[pos - 1]:
                claimed.add(rows[pos - 1].id)
    added = 0
    for pos, (new, m) in enumerate(zip(parsed["methods"], rows), 1):
        if m is None:
            m = V2momMethod(version_id=v.id)
            s.add(m)
            added += 1
        m.position, m.name, m.description, m.status, m.progress, m.measures, m.active = (
            pos, new["name"], new["description"], new["status"], new["progress"], new["measures"], True)
    retired = 0
    for m in have:
        if m.id not in claimed and m.active:
            m.active = False
            retired += 1
    from ..storage.sync_log import record
    record(s, SOURCE, added)
    s.commit()
    return dict(methods=len(parsed["methods"]), added=added, retired=retired, obstacles=len(parsed["obstacles"]))


def due(s: Session, now: datetime | None = None) -> bool:
    """True when the V2MOM was never pulled, or not in the last 30 days."""
    last = s.scalar(select(func.max(SyncRun.at)).where(SyncRun.source == SOURCE))
    return last is None or (now or datetime.now()) - last > PULL_EVERY
