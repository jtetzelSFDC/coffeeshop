"""The local pages. They only answer on this computer, check each form post, and escape everything they show."""
from __future__ import annotations

import hashlib
import os
import hmac
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import delete, false, func, or_, select
from sqlalchemy.orm import Session

from ..config import DataDir
from ..export.csv_all import notebook_zip
from ..export.promo import promo_markdown
from ..export.wins import wins_markdown
from ..google import summaries
from ..guide import service as gsvc
from ..guide.parse import GuideFormatError, read_workbook
from ..guide.topics import grouped, short_name, suggest
from ..setup import choose_level, find_role, run_checks
from ..slack import importer as slack_imp
from ..storage.removal import remove_entry, restore_entry
from ..storage.sync_log import status as sync_status
from ..v2mom import connector as v2mom_conn, links as v2mom_links, report as v2mom_report, store as v2mom_store
from ..values import links as value_links
from . import syncs
from .jobs import Jobs
from ..storage.db import init_db, make_engine, make_session_factory
from ..guide import activities, work
from ..storage.models import (CompetencyLink, DailyTask, GuideItem, GuideLink, JournalAttachment, JournalEntry,
                              RemovedEntry, V2momLink,
                              V2momMethod, V2momVersion, Win, WorkItem)

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self'; "
       "form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")
SCRIPTS = {n: (Path(__file__).parent / "static" / f"{n}.js").read_text() for n in ("page", "sheet", "sync")}
IMG_DIR = Path(__file__).parent / "static" / "img"
IMG_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
IMAGES = {p.name for p in IMG_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMG_TYPES}
_write_lock = threading.Lock()

KINDS = [("meeting", "Had a meeting"), ("conversation", "Had a conversation"),
         ("document", "Worked on a document"), ("task", "Finished a task"), ("recognition", "Got recognition"),
         ("certification", "Gained a certification"), ("note", "Something else")]
KIND_LABEL = dict(KINDS)
ATTACH_KINDS = [("notes", "Meeting notes"), ("transcript", "Transcript"), ("link", "Link"),
                ("canvas", "Slack canvas"), ("prompt", "A prompt I wrote"), ("other", "Other text")]
ATTACH_LABEL = dict(ATTACH_KINDS)
MAX_BODY = 200_000
TABS = {  # path -> (kind, tab name, heading, what's on it)
    "/meetings": ("meeting", "Meetings", "Meetings", "Every meeting you've logged or pulled from your calendar, newest first. Notes and documents linked to a meeting show underneath it."),
    "/conversations": ("conversation", "Conversations", "Conversations", "Chats and calls you've noted, newest first."),
    "/documents": ("document", "Documents", "Documents", "Documents you've worked on, newest first."),
    "/tasks": ("task", "Tasks", "Tasks", "Google Tasks you've finished, grouped by the day you completed them, plus any you've noted yourself (open ones you typed stay at the top)."),
    "/recognition": ("recognition", "Kudos", "Kudos", "Recognition from other people: shout-outs and thanks found in public and private Slack channels (never DMs), and anything you marked as recognition. Each counts like a medium win on the Performance map."),
    "/certifications": ("certification", "Certifications", "Certifications", "Credentials you've earned, including ones from before this notebook. Each counts as a training or certification."),
    "/other": ("note", "Other", "Something else", "Anything that didn't fit the other tabs."),
}
PAGES = {"/", "/search", "/wins", "/performance", "/v2mom", "/kso", "/sheet", "/digest", "/ask", *TABS}
SOURCE_LABEL = {"calendar": "Calendar", "tasks": "Google Tasks", "slack": "Slack", "docs": "Google Docs", "github": "GitHub",
                "kudos": "Slack kudos", "daily": "Daily three", "": "Typed"}
SHEET_KIND = [("meeting", "Meeting"), ("conversation", "Convo"), ("document", "Doc"), ("task", "Task"), ("recognition", "Kudos"),
              ("certification", "Cert"), ("note", "Other")]
SHEET_SHOW = {"all": "Everything", "todo": "Not checked yet", "ai": "Changed by Claude", "linked": "Linked to the guide",
              "unlinked": "Not linked", "wins": "Wins", "checked": "Checked", "removed": "Removed"}
SHEET_PAGE = 100
LIST_LIMIT = 300
SIZES = [("small", "Small"), ("medium", "Medium"), ("large", "Large")]
SIZE_LABEL = dict(SIZES)
THEMES = ["Delivery", "Quality & reliability", "Leadership", "Collaboration", "Customer impact",
          "Process improvement", "Mentoring", "Learning & growth"]


