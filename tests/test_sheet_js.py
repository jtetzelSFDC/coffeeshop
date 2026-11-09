def test_row_keeps_typed_text_when_another_field_saves():
    """Runs sheet.js against a fake row: typed text and open details survive a different button."""
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    assert node, "node is required to run sheet.js"
    r = subprocess.run([node, str(Path(__file__).with_name("sheet_keep.js"))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
