"""The pre-commit check refuses personal-data paths and allows the leveling workbook."""
import runpy
from pathlib import Path

_check = runpy.run_path(str(Path(__file__).resolve().parents[1] / ".githooks" / "check_personal_data.py"))
refuse = _check["refuse"]
unstage_command = _check["unstage_command"]


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
        "data/leveling-other/salary.xlsx",
        "data/leveling/notes.csv",
        "data/leveling/notebook.db",
        "Data\\secret.xlsx",
        "FY27 V2MOM.docx",
        "docs/notes.DOCX",
        "src/data/v2mom.docx",
    ]
    allowed = [
        "src/coffeeshop/cli.py",
        "docs/TECHNICAL.md",
        "data/leveling/leveling-guides.xlsx",
        "data/Leveling/older/Guide.XLSX",
        "data\\leveling\\guide.xlsx",
        "data/templates/promo.docx",
        "README.md",
    ]
    for path in refused:
        assert refuse(path), path
    for path in allowed:
        assert refuse(path) is None, path


def test_unstage_hint_leaves_a_tracked_file_in_place():
    # git rm --cached on a tracked file would stage a deletion. Only a repo with no commit yet gets it.
    assert unstage_command(["dir with space/notes.csv"], has_head=True) == (
        "git restore --staged -- 'dir with space/notes.csv'")
    assert unstage_command(["notes.csv"], has_head=False) == "git rm --cached -- notes.csv"
