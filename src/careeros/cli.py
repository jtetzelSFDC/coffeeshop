"""careeros CLI: your personal notebook, its syncs and leveling guide, and a practice notebook of made-up data."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Optional

import typer

from .config import PERSONAL_DIR, DataDir, NotDemoData, resolve
from .storage.db import init_db, make_engine, make_session_factory

app = typer.Typer(no_args_is_help=True)
demo_app = typer.Typer(no_args_is_help=True, help="The practice notebook (made-up data)")
app.add_typer(demo_app, name="demo")
DataOpt = typer.Option(None, "--data-dir", help="Notebook folder (default: CAREEROS_DATA_DIR or your notebook)")


@demo_app.command("seed")
def demo_seed(data_dir: Optional[str] = DataOpt) -> None:
    """Create a practice notebook with a week of made-up records, a few wins, and a tiny made-up leveling guide."""
    from .fixtures import demo as fx
    os.umask(0o077)
    dd = resolve(data_dir, demo=True)
    try:
        dd.init_demo()
    except NotDemoData as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    engine = make_engine(dd.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        n = fx.seed(s)
    typer.echo(f"Practice notebook ready at {dd.root} ({n['records']} records, {n['wins']} wins). "
               f"Start it with:  uv run careeros serve --data-dir {dd.root}")


sync_app = typer.Typer(no_args_is_help=True, help="Pull in Slack and Google")
app.add_typer(sync_app, name="sync")


@sync_app.command("all")
def sync_all_cmd(force: bool = typer.Option(False, "--force", help="Run even if already synced since the last "
                                                                   "scheduled time (8 AM or 6 PM)"),
                 data_dir: Optional[str] = DataOpt) -> None:
    """Back up, then run the Slack and Google syncs (what the scheduled task runs). Logs go to logs/ in the notebook."""
    from . import sync_all
    os.umask(0o077)
    dd = resolve(data_dir)
    if not dd.is_personal:
        typer.echo("Syncing only works with your personal notebook.")
        raise typer.Exit(1)
    code = sync_all.run(dd, force=force)
    typer.echo("Synced." if code == 0 else "Another sync is already running." if code == sync_all.LOCKED
               else "Something didn't sync; see the notification or logs/ in your notebook.")
    raise typer.Exit(code)


schedule_app = typer.Typer(no_args_is_help=True, help="Keep the app running and sync on a schedule (macOS)")
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("install")
def schedule_install(data_dir: Optional[str] = DataOpt) -> None:
    """Start the app at login (restarting it if it stops), sync at 8 AM, 6 PM, and login, and show the digest Fridays at noon."""
    from . import schedule
    dd = resolve(data_dir)
    if not dd.is_personal:
        typer.echo("The schedule is only for your personal notebook.")
        raise typer.Exit(1)
    try:
        installed = schedule.install(dd)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    for p in installed:
        typer.echo(f"Installed {p}")
    typer.echo("If you started the app yourself in a Terminal, stop it (Ctrl+C); the scheduled one takes over.")


@schedule_app.command("uninstall")
def schedule_uninstall() -> None:
    """Stop and remove the scheduled tasks. Nothing else is touched."""
    from . import schedule
    removed = schedule.uninstall()
    typer.echo("\n".join(f"Removed {p}" for p in removed) or "Nothing was installed.")


@schedule_app.command("status")
def schedule_status(data_dir: Optional[str] = DataOpt) -> None:
    """Whether each scheduled task is on, and the last sync log line."""
    from . import schedule
    typer.echo("\n".join(schedule.status(resolve(data_dir))))


backup_app = typer.Typer(no_args_is_help=True, help="Daily copies of your notebook")
app.add_typer(backup_app, name="backup")


@backup_app.command("now")
def backup_now(data_dir: Optional[str] = DataOpt) -> None:
    """Copy the notebook into backups/ now (safe while the app is running), then drop copies past their keep date."""
    from .backup import make_backup, prune
    os.umask(0o077)
    dd = resolve(data_dir)
    try:
        dd.require_known()
    except NotDemoData as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    path = make_backup(dd)
    n = prune(dd)
    typer.echo(f"Backed up to {path}" + (f" (removed {n} older cop{'y' if n == 1 else 'ies'})" if n else ""))


@backup_app.command("list")
def backup_list(data_dir: Optional[str] = DataOpt) -> None:
    """The copies in backups/, newest first."""
    from .backup import backups
    dd = resolve(data_dir)
    found = backups(dd)
    if not found:
        typer.echo("No backups yet. Run: uv run careeros backup now")
    for d, p in reversed(found):
        typer.echo(f"{p.name}  {p.stat().st_size // 1024} KB")


notebook_app = typer.Typer(no_args_is_help=True, help="Your personal notebook")
app.add_typer(notebook_app, name="notebook")


@notebook_app.command("init")
def notebook_init(data_dir: Optional[str] = typer.Option(None, "--data-dir", help="Default: ~/Library/Application Support/CareerOS")) -> None:
    """Create your real, permanent notebook (journal only). Imports of work data stay off."""
    os.umask(0o077)
    dd = DataDir(__import__("pathlib").Path(data_dir).expanduser()) if data_dir else DataDir(PERSONAL_DIR)
    try:
        dd.init_personal()
    except NotDemoData as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    with_db = make_engine(dd.db)
    init_db(with_db)
    typer.echo(f"Your notebook is ready at {dd.root}")
    typer.echo("Start it with:  uv run careeros serve" + (f" --data-dir {dd.root}" if data_dir else ""))


guide_app = typer.Typer(no_args_is_help=True, help="Your leveling guide")
app.add_typer(guide_app, name="guide")


@guide_app.command("import")
def guide_import(file: str = typer.Argument(..., help="Leveling guide CSV export"),
                 data_dir: Optional[str] = DataOpt) -> None:
    """Load (or refresh) the leveling guide. Links you've already made are kept."""
    from .guide.parse import GuideFormatError
    from .guide.service import import_guide
    os.umask(0o077)
    dd = resolve(data_dir)
    try:
        dd.require_known()
    except NotDemoData as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    engine = make_engine(dd.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        try:
            r = import_guide(s, file)
        except (OSError, GuideFormatError) as exc:
            typer.echo(f"Couldn't load the guide: {exc}")
            raise typer.Exit(1)
    typer.echo(f"Guide loaded into {dd.root}: {r['added']} new, {r['updated']} changed, "
               f"{r['retired']} no longer in the guide.")


@guide_app.command("review")
def guide_review(redo: bool = typer.Option(False, "--redo", help="Also re-read records Claude already read "
                                                                   "(rows you marked reviewed are never touched)"),
                 limit: Optional[int] = typer.Option(None, help="Only read this many records (newest first)"),
                 data_dir: Optional[str] = DataOpt) -> None:
    """Have Claude read every record against the leveling guide: guide links, type fixes, and drafted wins (marked AI)."""
    from .claude_cli import ClaudeError
    from .guide.ai_review import pending, review
    dd, s = _open_personal(data_dir, "The Claude review")
    n = len(pending(s, redo)[:limit])
    if not n:
        typer.echo("Nothing to read: Claude has already read every record.")
        return
    typer.echo(f"Claude is reading {n} records against the leveling guide. This takes a few minutes.")
    try:
        r = review(s, redo=redo, limit=limit, progress=lambda i, t: typer.echo(f"  batch {i} of {t} done"))
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Read {r['read']} records: {r['links']} guide links, "
               + (f"{r['v2mom']} V2MOM links, " if r["v2mom"] else "") + f"{r['wins']} drafted wins, "
               f"{r['kinds']} type changes, all marked AI."
               + (f" {r['failed']} couldn't be read; run this again to retry them." if r["failed"] else ""))


