# Coffee Shop: technical notes

For people reviewing the code. The user guide is [INSTRUCTIONS.md](INSTRUCTIONS.md).

- [Stack and layout](#stack-and-layout)
- [Data flow](#data-flow)
- [Where data lives](#where-data-lives)
- [Security](#security)
- [What goes to Claude](#what-goes-to-claude)
- [Schedules](#schedules)
- [Database and migrations](#database-and-migrations)
- [Tests](#tests)
- [Reviewing a PR](#reviewing-a-pr)

## Stack and layout

Python 3.12, FastAPI, SQLAlchemy on SQLite, Jinja2, Typer, uv. No JavaScript framework; a few small scripts in `web/static/`.

| Path under `src/careeros/` | What it does |
|---|---|
| `cli.py` | Every `careeros …` command; thin glue over the modules below |
| `web/` | The pages (`app.py`), background jobs with progress (`jobs.py`, `syncs.py`), templates, static files |
| `google/` | Calendar, Tasks, Docs, and meeting-note summaries through Claude Code's Google Workspace connector |
| `slack/` | The activity-tracker canvas, its sorting and import, and kudos from public and private channels (never DMs) |
| `github/` | Merged PRs and weekly review counts through the `gh` CLI |
| `v2mom/` | Reading the V2MOM (PDF or Google Doc), stable method ids, links from work, per-method report |
| `guide/` | The leveling guide, links to it, grouping records into work, the Promo map, Claude's read-through |
| `promo/` | The promotion-case writer and its per-sentence checks |
| `daily.py` | Today's three: context, one Claude ask, strict validation, check and uncheck |
| `kso/` | KSOs: the yearly framework read (`framework.py`), V2MOM method to part matching (`map.py`), the page's plain math and bonus projection (`progress.py`), and the monthly estimate (`estimate.py`) |
| `digest.py`, `dashboard.py` | The Friday digest and the Home numbers |
| `export/` | Markdown and CSV downloads |
| `storage/` | Tables, removal and skip rules, the sync log behind the status chips |
| `claude_cli.py` | Runs `claude -p` headless for one narrow job |
| `sync_all.py`, `schedule.py`, `backup.py` | The scheduled sync, the launchd agents, daily backups |
| `fixtures/` | The practice notebook (made-up data only) |

## Data flow

```mermaid
flowchart LR
  subgraph sources [Sources, read-only]
    gw[Google Workspace connector]
    sl[Slack connector]
    gh[gh CLI]
    vm[V2MOM PDF or Doc]
  end
  gw & sl -->|"read through Claude Code"| sync[sync all, 8 AM and 6 PM]
  gh & vm --> sync
  sync --> db[(SQLite notebook)]
  db <-->|"titles and text, tools off"| claude[Claude headless]
  db --> pages[Local pages on 127.0.0.1]
  pages -->|"your checks and edits"| db
  sync --> kso[KSO estimate, monthly]
  sync --> daily[Daily three, last step]
  daily --> db
```

Every record lands as a `JournalEntry`. Claude's read-through sets its kind, guide links, V2MOM links, and whether it's a win, all marked AI until you check them. Pages read the database; their Sync buttons start the same jobs the schedule runs.

## Where data lives

Outside the repo, in `~/Library/Application Support/coffeeshop/` (the practice notebook uses `coffeeshop-demo/`). That folder holds the database, backups, logs, and connector settings. The KSO material is internal, so its parsed rubric lives only in the database (`kso_framework`), with the links to it in `kso.json`; your target incentive lives only in `kso_year`. `.gitignore` also covers every notebook file type (`*.db`, `*.pdf`, `*.csv`, `backups/`, `logs/`, connector files, `guides/`) in case a data folder is ever pointed inside the repo. Run `git config core.hooksPath .githooks` once per clone so the pre-commit check is on: it refuses a staged database, PDF, CSV, zip, backup, log, export, or connector file, and a spreadsheet anywhere except `data/leveling/`. Tests and docs use made-up names and data only.

## Security

- **Loopback only.** The server binds to 127.0.0.1, and requests whose Host isn't `127.0.0.1` or `localhost` are refused (DNS-rebinding guard).
- **Writes are guarded.** Every POST needs the CSRF token (an HMAC of the notebook's secret), and one with a cross-site Origin is refused.
- **Strict CSP.** `default-src 'none'`, scripts only from the app itself (inline styles allowed), no frames, forms only post back to the app.
- **Autoescaped templates.** No user or Claude text is rendered as HTML.
- **Read-only connectors.** The sync reads from Google, Slack, and GitHub; nothing is ever posted, sent, or edited there. The one exception is **Send to Google Docs**, which you press yourself.
- **Claude, boxed in.** `ask()` runs `claude -p --tools ""` with one turn; `call_tools()` allows only the named connector tools. Meeting summaries also allow `Read`, limited to Claude's own saved tool-result folders.

## What goes to Claude

Claude Code is both the reader and the sorter. Everything the Google and Slack connectors fetch passes through it, and the sorting jobs send it text from the notebook. GitHub (`gh`) and a V2MOM PDF are read locally, but their text is sorted by Claude too. Each job sends only what it needs, as data on stdin or as a tool result:

| Job | Claude sees |
|---|---|
| Google sync | Calendar events and their Gemini notes, tasks, and the Docs, Sheets, and Slides you wrote |
| Slack sync | The activity-tracker canvas, then its items for sorting |
| Kudos | Messages that mention you in public and private channels (never DMs), up to 1,500 characters each, with sender and channel |
| Sorting and grouping | Records' text and notes, the leveling guide, and the V2MOM methods |
| V2MOM | The V2MOM text, including your manager's check-in comments |
| Promo case | The numbered evidence list |
| Send to Google Docs | The whole case, written into a new Doc in your Drive |
| Daily three | Goals (V2MOM methods with open measures, Promo map items, and KSO parts with their explanation and two examples) and recent record and win titles, about 8k characters at most |
| KSO connect (yearly, by hand) | The KSO deck and guide canvases, through the Google and Slack connectors |
| KSO matching | KSO part names and explanations, and V2MOM method names, descriptions, and measures |
| KSO estimate (monthly) | The rubric, the matched V2MOM methods with measures and comments, this year's linked work titles (8k total, split evenly across parts), and the kudos count. Never your target or any dollar amount |

Prompts tell Claude the data is data, never instructions, and answers are checked before they're saved. A bad one saves nothing, except promo sentences that fail a check: those are kept and flagged **Check this**.

## Schedules

`careeros schedule install` writes three launchd agents:

| Agent | When | Runs |
|---|---|---|
| `com.careeros.app` | At login, kept alive | `careeros serve` |
| `com.careeros.sync` | 8 AM, 6 PM, and at login | `careeros sync all`: backup, then Slack, Google, GitHub, V2MOM (monthly, and new methods get matched to KSO parts), the KSO estimate (monthly, once KSOs are read and matched), then the daily three (once a day, after 8 AM) |
| `com.careeros.digest` | Friday at noon | `careeros digest notify` |

A missed time runs on wake. A failed step doesn't stop the others; each source that fails sends one macOS notification, and the chips on the pages show each source's last run.

## Database and migrations

One SQLite file, WAL mode, foreign keys on. `storage/db.py:init_db` runs at start: `create_all` makes any new table, and its `added` dict adds columns that came after a notebook was made (`ALTER TABLE … ADD COLUMN` with a default). To add a column, add it to the model and to `added`. Nothing is ever dropped or renamed in place. Daily backups use SQLite's backup API.

## Tests

```
uv run pytest -q
```

`tests/conftest.py` makes any call to the real Claude or `gh` fail, so tests pass fake readers instead. Web tests use FastAPI's `TestClient` against a temporary notebook. Test data is made up.

## Reviewing a PR

- One PR per feature, to `main`. When a PR is built on another, its body says so and gives the merge order.
- The body has three parts: what changed, how it was tested, and what isn't covered.
- Each PR updates `docs/INSTRUCTIONS.md`, and this file or the README when they change.
- A ponytail review runs on each PR; its findings and fixes are a comment on the PR.
- Larger choices get a short note in [`docs/decisions/`](decisions/): what was decided, why, and how to roll back.

The backdrop photos in `src/careeros/web/static/img/` are AI-generated, each in a light and dark version. To swap one, keep the file name and composition, about 1500 px on the long side. README screenshots in `docs/img/` come from the practice notebook only.