def day_label(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %B ") + str(d.day)


def short_day(day: str | date) -> str:
    """Oct 29 this year, Oct 29, 2025 before that."""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{d:%b} {d.day}" + ("" if d.year == date.today().year else f", {d.year}")


def _hostname(value: str) -> str:
    return urlparse(f"//{value}").hostname or ""


def guide_label(g: GuideItem, devops: bool) -> str:
    return f"{short_name(g.name, devops)} (Grade {g.grade})" if g.kind == "experience" else g.name


def is_devops(s: Session) -> bool:
    return grouped((gsvc.level(s) or {}).get("role", ""))


def guide_chips(s: Session, *, win_ids=(), entry_ids=()) -> dict[tuple[str, int], list[str]]:
    """("win"|"entry", id) -> short labels of the guide items it's linked to."""
    out: dict[tuple[str, int], list[str]] = {}
    q = select(GuideLink, GuideItem).join(GuideItem, GuideItem.id == GuideLink.item_id).where(
        (GuideLink.win_id.in_(list(win_ids))) | (GuideLink.entry_id.in_(list(entry_ids))))
    devops = is_devops(s)
    for l, g in s.execute(q.order_by(GuideItem.position)):
        label = guide_label(g, devops)
        k = ("win", l.win_id) if l.win_id else ("entry", l.entry_id)
        if label not in out.setdefault(k, []):
            out[k].append(label)
    return out


def create_app(dd: DataDir) -> FastAPI:
    dd.require_known()
    personal = dd.is_personal
    os.umask(0o077)
    engine = make_engine(dd.db)
    init_db(engine)
    Session_ = make_session_factory(engine)
    jobs = Jobs()
    csrf_token = hmac.new(dd.secret(), b"csrf", hashlib.sha256).hexdigest()
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
    env.globals.update(tabs=TABS, sizes=SIZES, themes=THEMES, level_note=gsvc.level_note)
    env.filters["short_day"] = short_day
    env.filters["status_class"] = v2mom_report.status_class
    env.globals["howto"] = env.get_template("_ui.html").module.howto
    app = FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in ALLOWED_HOSTS:
            return JSONResponse({"error": "bad host"}, status_code=400)
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and _hostname(urlparse(origin).netloc) not in ALLOWED_HOSTS:
                return JSONResponse({"error": "bad origin"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    def db():
        with Session_() as s:
            yield s

    def check_csrf(csrf: str = Form("")) -> None:
        if not hmac.compare_digest(csrf, csrf_token):
            raise _Forbidden()

    class _Forbidden(Exception):
        pass

    @app.exception_handler(_Forbidden)
    async def _forbidden(_r, _e):
        return JSONResponse({"error": "bad csrf token"}, status_code=403)

    def page_html(request: Request, tpl: str, page: str, **ctx) -> HTMLResponse:
        """A full page. Every page gets the CSRF token, the theme, the sync warning, which Menu item to highlight
        (`page`), and its own address (`here`) so the theme switch comes back to it."""
        ctx.setdefault("msg", None)
        here = request.url.path + (f"?{urlencode([(k, v) for k, v in request.query_params.multi_items() if k != 'msg'])}"
                                   if any(k != "msg" for k in request.query_params) else "")
        return HTMLResponse(env.get_template(tpl).render({
            "csrf": csrf_token, "personal": personal, "sync_warning": dd.sync_warning(), "theme": theme_of(request),
            "page": page, "here": here, **ctx}))

    def back(msg: str | None = None, to: str = "/") -> RedirectResponse:
        sep = "&" if "?" in to else "?"
        return RedirectResponse(to + (f"{sep}msg={quote(msg[:300])}" if msg else ""), status_code=303)

    def theme_of(request: Request) -> str:
        return "light" if request.cookies.get("theme") == "light" else "dark"

    def entry_dicts(s: Session, rows: list) -> list[dict]:
        """What a record card or queue row shows: its attachments (links only when http/https), guide chips, a
        suggested guide item when Claude hasn't read it yet, and whether its meeting notes are summarized."""
        atts: dict[int, list] = {}
        for a in s.scalars(select(JournalAttachment).where(
                JournalAttachment.entry_id.in_([e.id for e in rows])).order_by(JournalAttachment.id)):
            link = a.kind == "link" and urlparse(a.body.strip()).scheme in ("http", "https")
            atts.setdefault(a.entry_id, []).append(dict(
                id=a.id, label=ATTACH_LABEL.get(a.kind, "Text"), title=a.title, body=a.body,
                url=a.body.strip() if link else None,
                name=a.title or (urlparse(a.body.strip()).hostname or "Link" if link else ATTACH_LABEL.get(a.kind, "Text")),
                ai=a.kind == "notes" and a.title == summaries.AI_TITLE,
                slack_ai=a.kind == "notes" and a.title.startswith(slack_imp.NOTES_TITLE)))
        guided = gsvc.has_guide(s)
        chips = guide_chips(s, entry_ids=[e.id for e in rows]) if guided else {}
        has_win = set(s.scalars(select(Win.entry_id).where(Win.entry_id.in_([e.id for e in rows]))))
        out = []
        for e in rows:
            linked = chips.get(("entry", e.id), [])
            hint = [t.name for t in suggest(e.text)[0]] if guided and not linked and not e.ai_read else []
            mine = atts.get(e.id, [])
            impact = next((slack_imp.impact_of(a["body"]) for a in mine if a["slack_ai"]), "")
            has_notes = any(summaries.doc_ids([a["url"]]) for a in mine if a["url"])
            from_cal = e.source == "calendar"
            out.append(dict(id=e.id, day=e.day, text=e.text, kind_label=KIND_LABEL.get(e.kind, "Note"),
                            source=e.source or "typed", source_label=SOURCE_LABEL.get(e.source or "", e.source),
                            from_calendar=from_cal, status=e.status, attachments=mine, guided=guided,
                            guide=linked, hint=hint, from_slack=e.source == slack_imp.SOURCE, win_impact=impact,
                            suggested_win=bool(impact) and e.id not in has_win,
                            notes_state=("" if not from_cal else "summarized" if any(a["ai"] for a in mine)
                                         else "pending" if has_notes else "none")))
        return out

    @app.get("/", response_class=HTMLResponse)
    def today_page(request: Request, msg: str | None = None, s: Session = Depends(db)):
        today = date.today()
        from .. import daily as daily_mod, dashboard
        return page_html(request, "today.html", "/", dash=dashboard.build(s, today),
                         daily=daily_mod.today_tasks(s, today), kinds=KINDS,
                         attach_kinds=ATTACH_KINDS, today=today.isoformat(), msg=msg,
                         slack_canvas=slack_imp.load_canvas_id(dd) if personal else None,
                         v2mom_doc=v2mom_conn.load_source(dd) if personal else None, sync=sync_view(s))

    def tab_page(path: str):
        kind, _name, title, intro = TABS[path]

        def view(request: Request, msg: str | None = None, s: Session = Depends(db)):
            q = select(JournalEntry).where(JournalEntry.kind == kind)
            count = s.scalar(select(func.count()).select_from(q.subquery()))
            open_rows = list(s.scalars(q.where(JournalEntry.status == "open").order_by(JournalEntry.day.desc(), JournalEntry.id)))
            rows = list(s.scalars(q.where(JournalEntry.status != "open")
                                  .order_by(JournalEntry.day.desc(), JournalEntry.id.desc()).limit(LIST_LIMIT)))
            today = date.today()
            ents = entry_dicts(s, open_rows + rows)
            days: list[dict] = []
            for e in ents[len(open_rows):]:
                if not days or days[-1]["day"] != e["day"]:
                    days.append(dict(day=e["day"], label=day_label(date.fromisoformat(e["day"]), today), entries=[]))
                days[-1]["entries"].append(e)
            return page_html(request, "list.html", path, title=title, intro=intro, count=count,
                             shown=len(open_rows) + len(rows), days=days, open_entries=ents[:len(open_rows)],
                             kinds=KINDS, attach_kinds=ATTACH_KINDS, msg=msg)
        return view

    for _path in TABS:
        app.add_api_route(_path, tab_page(_path), methods=["GET"], response_class=HTMLResponse)

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str = "", s: Session = Depends(db)):
        q = q.strip()[:200]
        hits = []
        if q:
            terms = [w for w in q.split() if w][:6]
            needle = terms[0].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{needle}%"
            ids = set(s.scalars(select(JournalEntry.id).where(JournalEntry.text.ilike(like, escape="\\"))))
            ids.update(s.scalars(select(JournalAttachment.entry_id).where(or_(
                JournalAttachment.title.ilike(like, escape="\\"),
                JournalAttachment.body.ilike(like, escape="\\")))))
            by_entry: dict[int, dict] = {}
            if ids:
                for e in s.scalars(select(JournalEntry).where(JournalEntry.id.in_(ids))
                                   .order_by(JournalEntry.day.desc(), JournalEntry.id.desc())):
                    by_entry[e.id] = dict(e=e, atts=[])
                for a in s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id.in_(ids))):
                    by_entry[a.entry_id]["atts"].append(a)
            for v in by_entry.values():
                e = v["e"]
                texts = [("", e.text)] + [(f"{ATTACH_LABEL.get(a.kind, 'Text')}: {a.title}".strip(": "), a.body)
                                          for a in v["atts"]] + [("", a.title) for a in v["atts"] if a.title]
                blob = "\n".join(x for _, x in texts).lower()
                if not all(w.lower() in blob for w in terms):
                    continue
                snippets = []
                for label, body in texts[1:] if len(texts) > 1 else []:
                    low = body.lower()
                    i = low.find(terms[0].lower())
                    if i < 0:
                        continue
                    lo, hi = max(0, i - 80), min(len(body), i + len(terms[0]) + 120)
                    snippets.append(dict(label=label, before=("…" if lo else "") + body[lo:i].replace("\n", " "),
                                         hit=body[i:i + len(terms[0])],
                                         after=body[i + len(terms[0]):hi].replace("\n", " ") + ("…" if hi < len(body) else "")))
                hits.append(dict(day=e.day, kind_label=KIND_LABEL.get(e.kind, "Note"), text=e.text,
                                 snippets=snippets[:2]))
                if len(hits) >= 50:
                    break
            for w in s.scalars(select(Win).where(or_(
                    Win.title.ilike(like, escape="\\"), Win.impact.ilike(like, escape="\\"),
                    Win.theme.ilike(like, escape="\\"))).order_by(Win.day.desc(), Win.id.desc())):
                if all(t.lower() in f"{w.title}\n{w.impact}\n{w.theme}".lower() for t in terms):
                    hits.append(dict(day=w.day, kind_label="Win", text=w.title, snippets=[]))
            hits.sort(key=lambda h: h["day"], reverse=True)
        return page_html(request, "search.html", "/search", q=q, hits=hits)

    @app.post("/journal/add", dependencies=[Depends(check_csrf)])
    def journal_add(kind: str = Form(...), text: str = Form(..., max_length=500),
                    day: str = Form(""), a_kind: str = Form("notes"), a_title: str = Form("", max_length=200),
                    a_body: str = Form("", max_length=MAX_BODY), s: Session = Depends(db)):
        text = text.strip()
        try:
            d = date.fromisoformat(day) if day else date.today()
        except ValueError:
            d = date.today()
        d = min(d, date.today())
        if not text:
            return back("Write a few words first.", "/")
        with _write_lock:
            entry = JournalEntry(day=d.isoformat(), kind=kind if kind in KIND_LABEL else "note",
                                 text=text, created_at=datetime.now())
            if entry.kind == "certification":  # the user said what it counts as; Claude's activity pass leaves it
                entry.activity, entry.activity_fixed = "training", True
            s.add(entry)
            s.flush()
            if a_body.strip():
                s.add(JournalAttachment(entry_id=entry.id, kind=a_kind if a_kind in ATTACH_LABEL else "other",
                                        title=a_title.strip(), body=a_body.strip(), created_at=datetime.now()))
            s.commit()
            kind = entry.kind
        if read_new():
            msg = "Added. Claude is reading it now; the result will be in the Intake Review Queue."
        elif personal and jobs.running():
            msg = "Added. A sync is running, so Claude reads it when that finishes, or from the Intake Review Queue."
        else:
            msg = "Added."
        return back(msg, next(p for p, (k, *_rest) in TABS.items() if k == kind))

    def read_new() -> bool:
        """Has Claude sort what you just added (guide, V2MOM, impact), in the background. Not while a sync runs: a
        sync's last step reads new records too, or the next one will."""
        return personal and not jobs.running() and jobs.start(
            "review", syncs.REVIEW_STEPS, lambda j: syncs.run_review(j, Session_))

    def started_reply(request: Request, started: bool, ok: str, busy: str, to: str) -> Response:
        """The answer to a button that starts a background job: JSON for the page's script (sync.js), which then
        shows the progress box, or a redirect with a message for a plain form post."""
        if request.headers.get("x-sync") == "1":
            return JSONResponse({"started": started})
        return back(ok if started else busy, to)

    def start_sync(request: Request, name: str, force: bool = False, to: str = "/"):
        """Starts the background job `name` (one per Sync button) unless it's already running."""
        if not personal:
            return back("Syncing only works with your personal notebook.", to)
        runs = {
            "daily": (syncs.DAILY_STEPS, lambda j: syncs.run_daily(j, Session_, _write_lock, force=force)),
            "google": (syncs.GOOGLE_STEPS, lambda j: syncs.run_google(j, Session_, _write_lock)),
            "kso": (syncs.KSO_STEPS, lambda j: syncs.run_kso(j, Session_, _write_lock)),
            "review": (syncs.REVIEW_STEPS, lambda j: syncs.run_review(j, Session_)),
            "slack": (syncs.SLACK_STEPS, lambda j: syncs.run_slack(j, Session_, _write_lock, dd)),
            "v2mom": (syncs.V2MOM_STEPS, lambda j: syncs.run_v2mom(j, Session_, _write_lock, dd)),
        }
        if name == "review" and jobs.running():
            return started_reply(request, False, "", "A sync is already running.", to)
        steps, fn = runs[name]
        return started_reply(request, jobs.start(name, steps, fn),
                             "Started. Refresh this page in a minute or two to see the result.",
                             "That's already running.", to)

    @app.post("/daily/suggest", dependencies=[Depends(check_csrf)])
    def daily_suggest(request: Request, force: str = Form("")):
        """Ask for today's three now (or a new three, replacing all of them), in the background."""
        return start_sync(request, "daily", force=force == "1")

    @app.post("/daily/{tid}/done", dependencies=[Depends(check_csrf)])
    def daily_done(tid: int, details: str = Form("", max_length=20_000), s: Session = Depends(db)):
        from .. import daily
        with _write_lock:
            t = s.get(DailyTask, tid)
            if t is None:
                return back("That task isn't here any more.", "/")
            daily.check(s, t, details)
        read_new()
        return back("Done. It's logged as a finished task.", "/")

    @app.post("/daily/{tid}/undo", dependencies=[Depends(check_csrf)])
    def daily_undo(tid: int, s: Session = Depends(db)):
        from .. import daily
        with _write_lock:
            t = s.get(DailyTask, tid)
            if t is not None:
                daily.uncheck(s, t)
        return back(to="/")

    @app.post("/sync/google", dependencies=[Depends(check_csrf)])
    def google_sync(request: Request):
        """Calendar, Tasks, and meeting-note summaries in one go, in the background."""
        return start_sync(request, "google")

    @app.post("/slack/sync", dependencies=[Depends(check_csrf)])
    def slack_sync(request: Request):
        """Read your Slack messages and the tracker canvas, then sort and import what's new, in the background."""
        return start_sync(request, "slack")

    @app.post("/sync/v2mom", dependencies=[Depends(check_csrf)])
    def v2mom_sync(request: Request):
        """Re-read the V2MOM (after a check-in, say), in the background."""
        return start_sync(request, "v2mom")

    @app.post("/v2mom/upload", dependencies=[Depends(check_csrf)])
    def v2mom_upload(request: Request, pdf: UploadFile | None = File(None)):
        """Save a new V2MOM PDF into this notebook and read it now. Personal notebook only."""
        if not personal:
            return back("Uploading a V2MOM only works with your personal notebook.", "/v2mom")
        raw = pdf.file.read(v2mom_conn.MAX_PDF + 1) if pdf is not None and pdf.file is not None else b""
        try:
            path = v2mom_conn.store_upload(dd, raw)
            v2mom_conn.save_source(dd, str(path))
        except ValueError as exc:
            return back(str(exc), "/v2mom")
        return start_sync(request, "v2mom", to="/v2mom")

    @app.post("/v2mom/url", dependencies=[Depends(check_csrf)])
    def v2mom_url(request: Request, url: str = Form("")):
        """Connect the V2MOM app page by its link and read it now. Personal notebook only."""
        if not personal:
            return back("Connecting a V2MOM only works with your personal notebook.", "/v2mom")
        if not url.strip().lower().startswith("https://"):
            return back("Paste your V2MOM page's https:// link.", "/v2mom")
        try:
            v2mom_conn.save_source(dd, url)
        except ValueError as exc:
            return back(str(exc), "/v2mom")
        return start_sync(request, "v2mom", to="/v2mom")

    def sync_view(s: Session) -> dict[str, dict]:
        st = sync_status(s)
        if personal and not v2mom_conn.load_source(dd):
            st["v2mom"].update(ok=None, hint=syncs.V2MOM_CONNECT)
        return st

    @app.get("/sync/status")
    def sync_status_json():
        return JSONResponse(jobs.status(), headers={"Cache-Control": "no-store"})

    @app.get("/static/{name}.js")
    def script(name: str):
        if name not in SCRIPTS:
            return Response(status_code=404)
        return Response(SCRIPTS[name], media_type="text/javascript; charset=utf-8")

    @app.get("/static/img/{name}")
    def static_img(name: str):
        if name not in IMAGES:
            return Response(status_code=404)
        path = IMG_DIR / name
        return Response(path.read_bytes(), media_type=IMG_TYPES[path.suffix.lower()],
                        headers={"Cache-Control": "max-age=86400"})

    @app.post("/journal/{eid}/attach", dependencies=[Depends(check_csrf)])
    def journal_attach(eid: int, a_kind: str = Form("notes"), a_title: str = Form("", max_length=200),
                       a_body: str = Form(..., max_length=MAX_BODY), s: Session = Depends(db)):
        with _write_lock:
            if s.get(JournalEntry, eid) and a_body.strip():
                s.add(JournalAttachment(entry_id=eid, kind=a_kind if a_kind in ATTACH_LABEL else "other",
                                        title=a_title.strip(), body=a_body.strip(), created_at=datetime.now()))
                s.commit()
        return back(to="/")

    @app.post("/journal/attachment/{aid}/delete", dependencies=[Depends(check_csrf)])
    def journal_attachment_delete(aid: int, s: Session = Depends(db)):
        with _write_lock:
            a = s.get(JournalAttachment, aid)
            if a:
                s.delete(a)
                s.commit()
        return back(to="/")

    @app.post("/journal/{eid}/delete", dependencies=[Depends(check_csrf)])
    def journal_delete(eid: int, s: Session = Depends(db)):
        with _write_lock:
            remove_entry(s, eid)
        return back(to="/")

    def win_years(s: Session) -> list[int]:
        return sorted({int(d[:4]) for d in s.scalars(select(Win.day))} | {date.today().year}, reverse=True)

    def year_wins(s: Session, year: int) -> list[Win]:
        return list(s.scalars(select(Win).where(Win.day >= f"{year}-01-01", Win.day <= f"{year}-12-31")
                              .order_by(Win.day.desc(), Win.id.desc())))

    @app.get("/wins", response_class=HTMLResponse)
    def wins_page(request: Request, year: int | None = None, size: str = "", missing: bool = False,
                  msg: str | None = None, s: Session = Depends(db)):
        year = year or date.today().year
        rows = year_wins(s, year)
        counts = {k: sum(1 for w in rows if w.size == k) for k in SIZE_LABEL}
        shown = [w for w in rows if (not size or w.size == size) and (not missing or not w.impact)]
        entries = {e.id: e.text for e in s.scalars(select(JournalEntry).where(
            JournalEntry.id.in_([w.entry_id for w in shown if w.entry_id])))}
        chips = guide_chips(s, win_ids=[w.id for w in shown])
        months: list[dict] = []
        for w in shown:
            label = date.fromisoformat(w.day).strftime("%B")
            if not months or months[-1]["label"] != label:
                months.append(dict(label=label, wins=[]))
            months[-1]["wins"].append(dict(w=w, size_label=SIZE_LABEL.get(w.size, w.size),
                                           from_entry=entries.get(w.entry_id), guide=chips.get(("win", w.id), [])))
        return page_html(request, "wins.html", "/wins", year=year, years=win_years(s), size=size,
                         only_missing=missing, months=months, total=len(rows), counts=counts,
                         missing=sum(1 for w in rows if not w.impact), today=date.today().isoformat(),
                         guided=gsvc.has_guide(s), msg=msg)

    def win_fields(title: str, impact: str, size: str, theme: str, day: str) -> dict:
        try:
            d = min(date.fromisoformat(day), date.today()) if day else date.today()
        except ValueError:
            d = date.today()
        return dict(title=title.strip(), impact=impact.strip(), size=size if size in SIZE_LABEL else "small",
                    theme=theme if theme in THEMES else "", day=d.isoformat())

    @app.post("/wins/add", dependencies=[Depends(check_csrf)])
    def win_add(title: str = Form(..., max_length=500), impact: str = Form("", max_length=2000),
                size: str = Form("small"), theme: str = Form(""), day: str = Form(""),
                entry_id: int | None = Form(None), next: str = Form("/wins"), s: Session = Depends(db)):
        to = next if next in PAGES else "/wins"
        f = win_fields(title, impact, size, theme, day)
        if not f["title"]:
            return back("Write what you did first.", to)
        with _write_lock:
            entry = s.get(JournalEntry, entry_id) if entry_id else None
            w = Win(**f, entry_id=entry.id if entry else None, created_at=datetime.now())
            s.add(w)
            s.commit()
        if gsvc.has_guide(s):
            return RedirectResponse(f"/guide/link?win={w.id}&next={quote(to)}", status_code=303)
        return back(f"Saved to your wins: {f['title']}", to)

    @app.post("/wins/{wid}/edit", dependencies=[Depends(check_csrf)])
    def win_edit(wid: int, title: str = Form(..., max_length=500), impact: str = Form("", max_length=2000),
                 size: str = Form("small"), theme: str = Form(""), day: str = Form(""), s: Session = Depends(db)):
        f = win_fields(title, impact, size, theme, day)
        with _write_lock:
            w = s.get(Win, wid)
            if w and f["title"]:
                for k, v in f.items():
                    setattr(w, k, v)
                w.by_ai = False
                s.commit()
        return back(to=f"/wins?year={f['day'][:4]}")

    @app.post("/wins/{wid}/delete", dependencies=[Depends(check_csrf)])
    def win_delete(wid: int, s: Session = Depends(db)):
        with _write_lock:
            w = s.get(Win, wid)
            if w:
                gsvc.drop_links(s, win_id=wid)
                s.delete(w)
                s.commit()
        return back(to="/wins")

    def link_target(s: Session, win: int | None, entry: int | None):
        if win is not None:
            w = s.get(Win, win)
            return (w, dict(win_id=w.id), w.title + "\n" + w.impact) if w else None
        e = s.get(JournalEntry, entry) if entry is not None else None
        return (e, dict(entry_id=e.id), e.text) if e else None

    @app.get("/guide/link", response_class=HTMLResponse)
    def guide_link_page(request: Request, win: int | None = None, entry: int | None = None, next: str = "/wins",
                        s: Session = Depends(db)):
        t = link_target(s, win, entry)
        if t is None or not gsvc.has_guide(s):
            return back("That item is gone, or the leveling guide isn't loaded yet.", "/performance")
        pm = gsvc.promo_map(s)
        obj, ref, text = t
        linked = gsvc.linked_ids(s, **ref)
        linked_methods = v2mom_links.linked_ids(s, **ref)
        if isinstance(obj, Win) and obj.entry_id:
            linked = linked or gsvc.linked_ids(s, entry_id=obj.entry_id)
            linked_methods = linked_methods or v2mom_links.linked_ids(s, entry_id=obj.entry_id)
        suggested = set() if linked else gsvc.suggested_ids(s, text)
        return page_html(request, "guide_link.html", "/performance", obj=obj, is_win=isinstance(obj, Win), ref=ref,
                         checked=linked or suggested, suggested=bool(suggested), methods=v2mom_store.methods(s),
                         checked_methods=linked_methods, pm=pm, level=gsvc.level(s),
                         next=next if next in PAGES else "/wins")

    @app.post("/guide/link", dependencies=[Depends(check_csrf)])
    def guide_link_save(win: int | None = Form(None), entry: int | None = Form(None), item: list[int] = Form([]),
                        method: list[int] = Form([]), next: str = Form("/wins"), s: Session = Depends(db)):
        to = next if next in PAGES else "/wins"
        with _write_lock:
            t = link_target(s, win, entry)
            if t is None:
                return back("That item is gone.", to)
            offered = gsvc.shown_ids(s)
            gsvc.set_links(s, set(item), offered, **t[1])
            if shown := {m.id for m in v2mom_store.methods(s)}:
                v2mom_links.set_links(s, set(method), shown, **t[1])
        n = len(set(item) & offered)
        if not offered:
            return back("Saved.", to)
        return back(f"Linked to {n} leveling guide item{'' if n == 1 else 's'}." if n else "Saved, with no guide items.", to)

    def sheet_filters(show: str = "todo", source: str = "any", kind: str = "any", page: int = 1,
                      v2mom: str = "") -> dict:
        return dict(show=show if show in SHEET_SHOW else "todo",
                    source=source if source in SOURCE_LABEL or source == "any" else "any",
                    kind=kind if kind in KIND_LABEL or kind == "any" else "any", page=max(1, min(page, 1000)),
                    v2mom="none" if v2mom == "none" else "")

    def parse_ret(ret: str) -> dict:
        q = {k: v[0] for k, v in parse_qs(ret).items() if k in ("show", "source", "kind", "page", "v2mom")}
        try:
            return sheet_filters(**{**q, "page": int(q.get("page", 1))})
        except ValueError:
            return sheet_filters()

    def sheet_query(f: dict):
        """The queue's records for the filters in `f`. Open Google Tasks never show (they come in once done);
        "removed" records live in another table, so that view has no rows here."""
        linked = select(GuideLink.entry_id).where(GuideLink.entry_id.is_not(None))
        q = select(JournalEntry).where(~((JournalEntry.source == "tasks") & (JournalEntry.status == "open")))
        if f["source"] != "any":
            q = q.where(JournalEntry.source == f["source"])
        if f["kind"] != "any":
            q = q.where(JournalEntry.kind == f["kind"])
        q = {"todo": q.where(JournalEntry.reviewed.is_(False)), "checked": q.where(JournalEntry.reviewed.is_(True)),
             "ai": q.where(JournalEntry.reviewed.is_(False), (JournalEntry.kind_was != "") | JournalEntry.id.in_(
                 select(GuideLink.entry_id).where(GuideLink.by_ai)) | JournalEntry.id.in_(
                 select(Win.entry_id).where(Win.by_ai)) | JournalEntry.id.in_(
                 select(V2momLink.entry_id).where(V2momLink.by_ai)) | JournalEntry.id.in_(
                 select(CompetencyLink.entry_id).where(CompetencyLink.by_ai))),
             "linked": q.where(JournalEntry.id.in_(linked)), "unlinked": q.where(JournalEntry.id.not_in(linked)),
             "wins": q.where(JournalEntry.id.in_(select(Win.entry_id).where(Win.entry_id.is_not(None)))),
             "removed": q.where(false()), "all": q}[f["show"]]
        # shortcut: Removed is another table and has no V2MOM links, so this filter does not apply there
        if f.get("v2mom") == "none" and f["show"] != "removed":
            on_entry = select(V2momLink.entry_id).where(V2momLink.entry_id.is_not(None))
            on_win = select(Win.entry_id).join(V2momLink, V2momLink.win_id == Win.id).where(Win.entry_id.is_not(None))
            q = q.where(JournalEntry.v2mom_read.is_(True), JournalEntry.id.not_in(on_entry), JournalEntry.id.not_in(on_win))
        return q

    def sheet_ctx(s: Session, f: dict) -> dict:
        return dict(ret=urlencode(f), csrf=csrf_token, kind_opts=SHEET_KIND, size_label=SIZE_LABEL,
                    guided=gsvc.has_guide(s), activity_opts=[(k, label) for k, label, _ in activities.ACTIVITIES])

    def sheet_back(request: Request, s: Session, ret: str, eid: int | None = None, msg: str | None = None,
                   after: int | None = None) -> Response:
        """A full redirect for plain form posts; for the queue's script, just the redrawn row, or "gone"."""
        f = parse_ret(ret)
        if request.headers.get("x-sheet") == "1" and not eid:
            return Response("")  # nothing to redraw (the link was already gone): the script reloads the page
        if request.headers.get("x-sheet") == "1":
            s.expire_all()
            e = s.scalar(sheet_query(f).where(JournalEntry.id == eid))
            if e is None:
                return Response("", headers={"X-Row": "gone"})
            html = env.get_template("_sheet_row.html").render(r=sheet_rows(s, [e])[0], nxt="", **sheet_ctx(s, f))
            return HTMLResponse(html)
        if msg:
            f["msg"] = msg[:300]
        anchor = after or eid
        return RedirectResponse(f"/sheet?{urlencode(f)}" + (f"#r{anchor}" if anchor else ""), status_code=303)

    @app.get("/sheet", response_class=HTMLResponse)
    def sheet_page(request: Request, show: str = "todo", source: str = "any", kind: str = "any", page: int = 1,
                   v2mom: str = "", msg: str | None = None, s: Session = Depends(db)):
        f = sheet_filters(show, source, kind, page, v2mom)
        if f["show"] == "removed":
            q = select(RemovedEntry)
            if f["source"] != "any":
                q = q.where(RemovedEntry.source == f["source"])
            if f["kind"] != "any":
                q = q.where(RemovedEntry.kind == f["kind"])
            order = (RemovedEntry.removed_at.desc(), RemovedEntry.id.desc())
        else:
            q, order = sheet_query(f), (JournalEntry.day.desc(), JournalEntry.id.desc())
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        pages = max(1, -(-total // SHEET_PAGE))
        f["page"] = min(f["page"], pages)
        rows = list(s.scalars(q.order_by(*order).offset((f["page"] - 1) * SHEET_PAGE).limit(SHEET_PAGE)))
        out = ([dict(id=r.id, day=r.day, source=SOURCE_LABEL.get(r.source, r.source), text=r.text,
                     kind=dict(SHEET_KIND).get(r.kind, "Other")) for r in rows]
               if f["show"] == "removed" else sheet_rows(s, rows))
        counts = dict(
            total=s.scalar(select(func.count()).select_from(JournalEntry)) or 0,
            read=s.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.ai_read)) or 0,
            checked=s.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.reviewed)) or 0,
            unread=s.scalar(select(func.count()).select_from(JournalEntry).where(
                JournalEntry.ai_read.is_(False), JournalEntry.reviewed.is_(False))) or 0,
            **gsvc.ai_counts(s))
        return page_html(request, "sheet.html", "/sheet", rows=out, f=f, total=total, pages=pages, counts=counts,
                         show_opts=SHEET_SHOW, source_opts=SOURCE_LABEL, msg=msg, wide=True, sync=sync_view(s),
                         **sheet_ctx(s, f))

    def sheet_rows(s: Session, rows: list) -> list[dict]:
        ids = [e.id for e in rows]
        links: dict[int, list] = {}
        devops = is_devops(s)
        for l, g in s.execute(select(GuideLink, GuideItem).join(GuideItem, GuideItem.id == GuideLink.item_id)
                              .where(GuideLink.entry_id.in_(ids)).order_by(GuideItem.position)):
            links.setdefault(l.entry_id, []).append(dict(id=l.id, label=guide_label(g, devops), ai=l.by_ai,
                                                         name=g.name))
        wins = {w.entry_id: w for w in s.scalars(select(Win).where(Win.entry_id.in_(ids)).order_by(Win.id))}
        v2mom = v2mom_links.chips(s, ids)
        behaviors = value_links.chips(s, ids)
        notes: dict[int, str] = {}
        for a in s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id.in_(ids),
                                                           JournalAttachment.kind == "notes")):
            notes.setdefault(a.entry_id, a.body[:1200])
        nearby: list[WorkItem] = []
        if rows:
            span = timedelta(days=work.WINDOW_DAYS)
            lo = (date.fromisoformat(min(e.day for e in rows)) - span).isoformat()
            hi = (date.fromisoformat(max(e.day for e in rows)) + span).isoformat()
            nearby = list(s.scalars(select(WorkItem).where(WorkItem.day >= lo, WorkItem.day <= hi)
                                    .order_by(WorkItem.day.desc())))
        members = dict(s.execute(select(JournalEntry.work_item_id, func.count()).where(
            JournalEntry.work_item_id.in_([w.id for w in nearby])).group_by(JournalEntry.work_item_id)).all())
        by_id = {w.id: w for w in nearby}
        by_id.update({w.id: w for w in s.scalars(select(WorkItem).where(
            WorkItem.id.in_({e.work_item_id for e in rows if e.work_item_id} - set(by_id))))})
        group_wins = {w.work_item_id: w for w in s.scalars(select(Win).where(
            Win.work_item_id.in_(list(by_id))))} if by_id else {}

        def near(e) -> list[dict]:
            d = date.fromisoformat(e.day)
            return [dict(id=w.id, title=w.title, day=w.day) for w in nearby if w.id != e.work_item_id
                    and abs((date.fromisoformat(w.day) - d).days) <= work.WINDOW_DAYS][:20]

        return [dict(id=e.id, day=e.day, source=SOURCE_LABEL.get(e.source, e.source), kind=e.kind,
                     kind_was=dict(SHEET_KIND).get(e.kind_was, ""),
                     text=e.text, reviewed=e.reviewed, ai_read=e.ai_read, links=links.get(e.id, []),
                     v2mom=v2mom.get(e.id, []), behaviors=behaviors.get(e.id, []),
                     win=wins.get(e.id), notes=notes.get(e.id, ""),
                     work=(dict(id=w.id, title=w.title, ai=w.by_ai and not e.work_fixed, size=members.get(w.id, 1),
                                win_ai=bool((gw := group_wins.get(w.id)) and gw.by_ai))
                           if (w := by_id.get(e.work_item_id)) else None),
                     near=near(e), activity=e.activity, activity_label=activities.LABEL.get(e.activity, ""),
                     activity_ai=e.activity_read and not e.activity_fixed) for e in rows]

    @app.post("/sheet/{eid}/split", dependencies=[Depends(check_csrf)])
    def sheet_split(request: Request, eid: int, ret: str = Form(""), s: Session = Depends(db)):
        """Not the same work: take the record out of its group, and keep Claude from regrouping it."""
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e:
                e.work_item_id, e.work_fixed, e.grouped = None, True, True
                s.flush()
                work.drop_empty(s)
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/group", dependencies=[Depends(check_csrf)])
    def sheet_group(request: Request, eid: int, item: str = Form(""), title: str = Form("", max_length=200),
                    ret: str = Form(""), s: Session = Depends(db)):
        """Group with an existing piece of work, or start a new one with the given title."""
        with _write_lock:
            e = s.get(JournalEntry, eid)
            target = s.get(WorkItem, int(item)) if item.isdigit() else None
            if e and target is None and title.strip():
                target = WorkItem(title=title.strip(), day=e.day, started=e.day, by_ai=False, created_at=datetime.now())
                s.add(target)
                s.flush()
            if e and target:
                e.work_item_id, e.work_fixed, e.grouped = target.id, True, True
                target.day = max(target.day, e.day)
                target.started = min(target.started or target.day, e.day)
                s.flush()
                work.drop_empty(s)
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/one-win", dependencies=[Depends(check_csrf)])
    def sheet_one_win(request: Request, eid: int, ret: str = Form(""), s: Session = Depends(db)):
        """One win for the whole piece of work this record belongs to."""
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e and e.work_item_id:
                work.ensure_group_win(s, e.work_item_id, by_ai=False)
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/kind", dependencies=[Depends(check_csrf)])
    def sheet_kind(request: Request, eid: int, kind: str = Form(...), ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e and kind in KIND_LABEL:
                if e.kind != kind:
                    e.status = "done" if kind == "task" else ""
                e.kind, e.kind_was = kind, ""
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/win", dependencies=[Depends(check_csrf)])
    def sheet_win(request: Request, eid: int, size: str = Form("small"), ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e is None or size not in SIZE_LABEL:
                return sheet_back(request, s, ret, eid)
            w = s.scalar(select(Win).where(Win.entry_id == eid).order_by(Win.id).limit(1))
            if w:
                w.size, w.by_ai = size, False
            else:
                impact = next((slack_imp.impact_of(a.body) for a in s.scalars(select(JournalAttachment).where(
                    JournalAttachment.entry_id == eid, JournalAttachment.title.startswith(slack_imp.NOTES_TITLE)))), "")
                w = Win(day=e.day, title=e.text[:500], impact=impact, size=size, entry_id=eid, created_at=datetime.now())
                s.add(w)
                s.flush()
                for l in s.scalars(select(GuideLink).where(GuideLink.entry_id == eid)):
                    s.add(GuideLink(item_id=l.item_id, win_id=w.id, created_at=datetime.now(), by_ai=l.by_ai))
            s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/unwin", dependencies=[Depends(check_csrf)])
    def sheet_unwin(request: Request, eid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            for w in s.scalars(select(Win).where(Win.entry_id == eid)):
                gsvc.drop_links(s, win_id=w.id)
                s.delete(w)
            s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/link/{lid}/delete", dependencies=[Depends(check_csrf)])
    def sheet_unlink(request: Request, lid: int, ret: str = Form(""), s: Session = Depends(db)):
        eid = None
        with _write_lock:
            l = s.get(GuideLink, lid)
            if l and l.entry_id:
                eid = l.entry_id
                win_ids = select(Win.id).where(Win.entry_id == eid)
                s.execute(delete(GuideLink).where(GuideLink.item_id == l.item_id, GuideLink.win_id.in_(win_ids)))
                s.delete(l)
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/v2mom/{lid}/delete", dependencies=[Depends(check_csrf)])
    def sheet_v2mom_unlink(request: Request, lid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            eid = v2mom_links.unlink(s, lid)
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/values/{lid}/delete", dependencies=[Depends(check_csrf)])
    def sheet_values_unlink(request: Request, lid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            eid = value_links.unlink(s, lid)
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/ok", dependencies=[Depends(check_csrf)])
    def sheet_ok_bulk(request: Request, id: list[int] = Form([]), ret: str = Form(""), s: Session = Depends(db)):
        """Check the ticked rows. A row Claude has not read yet is skipped, same as one with no Looks right button."""
        confirmed: list[int] = []
        with _write_lock:
            waiting = personal and gsvc.has_guide(s)
            # shortcut: a list longer than one page is cut, the queue only posts the rows on the page
            for eid in list(dict.fromkeys(id))[:SHEET_PAGE]:
                e = s.get(JournalEntry, eid)
                if e is None or (waiting and not e.ai_read):
                    continue
                gsvc.confirm(s, eid)
                confirmed.append(eid)
        if request.headers.get("x-sheet") == "1":
            f = parse_ret(ret)
            s.expire_all()
            gone, rows = [], {}
            for eid in confirmed:
                e = s.scalar(sheet_query(f).where(JournalEntry.id == eid))
                if e is None:
                    gone.append(eid)
                else:
                    rows[str(eid)] = env.get_template("_sheet_row.html").render(
                        r=sheet_rows(s, [e])[0], nxt="", **sheet_ctx(s, f))
            return JSONResponse({"count": len(confirmed), "confirmed": confirmed, "gone": gone, "rows": rows})
        return sheet_back(request, s, ret)

    @app.post("/sheet/{eid}/ok", dependencies=[Depends(check_csrf)])
    def sheet_ok(request: Request, eid: int, ret: str = Form(""), after: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            gsvc.confirm(s, eid)
        return sheet_back(request, s, ret, eid, after=int(after) if after.isdigit() else None)

    @app.post("/sheet/{eid}/remove", dependencies=[Depends(check_csrf)])
    def sheet_remove(request: Request, eid: int, ret: str = Form(""), after: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            remove_entry(s, eid)
        return sheet_back(request, s, ret, eid, after=int(after) if after.isdigit() else None)

    @app.post("/sheet/removed/{rid}/restore", dependencies=[Depends(check_csrf)])
    def sheet_restore(request: Request, rid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            restore_entry(s, rid)
        if request.headers.get("x-sheet") == "1":
            return Response("", headers={"X-Row": "gone"})
        return sheet_back(request, s, ret)

    @app.post("/sheet/{eid}/undo", dependencies=[Depends(check_csrf)])
    def sheet_undo(request: Request, eid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e:
                e.reviewed = False
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/ai", dependencies=[Depends(check_csrf)])
    def sheet_ai(request: Request, ret: str = Form("")):
        """Have Claude read every record it hasn't read yet against the guide, in the background."""
        return start_sync(request, "review", to=f"/sheet?{urlencode(parse_ret(ret))}")

    def _v2_years(s: Session) -> list:
        """This year's V2MOM, and the newest earlier stored year beside it. A year that was never stored is left out."""
        cur = v2mom_report.build(s)
        if not cur:
            return []
        stored = cur["version"].fiscal_year
        prev = v2mom_report.prior_year(list(s.scalars(select(V2momVersion.fiscal_year))), stored) if stored else None
        old = s.scalar(select(V2momVersion).where(V2momVersion.fiscal_year == prev)
                       .order_by(V2momVersion.pulled_at.desc(), V2momVersion.id.desc()).limit(1)) if prev else None
        last = v2mom_report.build(s, version=old) if old is not None else None
        return [x for x in (last, cur) if x]

    def _kso_years(s: Session) -> list:
        from ..kso import progress as kso_progress
        cur = kso_progress.build(s)
        if not cur:
            return []
        prev = v2mom_report.prior_year(cur["years"], cur["fw"].fiscal_year)
        last = kso_progress.build(s, prev) if prev else None
        return [x for x in (last, cur) if x]

    @app.get("/performance", response_class=HTMLResponse)
    def performance_page(request: Request, msg: str | None = None, s: Session = Depends(db)):
        guided = gsvc.has_guide(s)
        hints = 0
        if guided:
            linked = set(s.scalars(select(GuideLink.entry_id).where(GuideLink.entry_id.is_not(None))))
            hints = sum(1 for eid, text in s.execute(select(JournalEntry.id, JournalEntry.text).where(
                JournalEntry.ai_read.is_(False))) if eid not in linked and suggest(text)[0])
        return page_html(request, "promo.html", "/performance", pm=gsvc.promo_map(s) if guided else None, hints=hints,
                         ai=gsvc.ai_counts(s), level=gsvc.level(s), guided=guided, msg=msg,
                         v2_years=_v2_years(s), kso_years=_kso_years(s))

    @app.get("/digest", response_class=HTMLResponse)
    def digest_page(request: Request, week: str = "", s: Session = Depends(db)):
        """The week ending on `week` (default today): what it added, and nudges."""
        from .. import digest
        try:
            end = min(date.fromisoformat(week), date.today()) if week else date.today()
        except ValueError:
            end = date.today()
        prev, nxt = end - timedelta(days=7), end + timedelta(days=7)
        weeks = [dict(iso=prev.isoformat(), label="Week before")] + (
            [dict(iso=nxt.isoformat(), label="Week after")] if nxt <= date.today() else [])
        return page_html(request, "digest.html", "/digest", d=digest.build(s, end), weeks=weeks,
                         size_label=SIZE_LABEL)

    def ask_html(request: Request, question: str = "", window: str = "week", answer: str | None = None,
                 error: str | None = None):
        from .. import ask as askmod
        return page_html(request, "ask.html", "/ask", question=question, window=window, windows=askmod.WINDOWS,
                         groups=askmod.preset_groups(), answer=answer, error=error)

    @app.get("/ask", response_class=HTMLResponse)
    def ask_page(request: Request):
        """A question for Claude. Nothing is saved."""
        return ask_html(request)

    @app.post("/ask", response_class=HTMLResponse, dependencies=[Depends(check_csrf)])
    def ask_post(request: Request, question: str = Form("", max_length=500), window: str = Form("week"),
                 s: Session = Depends(db)):
        from .. import ask as askmod
        from ..claude_cli import ClaudeError
        try:
            text = askmod.answer(s, question, window)
        except ClaudeError as exc:
            return ask_html(request, question=question.strip(), window=window, error=str(exc))
        return ask_html(request, question=question.strip(), window=window, answer=text)

    @app.get("/v2mom", response_class=HTMLResponse)
    def v2mom_page(request: Request, s: Session = Depends(db)):
        """Each method of the V2MOM with its measures, the work behind it, and whether it has gone quiet."""
        return page_html(request, "v2mom.html", "/v2mom", r=v2mom_report.build(s),
                         connected=bool(v2mom_conn.load_source(dd)) if personal else False)

    needs_personal = "Setup and Settings only work with your personal notebook."

    def setup_view(request: Request, s: Session, role: str = "", checks=None, skip=(), msg: str | None = None):
        try:
            guides = read_workbook()
        except GuideFormatError as exc:
            guides, msg = [], f"The leveling guide won't open. {exc}"
        lv = gsvc.level(s)
        return page_html(request, "setup.html", "/setup", guides=guides, lv=lv, msg=msg, checks=checks, skip=skip,
                         g=find_role(guides, role or (lv or {}).get("role", "")), v2mom=v2mom_conn.load_source(dd),
                         here="/setup")

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page(request: Request, role: str = "", msg: str | None = None, s: Session = Depends(db)):
        """The fallback for `/setup` in Claude Code: your role and level, the V2MOM, and a check of the connections."""
        if not personal:
            return back(needs_personal)
        return setup_view(request, s, role, msg=msg)

    @app.post("/setup/level", dependencies=[Depends(check_csrf)])
    def setup_level(role: str = Form("", max_length=200), grade: int = Form(...), s: Session = Depends(db)):
        if not personal:
            return back(needs_personal)
        try:
            g = find_role(read_workbook(), role)
            if g is None:
                raise ValueError("Choose your role first.")
            with _write_lock:
                pick, _r, lv = choose_level(s, g, grade)
        except ValueError as exc:
            return back(str(exc), "/setup")
        return back(f"Saved: {g['name']}, Grade {grade}" + (f" ({pick['title']})" if pick["title"] else "") + ". "
                    + (f"Next level: Grade {lv['next']}." if lv["next"] else "That's the top of this path."), "/setup")

    @app.post("/setup/check", dependencies=[Depends(check_csrf)])
    def setup_check(request: Request, on: list[str] = Form([]), s: Session = Depends(db)):
        """Runs every check (reads only); the connectors not ticked are skipped."""
        if not personal:
            return back(needs_personal)
        skip = {"google", "slack", "github"} - set(on)
        return setup_view(request, s, checks=run_checks(dd, skip), skip=skip)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, msg: str | None = None, s: Session = Depends(db)):
        if not personal:
            return back(needs_personal)
        prof = gsvc.profile(s)
        note = prof.get("responsibilities")
        return page_html(request, "settings.html", "/settings", lv=gsvc.level(s), msg=msg,
                         responsibilities=note.strip() if isinstance(note, str) else "",
                         friday_case=prof.get("friday_case") is True)

    @app.post("/settings", dependencies=[Depends(check_csrf)])
    def settings_save(responsibilities: str = Form(""), friday_case: str = Form("")):
        """Save the responsibilities note and the Friday case switch. An empty note clears it; an unticked box is off."""
        if not personal:
            return back(needs_personal)
        text = responsibilities.replace("\r\n", "\n").strip()[:gsvc.RESPONSIBILITIES_MAX]  # a browser sends CRLF
        with _write_lock:
            gsvc.save_profile(dd.root, responsibilities=text, friday_case=friday_case == "yes")
        return back("Saved.", "/settings")

    @app.get("/kso", response_class=HTMLResponse)
    def kso_page(request: Request, fy: str = "", msg: str | None = None, s: Session = Depends(db)):
        """This year's KSOs: how each is measured, and how you stand (plain math from your V2MOM)."""
        from ..kso import progress as kso_progress
        return page_html(request, "kso.html", "/kso", r=kso_progress.build(s, fy or None), msg=msg, sync=sync_view(s))

    @app.post("/kso/estimate", dependencies=[Depends(check_csrf)])
    def kso_estimate(request: Request):
        """Have Claude estimate this year's KSO ratings now, in the background."""
        return start_sync(request, "kso", to="/kso")

    def _kso_fw(s: Session, fy: str):
        from ..kso import framework as kso_fw
        return kso_fw.get(s, fy) if fy else None

    @app.post("/kso/rating", dependencies=[Depends(check_csrf)])
    def kso_rating(fy: str = Form(""), kso: str = Form(""), rating: str = Form(""), s: Session = Depends(db)):
        from ..kso import progress as kso_progress
        fw = _kso_fw(s, fy)
        if fw is None:
            return back("Those KSOs aren't here any more.", "/kso")
        try:
            with _write_lock:
                kso_progress.set_rating(s, fw, kso, rating)
        except ValueError as exc:
            return back(str(exc), f"/kso?fy={quote(fy)}")
        return back(f"KSO {kso}: " + (f"rated {rating}." if rating else "rating cleared."), f"/kso?fy={quote(fy)}")

    @app.post("/kso/map", dependencies=[Depends(check_csrf)])
    def kso_map(fy: str = Form(""), method_id: int = Form(...), component: str = Form(""), s: Session = Depends(db)):
        from ..kso import framework as kso_fw, map as kso_map_mod
        fw = _kso_fw(s, fy)
        m = s.get(V2momMethod, method_id)
        if fw is None or m is None or component not in ("", *(c["key"] for c in kso_fw.components(fw))):
            return back("That V2MOM method or KSO part isn't here any more.", "/kso")
        with _write_lock:
            kso_map_mod.set_pick(s, fy, method_id, component)
        return back(f"{m.label} now counts toward " + (f"KSO {component}." if component else "no KSO part."),
                    f"/kso?fy={quote(fy)}")

    @app.get("/v2mom/{mid}", response_class=HTMLResponse)
    def v2mom_method_page(request: Request, mid: int, s: Session = Depends(db)):
        """The wins and records linked to one method, newest first."""
        m = s.get(V2momMethod, mid)
        if m is None:
            return HTMLResponse("Not found", status_code=404)
        cur = v2mom_store.current(s)
        ev = v2mom_links.evidence(s).get(mid, dict(entries=[], wins=[]))
        return page_html(request, "v2mom_method.html", "/v2mom", m=m,
                         current=m.active and cur is not None and m.version_id == cur.id, wins=ev["wins"],
                         entries=ev["entries"], kind_label=dict(SHEET_KIND), source_label=SOURCE_LABEL,
                         size_label=SIZE_LABEL)

    @app.get("/impact/{key}", response_class=HTMLResponse)
    def impact_page(request: Request, key: str, window: str = "all", s: Session = Depends(db)):
        """The records behind one impact number, grouped by piece of work."""
        if key not in activities.KEYS:
            return HTMLResponse("Not found", status_code=404)
        window = window if window in ("half", "year", "all") else "all"
        groups = activities.records(s, key, window)
        return page_html(request, "impact.html", "/performance", label=activities.LABEL[key], key=key, window=window,
                         groups=groups)

    @app.post("/sheet/{eid}/activity", dependencies=[Depends(check_csrf)])
    def sheet_activity(request: Request, eid: int, activity: str = Form(""), ret: str = Form(""),
                       s: Session = Depends(db)):
        """Set what this record counts toward (or nothing); Claude won't change it after."""
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e and (activity in activities.KEYS or activity == ""):
                e.activity, e.activity_fixed, e.activity_read = activity, True, True
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/performance/write", dependencies=[Depends(check_csrf)])
    def promo_write(request: Request, start: str = Form(""), end: str = Form(""), name: str = Form("", max_length=80),
                    example: str = Form(""), s: Session = Depends(db)):
        """Start writing a draft in the background; the page shows progress per section. Too little data to write
        from is said here, before Claude is asked."""
        from ..promo import evidence as pe, write as pw
        if not personal:
            return back("Writing the case only works with your personal notebook.", "/performance/case")
        lo, hi = pw.default_window()
        try:
            start, end = date.fromisoformat(start or lo).isoformat(), date.fromisoformat(end or hi).isoformat()
        except ValueError:
            return back("Those dates don't look right; use the date pickers.", "/performance/case")
        if msg := pw.shortage(pe.build(s, start, end)[0], start, end):
            if request.headers.get("x-sync") == "1":
                return JSONResponse({"started": False, "message": msg}, status_code=409)
            return back(msg, "/performance/case")
        name = " ".join(name.split()) or pw.load_name(dd) or "the candidate"
        pw.save_name(dd, name)
        pw.save_example(dd, example)
        labels = [f"Write {h}" for _k, h, *_r in pw.SECTIONS]
        return started_reply(request, jobs.start("promo", labels, lambda j: syncs.run_promo(j, Session_, start, end, name)),
                             "Writing your performance case. This takes a minute or two; refresh to see it.",
                             "A draft is already being written.", "/performance/case")

    @app.post("/performance/case/{vid}/edit/{key}", dependencies=[Depends(check_csrf)])
    def promo_edit(vid: int, key: str, text: str = Form("", max_length=20_000), s: Session = Depends(db)):
        """Save your wording of one section as a new draft (one sentence per line; [n] keeps its sources)."""
        from ..promo import write as pw
        from ..storage.models import PromoVersion
        v = s.get(PromoVersion, vid)
        if v is None:
            return back("That draft is gone.", "/performance/case")
        with _write_lock:
            try:
                new = pw.edit_section(s, v, key, text)
            except KeyError:
                return back("That section isn't in this draft.", f"/performance/case/{vid}")
        return RedirectResponse(f"/performance/case/{new.id}#sec-{key}", status_code=303)

    @app.post("/performance/case/{vid}/rewrite/{key}", dependencies=[Depends(check_csrf)])
    def promo_rewrite(request: Request, vid: int, key: str, confirm: str = Form(""), s: Session = Depends(db)):
        """Have Claude redo one section, in the background; your edited sections need a confirm first."""
        from ..storage.models import PromoSection
        if not personal:
            return back("Writing the case only works with your personal notebook.", "/performance/case")
        sec = s.scalar(select(PromoSection).where(PromoSection.version_id == vid, PromoSection.key == key))
        if sec is None:
            return back("That section isn't in this draft.", f"/performance/case/{vid}")
        if sec.edited and confirm != "yes":
            msg = f"You've edited {sec.heading}. Tick “Replace my edits” to have Claude rewrite it anyway."
            if request.headers.get("x-sync") == "1":
                return JSONResponse({"started": False, "message": msg}, status_code=409)
            return back(msg, f"/performance/case/{vid}")
        return started_reply(request, jobs.start("promo", [f"Rewrite {sec.heading}"],
                                                 lambda j: syncs.run_rewrite(j, Session_, vid, key)),
                             "Rewriting it now; refresh in a minute.", "A draft is already being written.", "/performance/case")

    @app.post("/performance/case/{vid}/gdoc", dependencies=[Depends(check_csrf)])
    def promo_gdoc(request: Request, vid: int, s: Session = Depends(db)):
        """Send this draft to Google Docs in My Drive: a copy with sources, and a clean one for sharing."""
        from ..storage.models import PromoVersion
        if not personal:
            return back("Sending to Google Docs only works with your personal notebook.", "/performance/case")
        if s.get(PromoVersion, vid) is None:
            return back("That draft is gone.", "/performance/case")
        return started_reply(request, jobs.start("promo", syncs.GDOC_STEPS, lambda j: syncs.run_gdoc(j, Session_, dd, vid)),
                             "Sending it to Google Docs; refresh in a minute.", "Something is already running.",
                             f"/performance/case/{vid}")

    @app.get("/performance/compare", response_class=HTMLResponse)
    def promo_compare(request: Request, a: int = 0, b: int = 0, s: Session = Depends(db)):
        """Two drafts side by side, section by section: what was removed and what was added."""
        from ..promo import write as pw
        from ..storage.models import PromoSection, PromoVersion
        va, vb = s.get(PromoVersion, a), s.get(PromoVersion, b)
        if va is None or vb is None:
            return back("Pick two drafts to compare.", "/performance/case")
        stored = {v.id: list(s.scalars(select(PromoSection).where(PromoSection.version_id == v.id)
                                       .order_by(PromoSection.position))) for v in (va, vb)}
        by = {vid: {x.key: x for x in rows_} for vid, rows_ in stored.items()}
        # A saved draft keeps its own headings, including ones from before the PAT template.
        order = []
        for v in (va, vb):
            for sec in stored[v.id]:
                if sec.key not in order:
                    order.append(sec.key)
        rows = []
        for key in order:
            sa, sb = by[va.id].get(key), by[vb.id].get(key)
            rows.append(dict(heading=(sa or sb).heading,
                             diff=pw.compare(sa.sentences if sa else [], sb.sentences if sb else [])))
        return page_html(request, "promo_compare.html", "/performance", a=va, b=vb, rows=rows)

    @app.get("/performance/case", response_class=HTMLResponse)
    @app.get("/performance/case/{vid}", response_class=HTMLResponse)
    def promo_case(request: Request, vid: int | None = None, msg: str | None = None, s: Session = Depends(db)):
        from ..promo import write as pw
        from ..storage.models import PromoSection, PromoVersion
        versions = list(s.scalars(select(PromoVersion).order_by(PromoVersion.id.desc())))
        v = s.get(PromoVersion, vid) if vid else (versions[0] if versions else None)
        if vid and v is None:
            return HTMLResponse("Not found", status_code=404)
        sections = list(s.scalars(select(PromoSection).where(PromoSection.version_id == v.id)
                                  .order_by(PromoSection.position))) if v else []
        cited = sorted({n for sec in sections for x in sec.sentences for n in x["sources"]})
        by_n = {p["n"]: p for p in (v.evidence if v else [])}
        lo, hi = pw.default_window()
        return page_html(request, "promo_case.html", "/performance", v=v, versions=versions, sections=sections,
                         sources=[by_n[n] for n in cited if n in by_n], latest=versions[0].id if versions else None,
                         texts={x.key: pw.to_text(x.sentences) for x in sections},
                         flagged=sum(1 for sec in sections for x in sec.sentences if not x["valid"]), start=lo,
                         end=hi, name=pw.load_name(dd), example=gsvc.profile(s).get("example", ""), guided=gsvc.has_guide(s), msg=msg)

    def _promo_redirect(request: Request, rest: str = "") -> RedirectResponse:
        dest = "/performance" + (f"/{rest}" if rest else "")
        if request.url.query:
            dest += "?" + request.url.query
        return RedirectResponse(dest, status_code=308)

    @app.get("/promo")
    def promo_redirect(request: Request):
        """Old address of the performance map. The rest of a /promo path, and its query, come along."""
        return _promo_redirect(request)

    @app.get("/promo/{rest:path}")
    def promo_redirect_rest(request: Request, rest: str):
        return _promo_redirect(request, rest)

    @app.get("/performance/export")
    def promo_export(s: Session = Depends(db)):
        pm = gsvc.promo_map(s) if gsvc.has_guide(s) else None
        if pm is None:
            return back("There's no Performance map to download yet; see the Performance page.", "/performance")
        name = f"promo-case-{date.today().isoformat()}.md"
        return Response(promo_markdown(pm), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/wins/export")
    def win_export(year: int | None = None, s: Session = Depends(db)):
        year = year or date.today().year
        return Response(wins_markdown(year_wins(s, year), year), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="my-wins-{year}.md"'})

    @app.get("/export/everything")
    def export_everything(s: Session = Depends(db)):
        name = f"coffeeshop-notebook-{date.today().isoformat()}.zip"
        return Response(notebook_zip(s), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/theme", dependencies=[Depends(check_csrf)])
    def set_theme(theme: str = Form(...), next: str = Form("/")):
        local = next.startswith("/") and not next.startswith("//") and "\\" not in next  # never another site
        resp = back(to=next if local else "/")
        resp.set_cookie("theme", "light" if theme == "light" else "dark", max_age=31_536_000,
                        httponly=True, samesite="strict")
        return resp

    app.state.csrf_token = csrf_token
    return app