@guide_app.command("group")
def guide_group(dry_run: bool = typer.Option(False, "--dry-run", help="Show the groups Claude would make; save nothing"),
                redo: bool = typer.Option(False, "--redo", help="Also regroup records Claude already grouped "
                                                                "(never ones you grouped or split yourself)"),
                limit: Optional[int] = typer.Option(None, help="Only this many records (oldest first)"),
                data_dir: Optional[str] = DataOpt) -> None:
    """Group records that describe the same piece of work, so it counts once on the Promo map (marked AI)."""
    from .claude_cli import ClaudeError
    from .guide import work
    dd, s = _open_personal(data_dir, "Grouping")
    scratch = None
    if dry_run:  # try it on a copy, so the app can keep saving to the real notebook for the minutes Claude takes
        s.close()
        scratch = tempfile.TemporaryDirectory()
        with closing(sqlite3.connect(dd.db)) as src, closing(sqlite3.connect(Path(scratch.name) / "dry.db")) as dst:
            src.backup(dst)
        s = make_session_factory(make_engine(Path(scratch.name) / "dry.db"))()
    n = len(work.pending(s, redo)[:limit])
    if not n:
        typer.echo("Nothing to group.")
        return
    typer.echo(f"Claude is grouping {n} records, oldest first. This takes a few minutes.")
    try:
        r = work.group(s, everything=redo, limit=limit, dry_run=dry_run,
                       progress=lambda i, t: typer.echo(f"  batch {i} of {t} done"))
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    finally:
        s.close()
        if scratch:
            scratch.cleanup()
    if dry_run:
        for title, texts in sorted(r.get("groups", {}).items(), key=lambda kv: -len(kv[1])):
            typer.echo(f"\n{title} ({len(texts)} records)")
            for t in texts:
                typer.echo(f"  - {t[:100]}")
        typer.echo("\nDry run: nothing was saved.")
        return
    typer.echo(f"Grouped {r['read']} records: {r['new']} pieces of work started, {r['joined']} records joined one, "
               f"{r['alone']} on their own." + (f" {r['failed']} couldn't be read; run again." if r["failed"] else ""))


