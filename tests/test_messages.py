import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from coffeeshop.claude_cli import ClaudeError
from coffeeshop.slack import messages, search
from coffeeshop.slack.importer import import_items
from coffeeshop.slack.parse import SlackItem, TRACKER, parse_canvas
from coffeeshop.storage.models import JournalAttachment, JournalEntry, SyncRun
from coffeeshop.storage.removal import remove_entry
from test_slack import TRACKER as CANVAS

ME = "U01ME"
LINK = "https://example.slack.com/archives/C111/p1700000000000100?thread_ts=1700000000.000100"
ZONE = ZoneInfo("America/New_York")


def hit(text, ts, channel="#release-team", cid="C1", thread="", bot=False, uid=ME):
    link = f"https://example.slack.com/archives/{cid}/p{messages.p_digits(ts)}"
    if thread:
        link += f"?thread_ts={thread}"
    return search.Hit(link, channel, cid, "Jordan", uid, bot, date(2026, 10, 26), ts, text)


def ts_of(dt):
    return f"{dt.timestamp():.6f}"


def group_for(day, text="Deployed the hotfix to production and watched the errors drop", link=LINK):
    h = search.Hit(link, "#release-team", "C111", "Jordan", ME, False, day, "1700000000.000100", text)
    return messages.Group("#release-team", "C111", "1700000000.000100", day, [h])


def canvas_item(day="2026-10-27"):
    return SlackItem("slack:C111/p1700000000000100", day, "Deployment: Ship the hotfix",
                     "Action: Deployed the hotfix.\nWhy it mattered: Stopped the spike.",
                     "Stopped the spike.", LINK, TRACKER)


def test_day_comes_from_the_message_timestamp_in_local_time():
    utc = datetime(2026, 10, 27, 3, 30, tzinfo=timezone.utc)
    assert messages.local_day(f"{utc.timestamp():.6f}", date(2026, 10, 27), ZONE) == date(2026, 10, 26)


def test_noise_drops_short_replies_emoji_and_bots():
    long = "Deployed the hotfix to production"
    assert messages.noisy(hit("ok", "1.000000"))
    assert messages.noisy(hit("thanks", "1.000000"))
    assert messages.noisy(hit("👍", "1.000000"))
    assert messages.noisy(hit(":+1:", "1.000000"))
    assert messages.noisy(hit(long, "1.000000", bot=True))
    assert messages.noisy(hit(long, "1.000000", channel="Pat Lee", cid="D9"))
    assert not messages.noisy(hit("done, merged", "1.000000"))
    assert not messages.noisy(hit(long, "1.000000"))


def test_one_thread_on_one_day_is_one_record():
    parent = ts_of(datetime(2026, 10, 26, 15, tzinfo=ZONE))
    reply = ts_of(datetime(2026, 10, 26, 16, tzinfo=ZONE))
    later = ts_of(datetime(2026, 10, 27, 9, tzinfo=ZONE))
    other = ts_of(datetime(2026, 10, 26, 15, tzinfo=ZONE))
    groups = messages.group([
        hit("done, merged", reply, thread=parent),
        hit("Started the refresh and wrote the plan", parent),
        hit("Checked it the next morning once more", later, thread=parent),
        hit("A separate channel gets its own record", other, cid="C2"),
    ], ZONE)
    assert len(groups) == 3
    day = next(g for g in groups if g.day == date(2026, 10, 26) and g.channel_id == "C1")
    assert [m.text for m in day.messages] == ["Started the refresh and wrote the plan", "done, merged"]
    assert day.ext_id == f"slack:C1/p{messages.p_digits(parent)}:2026-10-26"
    again = messages.group([hit("done, merged", reply, thread=parent),
                            hit("Started the refresh and wrote the plan", parent)], ZONE)
    assert again[0].ext_id == day.ext_id
    nxt = next(g for g in groups if g.day == date(2026, 10, 27))
    assert nxt.needs_parent and not day.needs_parent


