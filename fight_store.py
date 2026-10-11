"""
Fight data storage and rules: cache, results archive, last-good data,
manual time overrides, UFC card order, big-name fights.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import json
import locks as _locks
import os
import re
import runs as _runs
import unicodedata
from admin_models import BigNameFighter
from datetime import date, datetime, timedelta
from core import data_path, logger
import formatting
import seo


# Big-name fighters - always show their fights (even non-title)
BIG_NAME_FIGHTERS = [
    # Top-ranked boxers
    'Naoya Inoue',
    'Terence Crawford',
    'Junto Nakatani',
    'Jaron Ennis',
    'Saul Alvarez',
    'Canelo Alvarez',  # Alternative name for Saul Alvarez
    'Shakur Stevenson',
    'David Benavidez',
    'Dmitrii Bivol',
    'Jesse Rodriguez',
    'Artur Beterbiev',
    'Devin Haney',
    'Gervonta Davis',
    'Teofimo Lopez',
    'Oleksandr Usyk',
    'Vergil Ortiz Jr',
    'Raymond Muratalla',
    'Zhanbek Alimkhanuly',
    'Rafael Espinoza',
    'Hamzah Sheeraz',
    'Nick Ball',
    'Xander Zayas',
    'Gilberto Ramirez',
    'Jermall Charlo',
    'Masamichi Yabuki',
    'Fabio Wardley',
    'Anthony Cacace',
    'Emanuel Navarrete',
    'Osleys Iglesias',
    'Jai Opetaia',
    'Subriel Matias',
    'Christian Mbilli',
    'Agit Kabayel',
    'Richardson Hitchins',
    'Oscar Collazo',
    'Liam Paro',
    'Jaime Munguia',
    'Brian Norman Jr',
    'Keyshawn Davis',
    'Eduardo Nunez',
    'Ricardo Rafael Sandoval',
    'Adam Azim',
    'Kenshiro Teraji',
    'Daniel Dubois',
    'Arnold Barboza Jr',
    'Ricardo Majika',
    'Diego Pacheco',
    'Luis Nery',
    'Stephen Fulton',
    'Callum Smith',
    'Sebastian Fundora',
    
    # Popular/celebrity boxers
    'Jake Paul',
    'Logan Paul',
    'Tommy Fury',
    'KSI',
    
    # Legends still fighting
    'Tyson Fury',
    'Anthony Joshua',
    'Manny Pacquiao',
]


# Cache file path (in persistent data directory)
CACHE_FILE = data_path('fights_cache.json')


CACHE_DURATION = timedelta(hours=6)  # Refresh every 6 hours


# Past events are kept for this long so results can be shown and the event
# URLs keep working (instead of vanishing the morning after).
RESULTS_WINDOW_DAYS = 30


# How long a finished fight may sit without a result before we stop calling it
# "pending". Wikipedia records notable bouts within hours; small-hall fights
# whose fighters have no article never get one.
RESULT_GRACE_DAYS = 3


def _retention_cutoff_iso():
    return (date.today() - timedelta(days=RESULTS_WINDOW_DAYS)).isoformat()


def upcoming_only(fights):
    today_iso = date.today().isoformat()
    return [f for f in fights if f.get('date', '') >= today_iso]


def recent_results(fights):
    """Past fights (newest first) within the retention window."""
    today_iso = date.today().isoformat()
    past = [f for f in fights if f.get('date', '') < today_iso]
    return sorted(past, key=lambda f: f.get('date', ''), reverse=True)


def load_time_overrides():
    """Load manual time overrides from persistent data directory"""
    try:
        with open(data_path('time_overrides.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Error loading time overrides: {e}")
        return {}


def get_fight_key(fight):
    """Generate unique key for a fight (used for time overrides)"""
    return f"{fight['fighter1']} vs {fight['fighter2']}|{fight['date']}"


def apply_time_overrides(fights):
    """Apply manual time overrides to fights"""
    overrides = load_time_overrides()
    
    if not overrides:
        return fights
    
    applied_count = 0
    for fight in fights:
        fight_key = get_fight_key(fight)
        if fight_key in overrides:
            old_time = fight.get('time', 'TBA')
            fight['time'] = overrides[fight_key]
            print(f"Time override applied: {fight['fighter1']} vs {fight['fighter2']}: {old_time} → {fight['time']}")
            applied_count += 1
    
    if applied_count > 0:
        print(f"\n✓ Applied {applied_count} manual time override(s)\n")
    
    return fights


def is_big_name_fight(fight):
    """Check if fight involves a big-name fighter"""
    model = BigNameFighter()
    fighter1 = fight.get('fighter1', '')
    fighter2 = fight.get('fighter2', '')

    return model.is_big_name(fighter1) or model.is_big_name(fighter2)


def score_fight_for_featuring(fight, today_date):
    """
    Score a fight for the Featured section. Higher = more prominent.

    Scoring:
      +50  Title fight
      +30  Big-name fighter involved
      +20  Main event / main card
      +10  Has confirmed (non-estimated) time
      +5   Per day closer (max 7 days out = +35 for today, +5 for 7 days away)
    """
    score = 0

    # Title fight
    wc = fight.get('weight_class', '')
    if 'Title' in wc or fight.get('card_type') == 'Title':
        score += 50

    # Big-name fighter
    if is_big_name_fight(fight):
        score += 30

    # Main event / main card
    if fight.get('is_main_event') or fight.get('card_type') == 'Main Card':
        score += 20

    # Confirmed time (not TBA, not estimated)
    time_val = fight.get('time', 'TBA')
    if time_val and time_val != 'TBA' and not fight.get('time_estimated', False):
        score += 10

    # Proximity bonus: closer fights score higher
    try:
        from datetime import date as date_cls
        fight_date = date_cls.fromisoformat(fight['date'])
        days_away = (fight_date - today_date).days
        if 0 <= days_away <= 7:
            score += max(0, (8 - days_away) * 5)  # today=+40, tomorrow=+35, ... 7 days=+5
    except (ValueError, KeyError):
        pass

    return score


_EPOCH = datetime(2000, 1, 1)


def _bout_start(f):
    try:
        return datetime.strptime(f"{f.get('date')} {f.get('time')}", '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return None


def _name_in_text(name, text):
    """True if some word of the fighter's name (3+ letters, not a suffix)
    appears as a whole word in text. Handles 'Wang Cong' in 'Silva vs. Wang'
    (family name first) as well as 'Silva' in it."""
    def fold(t):   # 'Procházka' -> 'prochazka', so accents on either side don't matter
        return ''.join(c for c in unicodedata.normalize('NFKD', t or '') if not unicodedata.combining(c)).lower()
    text = fold(text)
    words = [w for w in re.findall(r'\w{3,}', fold(name)) if w not in formatting._NAME_SUFFIXES]
    return any(re.search(r'\b' + re.escape(w) + r'\b', text) for w in words)


def _named_in_title(f, title):
    t = (title or '').lower()
    return bool(t) and all(_name_in_text(f.get(k) or '', t) for k in ('fighter1', 'fighter2'))


def normalize_ufc_cards(fights):
    """Put each UFC card's main event first and label main card vs prelims from
    the data, not from list order. ESPN lists bouts earliest first (main event
    last) and labels them all 'Main Card'; the site treats the first bout of an
    event as its main event. Order within a card: latest start first, the bout
    named in the event title first of all. Idempotent (stores 'bout_order')."""
    groups, order = {}, []
    for f in fights:
        if f.get('sport') == 'UFC' and f.get('event_name'):
            key = f['event_name']
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(f)
    if not groups:
        return fights
    for key in order:
        g = groups[key]
        if all('bout_order' in f for f in g):
            g.sort(key=lambda f: f['bout_order'])
            continue
        starts = {_bout_start(f) for f in g} - {None}
        if len(starts) > 1:
            # ESPN order is earliest first: reverse it, then latest segment first
            g.reverse()
            g.sort(key=lambda f: (_bout_start(f) is None, -((_bout_start(f) or _EPOCH) - _EPOCH).total_seconds()))
            latest = max(starts)
            if all((f.get('card_type') or 'Main Card') == 'Main Card' for f in g):
                for f in g:
                    f['card_type'] = 'Main Card' if _bout_start(f) == latest else 'Prelims'
        named = next((f for f in g if _named_in_title(f, key)), None)
        if named is not None and g[0] is not named:
            g.remove(named)
            g.insert(0, named)
        for i, f in enumerate(g):
            f['bout_order'] = i
    out, done = [], set()
    for f in fights:
        if f.get('sport') == 'UFC' and f.get('event_name'):
            key = f['event_name']
            if key in done:
                continue
            done.add(key)
            out.extend(groups[key])
        else:
            out.append(f)
    return out


def load_cache(max_age_hours=None):
    """
    Load cached fight data if it exists and is fresh
    
    Args:
        max_age_hours: If provided, accept cache up to this many hours old (for fallback scenarios)
    """
    if not os.path.exists(CACHE_FILE):
        logger.debug("No cache file found")
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        # Check if cache is still fresh
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        age = datetime.now() - cache_time
        
        # Use custom max age if provided (for fallback), otherwise use default CACHE_DURATION
        max_age = timedelta(hours=max_age_hours) if max_age_hours else CACHE_DURATION
        
        if age < max_age:
            if max_age_hours:
                logger.warning(f"[FALLBACK] Using stale cache from {cache_time.strftime('%Y-%m-%d %H:%M:%S')} (age: {age.seconds//3600} hours)")
            else:
                logger.info(f"[OK] Using cached data from {cache_time.strftime('%Y-%m-%d %H:%M:%S')} (age: {age.seconds//60} minutes)")
            
            # Apply time overrides to cached data
            fights = cache_data['fights']
            # A cache written before listings were deduplicated may hold repeats
            _seen = set()
            fights = [f for f in fights if not (_fight_key(f) in _seen or _seen.add(_fight_key(f)))]
            fights = normalize_ufc_cards(fights)
            fights = apply_time_overrides(fights)

            # Drop events older than the results window so stale cache served
            # during a scraper outage never shows ancient fights.
            cutoff = _retention_cutoff_iso()
            fights = [f for f in fights if f.get('date', '') >= cutoff]

            logger.info(f"  Loaded {len(fights)} fights from cache (incl. last {RESULTS_WINDOW_DAYS}d results)")
            return fights
        else:
            logger.info(f"[X] Cache expired (age: {age.seconds//3600} hours), fetching new data...")
            return None
    except Exception as e:
        logger.error(f"Error loading cache: {e}")
        return None


def save_cache(fights, keep_timestamp=False):
    """Save fight data to cache with timestamp. keep_timestamp=True (manual
    restores) leaves the scrape schedule untouched."""
    try:
        stamp = datetime.now().isoformat()
        if keep_timestamp:
            try:
                with open(CACHE_FILE) as fh:
                    stamp = json.load(fh).get('timestamp') or stamp
            except Exception:
                pass
        cache_data = {
            'timestamp': stamp,
            'fights': fights
        }
        # write-then-rename: readers in the other worker never see a half-written file
        _runs.write_json_atomic(CACHE_FILE, cache_data)
        logger.info(f"[OK] Cache saved: {len(fights)} fights at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        logger.error(f"Error saving cache: {e}")
        return
    archive_results(fights)
    seo.sync_page_versions(fights, reason='scrape')


RESULTS_ARCHIVE_FILE = data_path('results_archive.json')


def _fight_key(f):
    return (tuple(sorted([(f.get('fighter1') or '').lower(), (f.get('fighter2') or '').lower()])), f.get('date'))


def load_results_archive():
    try:
        with open(RESULTS_ARCHIVE_FILE) as fh:
            return json.load(fh)
    except Exception:
        return []


def archive_results(fights):
    """Add fights dated today or earlier to the archive (existing entries are
    updated in place, e.g. a corrected time). Safe across workers."""
    today_iso = date.today().isoformat()
    due = [f for f in fights if f.get('date') and f['date'] <= today_iso]
    if not due:
        return 0
    with _locks.job_lock('results_archive', wait_seconds=10) as got:
        if not got:
            logger.warning("results archive busy; will retry on next save")
            return 0
        archive = load_results_archive()
        index = {_fight_key(f): i for i, f in enumerate(archive)}
        added = 0
        for f in due:
            clean = {k: v for k, v in f.items() if k in _ARCHIVE_FIELDS}
            k = _fight_key(clean)
            if k in index:
                archive[index[k]].update(clean)
            else:
                index[k] = len(archive)
                archive.append(clean)
                added += 1
        archive.sort(key=lambda x: x.get('date') or '')
        _runs.write_json_atomic(RESULTS_ARCHIVE_FILE, archive)
    if added:
        logger.info(f"Results archive: +{added} fights ({len(archive)} total)")
    return added


LAST_GOOD_FILE = data_path('last_good.json')


def load_last_good(sport):
    try:
        with open(LAST_GOOD_FILE) as fh:
            return (json.load(fh).get(sport) or {}).get('fights') or []
    except Exception:
        return []


def save_last_good(sport, fights, merge=False):
    """Store a source's fights as its last known-good set (merge=True adds to
    the existing set instead of replacing it, used by manual restores)."""
    with _locks.job_lock('last_good', wait_seconds=10) as got:
        if not got:
            return
        try:
            with open(LAST_GOOD_FILE) as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        clean = [{k: v for k, v in f.items() if k in _ARCHIVE_FIELDS} for f in fights]
        if merge:
            existing = (data.get(sport) or {}).get('fights') or []
            keys = {_fight_key(f) for f in clean}
            clean = [f for f in existing if _fight_key(f) not in keys] + clean
        data[sport] = {'saved_at': datetime.utcnow().isoformat() + 'Z', 'fights': clean}
        _runs.write_json_atomic(LAST_GOOD_FILE, data)


# Only scraped fields are archived; derived fields (images, tape, results) are
# recomputed on display so they always reflect the latest data.
_ARCHIVE_FIELDS = ('fighter1', 'fighter2', 'date', 'time', 'time_estimated', 'venue', 'location', 'sport',
                   'event_name', 'weight_class', 'card_type', 'rounds', 'is_main_event', 'streaming',
                   'bout_order')


def archived_fights(live):
    """Finished fights older than the results window, from the archive. Their
    pages stay online (and in the sitemap) after they leave the lists, so
    links and search results for past fights keep working."""
    cutoff = _retention_cutoff_iso()
    seen = {_fight_key(f) for f in live}
    old = [dict(f) for f in load_results_archive()
           if f.get('date', '') < cutoff and _fight_key(f) not in seen]
    return normalize_ufc_cards(old) if old else []
