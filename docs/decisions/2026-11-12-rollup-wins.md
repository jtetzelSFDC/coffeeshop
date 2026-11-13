# One win per piece of work

**Date:** 2026-11-12.

## Context

A piece of work is several records: a meeting, a Slack thread, a task. The Performance map already counts that piece once. Wins were still one per record, so the performance case and the V2MOM could count the same work again for each record that had a win.

## Options

- Delete the member wins when the group win is made.
- Keep every win. When a group win exists, count that win and not the wins of its member records. Do not delete a win the user confirmed.

## Choice

The second. `Win.work_item_id` points at the piece of work. The Part of cell shows **Count this work as one win** only when the record is in a group. Grouping three or more records drafts one AI win from the same Claude reply: a `win` string on that record's work object, or the work title when the reply has none. There is no second Claude call. A group of two is not drafted. Looks right makes the AI group win yours, the same as other AI wins. The group win's size starts at the strongest member win, or small when there is none. Pressing the button on an AI draft raises that size if a member win is larger, and never lowers it. Guide links and V2MOM links on the members are copied onto the group win.

The performance case and the V2MOM win list count the group win only. The Performance map still scores the piece once, at the stronger of the group win and a member win, so a large win you already confirmed is not thrown away on the map. If the group is later emptied, an AI group win is removed with it. A win you confirmed stays, with the group link cleared.

## Consequences

Member wins remain in the notebook. A window that includes a member win but not the group win still counts the member win, because the group win is dated on the piece of work's latest day and is not in that window. A member win added after the group win does not change the case line until you press the button again (while the draft is still AI) or edit the group win. The map still takes the stronger score. Rollback is reverting this change. Wins already in the notebook are unchanged until a group win is made.
