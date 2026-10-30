#!/usr/bin/env python3
"""Build the feedback site: one private page per player plus an encrypted staff dashboard.

Feedback comes from published sheet tabs listed in sources.json (or the SHEET_SOURCES env var):
  [{"season": "2026-2027", "date": "2026-10-25", "label": "vs SHU", "csv": "<url or path>"}]
or, to pick up every dated tab of a published document automatically (tab name = the date):
  [{"document": "<published document link>"}]
A tab can hold many dates: add Date (and optional Season, Label) columns and append rows for each
new entry. Season/date/label in the source are only the defaults for rows that leave them blank.

Usage:
  python generate.py                                   # reads sources.json
  python generate.py --csv sample.csv --date 2026-10-25  # one local file, no sources.json
"""
import argparse
import base64
import csv
import datetime
import html
import io
import json
import os
import re
import secrets
import shutil
import sys
import urllib.request
from pathlib import Path
from string import Template

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---- Config (edit these) -------------------------------------------------------------
TEAM_NAME = "NYU Women's Lacrosse"
# Rows whose name matches one of these are team-level notes shown on EVERY player's page.
TEAM_ROWS = {"defense", "attack", "midfield", "goalies", "plan for next practice",
             "defense as a whole", "attack as a whole", "mid"}
# Notes that carry no feedback. "Status" notes show as a short line instead of a note.
EMPTY_NOTES = {"", "no notes", "no comments", "n/a", "none"}
STATUS_NOTES = {"injured", "did not attend", "did not attend game"}
PBKDF2_ITERATIONS = 600_000
MIN_PASSPHRASE = 8  # hard floor; under 16 prints a warning

ROOT = Path(__file__).parent
TEMPLATES = ROOT / "templates"
ANIMALS = (ROOT / "animals.txt").read_text().split()
OBJECTS = (ROOT / "objects.txt").read_text().split()  # fallback once the animals run out


def new_slug(used_words=()):
    """A five-letter word plus three digits, e.g. 'tiger482'. Prefers unused animals, then objects."""
    pool = ([w for w in ANIMALS if w not in used_words] or [w for w in OBJECTS if w not in used_words]
            or ANIMALS + OBJECTS)
    return f"{secrets.choice(pool)}{secrets.randbelow(1000):03d}"


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def fmt_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def default_season(iso):
    d = datetime.date.fromisoformat(iso)
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{start + 1}"


def fetch_csv(location):
    if location.startswith(("http://", "https://")):
        return urllib.request.urlopen(location).read().decode("utf-8-sig")
    return Path(location).read_text(encoding="utf-8-sig")


def parse_date(text, required=True):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%m.%d.%Y", "%m.%d.%y",
                "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    if required:
        sys.exit(f"Can't read the date '{text}'. Use YYYY-MM-DD or M/D/YYYY.")
    return None


def split_tab_name(name):
    """A tab name is a date, optionally followed by a label: '10/27/26', '10/27/26 - SHU', '10/27/26 vs SHU'.
    Returns (iso_date, label) or (None, "")."""
    name = name.strip()
    date = parse_date(name, required=False)
    if date:
        return date, ""
    m = re.match(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|[A-Za-z]+\.? \d{1,2}, \d{4})\s*[-:\u2013\u2014,]?\s*(.*)$", name)
    if m:
        date = parse_date(m.group(1), required=False)
        if date:
            return date, m.group(2).strip()
    return None, ""


