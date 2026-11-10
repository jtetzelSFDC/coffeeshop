"""Uploading a V2MOM PDF from the page, and the active-version lines. The sync job is stubbed: tests never read a PDF."""
import stat
from urllib.parse import unquote

from fastapi.testclient import TestClient

from careeros.config import DataDir
from careeros.v2mom import connector, store
from careeros.web.app import create_app, short_day
from careeros.web.jobs import Jobs

from helpers import BASE, connect, load_v2mom, open_session

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def stub_job(monkeypatch):
    started = []

    def start(self, name, steps, fn):
        started.append(name)
        return True

    monkeypatch.setattr(Jobs, "start", start)
    return started


def stored(dd):
    return dd.root / connector.UPLOAD_DIR / connector.STORED_PDF


def post_pdf(c, token, body=PDF, name="../../FY27 V2MOM Pat Example.pdf"):
    data = {} if token is None else {"csrf": token}
    return c.post("/v2mom/upload", data=data, files={"pdf": (name, body, "application/pdf")},
                  follow_redirects=False)


def test_upload_is_stored_privately_and_the_source_points_at_it(nb, monkeypatch):
    started = stub_job(monkeypatch)
    dd, c, token, _ = nb
    r = post_pdf(c, token)
    path = stored(dd)
    assert r.status_code == 303 and unquote(r.headers["location"]).startswith("/v2mom")
    assert "Started" in unquote(r.headers["location"])
    assert path.read_bytes() == PDF and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.name == "V2MOM.pdf" and path.parent != dd.root  # the browser's name is not a path
    (dd.root / "FY99 V2MOM.pdf").write_bytes(b"%PDF-1.4 other\n")  # same owner words, higher year
    assert connector.newest_pdf(str(path)) == path  # the sync still reads the upload, not that neighbor
    assert connector.load_source(dd) == {"kind": "pdf", "value": str(path.resolve())}
    assert stat.S_IMODE((dd.root / "v2mom.json").stat().st_mode) == 0o600
    assert not (path.parent / ".V2MOM.upload").exists()
    assert started == ["v2mom"]


def test_a_file_that_is_not_a_pdf_is_refused(nb, monkeypatch):
    started = stub_job(monkeypatch)
    dd, c, token, _ = nb
    r = post_pdf(c, token, b"This is a note, not a PDF.\n", "FY27 V2MOM.pdf")
    assert r.status_code == 303 and "isn't a PDF" in unquote(r.headers["location"])
    assert not stored(dd).exists() and connector.load_source(dd) is None and started == []


def test_a_pdf_over_the_size_cap_is_refused(nb, monkeypatch):
    started = stub_job(monkeypatch)
    dd, c, token, _ = nb
    r = post_pdf(c, token, b"%PDF-" + b"x" * connector.MAX_PDF)
    assert r.status_code == 303 and "too big" in unquote(r.headers["location"])
    assert not stored(dd).exists() and connector.load_source(dd) is None and started == []


def test_upload_without_the_csrf_token_is_refused(nb, monkeypatch):
    started = stub_job(monkeypatch)
    dd, c, *_ = nb
    r = post_pdf(c, None)
    assert r.status_code == 403
    assert not stored(dd).exists() and started == []


def test_the_practice_notebook_refuses_an_upload(tmp_path, monkeypatch):
    started = stub_job(monkeypatch)
    dd = DataDir(tmp_path / "practice")
    dd.init_demo()
    app = create_app(dd)
    c = TestClient(app, base_url=BASE)
    assert 'action="/v2mom/upload"' not in c.get("/v2mom").text
    r = post_pdf(c, app.state.csrf_token)
    assert r.status_code == 303 and "personal notebook" in unquote(r.headers["location"])
    assert not stored(dd).exists() and started == []


def test_the_active_version_lines_render(nb):
    dd, c, *_ = nb
    with open_session(dd) as s:
        load_v2mom(s)
        connect(s)
        read = short_day(store.current(s).pulled_at.date())
    page = c.get("/v2mom").text
    assert f"Active: FY27 V2MOM, read {read}" in page and 'action="/v2mom/upload"' in page
    assert "KSOs: FY27 Delivery" in c.get("/kso").text