def test_a_canvas_link_joins_the_day_that_message_was_sent(session):
    parent = ts_of(datetime(2026, 10, 26, 15, tzinfo=ZONE))
    later = ts_of(datetime(2026, 10, 27, 9, tzinfo=ZONE))
    monday = hit("Started the refresh and wrote the plan", parent)
    tuesday = hit("Checked it the next morning once more", later, thread=parent)
    groups = messages.group([tuesday, monday], ZONE)  # the later day is first on purpose
    item = SlackItem("k", "2026-10-26", "Refresh", "Action: Started the refresh.", "", monday.link, TRACKER)
    assert messages.attach(session, groups, [item]) == []
    home = next(g for g in groups if g.day == date(2026, 10, 26))
    other = next(g for g in groups if g.day == date(2026, 10, 27))
    assert home.canvas == [item] and other.canvas == []


def test_thread_context_is_capped_and_never_reads_a_dm(monkeypatch):
    prompts = []

    def read(prompt, tools, timeout, max_turns):
        prompts.append((prompt, tools))
        lines = [dict(re.findall(r"(\w+)='([^']*)'", line)) for line in prompt.splitlines() if line[:1].isdigit()]
        return [("t", {"channel_id": a["channel_id"], "message_ts": a["message_ts"]},
                 json.dumps({"messages": [{"text": "Parent: the release is stuck"}]})) for a in lines]
    monkeypatch.setattr("coffeeshop.claude_cli.call_tools", read)
    groups = []
    for n in range(messages.THREAD_CAP + 5):
        ts = f"170000{n:04d}.000100"
        g = messages.Group("#release-team", "C1", f"170000{n:04d}.000000", date(2026, 10, 26),
                           [hit("done, merged the listed fix", ts, thread=f"170000{n:04d}.000000")])
        groups.append(g)
    groups.append(messages.Group("Pat Lee", "D99", "1700000099.000000", date(2026, 10, 26),
                                 [hit("this is a direct message, ignore it", "1700000099.000200",
                                      channel="Pat Lee", cid="D99", thread="1700000099.000000")]))
    messages.add_context(groups)
    assert len(prompts) == 1 and prompts[0][1] == [messages.THREAD_TOOL]
    assert prompts[0][0].count("channel_id=") == messages.THREAD_CAP
    assert "D99" not in prompts[0][0] and "mpim" not in prompts[0][0]
    assert groups[0].context == "Parent: the release is stuck"
    assert groups[-1].context == "" and groups[messages.THREAD_CAP].context == ""


def test_a_failed_thread_read_keeps_the_reply(monkeypatch):
    def boom(prompt, tools, timeout, max_turns):
        raise ClaudeError("Slack didn't answer")
    monkeypatch.setattr("coffeeshop.claude_cli.call_tools", boom)
    g = messages.Group("#release-team", "C1", "1700000000.000000", date(2026, 10, 26),
                       [hit("done, merged the listed fix", "1700000000.000200", thread="1700000000.000000")])
    messages.add_context([g])
    assert g.context == "" and "done, merged" in g.full_text()


def test_search_never_requests_dms_and_drops_them_if_they_appear(monkeypatch):
    prompts = []
    when = ts_of(datetime(2026, 10, 26, 12, tzinfo=datetime.now().astimezone().tzinfo))
    dm = ("### Result 1 of 2\nChannel: Pat Lee (ID: D9)\nFrom: Jordan (ID: U01ME) \nTime: 2026-10-26 09:00:00 EDT\n"
          f"Message_ts: {when}\nPermalink: [link](https://example.slack.com/archives/D9/p1700000001000000)\n"
          "Text: \nThis is a long direct message that must be ignored.\n\n---\n\n")
    ok = ("### Result 2 of 2\nChannel: #release-team (ID: C1)\nFrom: Jordan (ID: U01ME) \n"
          "Time: 2026-10-26 10:00:00 EDT\n"
          f"Message_ts: {when}\nPermalink: [link](https://example.slack.com/archives/C1/p1700000002000000)\nText: \n"
          "Shipped the hotfix and told the channel.\n\n---\n\n")
    raw = json.dumps({"results": dm + ok, "pagination_info": ""})

    def search_once(prompt, tools, timeout, max_turns):
        prompts.append((prompt, tools))
        lines = [dict(re.findall(r"(\w+)='([^']*)'", line)) for line in prompt.splitlines() if line[:1].isdigit()]
        return [("t", a, raw) for a in lines]
    monkeypatch.setattr("coffeeshop.claude_cli.call_tools", search_once)
    groups, short = messages.fetch(ME, date(2026, 10, 26), date(2026, 10, 26))
    assert short == 0 and [g.channel for g in groups] == ["#release-team"]
    assert search.CHANNEL_TYPES.split(",") == ["public_channel", "private_channel"]
    assert "im" not in search.CHANNEL_TYPES.split(",") and "mpim" not in search.CHANNEL_TYPES.split(",")
    prompt, tools = prompts[0]
    assert tools == [search.SEARCH_TOOL]
    assert 'channel_types="public_channel,private_channel"' in prompt
    assert "mpim" not in prompt and "im" not in prompt.split('channel_types="')[1].split('"')[0]
    assert "from:<@U01ME>" in prompt and "slack_search_public_and_private" in prompt


