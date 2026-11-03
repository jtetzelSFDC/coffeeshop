# Daily three

**Date:** 2026-11-03. **PRs:** [#35](https://github.com/jmysterio/career-os/pull/35) (engine), [#36](https://github.com/jmysterio/career-os/pull/36) (morning sync), [#37](https://github.com/jmysterio/career-os/pull/37) (Home card).

## Decided

- **Titles only go to Claude.** Goals (V2MOM methods needing work first, then the Promo map's Aim for next, on-track methods with open measures, Promo gaps, and skills) plus the titles of the last 14 days of records and wins. No notes or transcripts. That's enough to suggest a 10-minute step, and it keeps what leaves the laptop small (about 8k characters at most).
- **Exactly three, every day, each under 10 minutes, each naming a goal from the list.** The answer is checked strictly; a bad one saves nothing and the day stays empty.
- **The last step of the morning sync, not its own 8:30 agent.** A separate agent would fire together with a missed 8:00 sync on wake (before fresh data) and would never catch up after a shutdown. As the last step of `sync all`, it always follows fresh data, catches up at login, and reuses the sync's failure notification. It runs once a day after 8 AM, and only when there are goals.
- **A finished task becomes a record** (`task`, `done`, source `daily`, your note as "What I did"), so it counts through the normal guide and V2MOM linking. Unticking removes it, unless you wrote a note, checked it, or made a win from it.

## Rollback

Revert the three PRs, or just ignore the card: the `daily_task` table is harmless if unused, and nothing else depends on it. The daily step skips itself when there are no goals.
