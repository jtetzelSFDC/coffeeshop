"""The app's background jobs (each Sync button, the scheduled sync, promo writing, the KSO estimate, the daily
three): what each runs, step by step, reporting progress into a Job that the page's progress box shows."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..claude_cli import ClaudeError
from ..config import DataDir
from .jobs import Job

GOOGLE_STEPS = ["Read Google Calendar (yesterday and today)", "Read Google Tasks", "Summarize meeting notes",
                "Read Google Docs you wrote or edited", "Link new records to the leveling guide"]
SLACK_STEPS = ["Read your Slack messages", "Read your Slack tracker canvas", "Sort the new items",
               "Look for kudos in your Slack channels", "Link new records to the leveling guide"]
TASKS_LOOKBACK = timedelta(days=14)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _tasks_since(s) -> datetime:
    """Where the next Google Tasks pull starts: a day before the last one, so a task finished just before it ran
    isn't missed (the merge skips ones already here); the first pull looks back TASKS_LOOKBACK."""
    from ..storage.sync_log import status
    last = status(s)["tasks"]["at"]
    return (last - timedelta(days=1)) if last else datetime.now() - TASKS_LOOKBACK


REVIEW_STEPS = ["Have Claude read the new records"]


def run_review(job: Job, Session_) -> None:
    """The queue's "Have Claude read" button, and what starts after you add an entry: the same linking step every
    sync ends with. No write lock: Claude takes minutes, and the review re-checks each record before it saves."""
    from ..guide.ai_review import pending
    n = 0
    with Session_() as s:
        for _ in range(3):  # shortcut: 3 passes; raise it if you add entries faster than Claude reads them
            got = _link_new(job, 0, s)
            n += got
            if not got or not pending(s):
                break
    job.finish(f"Claude read {_plural(n, 'record')}. Everything it picked is marked AI." if n
               else "Claude didn't read anything new, so nothing changed.")


def _link_new(job: Job, i: int, s) -> int:
    """Step `i` of a sync: Claude reads the records it hasn't read against the leveling guide (and V2MOM), then
    groups new records with earlier work and tags their impact activity. Returns how many records it read."""
    from ..guide import activities, work
    from ..guide.ai_review import pending, review
    from ..guide.service import SETUP_HINT, has_guide, level
    if not has_guide(s):
        job.skip(i, "The leveling guide isn't loaded.")
        return 0
    if level(s) is None:
        job.skip(i, f"Choose your role and level first: {SETUP_HINT}")
        return 0
    if not pending(s) and not work.pending(s) and not activities.pending(s):
        job.done(i, "Nothing new to link.")
        return 0
    job.start(i)
    r = dict(read=0, links=0, wins=0, v2mom=0, values=0, failed=0)
    try:
        if pending(s):
            r = review(s, progress=job.sub)
        g = work.group(s) if work.pending(s) else dict(new=0, joined=0)
        a = activities.tag(s) if activities.pending(s) else dict(tagged=0)
    except ClaudeError as exc:
        job.fail(i, str(exc))
        return 0
    job.done(i, f"{_plural(r['links'], 'guide link')}, " + (f"{r['v2mom']} V2MOM, " if r["v2mom"] else "")
             + (f"{r['values']} Values, " if r["values"] else "")
             + f"{_plural(r['wins'], 'drafted win')}, "
             f"{_plural(g['joined'], 'record')} grouped with earlier work, {a['tagged']} counted toward impact"
             + (f"; {r['failed']} couldn't be read" if r["failed"] else ""))
    return r["read"]


