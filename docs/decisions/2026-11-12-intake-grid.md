# Intake grid

**Date:** 2026-11-12.

## Context

The Intake Review Queue listed each record as one loose row. The activity (Counts as), the piece of work (Part of), and the V2MOM methods sat inside other cells, so a scan of the queue meant reading down a paragraph. Looks right was one row at a time. Records Claude had already read and not linked to a V2MOM method were mixed in with everything else.

## Options

- Keep the row layout and add only a bulk Looks right button.
- Make the queue a ruled grid with one column per fact, a checkbox on each row, and one Looks right for the rows you ticked. Add a filter for records Claude has read that have no V2MOM method.

## Choice

The second. POST `/sheet/ok` confirms each selected id through the same `confirm` that POST `/sheet/{id}/ok` already uses. A row Claude has not read yet is skipped, the same as a row that does not show a Looks right button, so a bulk check cannot accept picks Claude has not made. The single-row button stays. The filter is entry links only: a V2MOM link that exists only on a win still shows up as a gap, because that is what the V2MOM column shows.

## Consequences

Checking many rows is one action. Unread rows stay unchecked so Claude can still read them. Confirmed rows leave the current view the same way a single Looks right does, and a row that still belongs on the page redraws in place. The No V2MOM method filter does not apply to Removed. There is no Values column; that is a later change.
