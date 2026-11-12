# Coffee Shop: How to use it

Plain-language notes on running and testing the app. New questions and answers get added at the bottom under **Q&A**. For what the app *is*, see [README.md](../README.md); for how it's built, [TECHNICAL.md](TECHNICAL.md).

## Where things stand

Coffee Shop is your work notebook. It pulls in your Google Calendar meetings, finished Google Tasks, the Docs you wrote, your Slack messages and tracker, kudos, and GitHub pull requests. Claude sorts each one against your role's leveling guide. Your V2MOM and your KSOs join that sort when you connect them. Your wins stay too, so the Performance map, the performance case, the KSO page, and each morning's three small tasks reflect what you have actually done.

Everything stays on this laptop. Something leaves only when Claude reads or sorts it: a sync, adding an entry or checking off a daily task, Have Claude read, Write my performance case, Suggest now, Re-estimate, a `kso` command, or Send to Google Docs. The full list is in [What goes to Claude](TECHNICAL.md#what-goes-to-claude).

There's also a **practice notebook** of made-up data, for trying things out without touching your real one.

## Start your notebook (the everyday way)

Your real, permanent notebook lives in `~/Library/Application Support/coffeeshop` on a Mac, and in `%LOCALAPPDATA%\coffeeshop` on Windows. It survives restarts. Open Terminal, or PowerShell on Windows, and run:

```
cd ~/Documents/coffeeshop
uv run coffeeshop notebook init   # first time only: makes the notebook folder
uv run coffeeshop setup level     # first time only: your role and grade (see Leveling guide below)
uv run coffeeshop serve
```

Open **http://127.0.0.1:8765** in a browser. Leave the terminal running. Press **Ctrl+C** in it to stop the app. If the page stops loading (for example after a restart), run the same command again. Your entries and wins are still there.

Don't add `--data-dir` to this command. That flag points the app at a different folder, such as the practice demo below.

## Set up with Claude (or by hand)

New here? [SETUP.md](../SETUP.md) has the steps. In Claude Code, open this folder and type `/setup`. Claude asks for your role and level, where your V2MOM PDF is, and which of Google, Slack, and GitHub to turn on, then checks each one and says what to fix. It is safe to run again.

The fallback is the **Setup** page in the Menu (http://127.0.0.1:8765/setup): pick your role and level, see whether your V2MOM is connected, and press **Check connections**. Untick a connector to skip it. **Settings** in the Menu shows your saved role and level, with **Change** and **Run setup again**, the optional Projects and responsibilities box, and **Refresh the performance case every Friday** (off unless you turn it on). Until a role and level are saved, Home shows a **Finish setup** note.

`uv run coffeeshop setup check` prints the same checks in Terminal as pass, fail, or skipped, each with what to do. It only reads: one small read from Google and one from Slack, and nothing is changed. Add `--skip google`, `--skip slack`, `--skip github`, or `--skip schedule` to leave one out. Signing in to Google or Slack always happens in Claude Code's connector settings.

## Let it run on its own (recommended)

One command sets up three scheduled tasks, so you never start the app or press Sync yourself. On a Mac they are launchd agents. On Windows they are Task Scheduler tasks.

```
cd ~/Documents/coffeeshop
uv run coffeeshop schedule install
```

- **The app** starts when you log in and comes back if it stops. On Windows, Task Scheduler starts it at logon and, if it exits with an error, starts it again one minute later (up to 255 times). A clean exit waits until the next logon. It's at http://127.0.0.1:8765 once it's running. If you'd started it yourself in a Terminal, stop that one (Ctrl+C) first.
- **The sync** runs at 8:00 AM and 6:00 PM (after your 5 PM Slack automation), and once when you log in if a run was missed while the laptop was closed. Each run backs up the notebook first, then does exactly what the Sync Slack tracker and Sync Google buttons do, then pulls your GitHub pull requests. If nothing is due, it does nothing.
- **If something fails**, for example a connector's sign-in expired, a notification says which sync and what to do (usually: open Claude Code's connector settings and sign in again). On Windows, if the toast is blocked, the same words go in the sync log instead. Nothing is shown when everything works; the status chips show the times.
- **The daily three** come as the last step of the morning sync, so they're ready by about 8:15 to 8:30 AM and always see the work just pulled in. If the computer was off that morning, the login or 6 PM sync makes them. See **Daily three** below.
- **The digest** shows a notification on Fridays at 12:00 PM (if the laptop was asleep, as soon as it wakes). See **Weekly digest** below.
- `uv run coffeeshop schedule status` shows whether each is on and the last sync log line. Logs are in `logs/` in your notebook folder.
- `uv run coffeeshop sync all --force` runs a sync right now from Terminal.
- `uv run coffeeshop schedule uninstall` removes the three tasks and nothing else.

## Start the practice notebook (made-up data)

```
cd ~/Documents/coffeeshop
uv run coffeeshop demo seed --data-dir /tmp/cos-demo
uv run coffeeshop serve --data-dir /tmp/cos-demo
```

It holds a week of made-up meetings, Slack items, tasks, and notes, two wins, and a tiny made-up leveling guide, so every page has something to show. It never syncs with Slack or Google. `/tmp` is cleared when the Mac restarts; on Windows, use a folder such as `$env:TEMP\cos-demo` instead of `/tmp/cos-demo`. Just run `demo seed` again. Never put real notes here.

## Wins: your accomplishments for reviews, promotion, and your resume

The **Wins** tab is where accomplishments go, small to large, all year. You can add one in two ways:

- On the **Wins** tab, press **+ Add a win**, type what you did, why it mattered, how big it was, and a theme, then click **Save to my wins**.
- On any entry in the other tabs (a meeting, a finished task), press its trophy button (**Count this as a win**). It starts with the entry's text so you can reword it, and it remembers which entry it came from.

Tips:

- **What I did** is one line starting with a verb: "Led", "Fixed", "Mentored", "Automated".
- **Why it mattered** is the result: who it helped, what got faster, cheaper, or safer. Numbers help. You can leave it blank and fill it in later with the pencil button; a win without it shows an orange **add why it mattered** badge, and the **missing why** chip at the top lists just those.
- **Size** is your own call: small for a helpful fix, large for something you'd lead a performance case with.
- **Theme** (Delivery, Leadership, Mentoring, and so on) groups wins in the export, which maps nicely onto promotion criteria.

**Reading the page.** The chips at the top count the year's wins (all, small, medium, large, missing why); click one to show only those, and the year chips switch years. Each win is one line: the date, the title, its size and theme, and three icon buttons (pencil to edit, target to link it to the leveling guide, × to remove). Under it is why it mattered, the record it came from, and the guide items it shows.

## Leveling guide and Performance map

The app knows your role's leveling guide, so your work can be lined up against what the next grades ask for. It's set up for someone aiming at the next grade, with evidence for the grade after that where the work is already at that level. The next grade is the next one your role has, so on DevOps, Grade 9 goes for Grade 11. The examples below are for DevOps Grade 5, which goes for Grade 6 and Grade 7.

**Choosing your role and level.** The whole leveling guide workbook is in the repo, at `data/leveling/leveling-guides.xlsx`, one tab per role. Run this once, and again after a promotion:

```
cd ~/Documents/coffeeshop
uv run coffeeshop setup level
```

It lists the roles, then your role's grades with their job titles, saves your choice in your notebook, and loads that role's guide. To skip the questions: `uv run coffeeshop setup level --role DevOps --grade 5`. A few roles have two job titles at the same grade, such as a manager and an architect. Those are listed as two roles, for example "Quality Engineering" and "Quality Engineering (Test Automation Architect)"; pick the one you're on. On the top grade of your path there's no next level, so Home and the Performance map say that instead of showing bars. On paths other than DevOps, the Performance map lists your next grades' key experiences in one plain list, without the topics and ideas below.

**When a new guide comes out.** Download the whole Google Sheet as an `.xlsx` file and run `uv run coffeeshop guide update <file>`. It checks that every role tab reads, says which roles were added, removed, or changed, and only then replaces the copy in the repo. Commit it, then run `setup level` again to load it. Links you've made are kept. Anything the new guide drops leaves the map but stays on the wins that pointed to it.

**Linking your work.** Each time you save a win, the app asks **Which parts of the leveling guide does this show?** It ticks the items that look related based on your words, such as "sandbox", "deploy", "merge", or "demo". Untick what doesn't fit, tick what it missed, and click **Save**, or choose **Skip for now**. Nothing is linked until you save. Notebook entries can be linked too. Entries that look related show dashed **Might show** chips, and linked ones show **Shows** with the items; the target button on the entry links or changes them.

**The Performance map tab.** It leads with this year's V2MOM method progress and KSO bars. When an earlier year is already in the notebook, that year sits beside this one. The leveling guide is folded under **Promotion (optional)**. Open that, and it shows:

- A progress bar for Grade 6 and for Grade 7 with the percent shown (hover for the strong/started/not-yet detail), plus chips for Claude's unchecked picks and for records that might show guide items (each opens the right list in the Intake Review Queue).
- **Aim for next**: one concrete step per topic, one line each (hover for the guide item). Topics you've started come first, and a topic moves to its Grade 7 step once Grade 6 is shown.
- The 12 topics, each with the Grade 6 experiences beside the Grade 7 ones. Each has a colored dot and edge for **Not yet**, **Started**, **Shown**, or **Strong** (hover the dot for the word), with **Ideas to get here** underneath.
- The skills whose bar rises from Grade 6 to Grade 7, with the guide's rating as Grade 5 → 6 → 7 (hover a skill for its description) and your evidence for each.

Colors come from points. A linked entry is worth 1, and a small, medium, or large win is worth 2, 3, or 4. One point makes an item Started, 3 make it Shown, and 6 make it Strong. So one large win shows an experience, and a large win plus a medium one makes it strong. An entry and the win made from it only count once.

**Write my performance case** is on the Performance map, or at http://127.0.0.1:8765/performance/case. Pick who it is about (your first name, remembered next time) and the dates (the last 12 months by default), then press the button. It takes a minute or two, and each section shows its progress.

The draft follows the Performance Advocacy Tool: **Project Highlights, Business Contributions, Professional Development, Feedback,** and **Promotion Readiness** (**Strategic Business Need**, at least 25 words, and **Talent Readiness**, at most 400 words). Each section's guidance, including what is valued and what to avoid, is read from the blank template at `data/pat/pat-template.docx`. They are written in the third person, and only from your notebook: wins and why they mattered, pieces of work, linked records, the impact numbers, and the Performance map's gaps and next steps. Only items inside the dates are used. A draft saved under the older section names (Summary, Key accomplishments, Impact, Behaviors & values, Growth areas) still opens.

Every sentence ends with small [numbers] that jump to its sources. The sources are listed at the bottom as they were when the draft was written. The app then checks each sentence. One with no source, or with a number that is not in its evidence, is marked **Check this** and the reason is shown. The check catches invented numbers and missing sources, not every wrong word, so read the draft before you use it. A count such as "12 deployments" is used only in a section that also cites work of that kind.

If the dates hold fewer than three linked wins, pieces of work, or records, the page says so and does not ask Claude. Log more, let a sync link your records, or pick wider dates.

Under **Style example (optional)** you can paste a strong performance case, yours or someone else's. Claude copies only its tone and structure, never its facts, and the checks above still apply. The example stays on this computer, in `profile.json` next to your database. It is sent to Claude when you write or rewrite a section. Empty the box and write again to clear it. Every draft is kept.

From Terminal: `uv run coffeeshop performance write` (with `--start`, `--end`, `--name`).

On Settings, **Refresh the performance case every Friday** is off unless you turn it on. When it's on, the Friday noon digest also writes one draft for the last 12 months. When it's off, Friday only shows the digest. Turning it on does not write a draft by itself; the next Friday does.

**V2MOM alignment.** Once your V2MOM is loaded and records are linked to its methods, the evidence also has one piece per current method with work in the window, like "V2MOM M2 (Build Reusable Pipeline Accelerators, On Track, 50% progress): 3 wins and 12 records between … and …, for example: …", and each win and piece of work says which methods it advances ("Advances V2MOM M2."). These go to Project Highlights, Business Contributions, Strategic Business Need, and Talent Readiness, so the case can say a piece of work was "advancing V2MOM method M2 (its name)", but only when a source it cites says so; the usual check applies. Methods with nothing in the window, and ones dropped from your V2MOM, are left out. When your V2MOM came from the PDF, each check-in with manager comments also becomes a piece, like "V2MOM check-in (Midyear FY27), manager comments: …" (up to about 600 characters), for Feedback, so the case can quote your manager's own words. Check-ins without comments are left out. With no V2MOM loaded, the case is written exactly as before.

**Reading a draft.** The top of a draft shows chips for its number and date, the window it's written from, and how many sentences to check (or "every sentence sourced"). The **Sources** list at the bottom is folded; clicking any [number] in the draft opens it at that source.

**Editing and rewriting a draft.** Under each section, **Edit** opens it as plain text, one sentence per line, with its sources as [numbers] at the end of the line: keep a number to keep that source, and your wording is checked the same way as Claude's. **Rewrite** (beside the section's heading) has Claude redo just that section from the same evidence; if you've edited it, tick **Replace my edits** first. Either way the result is saved as a **new draft**, so nothing is ever overwritten. **All drafts and compare** lists every draft with what changed ("Edited Project Highlights", "Rewrote Talent Readiness") and shows any two side by side: struck-through sentences are only in the first, underlined ones only in the second. Viewing an older draft shows a link to the newest.

