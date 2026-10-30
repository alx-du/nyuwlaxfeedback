# NYU Women's Lacrosse – Feedback Envelopes

Each player opens a private page with a personal code. Staff open the same page and type the dashboard passphrase instead of a player code; the dashboard then shows everyone's feedback in that page. The site is static: `generate.py` builds `site/`, and GitHub Actions deploys it to GitHub Pages.

**This repo is public. Never commit real data.** `site/`, `data/`, `.env`, `sources.json` and all real CSVs are gitignored. Only placeholder files (`sample*.csv`, `sources.example.json`) are tracked.

## Weekly routine

The `SHEET_SOURCES` secret points at the **whole published document** once and never needs to change:
`[{"document": "<published link, ending in /pub>"}]`. The build finds every tab itself and reads each tab's **name as its date** (`10/27/26`, `11-03-26` or `2026-11-03` all work). Tabs whose name isn't a date are ignored, so scratch tabs are safe.

1. Duplicate last week's tab, rename it to the new date, and update the notes. Keep the `Name` and `SLUG` columns and the same `from <name>` headers.
2. Optional: add a `Label` column (e.g. "vs SHU") to show beside the date, and a `Season` column to override the season, which is otherwise worked out from the date (August to July).
3. Paste any new player's code into the `SLUG` column (a player's code only needs to appear on one tab, and codes are never changed once set).
4. Optional preview: `python generate.py` then `python -m http.server -d site`.
5. Wait a few minutes for Google to republish (File > Share > Publish to web must be set to **Entire document**), then run the **Build and deploy feedback site** workflow (Actions tab > Run workflow).

Rows can also carry their own `Date` column (several dates in one tab). A row's own Date/Season/Label wins over the tab name.

## One-time setup

**Local**
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in DASHBOARD_PASSPHRASE (16+ chars recommended, e.g. 4+ random words)
cp sources.example.json sources.json   # then point it at the real sheet tabs
```

**GitHub** (repo → Settings)
- Pages → Source: **GitHub Actions**.
- Secrets and variables → Actions → *Secrets*: `SHEET_SOURCES` (the full contents of `sources.json`), `DASHBOARD_PASSPHRASE`.
- Secrets and variables → Actions → *Variables*: `SITE_URL` (the site's address, used for the 404 page's "Try again" link).

## Privacy notes

- A player's page contains only their own feedback. Their code (a five-letter word plus three digits, like `tiger482`, a random animal from `animals.txt`, with common objects from `objects.txt` as a fallback) is the page's URL, so treat it like a password and send each player only their own. There are only about 60,000 possible codes, which stops casual guessing but not a determined scanner that requests tens of thousands of URLs.
- The dashboard data is published **encrypted** (`staff.json`) and only decrypted in the browser of someone who types the passphrase on the landing page; the passphrase never leaves your machine and the GitHub secret. Change it if a captain graduates or it's shared too widely.
- The deploy build runs with `--strict`: it fails if any player lacks a code in the sheet, so a link can never silently change.
- Pages is public even though the repo code is open, so anyone with a player's code can open that page. That is the intended model.