@guide_app.command("activities")
def guide_activities(redo: bool = typer.Option(False, "--redo", help="Also re-tag records Claude already tagged "
                                                                   "(never ones you set yourself)"),
                     limit: Optional[int] = typer.Option(None, help="Only this many records (oldest first)"),
                     data_dir: Optional[str] = DataOpt) -> None:
    """Tag each record with the activity it shows (deployment, sandbox refresh, …) for the impact numbers."""
    from .claude_cli import ClaudeError
    from .guide import activities
    dd, s = _open_personal(data_dir, "Impact tagging")
    n = len(activities.pending(s, redo)[:limit])
    if not n:
        typer.echo("Nothing to tag.")
        return
    typer.echo(f"Claude is tagging {n} records. This takes a minute or two.")
    try:
        r = activities.tag(s, everything=redo, limit=limit,
                           progress=lambda i, t: typer.echo(f"  batch {i} of {t} done"))
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Tagged {r['read']} records, {r['tagged']} with an activity."
               + (f" {r['failed']} couldn't be read; run again." if r["failed"] else ""))
    for c in activities.counts(s):
        typer.echo(f"  {c['all']:>4} {c['label']} ({c['year']} this year)")


promo_app = typer.Typer(no_args_is_help=True, help="Your promotion case")
app.add_typer(promo_app, name="promo")


@promo_app.command("write")
def promo_write_cmd(start: Optional[str] = typer.Option(None, help="First day, YYYY-MM-DD (default: a year ago)"),
                    end: Optional[str] = typer.Option(None, help="Last day, YYYY-MM-DD (default: today)"),
                    name: Optional[str] = typer.Option(None, help="Who it's about (default: the saved name)"),
                    data_dir: Optional[str] = DataOpt) -> None:
    """Have Claude draft the promotion case from your notebook; open it at /promo/case."""
    from .claude_cli import ClaudeError
    from .promo import write as pw
    dd, s = _open_personal(data_dir, "Writing the case")
    lo, hi = pw.default_window()
    who = name or pw.load_name(dd) or "the candidate"
    if name:
        pw.save_name(dd, name)
    typer.echo(f"Claude is writing the case about {who}, from {start or lo} to {end or hi}. A minute or two.")
    try:
        v = pw.write_case(s, start=start or lo, end=end or hi, name=who,
                          on_section=lambda k, d: typer.echo(f"  {k}: {d}"))
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    from sqlalchemy import select
    from .storage.models import PromoSection
    secs = list(s.scalars(select(PromoSection).where(PromoSection.version_id == v.id)))
    flagged = sum(1 for sec in secs for x in sec.sentences if not x["valid"])
    typer.echo(f"Draft {v.id} saved" + (f", {flagged} sentences to check" if flagged else ", every sentence sourced")
               + f". Open http://127.0.0.1:8765/promo/case/{v.id}")


