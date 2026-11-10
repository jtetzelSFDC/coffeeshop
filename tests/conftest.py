import pytest

from coffeeshop.storage.db import init_db, make_engine, make_session_factory

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from coffeeshop.cli import app as cli
from coffeeshop.config import DataDir
from coffeeshop.guide.service import save_profile
from coffeeshop.web.app import create_app
from helpers import BASE, write_guide


@pytest.fixture(autouse=True)
def new_york_time(monkeypatch):
    """Tests run on New York time wherever they run, so local-time results don't depend on the machine."""
    import time
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch):
    """Tests never start the real `claude` command; a test that needs Claude passes a fake reader or patches ask."""
    from coffeeshop import claude_cli

    def refuse():
        raise claude_cli.ClaudeError("tests never call the real Claude")
    monkeypatch.setattr(claude_cli, "_claude", refuse)

    def no_gh(*args):
        from coffeeshop.github.connector import GitHubError
        raise GitHubError("tests never call the real gh")
    monkeypatch.setattr("coffeeshop.github.connector._gh", no_gh)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def nb(tmp_path):
    """A personal notebook with the made-up leveling guide loaded: (DataDir, web client, CSRF token, guide CSV)."""
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    init_db(make_engine(dd.db))
    guide = write_guide(tmp_path / "guide.csv")
    r = CliRunner().invoke(cli, ["guide", "import", str(guide), "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    save_profile(dd.root, role="DevOps", grade=5, title="DevOps Engineer")
    app = create_app(dd)
    return dd, TestClient(app, base_url=BASE), app.state.csrf_token, guide