**Sending a draft to Google Docs.** On a draft, **Send to Google Docs** makes two Docs in My Drive: one with the [numbers], the **Check this** notes, and a Sources list (for you), and a clean copy without them (for sharing). Fix any **Check this** sentences first if you're sharing, since the clean copy includes them without the warning. The draft passes through the AI tool on its way to Google (the Google connector can't read files on this laptop), so the app reads each new Doc back and compares its words with the draft: a step that doesn't match shows an error, and its link is still saved so you can look. Links to both Docs appear on the draft, and a copy of what was sent is kept in `exports/` in the notebook folder.

**Download evidence (Markdown)** writes the evidence behind the Performance map grouped by grade and topic. Each guide item lists the wins and entries behind it, with dates and why they mattered, and a **Not shown yet** list at the end shows what to aim for before you submit.

## Intake Review Queue: sorting everything that comes in

The **Intake Review Queue** (in the Menu) is a grid of every record (calendar meetings, Google Tasks, Slack items, and what you typed), newest first, 100 to a page. The columns are **Select**, **Record** (date, where it came from, and the text), **Type**, **Counts as**, **Part of**, **Leveling guide**, **V2MOM**, **Win**, and **Actions**. Each heading has a one-line hint: hover the heading, or read the legend above the grid.

- **Select**: tick rows, or the heading checkbox for every row on this page, then **Looks right for selected (N)**. A row Claude has not read yet is skipped. **Looks right** on one row still works.
- **Type**: Meeting, Convo, Doc, Task, Kudos, Cert, or Other. The lit one is the current type.
- **Counts as**: the activity this record adds to on the Performance map. **Part of**: the piece of work it belongs to, counted once.
- **Leveling guide**: the guide items the record shows. **V2MOM**: the methods it moves forward (the method's name, shortened if it's long; hover for the full name). Click &times; to remove one, or **edit**/**link** in that column to pick them yourself.
- **Win**: **S**, **M**, or **L** makes the record a small, medium, or large win (or resizes it), and &times; removes the win. Click the win's title to see why it mattered, then **Edit on Wins** to reword it.
- **Looks right** marks the row checked. Whatever Claude picked for it becomes yours, and the row leaves the **Not checked yet** list, so you can work down the list until it's empty. **Looks right for selected** does that for every ticked row. A row Claude has not read yet is skipped, the same as a row that shows no Looks right button.
- **Remove** (under Looks right) takes a record out for good, for example a meeting you didn't attend. Its pasted notes, guide links, and any win Claude drafted from it go too; wins you made or edited stay. Calendar, Tasks, and Slack syncs skip removed records so they don't come back. Choose **Removed** in the Show menu to see them and **Restore** one if you change your mind. **No V2MOM method**, beside the other filters, lists records Claude has read that aren't linked to a V2MOM method. Press **Show** to apply it. It does not change the Removed list.

**Is everything pulled in?** A row of small status chips (at the top of the queue, and under each Sync button on Home) shows each source with a dot, an icon, and when it was last pulled: a time for today, "Yesterday", or a date. A green dot means up to date: Slack was pulled after 5:30 PM on the latest evening (the tracker automation runs at 5 PM), the V2MOM in the last 31 days, and the others were synced today. An orange dot means it needs a pull; press that Sync button. Hover over a chip for the details: the exact time, how many new items came in, the date of the newest item, and what's missing. "(about)" means the time is estimated from when items were added, before the app kept a sync history.

**One piece of work, counted once.** A deployment often shows up three times: a calendar meeting, a Slack thread, and a Google task. Claude groups records like that into one piece of work, and the Performance map counts the piece once, at its strongest evidence (a large win made from one of them beats a plain record). A grouped row shows **Part of: Pine 5.1.2 release · 3 records** (marked AI until you check the row). **Not the same work** takes a row out of its group, and **Group with…** puts it in a nearby group or starts a new one you name. Claude never regroups a row you grouped, split, or marked **Looks right**. A piece of work runs at most 30 days from its first record, and a record joins only work that's had activity in the last 14 days, so groups don't snowball. New records are grouped after every sync. To group everything already in the notebook (it shows what it would do first with `--dry-run`):

```
uv run coffeeshop guide group --dry-run
uv run coffeeshop guide group
```

**Impact numbers.** Claude tags each record with the one activity it shows, from a fixed list: deployment, sandbox refresh, release coordinated, PR reviewed or approved, incident or blocker resolved, document written, process change, mentoring or teaching, demo or presentation, access request handled, branch audit, hotfix, and training or certification. Routine meetings and status pings get nothing, and a meeting *about* a deploy isn't a deployment. The Performance map's **By the numbers** table counts each activity for this half (calendar halves), this year, and all time. A piece of work counts once per day it was done: three records of the same deploy on the same day count once, and a release deployed to lab on Monday and to UAT on Thursday counts twice. Open tasks don't count. Click a number to see the records behind it. In the Intake Review Queue, **Counts as** shows each record's activity (marked AI until you set it) and lets you change it; Claude never changes one you set. New records are tagged after every sync. To tag everything already in the notebook: `uv run coffeeshop guide activities`. The performance case download includes the table.

**Skipping a recurring meeting for good.** To keep a meeting you don't attend out of the notebook, including future ones, add a skip rule. It removes the ones already here and Calendar sync skips any meeting whose title contains the text (any capitalization):

```
uv run coffeeshop calendar skip "Team Daily Standup"
uv run coffeeshop calendar skip                          # list the rules
uv run coffeeshop calendar unskip "Team Daily Standup"  # stop skipping
```

Buttons in the queue save without reloading the page: a row you check or remove fades out, and a row you change redraws in place.

Purple **AI** marks are Claude's picks: guide links, drafted wins, and type changes ("AI, was Other"). They count on the Performance map straight away, and the Performance map says how many are still unchecked. Use the **Show** menu for **Changed by Claude**, **Not linked**, **Wins**, or **Checked**.

**Claude's read-through.** Claude has read every record against the Grade 6 and 7 key experiences and skills. It linked each one to the guide items it shows (none for routine standups and status pings), drafted wins for the stand-out ones, and fixed obvious type mix-ups (only for Slack and typed records; calendar items stay meetings and Google Tasks stay tasks). Records you add by hand are read right away. When others come in and haven't been read (for example before the guide was loaded), the queue shows a **Have Claude read the N records it hasn't read** button. It only counts records you haven't checked yet: **Looks right** on a row Claude never read leaves it unread, so press **Checked** on it to take the check back first. It runs in the background with a progress box (the same step every sync ends with), so you can keep working. You can also run it in Terminal:

```
cd ~/Documents/coffeeshop
uv run coffeeshop guide review
```

It never touches rows you've marked checked or guide links you picked yourself. Because Claude takes a few minutes, it looks at each record again just before saving: a record you removed or checked in the meantime is skipped, and a record you retyped keeps your type. You can keep clicking around the app while it runs. Record text, attached notes, and the leveling guide pass through the AI tool, with Claude's built-in tools (files, shell, web) turned off. Calendar and Tasks syncs never delete a record that has a win, guide links, or your check on it.

## Slack: your Work Activity Tracker canvas

Your Slack Work Activity Tracker canvas (the one Slackbot fills in every day) comes into the notebook as entries. Claude reads each work item and decides whether it was a meeting, a conversation, a document, or a task. Anything it can't place goes to **Other**. Every entry from Slack has a **from Slack** label, the tracker's notes underneath (marked as written by Slack's AI), and a link back to the Slack thread. Items that are already in the notebook are skipped, so syncing again is safe. Tasks from Slack come in as done. When the tracker says why something mattered, the entry gets a dashed **suggested win** label and the **Count this as a win** form is pre-filled with that reason, so you can edit it into your own words and save.

**Your own messages.** The same sync searches Slack for messages you sent, in public and private channels only. DMs and group DMs are never searched. The first search looks back 90 days; after that, only the last couple of days. Messages you sent in one thread on one day become one record, with a link to the message, dated from the message's own time. Very short replies, emoji-only messages, and bots are left out before Claude reads anything. When you replied in someone else's thread, the sync reads that thread's first message (up to 20 threads a sync) so a short reply still has what it answers.

**The canvas confirms.** The tracker is still read. When one of its items links to a message already in the notebook, its summary is added to that record's notes and the message's date stays. An item with a date and a link but no matching message is still added, marked as from the canvas. An item with no link is added as before.

**The Sync Slack tracker button** on Home reads your messages and the canvas through Claude Code's Slack connector, sorts the new records, and has Claude link them to the leveling guide, with a progress bar under the button. It only works while Slack is signed in for Claude Code; if the sign-in has expired the progress box says so, and you sign Slack in again in Claude Code's connector settings and retry. The tracker canvas is large (over 250 KB), so the connector hands it over as a saved file, which the app reads back. The canvas is already connected. To connect a different one, run:

```
cd ~/Documents/coffeeshop
uv run coffeeshop slack connect <canvas link>
```

**Importing a saved canvas** (for example one of your old Weekly Contributions canvases): save its text to a file, then run `uv run coffeeshop slack import <file>`. The 2025 Weekly Contributions canvases are already imported.

## Daily three

Every morning, as the last step of the 8 AM sync (so it sees yesterday's work), Claude suggests **three small tasks**, each ten minutes or less, that each move one of your goals a step. Goals are offered in this order: V2MOM methods that are quiet, unstarted, or behind; the Performance map's Aim for next; V2MOM methods on track but with measures still open; Grade 6 or 7 key experiences that are gaps; and skills with little or no evidence. It reads only short summaries: the goals (names, status, progress, open measures), this week's context (the titles of this week's meetings, your open tasks, and the releases or projects your work was grouped into), and the titles of your last two weeks of work. Never your pasted notes or transcripts. If you saved a Projects and responsibilities note on Settings, that note is sent too; an empty box stops it. With only a few records, for example in your first days, the tasks lean on the goals themselves, and Claude is told not to make up a doc, release, or person that isn't in your titles.

```
cd ~/Documents/coffeeshop
uv run coffeeshop daily suggest           # today's three (does nothing if they already exist)
uv run coffeeshop daily suggest --force   # a new three, keeping any you've already done
uv run coffeeshop daily show              # print today's three
```

**On Home**, **Performance Progress** is the top cell. Open, it shows V2MOM and KSOs first, then the grade bars. Its title row has a small green bar for the next grade, and clicking the cell opens it. Under that are **Today's Three**, **New Entry**, and **Sync Status**. Each stays closed until you click it.

**New Entry** is for something a sync missed. **Gained a certification** is for a credential you earned, including one from before this notebook. **Date earned** appears so you can put the real date. It lands on the **Certifications** tab and counts as a training or certification. Every entry you add starts Claude reading it right away, in the background: it links the entry to the leveling guide and your V2MOM (your KSOs follow from the V2MOM methods), and marks its picks AI. Open the **Intake Review Queue**, check them, and press **Looks right**. If a sync is running when you add an entry, that sync's last step, or the next one, reads it instead. A row that Claude hasn't read yet says so.

- **Check one off:** press its box, add what you did if you like (optional), and press **Done**. It's logged as a finished task (from "daily"), so it counts like any other work, and the next sync links it to the leveling guide and your V2MOM.
- **Changed your mind:** press the checked box. The record it logged goes too, unless you wrote what you did, checked it in the Intake Review Queue, or made a win from it. Then the record stays, and checking the box again reuses it.
- **Suggest now** (when today's three aren't there yet) or **New three** (replace all three, even ones you checked off) asks Claude right away, with a progress box like the Sync buttons. A checked-off task stays in your notebook.
- When all three are done, the card says so.

Each task names its goal, like `V2MOM M4` or `Grade 6: …`. If Claude's answer doesn't fit (not exactly three, longer than ten minutes, or tied to a goal that wasn't offered), nothing is saved and the command says why. With no leveling guide and no V2MOM loaded there's nothing to aim at, so it says that instead. When it fails in the morning sync, the sync's usual notification says why and nothing is saved; the next sync that day tries again. The **Daily** chip in the Intake Review Queue turns green once today's three exist, and the sync log in `logs/` shows each run.

## Weekly digest

**Weekly digest** in the Menu shows the last seven days: how many records came in (and from where), the wins and kudos, the leveling guide items that gained evidence, and the week's activity counts next to this half's totals. **Week before** and **Week after** step through earlier weeks.

At the top are **nudges**, each with a link to where to act:

- **Aim for next:** the top two suggestions from the Performance map.
- **Big wins without "why it mattered":** medium and large wins with no impact sentence, which the performance case can't use well.
- **Quiet areas:** a Performance map area with evidence before but nothing in the last 60 days (unless it's already an Aim for next).
- **Quiet V2MOM methods:** each method of your current V2MOM with nothing linked in the last 30 days, or nothing linked at all. Methods the Doc marks Completed are left out, and so are weeks before the V2MOM's fiscal year. Each links to the **V2MOM** page.
- **The queue:** 25 or more records in the Intake Review Queue not checked yet.

When nothing needs you, it says so. The page is worked out when you open it, from the notebook only: no Claude, nothing stored.

On Fridays at 12:00 PM the schedule shows a notification like "This week: 13 wins, 54 records, 3 nudges. Open http://127.0.0.1:8765/digest". The notification doesn't open the link, so open the page from the Menu. To see it now: `uv run coffeeshop digest notify`. If **Refresh the performance case every Friday** is on in Settings, that same run also writes one performance-case draft for the last 12 months. The switch is off by default, and then Friday only shows the notification.

## Kudos: recognition from other people

**Sync Slack tracker** (and the scheduled sync) also looks for kudos: messages that mention you and recognize your work, in your **public and private Slack channels**. **DMs and group DMs are never searched.**

- It searches your @-mentions a week at a time (the first pull goes back a year) and leaves out your own messages and bots.
- **Before Claude sees anything**, messages without a word of praise (thanks, great, shout-out, congrats, appreciate, and so on) are dropped. A year of mentions can run into the thousands; only the ones with praise words are sent on.
- Claude then keeps only real recognition: praise, a shout-out, or thanks that says what you did. A bare "thanks!", thanks for an invite, requests, FYIs, and announcements that just list you among many people are dropped. When unsure, Claude drops it.

Each kept message becomes a **Kudos** record with a short **word-for-word quote** and who said it, like `Robin Vale: "really nice work on that planning meeting with the PMs!!!"`, with a link to the message. If Claude's quote isn't exactly in the message, the message's own words are used instead. On the Performance map, a kudos record **counts like a medium win**, and the performance case quotes it exactly.

You can also mark any record as kudos yourself: press **Kudos** in its row of the Intake Review Queue. Everything recognition-related is on the **Kudos** tab.

What to expect: the first pull (a year) takes several minutes; after that each sync only looks at the last couple of days. A week with more than 200 mentions (big release weeks) is read newest first, and the step says how many weeks were cut short.

Messages from private channels pass through Claude Code to be checked (only ones with praise words, and only their text, sender, and channel name). Your Slack user id and name are looked up once and saved in `slack_user.json` in the notebook folder. Kudos' last pull shows as the **Kudos** chip on Home and in the queue.

## Google Docs, Sheets and Slides you wrote

**Sync Google** (and the scheduled sync) also brings in the Google Docs, Sheets and Slides you worked on:

- **Files you own** that changed since the last pull.
- **Files someone else owns** where you were the **last person to edit** when the sync looked. Google Drive doesn't say how much each person edited, only who edited last, so this is the stand-in for "edited heavily". Since the sync runs twice a day, it catches most of your editing sessions.
- **Gemini meeting notes are left out**, and so is any file already linked to a meeting: those come in with the meeting.

Each file comes in as a **document** record like "Wrote doc: Release Manager Runbook" (or "Edited sheet: ..." for someone else's file), with a link, and Claude adds a two-line **AI summary** of what the file is and what it covers. If the same file changes again in a later week, a short "Updated doc: ..." record is added, which Claude groups with the first. A summary that fails is retried on the next sync, and the record stays meanwhile.

The **first pull goes back a year**, which can take several minutes. After that it's quick. Docs' last pull shows as the **Docs** chip on Home and in the queue.

To keep files out by title (Drive's search doesn't show folders, so skipping is by title text):

```
cd ~/Documents/coffeeshop
uv run coffeeshop docs skip "Untitled"
uv run coffeeshop docs skip               # list the rules
uv run coffeeshop docs unskip "Untitled"
```

Adding a rule also removes matching records already in the notebook, and **Remove** in the Intake Review Queue keeps a file out for good, including later updates.

The file's text passes through Claude Code to write the summary. Claude has no tools while it summarizes, and only the two lines are saved, not the file.

## GitHub: pull requests you merged or reviewed

The scheduled sync (8 AM and 6 PM) also reads your GitHub pull requests on github.com, through the `gh` command already signed in to your work account. No Claude is involved in reading them; only the title, repo, date, and link are kept.

- **PRs you wrote and merged** come in one record each, like "Merged PR: Add Cherry-Pick Report (example-automations#12)", with a link to the PR.
- **PRs you reviewed** come in as **one record per repo per week**, like "Reviewed 31 pull requests in example-org, week of Oct 19", with the list of PRs attached. A busy reviewer approves hundreds a year, mostly routine, so one record each would bury the Intake Review Queue. A week's record grows as more reviews arrive.
- The **first pull goes back a year**; after that each pull starts two days before the last one. Nothing is ever deleted by a sync.
- Then Claude links the new records to the leveling guide, like every other source. GitHub's last pull shows as the **GitHub** chip in the Intake Review Queue.

To pull right away instead of waiting for the schedule:

```
cd ~/Documents/coffeeshop
uv run coffeeshop github sync
```

To keep a repo (or any title text) out, for example this app's own PRs:

```
uv run coffeeshop github skip example-org/notes-app
uv run coffeeshop github skip                    # list the rules
uv run coffeeshop github unskip example-org/notes-app
```

Adding a rule also removes the matching records already in the notebook. **Remove** in the Intake Review Queue works too, and a removed week stays removed.

If `gh` is not installed or not signed in, that step is skipped and you are not notified. Install it and run `gh auth login` when you want pull requests in the notebook.

## V2MOM: your Vision, Values, Methods, Obstacles, and Measures

The V2MOM app won't let the command line sign in, so the app reads your V2MOM from the PDF the V2MOM app exports (recommended: it has every measure's progress and comments, and your check-ins) or from a Google Doc you paste it into.

**The easy way.** In the V2MOM app, use **download as PDF**. Open **V2MOM** in the Menu and press **Upload and read**. The PDF is saved in your notebook folder, readable only by you, and the app starts reading it. The page says which one is active, like "Active: FY27 V2MOM, read Nov 3". A new fiscal year is kept beside the old one; last year's methods and the work already linked to them stay as they were.

The command still works. Save the PDF (keep the name it gives you, something like "FY27 V2MOM Your Name.pdf") and connect it once:

```
cd ~/Documents/coffeeshop
uv run coffeeshop v2mom connect ~/Desktop/"FY27 V2MOM Your Name.pdf"
uv run coffeeshop v2mom sync
```

The app pulls the text out of the PDF on your laptop (with pypdf), then Claude (with no tools) picks out the fiscal year, the vision, the values, each method in order (M1, M2, …) with its description and its measures (each with its status, its percent, and any comments), the obstacles with the methods they relate to, and the check-ins with your manager's comments. The PDF doesn't print a method's own status or percent, so the app works them out from its measures: the percent is the average of the measures' percents (a Completed measure counts as 100), and the status is Completed when every measure is, On Track when any has progress or says On Track. If it can't find any methods, it says so and nothing changes.

**Or a Google Doc** (still works): open your V2MOM in the V2MOM app, expand each method so its measures show, select the whole page, copy, and paste it into a new Google Doc; the page's extra text is ignored. Then connect the Doc's link instead: `uv run coffeeshop v2mom connect "https://docs.google.com/document/d/…/edit"`. The sync reads it through Claude Code's Google Workspace connector. The Doc has no check-ins or measure comments. Connecting the PDF later keeps your methods and their links.

**Keeping it current.** The scheduled sync re-reads your V2MOM once a month. After each check-in, download the PDF again and upload it on the V2MOM page. If you connected a folder, save the new PDF there and press **Sync V2MOM** on Home.

Which file is read:

- The name must contain "V2MOM".
- A re-download saved as "… (1).pdf" is picked up. You do not connect it again.
- The latest fiscal year in the name wins. Opening last year's PDF does not replace this year's. An FY28 PDF is picked up on its own.
- If the file is gone, the sync says where to save it.

With a Doc, paste the updated page over the Doc's text instead. Methods are matched by name, so reordering them is fine, and a method renamed in the same place keeps its row. A method you drop is kept but marked inactive, so anything linked to it still makes sense. A new fiscal year (FY28) starts a new V2MOM and leaves last year's as it was.

**The V2MOM chip** (on Home and at the top of the Intake Review Queue) is green when your V2MOM was read in the last 31 days, orange when it's older, and grey with a hint when nothing is connected yet. The PDF's path or the Doc's id is kept in `v2mom.json` in the notebook folder, readable only by you (a `v2mom.doc` from before still works). An upload is saved in that folder as `v2mom/V2MOM.pdf`, also only you can read it. A PDF you connected with the command stays where you saved it. The text passes through Claude Code to be read.

**Linking your work to methods.** Once the V2MOM is loaded, Claude's read-through of new records (right after you add an entry, after every sync, and the queue's **Have Claude read** button) also picks the V2MOM methods each record really moves forward: none for routine meetings and status pings, at most two. It's the same read as the leveling-guide links, so it costs no extra Claude time. In the Intake Review Queue they show as chips with the method's name, shortened if it's long (hover for the full name), purple when Claude picked them. **Looks right** makes them yours, **&times;** on a chip removes it for good (Claude won't put it back), and **edit** opens the linking page, which now has a **Which V2MOM methods does this move forward?** list at the top. Once you've changed a record's methods, Claude leaves them alone. A method that's no longer in your current V2MOM (dropped, or last year's) still shows its name; hover says so. It stays so the history makes sense.

**Linking what's already in the notebook** (once, after the first V2MOM sync). Records Claude read before the V2MOM existed have no methods yet. This reads them in batches of 40 (about 16 batches for 600 records, a few minutes):

```
uv run coffeeshop v2mom tag --all     # every record
uv run coffeeshop v2mom tag           # just the last 90 days
```

It skips records already read against the V2MOM and ones whose methods you set, so running it again only does what's left (for example after a batch failed). Its picks are marked AI too, including on rows you'd already checked. Record text and the V2MOM's methods pass through the AI tool.

### The V2MOM page

**V2MOM** in the Menu shows your current V2MOM. At the top it says which one is active, like "Active: FY27 V2MOM, read Nov 3", then how many methods had work this quarter, when it was published, and when the app last read your PDF or Doc. **Upload and read** takes a new PDF. **Vision and values** folds open to its vision and values.

Below, one row per method, in your V2MOM's order:

- **A dot:** green when something was linked in the last 30 days, orange when it has gone quiet (work before, nothing in 30 days), grey when nothing is linked yet.
- **M1 and the name**, then the **status** as a chip (green for Completed, orange for At Risk, Off Track or Behind) and its **percent** as a small bar (from the Doc, or worked out from the measures for a PDF).
- **The numbers:** wins plus records linked to it **this quarter** (calendar quarters: Jan to Mar, Apr to Jun, Jul to Sep, Oct to Dec) and **in FY27** (the company's fiscal year, Feb 1 to Jan 31; FY27 runs Feb 1, 2026 to Jan 31, 2027), and the date of the latest one. A win made from a linked record counts too, so a record and its win count as two. An open task doesn't count until it's done.
- **The measures**, each with its own status chip, its percent as a small bar, and **Comments** folded under it when it has any.
- **About this method** folds open to the description and any obstacles related to it (an obstacle related to two methods shows under both). Obstacles that don't name a method are listed at the bottom.

**Check-ins** (from the PDF) is folded at the bottom: each check-in by name with your manager's comments, or "No manager comments."

**see the work** opens that method's page: its wins and linked records, newest first. To change which methods a record moves forward, use **edit** on its row in the Intake Review Queue.

On **Home**, a strip under the readiness bars says "V2MOM: 6 of 8 methods active this quarter", with a small bar per method (how many wins and records it has this quarter, longest for the busiest; orange for a method that's gone quiet). Click the line for the V2MOM page, or a bar for that method. The strip is hidden until a V2MOM is loaded. Everything here is worked out when the page opens, from the notebook only: no Claude, nothing stored.

The performance case then shows how your work lines up with your V2MOM (see **V2MOM alignment** under the performance case).

## KSOs: how your manager rates the year

KSOs (Key Strategic Objectives) are what your manager rates 1 to 5, once a year for Delivery, against the goals in your V2MOM. The app reads this year's KSO material (the framework deck and the guide and FAQ canvases) into your notebook only, because it's internal, and keeps one copy per fiscal year.

**Connect a year** (once a year, or when the material changes):

```
uv run coffeeshop kso connect --deck <the KSO framework deck link> --canvas <the KSO guide canvas link> --canvas <the FAQ canvas link>
```

It reads the deck through the Google connector and the canvases through the Slack connector. Claude then sorts them into the KSOs, their weights, their components, the five rubric levels for each, a few example daily or weekly tasks, and the key dates. A bad read changes nothing. `--track` picks your track (Delivery by default), and `--manager` keeps the people-manager parts. Running `uv run coffeeshop kso connect` with no links re-reads the saved ones.

**Which V2MOM methods count toward which KSO part.** After connecting, Claude matches each V2MOM method to the one KSO component it gives the most evidence for (marked AI). New methods are matched after each monthly V2MOM sync. `uv run coffeeshop kso show` lists each component and its methods; a component with none says "no V2MOM goal yet", and every component needs one. `uv run coffeeshop kso map --redo` asks Claude again for its own matches; yours never change.

**The KSOs page** (Menu > KSOs) shows this year's KSOs, with a year picker once there's more than one.

- **At the top:** the year in use, like "KSOs: FY27 Delivery", then how you're rated, and the next key dates. Older years stay in the year picker.
- **One card per KSO:** what it measures, and a bar. Then one row per part:
  - **The bar:** the average progress of the V2MOM methods that count toward the part, taken from your V2MOM. A part with no V2MOM goal gets a warning and counts as 0 in the KSO's bar, because your manager counts a missing one against you too.
  - **What the manager looks at,** in plain words.
  - **The methods that count,** each with a **Move** list to point it at another part. That makes the pick yours.
  - **How many wins and records** back those methods this year, plus your kudos count for the feedback part.
  - **Try this week:** a few small things to do.
  - **What a 4 and a 5 look like,** from the rubric.
- **Your rating:** set a guess per KSO, or the real rating once your manager has entered it.

The practice notebook has made-up KSOs, so you can try the page without real material.

**Claude's estimate.** Once a month (once KSOs are read and some V2MOM method counts toward a part), right after the V2MOM step of the sync, Claude reads the rubric against what your V2MOM shows for each part (status, progress, measures, comments), the titles of the work linked to those methods this year, and your kudos count. It then guesses the 1 to 5 your manager would give each KSO. Each KSO card shows the guess (marked AI), one line per part on why, and the three next steps that would raise it most, next to the rating you set. Press **Re-estimate** to run it now, or run `uv run coffeeshop kso estimate`. A bad answer changes nothing, and the **KSO estimate** chip shows when it last ran. The daily three also offers KSO parts with no V2MOM goal, and the part furthest behind, as goals.

## Year-end exports

At year end, pick the year on the Wins tab and click **Download as Markdown**. The file opens with your large wins as highlights, then lists everything by theme with its date and why it mattered. Paste it into a promotion doc or use it to pick resume bullets. Removing a notebook entry never removes a win made from it.

## What you should see

The app has these pages, opened from the three-bar **Menu** at the top left (Home, Wins, Performance map, V2MOM, KSOs, Intake Review Queue, Weekly digest, then Meetings, Conversations, Documents, Tasks, Kudos, Other). The name of the page you're on sits next to the Menu button:

- **Home**: Performance Progress, Today's Three, New Entry, then Sync Status. Each cell stays closed until you click it.
  - **Performance Progress:** V2MOM and KSOs first, then the grade bars. The title row has a small green bar for the next grade. Clicking the tile opens it; it does not leave Home.
  - **Today's Three:** see **Daily three** above. The practice notebook shows a made-up three (run `demo seed` again on a new day to see it).
  - **V2MOM:** how many of your V2MOM's methods had work this quarter, with a small bar per method (see **The V2MOM page**). Hidden until a V2MOM is loaded.
  - **KSOs:** a bar for each KSO this year. Hidden until KSOs are loaded.
  - **Grade bars:** a bar each for Grade 6 and Grade 7, showing how many key experiences are shown, with a percentage (hover for the detail; click for the Performance map).
  - **Four tiles:** leveling-guide skills with evidence, wins this half, kudos this half, and records waiting in the Intake Review Queue.
  - **Momentum:** a small chart of evidence per week (wins plus records linked to the guide) for the last 12 weeks, with the current week in darker green. Hover over a bar for its count.
  - **Next:** one line with the Performance map's top Aim for next.
  - **Sync Status:** the Sync buttons and the last-pull chips for Calendar, Tasks, Docs, Slack, Kudos, and the V2MOM. Closed until you click it.
  - There's no day-by-day list here any more. The daily review happens in the Intake Review Queue, and the Friday digest covers the week. Every record is still on its tab.
- **Wins**, **Performance map**, **V2MOM**, **KSOs**, and the **Intake Review Queue**: described in their own sections above.
- **Meetings / Conversations / Documents / Tasks / Kudos / Certifications / Other**: one tab per kind of entry, newest first. Each entry is one line: a small icon for where it came from (calendar, Slack, Docs, GitHub, Tasks, kudos, or a pencil for typed), the text, and four icon buttons on the right (hover for their names):
  - **+** adds notes or a link to it.
  - **Trophy** counts it as a win.
  - **Target** links it to the leveling guide.
  - **×** removes it.
  The add and win buttons open a small panel over the list; only one is open at a time, and Escape closes it. Under the line, small chips show what's attached: links by name (hover for the address; **×** on the chip removes it), notes and AI summaries (click to read), and the guide items it shows or might show. On **Tasks**, anything still open is listed at the top, and finished tasks are grouped by the day you completed them.

The page opens in **dark mode**; the small sun button next to **Coffee Shop** (top right) switches to light (a moon switches back), and the app remembers your choice. Longer explanations on each page are folded behind **How this works**; click it to open. Dates are short ("Oct 29"); hover over one for the full date.

## Testing steps (about 5 minutes, in the practice notebook)

1. Start the practice notebook (above) and open http://127.0.0.1:8765. A note at the top says it's a practice notebook.
2. On **Home**, add an entry ("Paired with Sam on the release", kind "Had a conversation") and check you land on **Conversations** with it at the top.
3. Open **Wins**: two made-up wins are there. Use **Count this as a win** on your new entry, pick a size, and save; it asks which leveling guide items it shows.
4. Open **Performance map**, then **Promotion (optional)**: the made-up guide shows a few experiences as started or shown.
5. Open the **Intake Review Queue**, pick **Everything** in the first menu, and try **Looks right**, **Looks right for selected**, a type button, and **Remove** on a row. Rows update without the page reloading. Tick **No V2MOM method** and press **Show**.
6. Search for "rollback" with the box at the top.

If something looks wrong or confusing, note what you clicked and what you saw.

## Running the automated tests

```
cd ~/Documents/coffeeshop
uv run pytest
```

Every test should pass: the last line says `passed`, with no `failed`. A failure means something broke. Don't use the app until it's fixed.

## What comes next

Your personal notebook is connected to Google Calendar, Google Tasks, Google Docs, your Slack messages and tracker canvas, Slack kudos, and GitHub, and Claude links what comes in to the leveling guide. Ideas still open:

1. **Fill in older history.** Older Google Calendar history needs a little setup: the Claude connector reaches back 14 days at most (`uv run coffeeshop calendar pull --days 14`), while connecting the calendar's private iCal address (`calendar connect`) lets `calendar sync --days 60` go back two months at a time. Slack messages older than 90 days are not searched.
2. **Keep the approvals questions in mind:**
   - Do the owners of the customer-related channels and repos mind a personal tool keeping titles and short notes from them?
   - Is Claude, through Claude Code, approved for this kind of work content?
   - Is the notebook folder backed up (Time Machine) and kept out of synced folders (iCloud, Dropbox)?
3. **At year end,** download the performance case from the Performance map and your wins from the Wins tab.

Keep real data out of `/tmp/cos-demo`; the practice notebook never syncs with Slack or Google.

## Q&A

**Can one entry hold several pieces, like a link plus notes plus a transcript?**
Yes. An entry is the thing you did ("Rollout sync with Sam"). Under it you can attach any number of pieces, each with a type (meeting notes, transcript, link, Slack canvas, prompt, other text) and an optional name. Removing the entry removes its pieces. Pasted text is shown as plain text only, and links are never opened or fetched by the app. Each piece is limited to about 200,000 characters.

**How do I search?**
Use the search box at the top of any page. It looks through your entry headlines, pasted text, and names, and every word you type must appear somewhere in the entry. It is not case-sensitive and the match is highlighted. `%` and `_` are searched as ordinary characters.

**Is my real notebook backed up?**
Yes, on this laptop. `uv run coffeeshop backup now` copies the notebook into `backups/` in the notebook folder, safely even while the app is running, and the daily automatic sync does it too. It keeps the last 30 days plus the first copy of each of the last 12 months, and deletes older ones. `uv run coffeeshop backup list` shows them. These copies sit next to the notebook, so they protect against mistakes, not against losing the laptop: for that you'd also need Time Machine or a copy somewhere else.

**How do I restore from a backup?**
1. Stop the app (Ctrl+C in its Terminal window).
2. In the notebook folder (`~/Library/Application Support/coffeeshop` on a Mac, `%LOCALAPPDATA%\coffeeshop` on Windows), move `coffeeshop.db`, `coffeeshop.db-wal`, and `coffeeshop.db-shm` into a spare folder (don't delete them yet).
3. Copy the backup you want from `backups/` (for example `coffeeshop-2026-10-28.db`) into the notebook folder and rename it `coffeeshop.db`.
4. Start the app again with `uv run coffeeshop serve` and check your entries. Once you're happy, the moved files can go.

**How do I pull in my Google Calendar meetings?**
This uses your calendar's private address, so no Google Cloud setup or admin sign-off is needed, and the data never passes through an AI tool. One-time setup:
1. In Google Calendar on the web, open Settings, pick your calendar under "Settings for my calendars", and scroll to **Integrate calendar**.
2. Copy the **Secret address in iCal format**. Treat it like a password: anyone with it can read that calendar.
3. In Terminal (in `~/Documents/coffeeshop`): `uv run coffeeshop calendar connect`, paste it (nothing shows as you paste), and press Enter.
4. `uv run coffeeshop calendar sync` pulls the last 14 days (`--days 30` for more, max 60).

Meetings show on the **Meetings** tab with a small calendar icon. Hover it for the source, kind, and date. Only the **title and time** are kept. Attendees, descriptions, locations, and video links are dropped before anything is saved. All-day items and cancelled meetings are skipped.

Running it again does not add a second copy. A meeting Sync Google already saved, with the same day and title, is left as it is, and this command does not delete those. A meeting this command saved is updated if you rename or move it, and removed if it disappears, unless you attached notes. Anything you typed yourself is never touched.

The address is stored in `calendar.url` in your notebook folder, readable only by you. If you reset the secret address in Google, run `connect` again.

Before using it on a work calendar, check that titles of meetings (which can name other people or customer-related topics) are okay to keep on this laptop. This iCal route isn't part of the scheduled sync; the scheduled sync uses the Sync Google route below.

**Can I sync my calendar without the secret iCal address?**
Yes. On Home, press **Sync Google**. For the calendar part only, run `uv run coffeeshop calendar pull`.

Sync Google does four things, then has Claude link the new records to the leveling guide:

- **Calendar.** Only meetings that have ended come in. One later today shows up on the first sync after it ends, which is usually when its Gemini notes are attached. The 8 AM sync catches notes that arrived overnight. Declined meetings and all-day items are skipped. Title, time, and Google file links (notes, recordings) are saved.
- **Docs you wrote.** See that section. Only files from the last 7 days are summarized. A failure is tried again on the next sync, while the file is still inside that window.
- **Tasks.** Only tasks you have marked complete in Google, from lists that changed since the last pull. Open tasks never come in. One you finish shows up on the next sync, dated the day you completed it. A task you removed while it was open still comes in once you finish it. A list that could not be read is reported, never treated as deleted, and the pull is not counted, so the next Sync Google looks back to the same point.
- **Meeting notes.** The Docs attached to each meeting are read, and a short "AI summary" is saved under the meeting. Meetings without notes say so. Recordings and chat files are not read. A failed summary is tried again next time.

A progress bar under the button ticks through each step and shows any error in plain words. You can keep using the app while it runs. If the calendar connector answers with an error, for example an expired Google sign-in, that step stops with the message. It is not read as an empty calendar, so no meetings are removed.

The calendar part starts Claude Code with permission to use only the calendar tool, and fetches yesterday and today through the Google Workspace connector. Meeting titles, times, and attendee details pass through Claude, so this runs only when you press the button or when the schedule you installed runs it. It needs Claude Code and the Google Workspace connector signed in. `uv run coffeeshop calendar pull --days 7` reaches further back (max 14). Nothing is saved twice.

**Where is my information stored, and is it backed up?**
Everything (entries, pasted notes, wins) is in one file, `coffeeshop.db`, in the notebook folder (`~/Library/Application Support/coffeeshop` on a Mac, `%LOCALAPPDATA%\coffeeshop` on Windows), on this computer only. It is not in iCloud, OneDrive, or any synced folder, and the app refuses to keep a real notebook in one. Time Machine backs it up on a Mac if Time Machine is on. Daily copies go into `backups/` next to it (see "Is my real notebook backed up?" above).

**Can I export everything, not just wins?**
Yes. Click **Download everything (CSV)** at the bottom of any page. You get one zip with six spreadsheets: `entries.csv` (every meeting, task, and note), `pasted_notes.csv` (everything pasted under them, with the entry it belongs to), `wins.csv`, `guide_links.csv` (which wins and entries you linked to which leveling guide items), `v2mom_links.csv` (which ones advance which V2MOM method), and `promo_drafts.csv` (every section of every performance case draft). They open in Excel, Numbers, or Google Sheets, so the data stays readable even without this app. It's a snapshot of that moment; download a fresh one whenever you like, for example at year end. The zip holds everything you pasted, so keep it somewhere as safe as this laptop, and remember that removing something in the app doesn't remove it from zips you already downloaded. Text that starts with `=`, `+`, `-`, or `@` gets a leading `'` so a spreadsheet shows it instead of running it as a formula.

**After a restart the app opened with demo data and my entries were missing. Were they lost?**
No. The app had been started with `--data-dir /tmp/cos-demo`, which opens the practice folder instead of your notebook. Run `uv run coffeeshop serve` with no `--data-dir` and your notebook comes back.