slack_app = typer.Typer(no_args_is_help=True, help="Bring Slack canvases into your notebook (read-only)")
app.add_typer(slack_app, name="slack")


def _slack_import(dd: DataDir, s, raw: str, fallback_day: Optional[str] = None) -> None:
    from .claude_cli import ClaudeError
    from .slack.classify import classify
    from .slack.importer import import_items
    from .slack.parse import CanvasFormatError, parse_canvas
    try:
        r = import_items(s, parse_canvas(raw, fallback_day), classify)
    except (CanvasFormatError, ClaudeError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Slack: {r['added']} added ({r['meeting']} meetings, {r['conversation']} conversations, "
               f"{r['document']} documents, {r['task']} tasks, {r['note']} other), {r['skipped']} already here.")


@slack_app.command("import")
def slack_import(file: str = typer.Argument(..., help="Canvas markdown or canvas JSON, or - for stdin"),
                 day: Optional[str] = typer.Option(None, help="Date for items the canvas doesn't date, YYYY-MM-DD"),
                 data_dir: Optional[str] = DataOpt) -> None:
    """Import a Slack Work Activity Tracker or contributions canvas. Claude sorts each item into a kind."""
    import sys
    dd, s = _open_personal(data_dir, "Slack import")
    raw = sys.stdin.read() if file == "-" else open(file, encoding="utf-8").read()
    _slack_import(dd, s, raw, day)


@slack_app.command("connect")
def slack_connect(canvas: str = typer.Argument(..., help="Link to, or ID of, your Slack Work Activity Tracker canvas"),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Remember which canvas the Sync Slack button reads."""
    from .slack.importer import save_canvas_id
    dd, _ = _open_personal(data_dir, "Slack sync")
    try:
        typer.echo(f"Saved canvas {save_canvas_id(dd, canvas)}. Now run: uv run careeros slack pull")
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)


@slack_app.command("pull")
def slack_pull(data_dir: Optional[str] = DataOpt) -> None:
    """Read the connected canvas through Claude Code's Slack connector and import new items (the Sync Slack button)."""
    from .claude_cli import ClaudeError
    from .slack.connector import fetch_canvas
    from .slack.importer import load_canvas_id
    dd, s = _open_personal(data_dir, "Slack sync")
    cid = load_canvas_id(dd)
    if not cid:
        typer.echo("No canvas connected yet. Run: uv run careeros slack connect <canvas link>")
        raise typer.Exit(1)
    try:
        raw = fetch_canvas(cid)
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    _slack_import(dd, s, raw)


v2mom_app = typer.Typer(no_args_is_help=True, help="Your V2MOM, read from its PDF or a Google Doc (read-only)")
app.add_typer(v2mom_app, name="v2mom")


@v2mom_app.command("connect")
def v2mom_connect(doc: str = typer.Argument(..., help="The PDF downloaded from the V2MOM app, or a link to the "
                                                      "Google Doc you pasted your V2MOM into"),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Remember where your V2MOM is: its PDF (the newest V2MOM PDF in that folder is read each time) or a Doc."""
    from .v2mom.connector import save_source
    dd, _ = _open_personal(data_dir, "V2MOM sync")
    try:
        src = save_source(dd, doc)
        typer.echo(f"Saved {'PDF' if src['kind'] == 'pdf' else 'Doc'} {src['value']}. "
                   "Now run: uv run careeros v2mom sync")
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)


@v2mom_app.command("sync")
def v2mom_sync(data_dir: Optional[str] = DataOpt) -> None:
    """Read the connected PDF or Doc and update your V2MOM's methods and measures (the Sync V2MOM button)."""
    import threading
    from .web import syncs
    from .web.jobs import Job
    dd, s = _open_personal(data_dir, "V2MOM sync")
    s.close()
    job = Job(syncs.V2MOM_STEPS)
    syncs.run_v2mom(job, make_session_factory(make_engine(dd.db)), threading.Lock(), dd)
    for st in job.steps:
        typer.echo(f"{st['label']}: {st['state']}" + (f" ({st['detail']})" if st["detail"] else ""))
    typer.echo(job.message)
    if job.state in ("error", "partial"):
        raise typer.Exit(1)


@v2mom_app.command("tag")
def v2mom_tag(everything: bool = typer.Option(False, "--all", help="Every record, not just the last 90 days"),
              data_dir: Optional[str] = DataOpt) -> None:
    """Have Claude link records it already read to the V2MOM methods they advance (marked AI). Records it has
    read against the V2MOM, and ones whose methods you set, are skipped, so running it again only does the rest."""
    from datetime import date, timedelta
    from .claude_cli import ClaudeError
    from .v2mom import links
    dd, s = _open_personal(data_dir, "V2MOM tagging")
    todo = links.pending(s, "" if everything else (date.today() - timedelta(days=90)).isoformat())
    if not todo:
        typer.echo("Nothing to read: every record has been read against the V2MOM.")
        return
    typer.echo(f"Claude is reading {len(todo)} records against your V2MOM. This takes a few minutes.")
    try:
        r = links.tag(s, todo, progress=lambda i, t: typer.echo(f"  batch {i} of {t} done"))
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Read {r['read']} records: {r['links']} V2MOM links, all marked AI."
               + (f" {r['failed']} couldn't be read; run this again to retry them." if r["failed"] else ""))


kso_app = typer.Typer(no_args_is_help=True, help="Your KSOs: how you're rated, read from the KSO deck and guides")
app.add_typer(kso_app, name="kso")


@kso_app.command("connect")
def kso_connect(deck: list[str] = typer.Option([], "--deck", help="The KSO framework deck (Google Slides link or id)"),
                canvas: list[str] = typer.Option([], "--canvas", help="A KSO guide or FAQ Slack canvas (link or id)"),
                track: str = typer.Option("Delivery", help="Your KSO track, as the material names it"),
                manager: bool = typer.Option(False, "--manager", help="Include people-manager-only components"),
                data_dir: Optional[str] = DataOpt) -> None:
    """Read this year's KSOs (each year, or when the material changes). With no links, re-reads the ones saved."""
    from .claude_cli import ClaudeError
    from .kso import framework, map as kmap
    dd, s = _open_personal(data_dir, "KSOs")
    try:
        src = framework.sources(deck, canvas, track, manager) if deck or canvas else framework.load_sources(dd)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    if not src:
        typer.echo("Give the KSO deck and guide canvases: uv run careeros kso connect --deck <link> --canvas <link>")
        raise typer.Exit(1)
    typer.echo("Reading the KSO material and having Claude sort it. This takes a few minutes.")
    try:
        fw = framework.save(s, framework.parse(framework.fetch(src), src["track"], src["manager"]), src)
        framework.save_sources(dd, src)
        typer.echo(_kso_summary(fw))
        if framework.v2mom_year(s) not in (None, fw.fiscal_year):
            typer.echo(f"Your V2MOM is still for {framework.v2mom_year(s)}; its methods get matched to {fw.fiscal_year} "
                       "once you sync the new V2MOM.")
            return
        r = kmap.suggest(s, fw)
        typer.echo(f"Matched {r['mapped']} V2MOM methods to KSO components (marked AI); {r['none']} fit none.")
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)


@kso_app.command("map")
def kso_map(redo: bool = typer.Option(False, "--redo", help="Also redo Claude's earlier matches (yours stay)"),
            data_dir: Optional[str] = DataOpt) -> None:
    """Have Claude match V2MOM methods to KSO components (only ones not matched yet, unless --redo)."""
    from .claude_cli import ClaudeError
    from .kso import framework, map as kmap
    dd, s = _open_personal(data_dir, "KSOs")
    fw = framework.for_current(s)
    if fw is None:
        typer.echo("No KSOs yet. Run: uv run careeros kso connect --deck <link> --canvas <link>")
        raise typer.Exit(1)
    try:
        r = kmap.suggest(s, fw, redo=redo)
    except ClaudeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Matched {r['mapped']} V2MOM methods (marked AI); {r['none']} fit none.")


@kso_app.command("show")
def kso_show(data_dir: Optional[str] = DataOpt) -> None:
    """This year's KSOs, their components, and which V2MOM methods count toward each."""
    from .kso import framework, map as kmap
    dd, s = _open_personal(data_dir, "KSOs")
    fw = framework.for_current(s)
    if fw is None:
        typer.echo("No KSOs yet. Run: uv run careeros kso connect --deck <link> --canvas <link>")
        raise typer.Exit(1)
    typer.echo(_kso_summary(fw))
    picks = kmap.by_component(s, fw)
    for c in framework.components(fw):
        ms = ", ".join(f"{m.label}{' (AI)' if p.by_ai else ''}" for m, p in picks[c["key"]]) or "no V2MOM goal yet"
        typer.echo(f"  {c['key']} {c['name']}: {ms}")


@kso_app.command("estimate")
def kso_estimate(data_dir: Optional[str] = DataOpt) -> None:
    """Have Claude estimate this year's KSO ratings now (it also runs monthly with the sync; marked AI)."""
    import threading
    from .web import syncs
    from .web.jobs import Job
    dd, s = _open_personal(data_dir, "KSOs")
    s.close()
    job = Job(syncs.KSO_STEPS)
    syncs.run_kso(job, make_session_factory(make_engine(dd.db)), threading.Lock())
    for st in job.steps:
        typer.echo(f"{st['label']}: {st['state']}" + (f" ({st['detail']})" if st["detail"] else ""))
    typer.echo(job.message)
    if job.state in ("error", "partial"):
        raise typer.Exit(1)


def _kso_summary(fw) -> str:
    pay = ", ".join(f"{r}={p:g}%" for r, p in fw.data["payout"].items())
    ksos = "; ".join(f"KSO {k['key']} {k['name']} ({k['weight']:g}%, {len(k['components'])} parts)"
                     for k in fw.data["ksos"])
    return f"{fw.fiscal_year} {fw.track}: {ksos}. Payout by rating: {pay}."


calendar_app = typer.Typer(no_args_is_help=True, help="Pull Google Calendar meetings into your notebook (read-only)")
app.add_typer(calendar_app, name="calendar")


def _open_personal(data_dir: Optional[str], what: str = "Calendar sync"):
    from .google import calendar as gcal  # noqa: F401
    os.umask(0o077)
    dd = resolve(data_dir)
    if not dd.is_personal:
        typer.echo(f"{what} only works with your personal notebook (run `careeros notebook init`).")
        raise typer.Exit(1)
    engine = make_engine(dd.db)
    init_db(engine)
    return dd, make_session_factory(engine)()


@calendar_app.command("skip")
def calendar_skip(text: Optional[str] = typer.Argument(None, help="Title text to skip, e.g. \"Team Daily Standup\""),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Never bring in meetings whose title contains TEXT, and remove the ones already here. No TEXT lists the rules."""
    from .storage.removal import add_skip_rule, skip_patterns
    from .storage.models import SkipRule
    from sqlalchemy import select
    dd, s = _open_personal(data_dir, "Calendar rules")
    if not text:
        rules = list(s.scalars(select(SkipRule.pattern).where(SkipRule.source == "calendar")))
        typer.echo("\n".join(f"Skipping meetings titled with: {p}" for p in rules) or "No skip rules yet.")
        return
    n = add_skip_rule(s, text)
    typer.echo(f"Calendar sync will skip meetings whose title contains \"{' '.join(text.split())}\". "
               f"Removed {n} already in the notebook (see Removed in the Intake Review Queue).")


@calendar_app.command("unskip")
def calendar_unskip(text: str = typer.Argument(..., help="The rule's text, exactly as listed by `calendar skip`"),
                    data_dir: Optional[str] = DataOpt) -> None:
    """Stop skipping meetings with this title text. Removed meetings stay removed until you restore them."""
    from .storage.removal import drop_skip_rule
    dd, s = _open_personal(data_dir, "Calendar rules")
    typer.echo("Rule removed." if drop_skip_rule(s, text) else "No rule with that text. Run `calendar skip` to list them.")


@calendar_app.command("connect")
def calendar_connect(data_dir: Optional[str] = DataOpt) -> None:
    """Save your calendar's secret iCal address (typed hidden, stored owner-only, never shown again)."""
    from .google import calendar as gcal
    dd, _ = _open_personal(data_dir)
    url = typer.prompt("Paste the 'Secret address in iCal format'", hide_input=True)
    try:
        gcal.save_url(dd, url)
    except gcal.CalendarError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo("Saved. Now run: uv run careeros calendar sync")


@calendar_app.command("sync")
def calendar_sync(days: int = typer.Option(14, help="How many past days to pull (max 60)"),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Pull meetings (title and time only) for the last few days into the Today page."""
    from datetime import date, timedelta
    from .google import calendar as gcal
    dd, s = _open_personal(data_dir)
    last = date.today()
    first = last - timedelta(days=max(1, min(days, 60)))
    try:
        events = gcal.parse_events(gcal.fetch_ics(gcal.load_url(dd)), first, last)
    except gcal.CalendarError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    r = gcal.sync(s, events, first, last)
    typer.echo(f"Calendar: {r['added']} added, {r['updated']} changed, {r['removed']} removed "
               f"({len(events)} meetings between {first} and {last}).")


@calendar_app.command("import")
def calendar_import(file: str = typer.Argument("-", help="JSON file of meetings, or - for stdin"),
                    first: str = typer.Option(..., help="First day covered, YYYY-MM-DD"),
                    last: str = typer.Option(..., help="Last day covered, YYYY-MM-DD"),
                    data_dir: Optional[str] = DataOpt) -> None:
    """Load meetings fetched through the Google Workspace connector (what the Sync button runs)."""
    import json
    import sys
    from datetime import date
    from .google import calendar as gcal
    dd, s = _open_personal(data_dir)
    try:
        items = json.loads(sys.stdin.read() if file == "-" else open(file).read())
        r = gcal.import_events(s, items, date.fromisoformat(first), date.fromisoformat(last))
    except (ValueError, gcal.CalendarError) as exc:
        typer.echo(f"Couldn't import: {exc}")
        raise typer.Exit(1)
    typer.echo(f"Calendar: {r['added']} added, {r['updated']} changed, {r['removed']} removed, "
               f"{r['links']} file links ({len(items)} meetings between {first} and {last}).")


@calendar_app.command("pull")
def calendar_pull(days: int = typer.Option(1, help="How many past days to include besides today (max 14)"),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Ask Claude Code to fetch your meetings through the Google Workspace connector (what the Sync button runs)."""
    from datetime import date, timedelta
    from .google import calendar as gcal, connector, summaries
    dd, s = _open_personal(data_dir)
    last = date.today()
    first = last - timedelta(days=max(0, min(days, connector.MAX_DAYS)))
    try:
        r = gcal.import_events(s, connector.fetch(first, last), first, last)
        n = summaries.summarize_pending(s, first, last)
    except gcal.CalendarError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Calendar: {r['added']} added, {r['updated']} changed, {r['removed']} removed, "
               f"{r['links']} file links ({first} to {last}). "
               f"Summaries: {n['summarized']} written, {n['failed']} failed.")


github_app = typer.Typer(no_args_is_help=True, help="Pull your GitHub pull requests into your notebook (read-only)")
app.add_typer(github_app, name="github")


@github_app.command("sync")
def github_sync(data_dir: Optional[str] = DataOpt) -> None:
    """Bring in PRs you merged or reviewed (the first run goes back a year), then link them to the guide."""
    import threading
    from .web import syncs
    from .web.jobs import Job
    dd, s = _open_personal(data_dir, "GitHub sync")
    s.close()
    engine = make_engine(dd.db)
    job = Job(syncs.GITHUB_STEPS)
    syncs.run_github(job, make_session_factory(engine), threading.Lock())
    for st in job.steps:
        typer.echo(f"{st['label']}: {st['state']}" + (f" ({st['detail']})" if st["detail"] else ""))
    typer.echo(job.message)
    if job.state in ("error", "partial"):
        raise typer.Exit(1)


@github_app.command("skip")
def github_skip(text: Optional[str] = typer.Argument(None, help="Text to skip, e.g. a repo: \"jmysterio/career-os\""),
                data_dir: Optional[str] = DataOpt) -> None:
    """Never bring in PRs whose title or repo contains TEXT, and remove the ones already here. No TEXT lists them."""
    from .storage.removal import add_skip_rule, skip_patterns
    dd, s = _open_personal(data_dir, "GitHub rules")
    if not text:
        typer.echo("\n".join(f"Skipping PRs with: {p}" for p in skip_patterns(s, "github")) or "No skip rules yet.")
        return
    n = add_skip_rule(s, text, "github")
    typer.echo(f"GitHub sync will skip PRs whose title or repo contains \"{' '.join(text.split())}\". "
               f"Removed {n} already in the notebook (see Removed in the Intake Review Queue).")


@github_app.command("unskip")
def github_unskip(text: str = typer.Argument(..., help="The rule's text, as listed by `github skip`"),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Stop skipping PRs with this text. Removed PRs stay removed until you restore them."""
    from .storage.removal import drop_skip_rule
    dd, s = _open_personal(data_dir, "GitHub rules")
    typer.echo("Rule removed." if drop_skip_rule(s, text, "github") else "No rule with that text.")


docs_app = typer.Typer(no_args_is_help=True, help="Google Docs, Sheets and Slides you wrote (pulled by Sync Google)")
app.add_typer(docs_app, name="docs")


@docs_app.command("skip")
def docs_skip(text: Optional[str] = typer.Argument(None, help="Title text to skip, e.g. \"Untitled\""),
              data_dir: Optional[str] = DataOpt) -> None:
    """Never bring in files whose title contains TEXT, and remove the ones already here. No TEXT lists the rules."""
    from .storage.removal import add_skip_rule, skip_patterns
    dd, s = _open_personal(data_dir, "Docs rules")
    if not text:
        typer.echo("\n".join(f"Skipping files titled with: {p}" for p in skip_patterns(s, "docs")) or "No skip rules yet.")
        return
    n = add_skip_rule(s, text, "docs")
    typer.echo(f"Sync Google will skip files whose title contains \"{' '.join(text.split())}\". "
               f"Removed {n} already in the notebook (see Removed in the Intake Review Queue).")


@docs_app.command("unskip")
def docs_unskip(text: str = typer.Argument(..., help="The rule's text, as listed by `docs skip`"),
                data_dir: Optional[str] = DataOpt) -> None:
    """Stop skipping files with this title text. Removed files stay removed until you restore them."""
    from .storage.removal import drop_skip_rule
    dd, s = _open_personal(data_dir, "Docs rules")
    typer.echo("Rule removed." if drop_skip_rule(s, text, "docs") else "No rule with that text.")


digest_app = typer.Typer(no_args_is_help=True, help="Your weekly digest")
app.add_typer(digest_app, name="digest")


@digest_app.command("notify")
def digest_notify(data_dir: Optional[str] = DataOpt) -> None:
    """Show this week's digest as a macOS notification (what the Friday noon schedule runs)."""
    from . import digest
    from .sync_all import mac_notify
    dd, s = _open_personal(data_dir, "The digest")
    line = digest.summary(digest.build(s))
    mac_notify("Career OS: your week", line)
    typer.echo(line)


daily_app = typer.Typer(no_args_is_help=True, help="Three small tasks a day toward your promotion and V2MOM")
app.add_typer(daily_app, name="daily")


@daily_app.command("suggest")
def daily_suggest(force: bool = typer.Option(False, "--force", help="Ask again even if today's three exist"),
                  data_dir: Optional[str] = DataOpt) -> None:
    """Have Claude suggest today's three tasks (the morning sync does this too). Does nothing if they exist."""
    from . import daily
    from .claude_cli import ClaudeError
    dd, s = _open_personal(data_dir, "The daily three")
    try:
        tasks = daily.suggest(s, force=force)
    except ClaudeError as exc:
        typer.echo(f"No new tasks today: {exc}")
        raise typer.Exit(1)
    typer.echo("\n".join(_task_line(t) for t in tasks))


@daily_app.command("show")
def daily_show(data_dir: Optional[str] = DataOpt) -> None:
    """Print today's three."""
    from . import daily
    dd, s = _open_personal(data_dir, "The daily three")
    tasks = daily.today_tasks(s)
    typer.echo("\n".join(_task_line(t) for t in tasks) or "No tasks yet today. They come with the morning sync, or run: uv run careeros daily suggest")


def _task_line(t) -> str:
    return f"{'[x]' if t.done_at else '[ ]'} {t.text}  (~{t.minutes} min, {t.goal})"


@app.command("serve")
def serve(port: int = 8765, data_dir: Optional[str] = DataOpt) -> None:
    """Serve the review UI on loopback only (host is not configurable)."""
    import uvicorn
    from .web.app import create_app
    dd = resolve(data_dir)
    uvicorn.run(create_app(dd), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    app()
