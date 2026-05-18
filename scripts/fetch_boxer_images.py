"""
Automatically fetch missing boxer images from Wikipedia.

Finds all boxers that appear in fighters.json (null entry) or in the live
schedule cache but have no image entry at all, then queries the Wikipedia
API for each one, downloads whatever thumbnail it finds, saves it to
static/fighters/, and updates data/fighters.json.

Usage:
    python scripts/fetch_boxer_images.py           # process all missing
    python scripts/fetch_boxer_images.py --dry-run  # show what would be fetched
    python scripts/fetch_boxer_images.py "Name One" "Name Two"  # specific names
"""

import sys
import os
import json
import time
import unicodedata
import re
import argparse
import requests
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('DATA_DIR', ROOT / 'data'))
FIGHTERS_JSON = DATA_DIR / 'fighters.json'
CACHE_JSON = DATA_DIR / 'fights_cache.json'
STATIC_DIR = ROOT / 'static' / 'fighters'

STATIC_DIR.mkdir(parents=True, exist_ok=True)


def to_slug(name: str) -> str:
    """Convert fighter name to a filesystem-safe slug."""
    normalized = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    slug = ascii_name.lower().replace(' ', '-').replace("'", '').replace('.', '')
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    return slug


def load_fighters_db() -> dict:
    if FIGHTERS_JSON.exists():
        with open(FIGHTERS_JSON) as f:
            return json.load(f)
    return {}


def save_fighters_db(db: dict):
    with open(FIGHTERS_JSON, 'w') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def boxers_from_schedule() -> list[str]:
    """Return boxer names from the live schedule cache."""
    if not CACHE_JSON.exists():
        return []
    with open(CACHE_JSON) as f:
        cache = json.load(f)
    names = set()
    for fight in cache.get('fights', []):
        if fight.get('sport') == 'Boxing':
            names.add(fight['fighter1'])
            names.add(fight['fighter2'])
    return sorted(names)


def wikipedia_image(name: str) -> str | None:
    """
    Query Wikipedia for a fighter's page image.
    Tries the exact name first, then with "(boxer)" disambiguation.
    Returns a direct image URL or None.
    """
    session = requests.Session()
    session.headers['User-Agent'] = 'FightScheduleBot/1.0 (https://fightschedule.live)'

    candidates = [name, f"{name} (boxer)"]

    for title in candidates:
        try:
            # MediaWiki API — pageimages prop gives the page's lead image
            params = {
                'action': 'query',
                'titles': title,
                'prop': 'pageimages',
                'pithumbsize': 400,
                'format': 'json',
                'redirects': 1,
            }
            resp = session.get(
                'https://en.wikipedia.org/w/api.php',
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            pages = data.get('query', {}).get('pages', {})
            for page in pages.values():
                if page.get('pageid', -1) == -1:
                    continue  # page doesn't exist
                thumb = page.get('thumbnail', {}).get('source')
                if thumb:
                    return thumb
        except Exception as e:
            print(f"  Wikipedia API error for '{title}': {e}")

    return None


def download_image(url: str, dest: Path) -> bool:
    """Download url to dest. Returns True on success."""
    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'FightScheduleBot/1.0 (https://fightschedule.live)'
        })
        resp.raise_for_status()
        content_type = resp.headers.get('content-type', '')
        if 'image' not in content_type:
            return False
        with open(dest, 'wb') as f:
            f.write(resp.content)
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        return False


def ext_from_url(url: str) -> str:
    """Guess file extension from URL."""
    path = url.split('?')[0].lower()
    for ext in ('.jpg', '.jpeg', '.png', '.webp'):
        if path.endswith(ext):
            return ext
    return '.jpg'


def process(names: list[str], db: dict, dry_run: bool) -> dict:
    found = 0
    not_found = 0

    for name in names:
        existing = db.get(name)
        if existing:
            # Already has a non-null image — skip
            continue

        print(f"\n→ {name}")

        img_url = wikipedia_image(name)
        if not img_url:
            print(f"  ✗ Not found on Wikipedia")
            not_found += 1
            if name not in db:
                db[name] = None  # add null entry so we know we tried
            continue

        print(f"  ✓ Found: {img_url}")

        if dry_run:
            found += 1
            continue

        ext = ext_from_url(img_url)
        filename = f"{to_slug(name)}{ext}"
        dest = STATIC_DIR / filename

        if download_image(img_url, dest):
            static_path = f"/static/fighters/{filename}"
            db[name] = static_path
            print(f"  Saved → {static_path}")
            found += 1
        else:
            print(f"  ✗ Download failed")
            not_found += 1

        time.sleep(0.3)  # be polite to Wikipedia

    return {'found': found, 'not_found': not_found}


def main():
    parser = argparse.ArgumentParser(description='Fetch missing boxer images from Wikipedia')
    parser.add_argument('names', nargs='*', help='Specific fighter names (default: all missing)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fetched without downloading')
    args = parser.parse_args()

    db = load_fighters_db()

    if args.names:
        targets = args.names
    else:
        # All boxers missing an image: null entries + schedule fighters not in db at all
        null_entries = [k for k, v in db.items() if not v]
        schedule_names = boxers_from_schedule()
        missing_from_db = [n for n in schedule_names if n not in db]
        targets = sorted(set(null_entries + missing_from_db))

    if not targets:
        print("Nothing to fetch — all boxers already have images.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Fetching images for {len(targets)} boxer(s)...")

    stats = process(targets, db, dry_run=args.dry_run)

    if not args.dry_run:
        save_fighters_db(db)
        print(f"\nUpdated {FIGHTERS_JSON}")

    print(f"\nDone — found: {stats['found']}, not found: {stats['not_found']}")


if __name__ == '__main__':
    main()