def test_canvas_summary_joins_the_message_and_the_message_date_wins(session):
    g = group_for(date(2026, 10, 26))
    n, r = messages.save(session, [g], [canvas_item("2026-10-27")], lambda t: {g.ext_id: "task"})
    assert n == 1 and r["added"] == 0
    rows = session.scalars(select(JournalEntry)).all()
    assert len(rows) == 1 and rows[0].day == "2026-10-26" and rows[0].kind == "task"
    assert rows[0].external_id == g.ext_id and rows[0].source == "slack"
    notes = session.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == rows[0].id,
                                                            JournalAttachment.kind == "notes")).one()
    assert "Stopped the spike" in notes.body and notes.title.startswith("From Slack (AI-written)")
    link = session.scalars(select(JournalAttachment).where(JournalAttachment.kind == "link")).one()
    assert link.body == LINK


def test_a_later_reply_joins_the_same_days_record(session):
    parent = ts_of(datetime(2026, 10, 26, 15, tzinfo=ZONE))
    later = ts_of(datetime(2026, 10, 26, 18, tzinfo=ZONE))
    first = messages.group([hit("Started the refresh and wrote the plan", parent)], ZONE)[0]
    messages.save(session, [first], [], lambda t: {first.ext_id: "task"})
    both = messages.group([
        hit("Started the refresh and wrote the plan", parent),
        hit("done, merged the listed fix", later, thread=parent),
    ], ZONE)[0]
    messages.save(session, [both], [], lambda t: {})
    rows = session.scalars(select(JournalEntry)).all()
    assert len(rows) == 1 and rows[0].kind == "task"
    assert "Started the refresh" in rows[0].text and "done, merged" in rows[0].text
    both.context = "The refresh plan is in the doc"
    messages.save(session, [both], [], lambda t: {})
    text = session.scalar(select(JournalEntry)).text
    assert text.startswith("In reply to: The refresh plan") and "done, merged" in text


def test_an_older_canvas_record_takes_the_message_date(session):
    from coffeeshop.storage.models import Win
    import_items(session, [canvas_item("2026-10-27")], lambda t: {canvas_item().key: "note"})
    row = session.scalar(select(JournalEntry))
    session.add(Win(day=row.day, title="Shipped the hotfix", impact="", size="small", entry_id=row.id,
                    created_at=datetime.now(), by_ai=True))
    session.commit()
    g = group_for(date(2026, 10, 26))
    messages.save(session, [g], [], lambda t: {})
    rows = session.scalars(select(JournalEntry)).all()
    assert len(rows) == 1 and rows[0].day == "2026-10-26"
    assert session.scalar(select(Win.day)) == "2026-10-26"


def test_canvas_item_with_a_link_and_no_message_is_marked_from_the_canvas(session):
    items = parse_canvas(CANVAS)
    import_items(session, items, lambda t: {})
    rows = session.scalars(select(JournalEntry).order_by(JournalEntry.id)).all()
    assert len(rows) == 3
    linked = session.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == rows[0].id,
                                                             JournalAttachment.kind == "notes")).one()
    assert linked.body.startswith("From the canvas.") and "Stopped the error spike" in linked.body
    plain = session.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == rows[1].id,
                                                            JournalAttachment.kind == "notes")).one()
    assert not plain.body.startswith("From the canvas.") and plain.body.startswith("Action:")


