"""Slack search shared by kudos and your own messages.

Public and private channels only. The search tool's default includes DMs and group DMs, so every search names
channel types and never asks for im or mpim.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

SEARCH_TOOL = "mcp__plugin_slack_slack__slack_search_public_and_private"
CHANNEL_TYPES = "public_channel,private_channel"  # never im (DMs) or mpim (group DMs)
LIMIT = 20  # the search tool's maximum per page
MAX_PAGES = 10  # 200 messages in one window; a busier window is counted and the rest of that window is skipped
CHUNK = timedelta(days=6)  # a week per search
RESULT = re.compile(r"^### Result \d+ of \d+\n(.*?)(?=^---$)", re.M | re.S)


@dataclass(frozen=True)
class Hit:
    link: str
    channel: str
    channel_id: str
    who: str
    who_id: str
    bot: bool
    day: date  # the date printed on the result; kudos keeps this
    ts: str
    text: str


def _field(block: str, name: str) -> str:
    m = re.search(rf"^{name}: (.*)$", block, re.M)
    return m.group(1).strip() if m else ""


def parse(raw: str) -> tuple[list[Hit], str]:
    """(hits, cursor for the next page or "") from one search answer."""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    text = str(data.get("results", "")) if isinstance(data, dict) else raw
    nxt = re.search(r"cursor `([^`]+)`", str(data.get("pagination_info", ""))) if isinstance(data, dict) else None
    out = []
    for block in RESULT.findall(text):
        frm = _field(block, "From")
        link = re.search(r"Permalink: \[link\]\((\S+?)\)", block)
        when = re.match(r"(\d{4}-\d{2}-\d{2})", _field(block, "Time"))
        body = block.split("\nText: \n", 1)[1].strip() if "\nText: \n" in block else ""
        if not (link and when and body):
            continue
        who = re.match(r"(.*?)\s*(?:<[^>]*>)?\s*\(ID: (\w+)\)", frm)
        channel = _field(block, "Channel")
        cid = re.search(r"\(ID: (\w+)\)", channel)
        out.append(Hit(link.group(1), channel.split(" (ID")[0], cid.group(1) if cid else "",
                         (who.group(1).strip() if who else ""), who.group(2) if who else "", "[BOT]" in frm,
                         date.fromisoformat(when.group(1)), _field(block, "Message_ts"), body))
    return out, nxt.group(1) if nxt else ""


def windows(since: date, today: date, chunk: timedelta) -> list[str]:
    out, start = [], since
    while start <= today:
        end = min(start + chunk, today)
        out.append(f"after:{start - timedelta(days=1)} before:{end + timedelta(days=1)}")
        start = end + timedelta(days=1)
    return out


def fetch(keywords: list[str], prefix: str, since: date, today: date, chunk: timedelta, accept,
          progress=None) -> tuple[list[Hit], int]:
    """Hits `accept` keeps, one chunk of days per search, following extra pages.

    `prefix` is a filter in front of each date window (your own messages use ``from:<@id>``). Returns
    (hits, windows not fully read: a search that didn't come back, or more than MAX_PAGES pages).
    """
    from ..claude_cli import ClaudeError, call_tools, connector_error
    todo = [(f"{prefix} {w}".strip(), "") for w in windows(since, today, chunk)]
    total = len(todo)
    found: dict[str, Hit] = {}
    for _ in range(MAX_PAGES):
        if not todo:
            break
        lines = [f"{i + 1}. filters={w!r}" + (f", cursor={c!r}" if c else "") for i, (w, c) in enumerate(todo)]
        prompt = (f"Call the slack_search_public_and_private tool once for each line below, each with "
                  f'keywords={json.dumps(keywords)}, channel_types="{CHANNEL_TYPES}", limit={LIMIT}, '
                  f"sort=timestamp, include_bots=false, include_context=false, response_format=detailed, "
                  f'natural_language_query="", plus the filters (and cursor, when given) on that line, and nothing '
                  f"else. When they have all returned, reply with only DONE.\n" + "\n".join(lines))
        asked, todo = set(todo), []
        for _tool, args, raw in call_tools(prompt, [SEARCH_TOOL], timeout=600, max_turns=len(asked) + 6):
            key = (args.get("filters"), args.get("cursor") or "")
            if key not in asked:
                continue
            if err := connector_error(raw, "Slack"):
                raise ClaudeError(err)
            asked.discard(key)
            got, nxt = parse(raw)
            if nxt:
                todo.append((key[0], nxt))
            for hit in got:
                if accept(hit):
                    found.setdefault(hit.link.split("?")[0], hit)
        todo += sorted(asked)  # didn't come back: asked again next round
        if progress and total:
            progress(total - len({w for w, _ in todo}), total)
    return list(found.values()), len({w for w, _ in todo})
