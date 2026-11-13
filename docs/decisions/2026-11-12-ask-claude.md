# Ask Claude

**Date:** 2026-11-12.

## Context

Someone wants to ask about their own notebook (what was impactful, where a behavior shows up, what is missing, which work has no V2MOM method) without starting a performance case or a sync.

## Options

- Save each answer as a note.
- Send the question with full notes and transcripts.
- Send the question with a clipped slice (record and win lines in a chosen window, V2MOM methods, Values & Behaviors, leveling-guide topics), tell Claude to cite record numbers, and save nothing.

## Choice

The third. `claude_cli.ask` runs with tools off and one turn, the same as the other notebook reads. The slice follows the daily three's 8,000-character cap. Notes and transcripts stay on the laptop. The page and `coffeeshop ask` only show the answer.

## Consequences

An answer can only use what was in the slice, so a wider question needs a wider window. A citation is a record number from that slice. Nothing is written, so removing the page and the command is the rollback. There is no new table.
