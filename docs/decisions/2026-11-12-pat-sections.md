# PAT sections for the performance case

**Date:** 2026-11-12.

## Context

The case was five sections we wrote ourselves: Summary, Key accomplishments, Impact, Behaviors & values, and Growth areas. The case people actually file is the Performance Advocacy Tool, which has its own headings and a blank template.

## Options

- Keep the five sections and only mention the tool's names in the help text.
- Write the tool's headings, with each section's guidance read from a blank template kept in the repo, and leave a Friday refresh off unless Settings turns it on.

## Choice

The second. New drafts use Project Highlights, Business Contributions, Professional Development, Feedback, and Promotion Readiness (Strategic Business Need, at least 25 words, and Talent Readiness, at most 400 words). The template's "What is valued" and "What to avoid" lists go in the prompt. A draft saved under the old headings still opens, and it can still be edited or rewritten. The Friday digest writes a draft for the last 12 months only when `friday_case` is true in `profile.json`. That switch is off unless someone turns it on, so Friday does nothing extra until then. A second run in the same week does not write another.

## Consequences

The template is `data/pat/pat-template.docx`. A copy that drops a heading fails the test, and the reader fails at startup. The Friday job is still the one digest schedule. Rollback is reverting this change. Drafts already saved stay in the notebook either way, and the case page shows whatever headings they were saved with.