def run_google(job: Job, Session_, lock) -> None:
    """Sync Google: calendar, tasks, meeting-note summaries, Docs you wrote, then guide links."""
    from ..google import calendar as gcal, connector, docs as gdocs, summaries, tasks as gtasks
    last = date.today()
    first = last - timedelta(days=1)
    new = []
    with Session_() as s:
        job.start(0)
        try:
            items = connector.fetch(first, last)
            with lock:
                r = gcal.import_events(s, items, first, last)
            job.done(0, f"{_plural(r['added'], 'new meeting')}, {r['updated']} changed, {r['removed']} gone"
                        + (f"; {r['later']} later today come in once they've ended" if r.get("later") else ""))
            new.append(_plural(r["added"], "meeting"))
        except (gcal.CalendarError, ClaudeError) as exc:
            job.fail(0, f"{exc} Is Google Workspace signed in for Claude Code?")
        job.start(1)
        try:
            tasks, failed = gtasks.fetch(_tasks_since(s))
            with lock:
                r = gtasks.merge(s, tasks, complete=not failed)
            detail = _plural(r["added"], "finished task")
            if failed:
                job.fail(1, detail + f"; {_plural(failed, 'task list')} couldn't be read. Press Sync Google again.")
            else:
                job.done(1, detail)
            new.append(_plural(r["added"], "task"))
        except ClaudeError as exc:
            job.fail(1, str(exc))
        job.start(2)
        try:
            n = summaries.summarize_pending(s, first, last, progress=job.sub)
            if n["failed"]:
                job.fail(2, f"{n['summarized']} written, {n['failed']} couldn't be read. Press Sync Google again.")
            else:
                job.done(2, f"{n['summarized']} written" if n["summarized"] else "No new meeting notes.")
        except gcal.CalendarError as exc:
            job.fail(2, str(exc))
        job.start(3)
        try:
            found, short = gdocs.fetch(gdocs.since(s))
            with lock:
                r = gdocs.merge(s, found, complete=not short)
            n = gdocs.summarize_pending(s, progress=job.sub)
            detail = f"{_plural(r['added'], 'new file')}, {n['summarized']} summarized" + (
                f", {r['skipped']} skipped by your rules" if r["skipped"] else "")
            if short or n["failed"]:
                job.fail(3, detail + (f"; {_plural(short, 'search')} came back incomplete" if short else "")
                         + (f"; {n['failed']} couldn't be read" if n["failed"] else "") + ". Press Sync Google again.")
            else:
                job.done(3, detail)
            new.append(_plural(r["added"], "file"))
        except ClaudeError as exc:
            job.fail(3, str(exc))
        _link_new(job, 4, s)
    listed = ", ".join(new[:-1]) + " and " + new[-1] if len(new) > 1 else "".join(new)
    job.finish(f"Google synced: {listed} new." if new else "Google sync couldn't read anything.")


def run_promo(job: Job, Session_, start: str, end: str, name: str) -> None:
    """Write a promo case draft: one step per section, ticked as each comes back."""
    from ..promo import write as pw
    keys = [k for k, *_ in pw.SECTIONS]
    for i in range(len(keys)):
        job.start(i)

    def on_section(key: str, detail: str) -> None:
        i = keys.index(key)
        if detail.endswith(" sentences"):
            job.done(i, detail)
        elif detail.startswith("No evidence"):
            job.skip(i, detail)
        else:
            job.fail(i, detail)

    with Session_() as s:
        try:
            v = pw.write_case(s, start=start, end=end, name=name, on_section=on_section)
        except ClaudeError as exc:
            for i, st in enumerate(job.steps):
                if st["state"] == "running":
                    job.fail(i, str(exc))
            job.finish("No draft was saved.")
            return
    job.finish(f"Draft {v.id} is ready.")


def run_rewrite(job: Job, Session_, vid: int, key: str) -> None:
    """Claude redoes one section of a draft; the result is saved as a new draft."""
    from ..promo import write as pw
    from ..storage.models import PromoVersion
    job.start(0)
    with Session_() as s:
        v = s.get(PromoVersion, vid)
        try:
            new = pw.rewrite_section(s, v, key)
        except (ClaudeError, KeyError) as exc:
            job.fail(0, str(exc) if isinstance(exc, ClaudeError) else "That section isn't in this draft.")
            job.finish("Nothing changed.")
            return
    job.done(0, f"Saved as draft {new.id}")
    job.finish(f"Draft {new.id} is ready: open the newest draft to see it.")


GDOC_STEPS = ["Send the copy with sources", "Send the clean copy for sharing"]


def run_gdoc(job: Job, Session_, dd: DataDir, vid: int) -> None:
    """Send a draft to Google Docs twice (with sources, and clean), reading each back to check every word arrived."""
    from sqlalchemy import select
    from ..google import docs_export
    from ..storage.models import PromoSection, PromoVersion
    with Session_() as s:
        v = s.get(PromoVersion, vid)
        sections = list(s.scalars(select(PromoSection).where(PromoSection.version_id == vid)
                                  .order_by(PromoSection.position)))
        for i, sourced in enumerate((True, False)):
            job.start(i)
            try:
                link, same = docs_export.send(dd, v, sections, sourced)
            except ClaudeError as exc:
                job.fail(i, str(exc))
                continue
            if sourced:
                v.google_doc_url = link
            else:
                v.google_doc_clean_url = link
            s.commit()
            if same:
                job.done(i, "Created in My Drive; every word checked")
            else:
                job.fail(i, "Created, but its words don't fully match the draft; open the Doc and check it")
    job.finish("Sent to Google Docs. The links are on the draft.")


