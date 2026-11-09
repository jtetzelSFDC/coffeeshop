"""The pre-commit check refuses personal-data paths and allows the leveling workbook."""
import runpy
from pathlib import Path

refuse = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / ".githooks" / "check_personal_data.py"))["refuse"]


def test_personal_paths_are_refused_and_the_leveling_workbook_is_allowed():
    refused = [
        "notebook.db",
        "notebook.db-wal",
        "notebook.db-shm",
        "notebook.db-journal",
        "notes.sqlite",
        "notes.sqlite3",
        "Scan.PDF",
        "wins.csv",
        "takeout.zip",
        "backups/day.txt",
        "logs/run.txt",
        "src/exports/out.txt",
        ".secret",
        "nested/.personal",
        "app/.demo",
        "profile.json",
        "dir/slack_user.json",
        "slack.canvas",
        "calendar.url",
        "v2mom.json",
        "kso.json",
        "budget.xlsx",
        "data/leveling.xlsx",
        "data/leveling/notes.csv",
        "data/leveling/notebook.db",
        "Data\\secret.xlsx",
    ]
    allowed = [
        "src/careeros/cli.py",
        "docs/TECHNICAL.md",
        "data/leveling/leveling-guides.xlsx",
        "data/Leveling/older/Guide.XLSX",
        "README.md",
    ]
    for path in refused:
        assert refuse(path), path
    for path in allowed:
        assert refuse(path) is None, path
