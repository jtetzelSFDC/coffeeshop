# Coffee Shop: every Claude prompt

The one place to look for the prompts. Each is a module constant next to the code that checks Claude's answer, because a prompt and its check have to change together; this index doesn't move them. What good output looks like is in [quality.md](quality.md).

Every prompt runs through `claude_cli.ask()`: tools off, one turn, data on stdin, and the prompt says the data is never instructions (the meeting-notes prompt is the one exception, below). Prompts that only tell Claude to call one connector tool (`call_tool`, `call_tools`) aren't listed: Claude's words are thrown away there, and code parses the tool's answer.

**Role and level.** Prompts 1, 2, 6, and 7 use the role and level you saved. A DevOps Grade 5 reads as someone on the DevOps path, going for Grade 6, with some Grade 7 work. Another role or grade changes those words. A few sample titles in the grouping, impact, and Slack prompts are still written as DevOps work.

| # | File and constant | For | Decision |
|---|---|---|---|
| 1 | `daily.py` `PROMPT` | Today's three | Change |
| 2 | `guide/ai_review.py` `PROMPT` + `REPLY` | Read-through: guide links, kind, win | Change |
| 3 | `v2mom/links.py` `PROMPT_PART` | Read-through: V2MOM links (appended to 2) | Keep |
| 4 | `v2mom/links.py` `TAG_PROMPT` | V2MOM links for already-read records | Keep |
| 5 | `guide/work.py` `PROMPT` | Group records into pieces of work | Change |
| 6 | `guide/activities.py` `PROMPT` | One impact activity per record | Change |
| 7 | `promo/write.py` `PROMPT` | One section of the promo case | Change |
| 8 | `slack/classify.py` `PROMPT` | Kind of each tracker canvas item | Keep, then change |
| 9 | `slack/kudos.py` `FILTER_PROMPT` | Keep real recognition, pick a quote | Keep |
| 10 | `google/summaries.py` `PROMPT` | Summary of a meeting's notes | Keep |
| 11 | `google/docs.py` `SUMMARY_PROMPT` | Two-line summary of a file you wrote | Keep |
| 12 | `v2mom/connector.py` `PROMPT` | V2MOM from a Google Doc | Keep |
| 13 | `v2mom/connector.py` `PDF_PROMPT` | V2MOM from the PDF | Keep |
| 14 | `kso/framework.py` `PROMPT` | KSO framework from the deck and canvases | Keep |
| 15 | `kso/map.py` `PROMPT` | Match V2MOM methods to KSO parts | Keep |
| 16 | `kso/estimate.py` `PROMPT` | Monthly 1 to 5 guess per KSO | Keep |

That's 15 prompts; `PROMPT_PART` (3) is a piece of 2, listed so its rule isn't missed.

## 1. Today's three

`daily.py` `PROMPT`. Three tasks of ten minutes or less, each tied to one offered goal.
- **Gets:** up to `MAX_GOALS` 15 goals (V2MOM methods, KSO parts, Promo map items, skills; each clipped to 50 to 160 characters, at most 3 open measures and 2 KSO ideas) and up to `MAX_RECENT` 40 titles from the last `RECENT_DAYS` 14 days, each clipped to 100. All of it fits `MAX_CONTEXT` 8,000 characters: old titles go first, then the least useful goals, but `MIN_RECENT` 10 titles stay.
- **Checked by:** `validate()`: exactly 3 tasks, text up to 110 characters (prompt asks 90), why up to 90 (prompt asks 75), minutes a whole number from 1 to 10, goal one of the ids offered. A bad answer saves nothing.
- **New user:** no guide and no V2MOM means no goals, and it refuses with a plain message before asking. With a few records, `recent` is short and the prompt still asks for work-specific tasks, so Claude may invent detail.
- **Decision: keep.** It uses this week's records and the saved level, and it says so when there are few records.

## 2. Read-through

`guide/ai_review.py` `PROMPT` + `REPLY` (with 3 added when a V2MOM is loaded). For each record: guide items it shows, its kind, and whether it's a win.
- **Gets:** `BATCH` 20 records (full text, plus attached Slack, AI summary, and task notes, 900 characters each and 1,500 in all), the whole guide (experiences with descriptions up to 400, skills up to 300), the win themes, and the V2MOM methods (description up to 300, 6 measures up to 150). 3 batches at a time.
- **Checked by:** `_apply()`: only offered guide ids, at most `MAX_LINKS` 3; kind only from meeting, conversation, document, task, certification, or note, and never for calendar, tasks, GitHub, docs, or kudos records, or a certification you chose; a bad win size becomes small and an unknown theme is dropped. Links you made, checked rows, and a kind you changed meanwhile are never overwritten. Everything is marked AI. If no batch reads, nothing changes.
- **New user:** refuses without a guide. A few records make one small batch, which is fine. Win impact "no invented numbers" is only asked, not checked.
- **Decision: change.** Replace "DevOps release manager", `GRADES`, and "Grades 6 and 7" / "Grade 7 ... Grade 6" with the saved role and levels; the rules stay.