GITHUB_STEPS = ["Read your GitHub pull requests", "Link new records to the leveling guide"]


def run_github(job: Job, Session_, lock) -> None:
    """Sync GitHub: PRs you merged and a weekly tally of ones you reviewed, then guide links."""
    from ..github import connector as gh
    with Session_() as s:
        job.start(0)
        try:
            me, prs = gh.fetch(gh.since(s))
            with lock:
                r = gh.merge(s, prs)
        except gh.GitHubError as exc:
            msg = str(exc)
            if "isn't installed" in msg or "isn't signed in" in msg:
                job.skip(0, msg)
                job.skip(1)
                job.finish("GitHub isn't connected, so that step was skipped.")
                job.state = "done"  # an all-skipped job would otherwise count as a failure and notify
                return
            job.fail(0, msg)
            job.skip(1)
            job.finish("GitHub sync couldn't read anything.")
            return
        job.done(0, f"{_plural(r['added'], 'new record')} for {me}, {r['updated']} weeks of reviews grew"
                    + (f", {r['skipped']} skipped by your rules" if r["skipped"] else ""))
        _link_new(job, 1, s)
    job.finish(f"GitHub synced: {_plural(r['added'], 'new record')}.")


def run_slack(job: Job, Session_, lock, dd: DataDir) -> None:
    """Sync Slack: your own messages, then the tracker canvas, sorting, kudos, and guide links."""
    from ..slack import messages as slack_msgs
    from ..slack.classify import classify
    from ..slack.connector import fetch_canvas
    from ..slack.importer import import_items, load_canvas_id
    from ..slack.kudos import user
    from ..slack.parse import CanvasFormatError, parse_canvas
    with Session_() as s:
        job.start(0)
        groups, fetched = [], False
        try:
            uid, _name = user(dd)
            groups, short = slack_msgs.fetch(uid, slack_msgs.since(s), progress=job.sub)
            fetched = True
        except ClaudeError as exc:
            job.fail(0, str(exc))
        else:
            bare = sum(1 for g in groups if g.needs_parent and not g.context)
            job.done(0, _plural(len(groups), "conversation")
                     + (f"; {_plural(short, 'window')} had more messages than could be read" if short else "")
                     + (f"; {_plural(bare, 'reply')} had no thread start" if bare else ""))
        cid = load_canvas_id(dd)
        items = []
        if not cid:
            job.skip(1, "No Slack canvas connected. In Terminal run: uv run coffeeshop slack connect <canvas link>")
        else:
            job.start(1)
            try:
                items = parse_canvas(fetch_canvas(cid))
            except (ClaudeError, CanvasFormatError) as exc:
                job.fail(1, str(exc))
            else:
                job.done(1, f"{_plural(len(items), 'item')} on the canvas")
        job.start(2)
        try:  # not under the write lock: Claude's sorting takes a while and the page stays usable meanwhile
            if fetched:
                fresh = slack_msgs.attach(s, groups, items)
                nmsg, r = slack_msgs.save(s, groups, fresh, lambda t: classify(t, progress=job.sub))
            else:
                nmsg, r = 0, import_items(s, items, lambda t: classify(t, progress=job.sub))
        except ClaudeError as exc:
            job.fail(2, str(exc))
            job.skip(3)
            job.skip(4)
            job.finish("Slack sync couldn't sort the new items, so nothing was saved.")
            return
        added = nmsg + r["added"]
        job.done(2, f"{r['meeting']} meetings, {r['conversation']} conversations, {r['document']} documents, "
                    f"{r['task']} tasks, {r['note']} other" if added else "Nothing new since the last pull.")
        praised = _kudos(job, 3, s, lock, dd)
        _link_new(job, 4, s)
    job.finish(f"Slack synced: {_plural(added, 'new item')}" + (f" and {praised} kudos." if praised else "."))


V2MOM_STEPS = ["Read your V2MOM", "Save its methods and measures"]
V2MOM_CONNECT = ("No V2MOM connected yet. On the V2MOM page, upload the PDF, or in Terminal run: "
                 "uv run coffeeshop v2mom connect <path to the PDF>")