def test_sorting_new_messages_leaves_the_notebook_writable(session):
    import sqlite3
    g = group_for(date(2026, 10, 26))
    messages.save(session, [g], [], lambda t: {})
    other = "https://example.slack.com/archives/C111/p1700000000000200"
    fresh = group_for(date(2026, 10, 27), link=other)
    db = session.get_bind().url.database

    def classify(todo):
        with sqlite3.connect(db, timeout=0.2) as live:
            live.execute("update journal_entry set text = text")
            live.commit()
        return {}

    messages.save(session, [g, fresh], [canvas_item("2026-10-26")], classify)
    assert session.scalar(select(func.count()).select_from(JournalEntry)) == 2


def test_a_removed_message_is_not_added_again(session):
    g = group_for(date(2026, 10, 26))
    messages.save(session, [g], [], lambda t: {g.ext_id: "task"})
    eid = session.scalar(select(JournalEntry.id))
    remove_entry(session, eid)
    messages.save(session, [g], [canvas_item()], lambda t: {})
    assert session.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_first_search_looks_back_ninety_days_then_two(session):
    assert messages.since(session) == date.today() - timedelta(days=90)
    session.add(SyncRun(source=messages.CURSOR, at=datetime(2026, 10, 20, 12, 0), added=1))
    session.commit()
    assert messages.since(session) == date(2026, 10, 18)


def test_sync_step_saves_the_message_and_does_not_duplicate_the_canvas(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from coffeeshop.slack import classify as cls
    from coffeeshop.slack import connector, kudos
    from coffeeshop.slack.importer import save_canvas_id
    from coffeeshop.web.app import create_app
    from helpers import personal, run_sync
    dd, Session = personal(tmp_path)
    save_canvas_id(dd, "F0EXAMPLE01")
    kudos.save_user(dd, ME, "Jordan")
    g = group_for(date(2026, 10, 20), "Deployed the hotfix to production and watched it")
    monkeypatch.setattr(messages, "fetch", lambda uid, since, today=None, progress=None: ([g], 0))
    monkeypatch.setattr(kudos, "fetch", lambda uid, since: ([], 0))
    monkeypatch.setattr(connector, "call_tool", lambda prompt, tool: json.dumps({"markdown_content": CANVAS}))
    seen = []

    def ask(prompt, data):
        seen.append(json.loads(data))
        return "{}"
    monkeypatch.setattr(cls, "ask", ask)
    app = create_app(dd)
    c, token = TestClient(app, base_url="http://127.0.0.1"), app.state.csrf_token
    job = run_sync(c, token, "slack")
    assert job["steps"][0]["state"] == "done" and "1 conversation" in job["steps"][0]["detail"]
    assert "had no thread start" not in job["steps"][0]["detail"]
    assert job["state"] == "done"
    with Session() as s:
        rows = s.scalars(select(JournalEntry).order_by(JournalEntry.id)).all()
        assert len(rows) == 3  # the linked canvas item joined the message; two items had no link
        msg = rows[0]
        assert msg.day == "2026-10-20" and msg.external_id == g.ext_id
        notes = s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == msg.id,
                                                          JournalAttachment.kind == "notes")).one()
        assert "Stopped the error spike" in notes.body
        assert "/archives/C111/p1700000000000100" in s.scalar(
            select(JournalAttachment.body).where(JournalAttachment.entry_id == msg.id, JournalAttachment.kind == "link"))
    assert any("Deployed the hotfix" in row["text"] and "Stopped the error spike" in row["text"] for row in seen[0])


def test_a_reply_with_no_thread_start_is_called_out(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from coffeeshop.slack import classify as cls
    from coffeeshop.slack import kudos
    from coffeeshop.web.app import create_app
    from helpers import personal, run_sync
    dd, _Session = personal(tmp_path)
    kudos.save_user(dd, ME, "Jordan")
    reply = messages.Group("#release-team", "C111", "1700000000.000100", date(2026, 10, 26), [
        hit("done, merged the listed fix", "1700000001.000000", cid="C111", thread="1700000000.000100")])
    assert reply.needs_parent and not reply.context
    monkeypatch.setattr(messages, "fetch", lambda uid, since, today=None, progress=None: ([reply], 0))
    monkeypatch.setattr(kudos, "fetch", lambda uid, since: ([], 0))
    monkeypatch.setattr(cls, "ask", lambda p, d: "{}")
    app = create_app(dd)
    c, token = TestClient(app, base_url="http://127.0.0.1"), app.state.csrf_token
    job = run_sync(c, token, "slack")
    assert "1 reply had no thread start" in job["steps"][0]["detail"]
