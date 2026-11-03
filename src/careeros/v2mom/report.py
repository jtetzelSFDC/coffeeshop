"""Per V2MOM method: how much work backs it this quarter and this fiscal year, and whether it has gone quiet. For the
V2MOM page, the Home strip, and the digest. Built from the notebook when the page loads (no Claude, nothing stored)."""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from . import links, store

QUIET_DAYS = 30
LATE_STATUS = ("at risk", "off track", "behind")


def fy_name(text: str) -> str:
    """FY27 from "FY27", "fy 27", "FY2027" or a file name holding one; "" when there's none. The one way fiscal
    years are written everywhere, so the V2MOM, KSOs and PDFs always agree."""
    m = re.search(r"FY\s*(?:20)?(\d{2})\b", text or "", re.I)
    return f"FY{m.group(1)}" if m else ""


def fiscal_year(fy: str, today: date) -> tuple[str, date, date]:
    """The company's fiscal year runs Feb 1 to Jan 31 and is named for the year it ends in: FY27 is Feb 1, 2026 to
    Jan 31, 2027. Taken from the V2MOM's "FY27" when it has one, else from `today`."""
    name = fy_name(fy)
    end = 2000 + int(name[2:]) if name else today.year + (today.month >= 2)
    return f"FY{end % 100:02d}", date(end - 1, 2, 1), date(end, 1, 31)


def quarter(today: date) -> tuple[date, date]:
    """The calendar quarter `today` is in."""
    lo = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    return lo, date(lo.year + lo.month // 10, (lo.month + 2) % 12 + 1, 1) - timedelta(days=1)


def status_class(status: str) -> str:
    """The chip style for a status the Doc gives a method or measure: green when completed, orange when behind."""
    st = status.strip().lower()
    return "done" if st == "completed" else "late" if st in LATE_STATUS else ""


def build(s: Session, today: date | None = None) -> dict | None:
    """None when no V2MOM is loaded. Each method's state is "active" (work in the last 30 days), "quiet" (work, but
    none in 30 days) or "none" (nothing linked yet). Work dated after `today` and open tasks are left out."""
    v = store.current(s)
    if v is None:
        return None
    today = today or date.today()
    fy, fy_lo, fy_hi = fiscal_year(v.fiscal_year, today)
    q_lo, q_hi = quarter(today)
    end, quiet_since = today.isoformat(), (today - timedelta(days=QUIET_DAYS)).isoformat()
    methods = store.methods(s, v)
    by_name = {store._norm(m.name): m.id for m in methods}
    obstacles: dict[int, list[dict]] = {}
    loose = []
    for o in v.obstacles:
        mids = {by_name.get(store._norm(n)) for n in o.get("related_methods") or [o.get("related_method") or ""]}
        mids.discard(None)
        for mid in mids:
            obstacles.setdefault(mid, []).append(o)
        if not mids:
            loose.append(o)
    ev = links.evidence(s)
    rows = []
    for m in methods:
        e = ev.get(m.id, dict(entries=[], wins=[]))
        entries = [x.day for x in e["entries"] if x.day <= end and x.status != "open"]
        wins = [x.day for x in e["wins"] if x.day <= end]
        days = entries + wins
        last = max(days, default="")
        rows.append(dict(
            m=m, entries=len(entries), wins=len(wins),
            quarter=sum(1 for d in days if q_lo.isoformat() <= d), last=last,
            year=sum(1 for d in days if fy_lo.isoformat() <= d <= fy_hi.isoformat()),
            state="none" if not days else "active" if last >= quiet_since else "quiet",
            obstacles=obstacles.get(m.id, [])))
    top = max([r["quarter"] for r in rows] + [1])
    for r in rows:
        r["pct"] = round(100 * r["quarter"] / top)
    return dict(version=v, fy=fy, fy_lo=fy_lo, fy_hi=fy_hi, q_lo=q_lo, q_hi=q_hi, methods=rows, loose=loose,
                active=sum(1 for r in rows if r["quarter"]))
