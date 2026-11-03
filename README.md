<h1 align="center">Career Tracker</h1>

<p align="center"><em>Do the work. It remembers.</em></p>

<p align="center">
  <img src="docs/img/home.jpg" width="820" alt="Career Tracker's Home page in dark mode: a latte in the corner, house plants down the side, and one card with Grade 6 and Grade 7 readiness bars, tiles for skills, wins, kudos and records to check, a 12-week evidence chart, and the next step.">
</p>

## What it does

- It gathers your days from Calendar, Tasks, Docs, Slack, and GitHub, twice each day.
- It sorts each record by its kind, and by the part of the leveling guide it shows.
- It counts a deed once, however many places it appears.
- It keeps the kind words others say of you, word for word.
- It holds your V2MOM, and notes which work moves each method forward.
- It shows the path: what is shown, what is strong, what is still to come.
- Each morning it offers three small steps, none longer than ten minutes.
- When the season comes, it writes your promotion case, each sentence with its source.
- On Friday it tells you what the week added.
- It marks what Claude chose, so that you may decide.
- It lives on your machine, and nowhere else.

## Begin

You need a Mac, [uv](https://docs.astral.sh/uv/), and Claude Code signed in to the Google Workspace and Slack connectors.

```
uv run careeros notebook init
uv run careeros schedule install
open http://127.0.0.1:8765
```

To try it with made-up data: `uv run careeros demo seed --data-dir /tmp/cos-demo && uv run careeros serve --data-dir /tmp/cos-demo`. The screenshot above is that practice notebook.

## Read more

- [INSTRUCTIONS.md](docs/INSTRUCTIONS.md): every page, button, and command.
- [TECHNICAL.md](docs/TECHNICAL.md): how it is built, for people reviewing the code.
