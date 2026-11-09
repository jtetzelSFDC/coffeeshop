<h1 align="center">Coffee Shop</h1>

<p align="center"><em>Do the work. It remembers.</em></p>

<p align="center">
  <img src="docs/img/home.jpg" width="820" alt="Coffee Shop's Home page in dark mode: a latte in the corner, house plants down the side, a Today's three card with three small tasks, and a card with Grade 6 and Grade 7 readiness bars, tiles for skills, wins, kudos and records to check, a 12-week evidence chart, and the next step.">
</p>

## What it does

- It gathers your days from Calendar, Tasks, Docs, Slack, and GitHub, twice each day.
- It sorts each record by its kind, and by the part of the leveling guide it shows.
- It counts a deed once, however many places it appears.
- It keeps the kind words others say of you, word for word.
- It holds your V2MOM, and notes which work moves each method forward.
- It shows how your year will be weighed for the bonus, and what it may pay.
- It shows the path: what is shown, what is strong, what is still to come.
- Each morning it offers three small steps, none longer than ten minutes.
- When the season comes, it writes your promotion case, each sentence with its source, for you to shape and send to Google Docs.
- On Friday it tells you what the week added.
- It marks what Claude chose, so that you may decide.
- Each day it keeps a copy, and you may take everything with you.
- It lives on your machine. Only what Claude must read leaves it.

## Begin

You need [uv](https://docs.astral.sh/uv/) and Claude Code signed in to the Google Workspace and Slack connectors. The same commands work on a Mac and on Windows.

```
cd ~/Documents/coffeeshop
uv run careeros notebook init
uv run careeros schedule install
```

Then open http://127.0.0.1:8765 in a browser. On a Mac you can run `open http://127.0.0.1:8765`.

Then load your leveling guide and connect your V2MOM ([INSTRUCTIONS.md](docs/INSTRUCTIONS.md)); without them there is nothing to sort against.

To try it with made-up data: `uv run careeros demo seed --data-dir /tmp/cos-demo && uv run careeros serve --data-dir /tmp/cos-demo`. The screenshot above is that practice notebook.

## Read more

- [INSTRUCTIONS.md](docs/INSTRUCTIONS.md): every page, button, and command.
- [TECHNICAL.md](docs/TECHNICAL.md): how it is built, for people reviewing the code.
