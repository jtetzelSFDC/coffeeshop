"""How you stand on each KSO, in plain math. No Claude here: the bars come from your V2MOM's own progress."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..storage.models import JournalEntry, KsoFramework, KsoYear
from . import framework, map as kmap


def year(s: Session, fy: str, create: bool = False) -> KsoYear | None:
    row = s.scalar(select(KsoYear).where(KsoYear.fiscal_year == fy))
    if row is None and create:
        row = KsoYear(fiscal_year=fy, ratings={})
        s.add(row)
    return row


def set_rating(s: Session, fw: KsoFramework, kso: str, rating: str) -> None:
    """Your 1-5 for one KSO ("" clears it)."""
    if kso not in {k["key"] for k in fw.data["ksos"]} or rating not in ("", *framework.RATINGS):
        raise ValueError("That isn't a KSO and a rating from 1 to 5.")
    row = year(s, fw.fiscal_year, create=True)
    ratings = {k: v for k, v in (row.ratings or {}).items() if k != kso}
    if rating:
        ratings[kso] = int(rating)
    row.ratings = ratings
    s.commit()


def _avg(xs: list[float]) -> int | None:
    return round(sum(xs) / len(xs)) if xs else None


def build(s: Session, fy: str | None = None, today: date | None = None) -> dict | None:
    """Everything the KSO page shows for one fiscal year (default: the current V2MOM's), or None without KSOs.
    A component's bar is the average progress of the V2MOM methods matched to it; a KSO's bar averages its
    components, a component with no V2MOM goal counting as 0, because the rating counts it against you too."""
    from ..v2mom import report
    today = today or date.today()
    fw = framework.get(s, fy) if fy else (framework.for_current(s) or framework.get(s))
    if fw is None:
        return None
    _, fy_lo, fy_hi = report.fiscal_year(fw.fiscal_year, today)
    rep = report.build(s, today)
    current = bool(rep) and rep["fy"] == fw.fiscal_year  # work counts exist only for the current V2MOM's year
    counts = {r["m"].id: r["year"] for r in rep["methods"]} if current else {}
    kudos = s.scalar(select(func.count()).select_from(JournalEntry).where(
        JournalEntry.kind == "recognition", JournalEntry.day >= fy_lo.isoformat(),
        JournalEntry.day <= min(fy_hi, today).isoformat())) or 0
    picks = kmap.by_component(s, fw)
    ksos = []
    for k in fw.data["ksos"]:
        comps = []
        for c in k["components"]:
            methods = [dict(m=m, by_ai=p.by_ai) for m, p in picks[c["key"]]]
            pcts = [x["m"].progress for x in methods if x["m"].progress is not None]
            comps.append(dict(c, methods=methods, bar=_avg(pcts),
                              work=sum(counts.get(x["m"].id, 0) for x in methods) if current else None,
                              kudos=kudos if "feedback" in c["name"].lower() else None, gap=not methods))
        bars = [0 if x["gap"] else x["bar"] for x in comps if x["gap"] or x["bar"] is not None]
        ksos.append(dict(k, components=comps, bar=_avg(bars), gaps=sum(1 for x in comps if x["gap"])))
    counted = {x["m"].id for k in ksos for c in k["components"] for x in c["methods"]}
    loose = [r["m"] for r in rep["methods"] if r["m"].id not in counted] if current else []
    from .estimate import latest
    est = latest(s, fw.fiscal_year)
    guessed = {k["key"]: k for k in est.data["ksos"]} if est else {}
    for k in ksos:
        k["estimate"] = guessed.get(k["key"])
    row = year(s, fw.fiscal_year)
    ratings = dict(row.ratings) if row and row.ratings else {}
    return dict(fw=fw, ksos=ksos, loose=loose, ratings=ratings,
                estimated_at=est.made_at if est else None, current=current,
                choices=[(c["key"], c["name"]) for c in framework.components(fw)],
                years=list(s.scalars(select(KsoFramework.fiscal_year).order_by(KsoFramework.fiscal_year.desc()))),
                upcoming=[d for d in fw.data.get("dates", []) if d["date"] >= today.isoformat()])
