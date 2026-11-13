"""The Values & Behaviors workbook in the repo: English value, behavior, and definition only."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..guide.parse import slug

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "competencies" / "values-behaviors.xlsx"
# Excel keeps 31 characters of a tab name, so the full title is stored cut off.
SHEET = "Updated V&B Individual Contributor"[:31]
_cached: tuple[str, list[dict]] | None = None


def _text(v) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\u200b", "")).strip()


def _at(row, i: int):
    return row[i] if row is not None and i < len(row) else None


def _columns(header) -> tuple[int, int, int]:
    """English columns. The sheet repeats Value and Behavior for Japanese and French; the English definition
    header is the only one that starts with "Behavior and Sub-Behavior"."""
    cells = [_text(c).lower() for c in header]
    try:
        value = cells.index("value")
        behavior = cells.index("behavior", value + 1)
        definition = next(i for i, c in enumerate(cells) if c.startswith("behavior and sub-behavior definition"))
    except (ValueError, StopIteration):
        raise ValueError("Couldn't find the English Value, Behavior, and definition columns.") from None
    return value, behavior, definition


def parse_behaviors(path: Path | str | None = None) -> list[dict]:
    """[{key, value, name, description}] in sheet order. Interview questions are not read."""
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException
    src = str(Path(path).resolve() if path else WORKBOOK)
    global _cached
    if _cached and _cached[0] == src:
        return _cached[1]
    # shortcut: People Leader and Executive tabs are not loaded, load them when a people-leader or executive level is saved
    try:
        wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    except (OSError, zipfile.BadZipFile, InvalidFileException) as exc:
        raise ValueError(f"Couldn't open the Values & Behaviors workbook ({exc}).") from None
    try:
        if SHEET not in wb.sheetnames:
            raise ValueError(f"Workbook has no '{SHEET}' sheet.")
        cols = None
        items: list[dict] = []
        seen: set[str] = set()
        for row in wb[SHEET].iter_rows(values_only=True):
            if cols is None:
                if any(_text(c).lower().startswith("behavior and sub-behavior definition") for c in (row or ())):
                    cols = _columns(row)
                continue
            value, behavior = _text(_at(row, cols[0])), _text(_at(row, cols[1]))
            if not value or not behavior:
                continue
            key = f"vb:{slug(value)}:{slug(behavior)}"
            if not key.strip(":") or key in seen:
                continue
            seen.add(key)
            items.append(dict(key=key, value=value, name=behavior, description=_text(_at(row, cols[2]))))
        if not items:
            raise ValueError("No English behaviors on the Individual Contributor tab.")
    finally:
        wb.close()
    _cached = (src, items)
    return items
