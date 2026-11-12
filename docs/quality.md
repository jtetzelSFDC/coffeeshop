# Coffee Shop: what good output looks like

What each AI feature should produce, written before anyone tunes a prompt, so a change can be checked against it. Examples use made-up data only. The prompts themselves are listed in [prompts.md](prompts.md).

- [Today's three](#todays-three)
- [What comes in from Slack](#what-comes-in-from-slack)
- [What comes in from Google](#what-comes-in-from-google)
- [After every sync: the read-through](#after-every-sync-the-read-through)
- [Write my performance case](#write-my-performance-case)
- [Weekly digest](#weekly-digest)

## Today's three

`daily.py`. Three small tasks each morning, each ten minutes or less, each moving one of your goals (a V2MOM method, a KSO part, or a next-level Performance map item) a small step.

Good output:
- Exactly three tasks, each tied to a goal that was offered, three different goals when there are three.
- Each takes ten minutes or less, or is a simple daily habit, and needs no one's permission.
- Specific to your work: it names the doc, release, or role from your recent titles.
- Doesn't repeat something your recent titles show is done.
- One plain line starting with a verb, and a short why that says what the step moves.
- With only a few records, it leans on the goals themselves and says so, instead of making up context.

| | Task | Why |
|---|---|---|
| Good | Add a rollback step to the Maple 2.4 runbook · 8 min · V2MOM M2 | M2 has had no linked work in 30 days |
| Good, few records | Write one line on what "done" means for KSO 1.2 · 5 min · KSO 1.2 | No V2MOM goal covers this part yet |
| Bad | Network with senior leadership | Not ten minutes, needs other people, not tied to anything you did |
| Bad | Follow up with Dana on the audit | No Dana and no audit in your titles: invented |
| Bad | Finish the Maple 2.4 release notes | Your titles already say "Wrote Maple 2.4 release notes" |

## What comes in from Slack

`slack/`. Two jobs. The tracker canvas becomes one record per work item, sorted into the right kind. Kudos keeps only real recognition from other people in public and private channels (never DMs), as an exact quote with who said it.

Good output, tracker:
- One record per canvas item; syncing again adds nothing new.
- The kind matches what you did: a scheduled call is a meeting, a discussion is a conversation, writing something lasting is a document, hands-on work is a task, and anything unclear is Other.
- The tracker's own text is kept under the record, marked as written by Slack's AI, with a link to the thread.

Good output, kudos:
- Kept only when someone praises or credits what you did, or thanks you for something named.
- The quote is word for word from the message, 30 words or fewer, and says who said it.
- Never your own messages, bots, or DMs. When unsure, dropped.

| | Item | Result |
|---|---|---|
| Good | "Deployment: Maple 2.4 to UAT" | task |
| Good | "Release sync: Maple 2.4 go/no-go" | meeting |
| Bad | "Release sync: Maple 2.4 go/no-go" | task (it was a call, not the deploy) |
| Good kudos | Sam Sample: "thanks for untangling the merge conflicts before the freeze, saved us a day" | kept, quoted exactly |
| Bad kudos | Sam Sample: "thanks!" | kept (no reason given; should be dropped) |
| Bad kudos | "@Avery can you review this PR?" | kept (a request, not recognition) |

## What comes in from Google

`google/`. Calendar meetings, finished tasks, and the Docs, Sheets, and Slides you wrote come in through the connector, parsed by code; Claude only runs the connector tool there, and its own words are thrown away. Claude writes two things: a summary of a meeting's notes, and a two-line summary of each file you wrote.

Good output, meeting notes summary:
- One or two sentences on what the meeting was about, then "Decisions:" and "Action items:" bullets (with the owner when the notes name one). Empty sections left out.
- Only what the notes say. "The notes don't say" beats a guess.
- Plain text, no headings or bold.

Good output, file summary:
- Exactly two short lines, under 50 words: what the file is, then what it covers or decides.
- Nothing about what it skipped, no risks, nothing from outside the file.

| | Summary |
|---|---|
| Good meeting | Planned the Maple 2.4 cutover. Decisions: freeze starts Thursday. Action items: Avery updates the runbook; Sam books the UAT window. |
| Bad meeting | A productive session where the team aligned on strategy and showed strong ownership. (Says nothing, adds praise the notes don't have.) |
| Good file | Runbook for refreshing the training sandbox.<br>Covers the order of steps, who approves, and the post-refresh checks. |
| Bad file | This document appears to be a runbook. I skipped the appendix. Risks: it may be out of date. (Guessing, notes on itself, a third line.) |

## After every sync: the read-through

`guide/`, `v2mom/links.py`. After Slack, Google, and GitHub records come in, Claude reads them against the leveling guide and the V2MOM, groups records of the same work, and tags each with one activity. Every pick is marked AI until you check it.

Good output:
- Guide and V2MOM links only when the record is real evidence. An empty list beats a weak link; standups, 1:1s, and status pings get none.
- Next-level items only when the record shows that level (owning or leading it across teams).
- A win only for a real accomplishment, with an impact sentence that uses only facts in the record. Most records aren't wins.
- One piece of work groups records of the same release, refresh, or doc, not "everything about releases".
- An activity only for what was done, not discussed: a meeting about a deploy isn't a deployment.

| | Record | Result |
|---|---|---|
| Good | "Deployed Maple 2.4 to UAT" | activity: deployment; joins "Maple 2.4 release" |
| Bad | "Weekly release sync" | activity: release; guide link to "Leads release planning" (a routine meeting) |
| Bad win | "Fixed a typo in the runbook" | win, large, "saved the team 40 hours" (inflated, number invented) |

## Write my performance case

`promo/`. A third-person draft in the Performance Advocacy Tool's sections (Project Highlights, Business Contributions, Professional Development, Feedback, and Promotion Readiness: Strategic Business Need and Talent Readiness), written only from the numbered evidence built from your notebook, every sentence citing its sources. The section guidance comes from `data/pat/pat-template.docx`.

Good output:
- Every sentence cites one or more evidence numbers, and they're in that section's evidence.
- Every number in a sentence appears in the evidence. No new names, teams, dates, or outcomes.
- Kudos and manager check-in comments are quoted exactly, saying who said them.
- A V2MOM method is named only when a cited piece says the work advances it.
- Plain, concrete English; no hype words.
- Strategic Business Need is at least 25 words. Talent Readiness stays within 400 words.
- Feedback quotes the person, and the same story is not repeated just to fill another section.
- With little evidence, a short section or "No evidence for this section in the window", never padding past what the evidence supports.

| | Sentence |
|---|---|
| Good | Pat led the Maple 2.4 release across three teams, coordinating 4 deployments between Mar 2 and Mar 20. [12, 31] |
| Good | Sam Sample wrote that Pat's work on the merge conflicts "saved us a day". [18] |
| Bad | Pat spearheaded a transformational release program. [12] (hype, no fact) |
| Bad | Pat cut release time by 40%. [12] (40 isn't in the evidence; flagged **Check this**) |
| Bad | Pat's runbook work advances V2MOM M3. [22] (piece 22 doesn't say it advances M3) |

## Weekly digest

`digest.py`. **It doesn't use Claude.** The page is worked out by code from the notebook when it opens, and nothing is stored; the Friday notification line is written by code too. It shows what the week added and a few nudges, each linking to where to act. Its quality rests on what the AI features above saved during the week (wins, links, activity tags).

Good output:
- Counts match the week's records and wins; open tasks don't count.
- Each nudge says what to do and links to the page to do it.
- When nothing needs you, it says so.

| | Nudge |
|---|---|
| Good | 2 big wins without "why it mattered". A sentence each makes them count in the performance case. → Open Wins |
| Good | Nothing new for V2MOM M3 (Grow the pipeline toolkit) in 30 days (last: 2026-02-02). → Open the V2MOM |
| Bad | You should do more this week. (No action, no link.) |