def expand_sources(sources):
    """A source with "document" (the published-document link) turns into one source per tab.
    Each tab's name is its date, e.g. a tab named 10/27/26. Tabs whose name isn't a date are skipped."""
    out = []
    for s in sources:
        if "document" not in s:
            out.append(s)
            continue
        base = s["document"].split("/pub")[0].rstrip("/")
        page = fetch_csv(base + "/pubhtml")
        tabs = re.findall(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)", pageUrl: "[^"]*", gid: "(\d+)"', page)
        if not tabs:
            sys.exit("Couldn't list the tabs. Is the whole document published (File > Share > Publish to web)?")
        found = 0
        for raw_name, gid in tabs:
            name = json.loads(f'"{raw_name}"')
            date, tab_label = split_tab_name(name)
            if not date:
                print(f"Skipping tab '{name}': its name isn't a date")
                continue
            found += 1
            out.append({"csv": f"{base}/pub?gid={gid}&single=true&output=csv", "date": date,
                        "season": s.get("season", ""), "label": tab_label or s.get("label", "")})
        print(f"Found {found} dated tab(s) in the document")
        if not found:
            sys.exit("No tab name starts with a date, so there is nothing to build. Name tabs like 10/27/26 or 10/27/26 - SHU.")
    return out


def read_entries(source):
    """Read one published tab. Rows sharing a Date (plus Season/Label) form one entry. A row's own
    Date/Season/Label columns win; otherwise the source's values are the default."""
    if not source.get("csv"):
        sys.exit(f"Source is missing 'csv': {source}")
    reader = csv.DictReader(io.StringIO(fetch_csv(source["csv"])))
    headers = [h.strip() for h in reader.fieldnames or []]
    lower = {h.lower(): h for h in headers}
    for needed in ("name", "slug"):
        if needed not in lower:
            sys.exit(f"Missing column '{needed}'. Found: {headers}")
    # Contributor columns are the ones starting with "from " (e.g. "from Alex").
    cols = [h for h in headers if h.lower().startswith("from ")]
    if not cols:
        sys.exit(f"No 'from <name>' columns found. Found: {headers}")
    contributors = [c.split(" ", 1)[1] for c in cols]
    groups = {}
    for raw in reader:
        r = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        name = r.get(lower["name"], "")
        if not name:
            continue  # blank spacer row
        date = r.get(lower.get("date", ""), "") or source.get("date", "")
        if not date:
            sys.exit(f"'{name}' has no date: fill the Date column or set 'date' in the source.")
        date = parse_date(date)
        season = r.get(lower.get("season", ""), "") or source.get("season") or default_season(date)
        label = r.get(lower.get("label", ""), "") or source.get("label", "")
        entry = groups.setdefault((season, date, label), {
            "season": season, "date": date, "label": label,
            "contributors": contributors, "cols": cols, "rows": []})
        entry["rows"].append({
            "name": name,
            "slug": r.get(lower["slug"], ""),
            "email": r.get(lower.get("email", ""), ""),
            "summary": r.get(lower.get("summary", ""), ""),
            "shoutout": r.get(next((h for l, h in lower.items() if l.startswith("shoutout")), ""), ""),
            "action": r.get(next((h for l, h in lower.items() if l.startswith("action item")), ""), ""),
            "team": name.lower() in TEAM_ROWS,
            "notes": {c: r.get(c, "") for c in cols},
        })
    return list(groups.values())


def load_entries(args):
    if args.csv:
        # Only pass along what was given; rows with their own Date/Season/Label columns win anyway.
        sources = [{"csv": args.csv, **{k: v for k, v in (("season", args.season), ("date", args.date),
                                                              ("label", args.label)) if v}}]
    else:
        raw = os.environ.get("SHEET_SOURCES")
        path = ROOT / "sources.json"
        if raw:
            sources = json.loads(raw)
        elif path.exists():
            sources = json.loads(path.read_text())
        else:
            sys.exit("No sources: add sources.json (see sources.example.json), set SHEET_SOURCES, or pass --csv")
    entries = [e for s in expand_sources(sources) for e in read_entries(s)]
    # Newest first: season, then date.
    entries.sort(key=lambda e: (e["season"], e["date"]), reverse=True)
    return entries


def build_roster(entries):
    """One record per player (matched by name across entries); slug found in any entry."""
    roster = {}
    for e in entries:
        for r in e["rows"]:
            if r["team"]:
                continue
            p = roster.setdefault(r["name"].lower(), {"name": r["name"], "slug": "", "email": ""})
            for field in ("slug", "email"):
                if r[field]:
                    if p[field] and p[field] != r[field] and field == "slug":
                        sys.exit(f"Conflicting slugs for {r['name']}: {p[field]} vs {r[field]}")
                    p[field] = r[field]
    used = {p["slug"] for p in roster.values() if p["slug"]}
    used_words = {s[:-3] for s in used}
    new = []
    for p in roster.values():
        if p["slug"]:
            continue
        slug = new_slug(used_words)
        while slug in used:
            slug = new_slug(used_words)
        used.add(slug)
        used_words.add(slug[:-3])
        p["slug"] = slug
        new.append(p)
    return roster, new


def classify(note):
    """Return (kind, text): kind is 'note', 'status' or 'empty'."""
    low = note.strip().lower().rstrip(".")
    if low in EMPTY_NOTES:
        return "empty", ""
    if low in STATUS_NOTES:
        return "status", note.strip()
    return "note", note.strip()


def merge_notes(row, cols):
    """Combine the contributors' notes into one unlabeled note. Returns (text, statuses)."""
    notes, statuses = [], []
    for c in cols:
        kind, text = classify(row["notes"][c])
        if kind == "note":
            notes.append(text)
        elif kind == "status" and text not in statuses:
            statuses.append(text)
    return "\n\n".join(notes), statuses


def p(text, cls=""):
    return f'<p class="{cls}">{html.escape(text)}</p>'


def render_entry(entry, row, hidden, latest):
    # An optional `summary` column wins; otherwise merge the notes (AI summary slots in here later).
    text, statuses = merge_notes(row, entry["cols"])
    if row["summary"]:
        text = row["summary"]
    personal = []
    if text:
        personal.append(p(text))
    if row["action"]:
        personal.append("<h3>Action items</h3>" + p(row["action"]))
    if not personal:
        # Status lines (injured, did not attend) only matter when there is no written feedback.
        personal = [p(s, "status") for s in statuses] or [p("No written feedback for this date.", "empty")]
    body = personal

    team = []
    has_summary_col = any(r["summary"] for r in entry["rows"])
    for t in entry["rows"]:
        if t["team"]:
            # Team notes come from the Summary column. Tabs with no Summary column at all fall back to
            # the merged raw notes; a blank summary on a tab that has the column is left out.
            t_text = t["summary"] if has_summary_col else merge_notes(t, entry["cols"])[0]
            # Summaries often start with "Defense:"; the heading already says that.
            prefix = t["name"] + ":"
            if t_text.lower().startswith(prefix.lower()):
                t_text = t_text[len(prefix):].strip()
                t_text = t_text[:1].upper() + t_text[1:]
            if t_text:
                team.append(f"<h4>{html.escape(t['name'])}</h4>{p(t_text)}")
    if team:
        body.append('<div class="team"><h3>Team notes</h3>' + "".join(team) + "</div>")

    label = f'<span class="note-label">{html.escape(entry["label"])}</span>' if entry["label"] else ""
    badge = '<span class="badge">Latest</span>' if latest else ""
    return (
        f'<section class="entry" data-season="{html.escape(entry["season"])}" '
        f'data-date="{entry["date"]}" data-display="{html.escape(fmt_date(entry["date"]))}'
        f'{" – " + html.escape(entry["label"]) if entry["label"] else ""}"{" hidden" if hidden else ""}>'
        f'<article class="note"><div class="note-head"><span class="note-date">'
        f'{html.escape(fmt_date(entry["date"]))}</span>{label}{badge}</div>'
        f'<div class="note-body">{"".join(body)}</div></article></section>'
    )


def render_player(player, entries, tpl):
    blocks, first = [], True
    for e in entries:
        row = next((r for r in e["rows"] if not r["team"] and r["name"].lower() == player["name"].lower()), None)
        if row:
            blocks.append(render_entry(e, row, hidden=not first, latest=first))
            first = False
    return tpl.safe_substitute(player_name=html.escape(player["name"]), entries_html="".join(blocks))


def encrypt_payload(data, passphrase):
    salt, iv = os.urandom(16), os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS)
    key = kdf.derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(data).encode(), None)
    enc = lambda b: base64.b64encode(b).decode()
    return json.dumps({"salt": enc(salt), "iv": enc(iv), "ct": enc(ct), "iter": PBKDF2_ITERATIONS})


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="one local CSV instead of sources.json")
    ap.add_argument("--season", help="with --csv: default season (default: worked out from each date)")
    ap.add_argument("--date", help="with --csv: default date for rows without a Date column")
    ap.add_argument("--label", help="with --csv: optional short label, e.g. 'vs SHU'")
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--strict", action="store_true",
                    help="CI mode: fail if any player has no slug in the sheet (names only are printed)")
    args = ap.parse_args()

    entries = load_entries(args)
    roster, new = build_roster(entries)
    if args.strict and new:
        # Logs may be public, so never print slugs here. A CI-generated slug would also change every run.
        sys.exit("Players missing a slug in the sheet (generate one locally and paste it in):\n  "
                 + "\n  ".join(pl["name"] for pl in new))

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "f").mkdir(parents=True)
    shutil.copytree(TEMPLATES / "assets", out / "assets")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (out / ".nojekyll").write_text("")
    (out / "index.html").write_text((TEMPLATES / "landing.html").read_text())

    # 404 page is served at arbitrary URLs, so inline the CSS and logo instead of linking assets.
    logo = "data:image/png;base64," + base64.b64encode((TEMPLATES / "assets" / "logo.png").read_bytes()).decode()
    (out / "404.html").write_text(Template((TEMPLATES / "404.html").read_text()).safe_substitute(
        css=(TEMPLATES / "assets" / "style.css").read_text(), logo=logo,
        favicon="data:image/png;base64," + base64.b64encode((TEMPLATES / "assets" / "favicon-32.png").read_bytes()).decode(),
        home=os.environ.get("SITE_URL", "/") or "/"))

    tpl = Template((TEMPLATES / "player.html").read_text())
    for player in roster.values():
        (out / "f" / f"{player['slug']}.html").write_text(render_player(player, entries, tpl))

    # Staff dashboard: written ONLY encrypted (staff.json), opened from the landing page. Never write the plaintext data to disk.
    passphrase = os.environ.get("DASHBOARD_PASSPHRASE", "")
    if 0 < len(passphrase) < 16:
        print("NOTE: DASHBOARD_PASSPHRASE is under 16 chars; short passphrases can be guessed offline.")
    if len(passphrase) >= MIN_PASSPHRASE:
        data = {"entries": [
            {"season": e["season"], "date": e["date"],
             "display": fmt_date(e["date"]) + (f" – {e['label']}" if e["label"] else ""),
             "contributors": e["contributors"] + ["Shoutout/Encouragement", "Summary", "Action items"],
             "rows": [{"name": r["name"], "team": r["team"],
                       "notes": [r["notes"][c] for c in e["cols"]] + [r["shoutout"], r["summary"], r["action"]]}
                      for r in e["rows"]]}
            for e in entries]}
        (out / "staff.json").write_text(encrypt_payload(data, passphrase))
    else:
        print(f"WARNING: DASHBOARD_PASSPHRASE missing or under {MIN_PASSPHRASE} chars; dashboard skipped.")

    print(f"Built {len(roster)} player pages from {len(entries)} entries -> {out}")
    if new:
        print("\nNew slugs: paste these into the SLUG column of the sheet:")
        for pl in new:
            print(f"  {pl['name']}\t{pl['slug']}")


if __name__ == "__main__":
    main()
