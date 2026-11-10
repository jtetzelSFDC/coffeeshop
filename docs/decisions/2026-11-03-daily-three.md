# Daily three

**Date:** 2026-11-03. **PRs (on the earlier repo):** #35 (engine), #36 (morning sync), #37 (Home card).

## Decided

- **Titles only go to Claude.** It gets your goals and the titles from the last 14 days. Goals are V2MOM methods that need work, then Promo map next steps, methods with open measures, gaps, and skills. Notes and transcripts stay on the laptop. That is enough for a 10-minute step, and it keeps what leaves the laptop small (about 8,000 characters).
- **Exactly three, every day.** Each is 10 minutes or less and names a goal from the list. A bad answer saves nothing, and the day stays empty.
- **It is the last step of the morning sync.** It is not its own 8:30 job. A separate job would run before the missed 8:00 sync had fresh data, and it would not catch up after a shutdown. As the last step of `sync all`, it follows fresh data, catches up at login, and uses the sync's failure notification. It runs once a day after 8 AM, and only when there are goals.
- **A finished task becomes a record.** Kind `task`, status `done`, source `daily`, and your note is "What I did". It then counts like any other record. Unticking removes it, unless you wrote a note, checked it, or made a win from it.

## Rollback

Revert the three PRs, or just ignore the card: the `daily_task` table is harmless if unused, and nothing else depends on it. The daily step skips itself when there are no goals.
