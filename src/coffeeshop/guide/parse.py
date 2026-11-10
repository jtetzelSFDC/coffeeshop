"""Reads the leveling guide (the workbook in the repo, one tab per role, or a one-role CSV export; rows are
attributes, columns are grades) into flat items."""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "leveling" / "leveling-guides.xlsx"
SKILL_GROUPS = {"transferable skills": "Transferable", "group-specific skills": "Group-specific",
                "group specific skills": "Group-specific", "path-specific skills": "Path-specific",
                "path specific skills": "Path-specific"}
GRADE = re.compile(r"\s*Grade\s+(\d+)\b")  # "Grade 7", "Grade 7 ", "Grade 7 (3045, 4102)"
TARGET = re.compile(r"\s*(\d+)")  # "2", "2.0", or "2\n\nShadows senior engineers..."


class GuideFormatError(ValueError):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u200b", "")).strip()


def _cell(v) -> str:
    return "" if v is None else str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _labels(r: list[str]) -> set[str]:
    return {r[0].strip().lower(), r[1].strip().lower()}  # half the tabs put Grade and Job Titles in A, half in B


def _items(rows: list[list[str]], grades: dict[int, int]) -> list[dict]:
    items: list[dict] = []
    group = ""
    for r in rows:
        label = r[1].strip().lower()
        if r[0].strip().lower() in SKILL_GROUPS:
            group = SKILL_GROUPS[r[0].strip().lower()]
        if label == "role summary":
            items += [dict(key=f"summary:{g}", kind="summary", grade=g, category="", name=_clean(r[i]),
                           description="", targets={}) for i, g in grades.items() if r[i].strip()]
        elif label == "key experiences":
            for i, g in grades.items():
                for line in re.split(r"\n\s*-\s*|^\s*-\s*", r[i]):
                    if (text := _clean(line)):
                        items.append(dict(key=f"exp:{g}:{slug(text)}", kind="experience", grade=g, category="",
                                          name=text, description="", targets={}))
        elif group and r[1].strip():
            targets = {str(g): int(m.group(1)) for i, g in grades.items() if (m := TARGET.match(r[i]))}
            if targets:
                name = _clean(r[1]).lstrip("*").strip()
                items.append(dict(key=f"skill:{slug(name)}", kind="skill", grade=None, category=group,
                                  name=name, description=_clean(r[2]), targets=targets))
    if not any(i["kind"] == "experience" for i in items):
        raise GuideFormatError("Couldn't find any key experiences in that file.")
    return items


def _guides(rows: list[list[str]], name: str) -> list[dict]:
    """One guide per track: {name, levels: [{grade, title}], items}. A tab that repeats a grade (Quality Engineering
    has a manager and an architect column at Grades 7 and 8) is two tracks sharing the other columns; the second is
    named after its job title at the first repeated grade."""
    width = max(map(len, rows), default=0) + 3
    rows = [r + [""] * (width - len(r)) for r in rows]
    grade_row = next((r for r in rows if "grade" in _labels(r)), None)
    if grade_row is None:
        raise GuideFormatError("Couldn't find the 'Grade' row; is this a leveling guide export?")
    titles = next((r for r in rows if "associated job titles" in _labels(r)), [""] * width)
    cols = [(i, int(m.group(1))) for i, c in enumerate(grade_row) if (m := GRADE.match(c))]
    nth, seen = {}, Counter()
    for i, g in cols:
        nth[i], seen[g] = seen[g], seen[g] + 1
    out = []
    for track in range(max(seen.values(), default=1)):
        pick = {g: i for i, g in cols if nth[i] == 0} | {g: i for i, g in cols if nth[i] == track}
        grades = {i: g for g, i in sorted(pick.items(), key=lambda kv: kv[1])}
        first = next((i for i, g in cols if nth[i] == track), None) if track else None
        out.append(dict(name=f"{name} ({_clean(titles[first])})" if track else name,
                        levels=[dict(grade=g, title=_clean(titles[i])) for i, g in grades.items()],
                        items=_items(rows, grades)))
    return out


def parse_guide(path: Path | str) -> list[dict]:
    """A one-role CSV export. Items: {key, kind: summary|experience|skill, grade, category, name, description,
    targets}."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return _guides(list(csv.reader(fh)), "")[0]["items"]


def read_workbook(path: Path | str | None = None) -> list[dict]:
    """Every role tab of the workbook (default: the one in the repo; not the Welcome index), as guides named by
    each tab's 'Career Path:' line, since tab names are cut at 31 characters. A tab that doesn't read raises
    GuideFormatError naming it."""
    import zipfile
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException
    try:
        wb = openpyxl.load_workbook(path or WORKBOOK, read_only=True, data_only=True)
    except (OSError, zipfile.BadZipFile, InvalidFileException) as exc:
        raise GuideFormatError(f"Couldn't open it as an .xlsx workbook ({exc}).") from None
    try:
        out = []
        for ws in wb.worksheets:
            if ws.title.strip().lower() == "welcome":
                continue
            rows = [[_cell(v) for v in r] for r in ws.iter_rows(values_only=True)]
            path_line = next((c for r in rows[:10] for c in r[:3] if c.strip().lower().startswith("career path:")), "")
            try:
                if not path_line:
                    raise GuideFormatError("Couldn't find its 'Career Path:' line.")
                out += _guides(rows, _clean(path_line.split(":", 1)[1]))
            except GuideFormatError as exc:
                raise GuideFormatError(f"Tab '{ws.title.strip()}': {exc}") from None
        return out
    finally:
        wb.close()