def run_v2mom(job: Job, Session_, lock, dd: DataDir) -> None:
    """Sync V2MOM: read the PDF or Doc, save methods and measures, and match new methods to KSO parts."""
    from ..v2mom import connector, store
    src = connector.load_source(dd)
    if not src:
        job.fail(0, V2MOM_CONNECT)
        job.skip(1)
        job.finish("V2MOM sync couldn't start.")
        return
    job.start(0)
    try:
        parsed, origin = connector.read(src)
    except ClaudeError as exc:
        was = src.get("was") if src.get("kind") == "url" else None
        if isinstance(was, dict) and was.get("kind") in ("pdf", "doc") and was.get("value"):
            connector.write_source(dd, dict(kind=was["kind"], value=was["value"]))
        job.fail(0, str(exc))
        job.skip(1)
        job.finish("V2MOM sync couldn't read your V2MOM, so nothing changed.")
        return
    if src.get("was"):
        connector.write_source(dd, dict(kind=src["kind"], value=src["value"]))
    job.done(0, f"{_plural(len(parsed['methods']), 'method')}, {_plural(len(parsed['obstacles']), 'obstacle')}"
             + (f", {_plural(len(parsed['check_ins']), 'check-in')}" if parsed["check_ins"] else ""))
    job.start(1)
    with Session_() as s:
        with lock:
            r = store.save(s, parsed, origin)
        ksos = _kso_matches(s, lock)
    job.done(1, f"{r['added']} new" + (f", {r['retired']} no longer in your V2MOM (kept, marked inactive)"
                                      if r["retired"] else "") + ksos)
    job.finish(f"V2MOM synced: {(parsed['fiscal_year'] + ', ') if parsed['fiscal_year'] else ''}"
               f"{_plural(r['methods'], 'method')}.")


def _kso_matches(s, lock) -> str:
    """New V2MOM methods get matched to this year's KSO components, when KSOs are connected."""
    from ..kso import framework, map as kmap
    fw = framework.for_current(s)
    if not fw or not kmap.pending(s, fw):
        return ""
    try:
        r = kmap.suggest(s, fw, lock=lock)
    except ClaudeError as exc:
        return f"; KSO matching didn't work ({exc})"
    return f"; {_plural(r['mapped'], 'new method')} matched to KSOs (marked AI)"


KSO_STEPS = ["Estimate your KSO ratings"]


def run_kso(job: Job, Session_, lock) -> None:
    """Re-estimate: Claude's 1-5 guess per KSO for this year."""
    from ..kso import estimate as kso_est, framework
    job.start(0)
    with Session_() as s:
        fw = framework.for_current(s)
        if fw is None:
            job.skip(0, "No KSOs for this year yet. Run: uv run coffeeshop kso connect")
            job.finish("No KSO estimate without KSOs.")
            return
        try:
            row = kso_est.estimate(s, fw, lock=lock)
        except ClaudeError as exc:
            job.fail(0, str(exc))
            job.finish("No new KSO estimate, so nothing changed.")
            return
        ratings = ", ".join(f"KSO {k['key']}: {k['rating']}" for k in row.data["ksos"])
    job.done(0, ratings)
    job.finish("The KSO estimate is on the KSOs page.")


DAILY_STEPS = ["Suggest today's three tasks"]


def run_daily(job: Job, Session_, lock, force: bool = False) -> None:
    """Today's three: suggested once a day (or a new three with `force`, replacing all of them)."""
    from .. import daily
    job.start(0)
    with Session_() as s:
        if not daily.goals(s, date.today()):
            job.skip(0, "Nothing to aim at yet: load the leveling guide or connect your V2MOM.")
            job.finish("No daily three without goals.")
            return
        try:
            tasks = daily.suggest(s, force=force, lock=lock)
        except ClaudeError as exc:
            job.fail(0, str(exc))
            job.finish("No daily three today, so nothing changed.")
            return
    job.done(0, f"{len(tasks)} tasks for today")
    job.finish("Today's three are on Home.")


def _kudos(job: Job, i: int, s, lock, dd: DataDir) -> int:
    from ..slack import kudos
    job.start(i)
    try:
        uid, name = kudos.user(dd)
        msgs, full = kudos.fetch(uid, kudos.since(s))
        todo = kudos.new(s, msgs)
        kept = kudos.choose(todo, uid, name, progress=job.sub)
        with lock:
            n = kudos.merge(s, kept)
    except ClaudeError as exc:
        job.fail(i, str(exc))
        return 0
    job.done(i, f"{_plural(len(todo), 'new mention')} read, {n} kept as kudos"
             + (f"; {_plural(full, 'week')} had more mentions than could be read, so the oldest there were skipped"
                if full else ""))
    return n
