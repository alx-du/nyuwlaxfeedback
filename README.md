# NYU Women's Lacrosse – Feedback Envelopes

Each player opens a private page with a personal code. A staff dashboard (passphrase-protected) shows everyone's feedback. The site is static: `generate.py` builds `site/`, and GitHub Actions deploys it to GitHub Pages.

**This repo is public. Never commit real data.** `site/`, `data/`, `.env`, `sources.json` and all real CSVs are gitignored. Only placeholder files (`sample*.csv`, `sources.example.json`) are tracked.

## Weekly routine

1. Contributors fill in a new tab in the Google Sheet (columns: `Name`, `SLUG`, `from <name>` ×4, optional `summary`, `Email`).
2. Publish the tab (File → Share → Publish to web → CSV) and add one line to `sources.json`:
   `{"season": "2026-2027", "date": "2026-11-01", "label": "vs NYU", "csv": "<published csv url>"}`
3. Paste any new player's code into the `SLUG` column (codes are never changed once set).
4. Build and preview locally: `python generate.py` then `python -m http.server -d site`.
5. Update the `SHEET_SOURCES` secret with the new `sources.json` contents, then run the **Build and deploy feedback site** workflow (Actions tab → Run workflow).

## One-time setup

**Local**
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in DASHBOARD_PASSPHRASE (16+ chars, e.g. 4+ random words)
cp sources.example.json sources.json   # then point it at the real sheet tabs
```

**GitHub** (repo → Settings)
- Pages → Source: **GitHub Actions**.
- Secrets and variables → Actions → *Secrets*: `SHEET_SOURCES` (the full contents of `sources.json`), `DASHBOARD_PASSPHRASE`.
- Secrets and variables → Actions → *Variables*: `SITE_URL` (the site's address, used for the 404 page's "Try again" link).

## Privacy notes

- A player's page contains only their own feedback. Their code (a five-letter word plus three digits, like `tiger482`, a random animal from `animals.txt`, with common objects from `objects.txt` as a fallback) is the page's URL, so treat it like a password and send each player only their own. There are only about 60,000 possible codes, which stops casual guessing but not a determined scanner that requests tens of thousands of URLs.
- The dashboard is published **encrypted**; the passphrase never leaves your machine and the GitHub secret. Change it if a captain graduates or it's shared too widely.
- The deploy build runs with `--strict`: it fails if any player lacks a code in the sheet, so a link can never silently change.
- Pages is public even though the repo code is open, so anyone with a player's code can open that page. That is the intended model.
