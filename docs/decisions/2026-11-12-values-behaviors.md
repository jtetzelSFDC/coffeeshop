# Values & Behaviors on the guide review

**Date:** 2026-11-12. **Branch:** `cursor/values-behaviors`.

## Decided

Values & Behaviors sit beside the leveling guide and the V2MOM. A record can show a behavior (Trust / Act with Integrity) the same way it can show a guide item or move a method forward, and the Intake Review Queue needs a column for that.

They share the existing guide-review call. A second Claude pass for every new record would read the same text again. The V2MOM already rides on that call (`v2mom/links.py` `PROMPT_PART` appended in `guide/ai_review.py`), so behaviors do too: a `"values"` list of short ids, at most 2. Records Claude already read before this change are covered by `values tag`, the same backfill shape as `v2mom tag`.

The catalog is the Individual Contributor tab of `data/competencies/values-behaviors.xlsx`. Only the English value, behavior, and definition columns are read. Interview questions stay in the file and are not sent. Excel cuts the tab name at 31 characters, so the sheet is stored as `Updated V&B Individual Contribu`.

## Consequences

- People Leader and Executive tabs are not loaded.
- The queue can drop a behavior (the × on the chip). It cannot add one Claude missed; that waits for the link page.
- The CSV download does not include these links yet.
- **Looks right** makes the picks yours. **Changed by Claude** includes a row whose only AI mark is a behavior.

## Rollback

Revert the commit. Old notebooks keep the new tables and the two flags (nothing is dropped). The app stops reading them.
