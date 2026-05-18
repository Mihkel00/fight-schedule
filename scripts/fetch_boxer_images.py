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


_ESPN_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
_BOT_UA  = 'FightScheduleBot/1.0 (https://fightschedule.live)'


def espn_image(name: str) -> str | None:
    """Search ESPN for a boxer and return their headshot URL."""
    try:
        resp = requests.get(
            'https://site.web.api.espn.com/apis/common/v3/search',
            params={'query': name, 'sport': 'boxing', 'type': 'athlete', 'limit': 5, 'lang': 'en'},
            headers={'User-Agent': _ESPN_UA},
            timeout=10,
        )
        resp.raise_for_status()
        for result in resp.json().get('results', []):
            if result.get('type') != 'athlete':
                continue
            for item in result.get('contents', []):
                athlete_id = item.get('data', {}).get('id')
                if not athlete_id:
                    continue
                espn_name = item.get('data', {}).get('displayName', '').lower()
                if not any(p in espn_name for p in name.lower().split() if len(p) > 2):
                    continue
                img_url = f'https://a.espncdn.com/i/headshots/boxing/players/full/{athlete_id}.png'
                head = requests.head(img_url, headers={'User-Agent': _ESPN_UA}, timeout=8)
                if head.status_code == 200 and int(head.headers.get('content-length', 0)) > 5000:
                    return img_url
    except Exception as e:
        print(f"  ESPN error for '{name}': {e}")
    return None


def wikipedia_image(name: str) -> str | None:
    """Query Wikipedia for a fighter's page image using search API for better name matching."""
    try:
        resp = requests.get(
            'https://en.wikipedia.org/w/api.php',
            params={'action': 'query', 'list': 'search', 'srsearch': f'{name} boxer',
                    'srlimit': 3, 'format': 'json'},
            headers={'User-Agent': _BOT_UA},
            timeout=10,
        )
        resp.raise_for_status()
        candidate_titles = [r['title'] for r in resp.json().get('query', {}).get('search', [])]
    except Exception:
        candidate_titles = []

    if not candidate_titles:
        candidate_titles = [name, f'{name} (boxer)']

    for title in candidate_titles[:3]:
        try:
            resp = requests.get(
                'https://en.wikipedia.org/w/api.php',
                params={'action': 'query', 'titles': title, 'prop': 'pageimages',
                        'pithumbsize': 400, 'format': 'json', 'redirects': 1},
                headers={'User-Agent': _BOT_UA},
                timeout=10,
            )
            resp.raise_for_status()
            pages = resp.json().get('query', {}).get('pages', {})
            for page in pages.values():
                if page.get('pageid', -1) == -1:
                    continue
                thumb = page.get('thumbnail', {}).get('source')
                if thumb:
                    return thumb
        except Exception as e:
            print(f"  Wikipedia error for '{title}': {e}")
    return None


def fetch_image(name: str) -> tuple[str | None, str]:
    """Try ESPN first, then Wikipedia. Returns (url, source) or (None, '')."""
    url = espn_image(name)
    if url:
        return url, 'espn'
    url = wikipedia_image(name)
    if url:
        return url, 'wikipedia'
    return None, ''


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


def is_broken_local_path(path: str) -> bool:
    """Return True if path is a /static/fighters/ reference pointing to a missing file."""
    if not path or not path.startswith('/static/fighters/'):
        return False
    abs_path = ROOT / path.lstrip('/')
    return not abs_path.exists()


def process(names: list[str], db: dict, dry_run: bool) -> dict:
    found = 0
    not_found = 0

    for name in names:
        existing = db.get(name)
        if existing and not is_broken_local_path(existing):
            # Already has a working image — skip
            continue

        print(f"\n→ {name}")

        img_url, source = fetch_image(name)
        if not img_url:
            print(f"  ✗ Not found on ESPN or Wikipedia")
            not_found += 1
            if name not in db:
                db[name] = None
            continue

        print(f"  ✓ Found via {source}: {img_url}")

        if dry_run:
            found += 1
            continue

        ext = ext_from_url(img_url)
        filename = f"{to_slug(name)}{ext}"
        # Save to the persistent data volume so files survive redeployment
        persist_dir = DATA_DIR / 'fighters'
        persist_dir.mkdir(parents=True, exist_ok=True)
        dest = persist_dir / filename

        if download_image(img_url, dest):
            db[name] = f"/persisted-fighters/{filename}"
            print(f"  Saved → {db[name]}")
            found += 1
        else:
            print(f"  ✗ Download failed")
            not_found += 1

        time.sleep(0.3)

    return {'found': found, 'not_found': not_found}


def main():
    parser = argparse.ArgumentParser(description='Fetch missing boxer images from ESPN then Wikipedia')
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
