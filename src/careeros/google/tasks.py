"""Google Tasks into the notebook, once they're done in Google. Title, notes, and completion time only."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..storage.models import JournalAttachment, JournalEntry

SOURCE = "tasks"


LISTS_TOOL = "mcp__plugin_google-workspace_google-workspace__list_task_lists"
TASKS_TOOL = "mcp__plugin_google-workspace_google-workspace__list_tasks"
LIST_LINE = re.compile(r"^- .* \(ID: ([^)\s]+)\)\n  Updated: (\S+)", re.M)
TASK_HEAD = re.compile(r"- (.*) \(ID: ([^)\s]+)\)")


@dataclass(frozen=True)
class Task:
    title: str
    done: bool
    when: datetime   # completion time if done, else due/updated time (local)
    notes: str = ""
    gid: str = ""    # Google's task id, when it came from the connector

    @property
    def key(self) -> str:
        return "task:" + hashlib.sha1(f"{self.title}|{self.done}|{self.when:%Y-%m-%dT%H:%M}".encode()).hexdigest()[:16]


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def parse_lists(text: str) -> list[tuple[str, datetime]]:
    return [(lid, _local(ts)) for lid, ts in LIST_LINE.findall(text)]


def parse_tasks(text: str) -> list[Task]:
    """The tasks in one list_tasks answer: title, done, completion (or due/updated) time, notes, Google's id."""
    out = []
    for block in re.split(r"\n(?=- )", text):
        head = TASK_HEAD.match(block.strip())
        if not head:
            continue
        f = dict(re.findall(r"^  (\w+): (.*)$", block, re.M))
        done = f.get("Status") == "completed"
        ts = (f.get("Completed") if done else f.get("Due")) or f.get("Updated")
        if not ts:
            continue
        out.append(Task(head.group(1).strip(), done, _local(ts), f.get("Notes", "").strip(), head.group(2)))
    return out


def fetch(since: datetime) -> tuple[list[Task], int]:
    """Tasks changed since `since`, from task lists changed since then. Returns (tasks, lists that failed)."""
    from ..claude_cli import ClaudeError, call_tool, call_tools, connector_error
    raw = call_tool("Call the list_task_lists tool exactly once. When it returns, reply with only DONE.", LISTS_TOOL)
    if err := connector_error(raw, "Google"):
        raise ClaudeError(err)
    lists = [lid for lid, updated in parse_lists(raw) if updated >= since]
    if not lists:
        return [], 0
    stamp = since.astimezone().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = ("Call the list_tasks tool once for each of these task_list_id values, with show_completed=true, "
              f"show_hidden=true, max_results=100, updated_min={stamp}: {', '.join(lists)}. "
              "When they have all returned, reply with only DONE.")
    tasks, ok = [], set()
    for _tool, args, text in call_tools(prompt, [TASKS_TOOL], timeout=300, max_turns=len(lists) + 6):
        if connector_error(text, "Google") is None and args.get("task_list_id") in lists:
            ok.add(args["task_list_id"])
            tasks += parse_tasks(text)
    return tasks, len(set(lists) - ok)


def _clear_open(s: Session) -> int:
    """Open Google Tasks don't belong in the notebook: deletes open ones, unless you built on one (checked it, set
    its links, made a win, added notes); those stay out of the queue until done. Not through the Removed list, so the
    finished task still comes in once it's done."""
    from ..storage.models import GuideLink, V2momLink
    n = 0
    from ..storage.removal import built_on
    for e in list(s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE, JournalEntry.status == "open"))):
        if built_on(s, e, ignore=("Task notes",)):
            continue
        for model in (JournalAttachment, GuideLink, V2momLink):
            s.execute(delete(model).where(model.entry_id == e.id))
        s.delete(e)
        n += 1
    s.flush()
    return n


def merge(s: Session, tasks: list[Task], complete: bool = True) -> dict[str, int]:
    """Adds tasks done in Google and updates a kept open record once its task is done. Open tasks are skipped; one
    reopened in Google goes back to open, and open ones are then cleared (see _clear_open). Never deletes a done one
    otherwise: a fetch only covers recently changed lists. An incomplete fetch isn't logged, so the next sync starts
    from the old mark."""
    from ..storage.models import RemovedEntry
    mine = list(s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE)))
    by_key = {e.external_id: e for e in mine}
    gone = set(s.scalars(select(RemovedEntry.external_id).where(  # removed while open: the finished one may come in
        RemovedEntry.source == SOURCE, RemovedEntry.status != "open", RemovedEntry.external_id.is_not(None))))
    today = date.today().isoformat()
    added = updated = 0
    for t in tasks:
        ext = f"gtask:{t.gid}"
        if not t.done:
            if (e := by_key.get(ext)) is not None and e.status == "done":
                e.status = "open"
            continue
        if ext in gone or t.key in gone:
            continue
        status, day = "done", min(t.when.date().isoformat(), today)
        e = by_key.get(ext) or by_key.get(t.key) or next(
            (x for x in mine if x.text == t.title[:500] and not (x.external_id or "").startswith("gtask:")
             and (x.status == "open" or (x.status == status and x.day == day))), None)
        if e is None:
            e = JournalEntry(day=day, kind="task", text=t.title[:500], created_at=datetime.now(), source=SOURCE,
                             external_id=ext, status=status)
            s.add(e)
            s.flush()
            if t.notes:
                s.add(JournalAttachment(entry_id=e.id, kind="notes", title="Task notes", body=t.notes,
                                        created_at=datetime.now()))
            mine.append(e)
            added += 1
        elif e.kind == "task" and (e.status != status or e.external_id != ext):
            if e.status != status:
                e.status, e.day = status, day
                updated += 1
            e.external_id = ext
        by_key[ext] = e
    _clear_open(s)
    if complete:
        from ..storage.sync_log import record
        record(s, SOURCE, added)
    s.commit()
    return dict(added=added, updated=updated)
