# V2MOM source and connector servers

**Date:** 2026-11-12. **Branch:** `cursor/setup-connections`.

## Decided

- **AI Expert Suite servers first.** `claude mcp list` on 2026-11-12 showed `plugin:slack:slack`, `plugin:google-workspace:google-workspace`, and `plugin:browser:browser` connected, and no second Slack or Google server. `SERVERS` in `claude_cli.py` lists the plugin prefix first, then a claude.ai connector name (`claude_ai_Slack`, `claude_ai_Google_Workspace`) that is a guess, marked `shortcut:`. When a run's init shows the plugin down and the second server connected, `call_tools()` runs once more with the tool names moved there. With one server, nothing changes. The rewrite works only if the second server's tools have the plugin's names.
- **The V2MOM page by URL.** `v2mom connect <https link>` saves `kind: url`. The sync reads it with the browser plugin's `browser_navigate`, `browser_wait`, and `browser_a11y_tree` (`mcp__plugin_browser_browser__…`). These names were checked against `claude mcp list` and the plugin's own tool list. `browser_screenshot` exists but gives no text, so it isn't used. `read()` takes the page reader as an argument, so tests parse made-up page text and never browse. Plain `http` is refused (the plugin navigates https only). The PDF and Google Doc paths are unchanged.
- **PDF upload stays first on the V2MOM page.** No live read of a V2MOM page was tried in this session: that needs an Okta sign-in and the person's own V2MOM, which stays out of the session. The URL is a second field under the upload. Lead with the URL once a live read has worked.
- **No "compare V2MOMs".** No such text exists in the repo. `newest_pdf` reads one PDF, the newest of yours in the folder (a later fiscal year in the name first, then the newest file), and never compares two. The V2MOM page now says so. Its selection logic is unchanged.
- **Word files.** The pre-commit check now refuses `*.docx` outside `data/`.

## Personal data in history

`git log --all --diff-filter=A --name-only -- '*.pdf' '*.docx' '*.xlsx'` lists one file, `data/leveling/leveling-guides.xlsx`, the shared leveling guide. No V2MOM PDF, Word file, or other personal spreadsheet was ever committed.

## Rollback

Revert the commit. Saved `kind: url` sources then read as not connected, and setup asks for a PDF again.
