# Set up Coffee Shop

About ten minutes. Claude does most of it with you; a page in the app is there if you would rather click.

## Before you start

- **Claude Code**, signed in. In its connector settings, sign in to **Google Workspace** and **Slack**. Setup cannot do this for you.
- **uv**, which runs the app. On a Mac: `brew install uv`. Other ways: https://docs.astral.sh/uv/
- **gh** (optional), only if you want your GitHub pull requests in the notebook. On a Mac: `brew install gh`, then `gh auth login`.

## On a Mac

1. Clone the repo, for example:

   ```
   cd ~/Documents
   git clone <the repo's address> coffeeshop
   ```

2. Open the `coffeeshop` folder in Claude Code.
3. Type `/setup`.

Claude asks for your role and your level, where your V2MOM PDF is, and which of Google, Slack, and GitHub to turn on. It checks each one, tells you plainly what is not working and what to do, and offers to keep the app running on its own. It ends by saying what goes to Claude. You can run `/setup` again any time; it only changes what is missing or what you ask to change.

## On Windows

The same commands work. `uv run coffeeshop schedule install` creates three Task Scheduler tasks: the app when you log on, the sync at 8:00 AM and 6:00 PM, and the Friday digest at noon.

## If you would rather click

Start the app, then open the setup page:

```
cd ~/Documents/coffeeshop
uv run coffeeshop notebook init
uv run coffeeshop serve
```

Open http://127.0.0.1:8765/setup. Pick your role and level, check that your V2MOM is connected, and press **Check connections**. Untick a connector to skip it for now. **Settings** in the Menu shows what you saved and lets you change it.

To check from Terminal instead: `uv run coffeeshop setup check`. It changes nothing.

## If something fails

| What you see | What to do |
|---|---|
| Google or Slack "isn't signed in" or "has expired" | Open Claude Code's connector settings, sign in to that service, then check again. |
| "Claude took too long" | The connector or the network is slow. Wait a minute and check again. |
| "Couldn't find the `claude` command" | Install Claude Code and sign in, then check again. |
| "Role and level saved" fails | Run `uv run coffeeshop setup level`, or use the setup page. |
| "V2MOM connected" fails | Download your V2MOM as a PDF from the V2MOM app, then run `uv run coffeeshop v2mom connect <path to the PDF>`. If you moved the file, connect it again. |
| "Local notebook" fails | Run `uv run coffeeshop notebook init`. |
| The setup page says it only works with your personal notebook | You opened the practice notebook. Start the app without `--data-dir`. |
| GitHub is skipped | That is fine. It is optional. |
| `uv: command not found` | Install uv (above), then open a new Terminal window. |

Your notebook lives outside the repo, in `~/Library/Application Support/coffeeshop`, so nothing you add can be committed by mistake.