## 3. Read-through: V2MOM part

`v2mom/links.py` `PROMPT_PART`. Adds rule 4 to 2: the V2MOM methods each record moves forward.
- **Gets:** the V2MOM methods in 2's data.
- **Checked by:** `apply_ai()`: only offered method ids, at most `MAX_PICKS` 2; methods you set are never changed.
- **New user:** only added when a V2MOM is loaded, so it's simply absent without one.
- **Decision: keep.** Its rule is the same sentence as 4's; edit both together.

## 4. V2MOM links for records already read

`v2mom/links.py` `TAG_PROMPT`. The one-time backfill (`v2mom tag`) for records read before the V2MOM existed.
- **Gets:** the V2MOM methods (as in 2) and `BATCH` 40 records (full text, no notes). 3 batches at a time.
- **Checked by:** `apply_ai()`, as in 3. If no batch reads, nothing changes.
- **New user:** refuses without a V2MOM. Usually not needed, since 3 covers new records.
- **Decision: keep.** Clear and checked; shares its rule with 3.

## 5. Group into pieces of work

`guide/work.py` `PROMPT`. Joins records of the same release, refresh, or doc into one piece of work, so it's counted once.
- **Gets:** `BATCH` 40 records, oldest first, text clipped to 500, and up to `OPEN_ITEMS` 60 open pieces of work active in the last `WINDOW_DAYS` 14 days and started within `MAX_SPAN_DAYS` 30.
- **Checked by:** `group()`: a join only to a piece that was sent or made in the same batch, and only when it fits the 14 and 30 day windows; new titles cut to 200; records you grouped or split are never regrouped.
- **New user:** no open work, so it starts pieces or leaves records alone; fine.
- **Decision: change.** Replace "DevOps release manager" with the saved role, and the release and sandbox example titles with role-neutral ones.

## 6. Impact activity

`guide/activities.py` `PROMPT`. Tags each record with the one activity it shows, for the Promo map counts.
- **Gets:** the 13 `ACTIVITIES` (key and meaning) and `BATCH` 40 records, text clipped to 500 and notes to 600. 3 batches at a time.
- **Checked by:** `tag()`: an unknown key becomes no activity; one you set is never changed.
- **New user:** fine with few records.
- **Decision: keep.** The prompt uses the saved role. The activity list is still DevOps work (deployments, sandbox refreshes, branch audits). Other roles need their own list later.

## 7. Promo case section

`promo/write.py` `PROMPT`. Writes one of five sections from that section's numbered evidence, in the third person, every sentence citing its sources.
- **Gets:** the section's slice of `promo/evidence.py`'s pieces, capped by `CAPS` (40, or 50 for accomplishments), from a window of 365 days by default. Piece text is clipped: check-in comments 600, kudos 400, single records 200, 4 records per piece of work at 120, 3 V2MOM examples at 80; at most 15 wins in the summary, 20 kudos, 60 single records. 3 sections at a time.
- **Checked by:** `check()`: sources must be in this section's evidence, and every number in a sentence must appear in it. A failing sentence is kept and flagged **Check this**. A section with no evidence says so; no linked work at all refuses before asking; if every section fails, nothing is saved.
- **New user:** with little evidence the prompt still asks for 3 to 8 sentences per section, which invites padding.
- **Decision: keep.** The prompt and the section descriptions use the saved role and level. Too little evidence refuses before asking Claude, and an activity count is used only in a section that also cites that kind of work.

## 8. Slack tracker kinds

`slack/classify.py` `PROMPT`. Sorts each tracker canvas item into meeting, conversation, document, task, or note.
- **Gets:** `BATCH` 30 items, each its headline plus the canvas description clipped to 1,200. 3 batches at a time.
- **Checked by:** `_batch()`: anything not one of the five becomes note. A failed batch imports as note; only if every batch fails is nothing imported.
- **New user:** fine with few items.
- **Decision: keep.** It sorts new Slack messages and canvas items into a kind. An answer that is not one of the five kinds is saved as a note.

## 9. Kudos filter

