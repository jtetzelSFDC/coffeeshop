# Performance first

**Date:** 2026-11-12.

## Context

The map people open was the leveling guide, under the name promotion. V2MOM method progress and KSO bars, which are what a year is judged on, each lived on their own page. Old links and the `promo write` command already exist.

## Options

- Leave `/promo` as the map and add the V2MOM and KSO bars above the guide.
- Rename the map to `/performance`, lead with this year's V2MOM and KSOs, and fold the leveling guide under Promotion (optional). When an earlier year is already stored, show it beside this year.

## Choice

The second. GET `/promo` and the old GET `/promo…` paths redirect to the new path and keep the rest of the path and the query. POST routes move to `/performance` and are not redirected. `coffeeshop performance write` is the command; `promo` stays a hidden alias. The `promo/` code and the `promo_version` and `promo_section` tables keep their names.

## Consequences

A bookmark to `/promo` lands on `/performance`. A year that was never stored is not shown. The leveling guide is still there, closed, for someone who wants it. A manager and Salesforce still see nothing unless the person shares it, for example by sending a case to Google Docs.
