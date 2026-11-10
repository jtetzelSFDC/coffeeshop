---
description: Set up Coffee Shop on this laptop: your notebook, role and level, V2MOM, connectors, and schedule.
disable-model-invocation: true
allowed-tools:
  - Bash(uv run careeros *)
  - Bash(uv --version)
  - Bash(git config core.hooksPath .githooks)
  - Bash(ls .githooks)
---

You are setting up Coffee Shop for the person at this keyboard, in this repo. Talk in short, plain sentences, one
question at a time, and wait for each answer. This command is safe to run again: look at what is already in place
first (step 2), and only change what is missing or what the person asks to change.

Rules that never bend:
- Never read Slack DMs or group DMs. Never print or open the person's notebook files, V2MOM, or messages.
- Never commit anything from their notebook (it lives outside this repo) or from their V2MOM PDF. Do not run `git add` or `git commit`.
- You cannot sign in to Google or Slack for them. That happens in Claude Code's connector settings.

## 1. Check uv

Run `uv --version`. If it is missing, tell them to install it from https://docs.astral.sh/uv/ (on a Mac:
`brew install uv`), then run `/setup` again. Stop here until it works.

## 2. See what is already in place

Run `uv run careeros setup check --skip google --skip slack --skip github` (no connector reads yet). It prints each
step as pass, fail, or skipped, with what to do. It exits with an error when a step fails; that is expected here.
Use it to skip the steps below that already pass.

## 3. The notebook

If "Local notebook" failed, run `uv run careeros notebook init`. Never use `--data-dir`.

## 4. Role and level

If "Role and level saved" passed, say what is saved and ask whether it is still right. Skip the rest of this step
unless they want to change it (for example after a promotion).

Otherwise ask for their role first. Run `uv run careeros setup level < /dev/null` to list the roles. It then asks
a question that cannot be answered here, so it ends with "Aborted"; that is fine, the list is what you wanted.
Always add `< /dev/null` so it cannot wait for typing. Show the list in
a short form and ask which one is theirs. Then run `uv run careeros setup level --role "<role>" < /dev/null` to list that
role's levels with their job titles (again it ends with "Aborted"). Ask which is their level now. Some roles list two
job titles at one grade; read both out. Save it with `uv run careeros setup level --role "<role>" --grade <number>`.
This also loads the role's leveling guide. Tell them the next level it found.

## 5. V2MOM

If "V2MOM connected" failed, ask where their V2MOM PDF is (downloaded from the V2MOM app), then run
`uv run careeros v2mom connect "<path>"`. If they have no PDF yet, skip this and say they can add it later on the
V2MOM page of the app.

## 6. Connectors

Ask which of Google, Slack, and GitHub they want to turn on. Google and Slack are what most people want; GitHub is
optional (pull requests). Then run `uv run careeros setup check`, adding `--skip google`, `--skip slack`, or
`--skip github` for each one they did not choose. This reads one small thing from each connector and changes
nothing. It takes up to a minute.

Explain each failure in plain words, using the "What to do" line:
- Google or Slack not signed in or expired: "Open Claude Code's connector settings, sign in to <service>, then run
  `/setup` again." Sign-in happens there, not in this app.
- No answer in time: the connector or the network is slow; try again in a minute.
- GitHub skipped: only if they want it, install `gh` (`brew install gh`) and run `gh auth login` themselves.
- Local notebook, role, guide, or V2MOM failed: go back to the matching step above.

## 7. Git hooks

If `ls .githooks` shows a folder, run `git config core.hooksPath .githooks`. It stops personal data from being
committed by mistake. If there is no `.githooks` folder, skip this.

## 8. The schedule

Offer `uv run careeros schedule install`. It keeps the app running and syncs twice a day. Run it only if they say
yes. If it says scheduling is not supported on this computer, skip it and tell them to start the app with
`uv run careeros serve`.

## 9. Finish

Tell them to open http://127.0.0.1:8765 (or start it with `uv run careeros serve` if they skipped the schedule).
If anything is still unfinished, point them to the setup page at http://127.0.0.1:8765/setup, which does the same
steps by hand.

End with one paragraph on what goes to Claude, before their first sync, in these words or close to them: Claude Code
reads your Google Calendar, Tasks, and the Docs you wrote, your Slack tracker canvas, and Slack messages that mention
you in public and private channels (never DMs), and it sorts the notebook's records, your V2MOM, and the leveling
guide to find the work that counts toward your next level. Each job sends only what it needs. Everything is stored
on this laptop, in your notebook folder, outside this repo; nothing else leaves it, except a promo case you choose
to send to Google Docs. The full list is in
docs/TECHNICAL.md under "What goes to Claude".