`slack/kudos.py` `FILTER_PROMPT`. Keeps only messages that recognize your work, with a short exact quote.
- **Gets:** `BATCH` 40 messages that mention you, each text clipped to 1,500, with sender and channel. Code drops your own messages, bots, DMs, and anything without a praise word first. Your first name and full name fill the prompt ("the user" when unknown). 3 batches at a time.
- **Checked by:** `_read()`: a keep must be `true` with a valid id; a quote not found word for word in the message is replaced by the message's own words; quotes cut to `MAX_QUOTE` 240. An unreadable answer fails the step.
- **New user:** few mentions, few or no kudos; fine.
- **Decision: keep.** Narrow input, and the exact-quote check is in code.

## 10. Meeting notes summary

`google/summaries.py` `PROMPT`. Summarizes a meeting's notes Docs: what it was about, decisions, action items.
- **Gets:** only the Doc ids; Claude reads them itself with `get_doc_as_markdown` and may `Read` only its own saved copies of long answers. Up to the number of Docs plus 8 turns, `TIMEOUT_SECONDS` 240. The only prompt with tools.
- **Checked by:** `summarize()`: an empty answer fails and is retried next sync; the summary is cut to `MAX_SUMMARY` 6,000. The format isn't checked.
- **New user:** meetings without notes get no summary; fine.
- **Decision: keep.** The tool list is the guard, and the output is saved as an AI summary under the meeting, not as facts.

## 11. File summary

`google/docs.py` `SUMMARY_PROMPT`. Two lines on a Doc, Sheet, or Slides you wrote: what it is, what it covers.
- **Gets:** the file's text, clipped to `MAX_READ` 60,000, and its title.
- **Checked by:** `_two_lines()`: drops lines starting "skipped", "risk", or "note:", keeps 2 lines, at most `MAX_SUMMARY` 400 characters. An empty answer fails and is retried next sync.
- **New user:** fine.
- **Decision: keep.** Short output, trimmed in code.

## 12 and 13. V2MOM reader

`v2mom/connector.py` `PROMPT` (from a Google Doc) and `PDF_PROMPT` (from the PDF), sharing `_REPLY`. Turns the V2MOM text into vision, values, methods with measures, obstacles, and check-ins, in its own words.
- **Gets:** the text, clipped to `MAX_READ` 60,000.
- **Checked by:** `validate()`: at least one named method, percents whole numbers from 0 to 100, lists in shape; a method's missing status and percent are worked out from its measures. A bad answer changes nothing.
- **New user:** doesn't depend on records.
- **Decision: keep.** Strict shape check, and one shared reply format.

## 14. KSO framework

`kso/framework.py` `PROMPT`. Turns the KSO deck and canvases into KSOs, weights, components, rubric, examples, payouts, and dates for your track.
- **Gets:** the material's text, clipped to `MAX_READ` 120,000; the track (Delivery by default) and whether you're a people manager.
- **Checked by:** `validate()`: ratings 1 to 5 everywhere; payouts numbers from 0 to 300 that rise with the rating; unique keys; weights above 0, at most 100 each and in all; 2 or more examples per part, each up to `MAX_EXAMPLE` 140; dates in ISO form. A bad answer changes nothing.
- **New user:** doesn't depend on records.
- **Decision: keep.** The strictest check in the app; once a year, by hand.

## 15. KSO matching

`kso/map.py` `PROMPT`. Picks the one KSO part each V2MOM method gives the most evidence for, or none.
- **Gets:** every KSO part (key, name, what it measures) and only the methods not matched yet (description up to 600, 8 measures up to 300).
- **Checked by:** `validate()`: an answer for every method sent, each an offered part or none. Your picks are never changed. A bad answer changes nothing.
- **New user:** doesn't depend on records.
- **Decision: keep.** Small, closed choice, fully checked.

## 16. KSO estimate

`kso/estimate.py` `PROMPT`. Guesses the 1 to 5 your manager would give each KSO, with a reason per part and 3 next steps.
- **Gets:** the rubric, the V2MOM methods matched to each part (6 measures, text and comments clipped to 160 and 200), this fiscal year's linked work titles (100 each, newest first, `MAX_EVIDENCE` 8,000 split evenly across parts), and a kudos count for feedback parts. Never money.
- **Checked by:** `validate()`: every KSO once, a whole number from 1 to 5, a reason for every part (cut to `MAX_WHY` 200; prompt asks 160), exactly `STEPS` 3 next steps up to `MAX_STEP` 110 (prompt asks 90). A bad answer changes nothing.
- **New user:** runs only once KSOs are read and matched. With little work it rates low, which the prompt asks for ("honest, not kind").
- **Decision: keep.** Evidence is capped per part, and the shape is checked.
