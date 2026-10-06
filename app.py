from flask import Flask, render_template, request, redirect, make_response, send_file, send_from_directory, session, jsonify, abort
from functools import wraps
import hmac
import threading
import time
from flask_compress import Compress
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
import os
import shutil
import unicodedata
import requests
from datetime import datetime, timedelta, date
import json
import re
import logging
from logging.handlers import RotatingFileHandler
from admin_setup_simple import setup_admin
from admin_models import BigNameFighter
import markdown
from bs4 import BeautifulSoup

# Import scrapers
# The scrapers return a result dict (fights + outcome + diagnostics); tests may
# replace these names with functions returning a plain list, which _run_source
# accepts too.
from scrapers import scrape_ufc as scrape_ufc_events, scrape_boxing as scrape_boxing_events
import runs as _runs
import usage as _usage
import image_pipeline as _images
import locks as _locks
import structured_data as _ld

# ============================================================================
# PERSISTENT DATA DIRECTORY
# ============================================================================
# On Railway: mount a persistent volume at /data and set DATA_DIR=/data
# Locally: defaults to ./data (relative to project root)
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))

def data_path(filename):
    """Get full path for a file in the persistent data directory"""
    return os.path.join(DATA_DIR, filename)

def _seed_data_files():
    """
    On first deploy, copy git-tracked seed files into DATA_DIR if they
    don't already exist there. This ensures a fresh Railway volume gets
    populated with the initial fighter databases and config.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'logs'), exist_ok=True)

    project_root = os.path.dirname(os.path.abspath(__file__))

    # Files to seed: (source relative to project root, dest relative to DATA_DIR)
    seed_files = [
        ('fighters.json', 'fighters.json'),
        ('fighters_ufc.json', 'fighters_ufc.json'),
        ('time_overrides.json', 'time_overrides.json'),
        ('data/big_name_fighters.json', 'big_name_fighters.json'),
        ('data/fight_previews.json', 'fight_previews.json'),
    ]

    for src_rel, dest_rel in seed_files:
        src = os.path.join(project_root, src_rel)
        dest = data_path(dest_rel)
        if not os.path.exists(dest) and os.path.exists(src):
            shutil.copy2(src, dest)
            print(f"[SEED] Copied {src_rel} → {dest}")

_seed_data_files()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/fighters'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size
app.config['DATA_DIR'] = DATA_DIR  # Make available to admin views
Compress(app)  # Enable gzip compression for all responses

@app.context_processor
def inject_current_date():
    now = datetime.now()
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    return {
        'current_year': now.year,
        'current_month_year': f"{month_names[now.month - 1]} {now.year}"
    }

# Setup Flask-Admin
admin = setup_admin(app)


def admin_required(f):
    """Require the Flask-Admin session login for app-level /admin/* routes."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return redirect('/admin/')
        return f(*args, **kwargs)
    return wrapper

@app.before_request
def redirect_www():
    """Redirect www to non-www for canonical URLs"""
    if request.host.startswith('www.'):
        return redirect(request.url.replace('www.', '', 1), code=301)

# ============================================================================
# LOGGING SETUP
# ============================================================================
# Create logs directory if it doesn't exist
log_dir = os.path.join(DATA_DIR, 'logs')
os.makedirs(log_dir, exist_ok=True)

# Set up logging to both file and console
logger = logging.getLogger('fight_schedule')
logger.setLevel(logging.DEBUG)

# File handler (rotates at 10MB, keeps 3 backup files)
file_handler = RotatingFileHandler(os.path.join(log_dir, 'app.log'), maxBytes=10*1024*1024, backupCount=3)
file_handler.setLevel(logging.DEBUG)

# Console handler (shows in terminal)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # Only show INFO+ in console

# Format: [2025-01-15 14:30:45] INFO: Message here
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)


def _to_slug(name):
    """Convert a fighter name to a URL slug, stripping diacritics and punctuation."""
    normalized = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return ascii_name.lower().replace(' ', '-').replace("'", '').replace('.', '')


logger.info("="*70)
logger.info("FIGHT SCHEDULE APP STARTING")
logger.info("="*70)
# ============================================================================

# Your Premium API Key
# Anthropic API Key for fight previews
# ⚠️ ADD YOUR NEW API KEY HERE (after creating it in console.anthropic.com)
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')  # Will load from environment variable

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

_NAME_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}


def surname(name):
    """Display surname: 'Julio Cesar Chavez Jr.' -> 'Chavez', 'Isaac "Pitbull" Cruz' -> 'Cruz'."""
    if not name:
        return ''
    # drop quoted nicknames and trailing rematch numbers ("Lopes 2")
    cleaned = re.sub(r'[\"“”‘’\'][^\"“”‘’\']+[\"“”‘’\']', ' ', name)
    cleaned = re.sub(r'\s+\d+$', '', cleaned).strip()
    parts = cleaned.split()
    while len(parts) > 1 and parts[-1].lower().strip(',') in _NAME_SUFFIXES:
        parts.pop()
    return parts[-1] if parts else name


app.jinja_env.filters['surname'] = surname


def result_text(r):
    """One-line result: 'Inoue wins · UD · 12 rounds', 'Walker wins · KO · Round 2'."""
    if not r:
        return ''
    if r.get('outcome') == 'draw':
        return 'Draw' + (f" · {r['method']}" if r.get('method') else '')
    if r.get('outcome') != 'win':
        return 'No contest'
    bits = [f"{surname(r.get('winner'))} wins"]
    method = r.get('method') or ''
    if method:
        bits.append(method)
    rnd = r.get('round')
    if rnd:
        decision = method.upper() in ('UD', 'SD', 'MD', 'TD', 'DECISION') or 'DEC' in method.upper()
        bits.append(f"{rnd} rounds" if decision else f"Round {rnd}" + (f", {r['time']}" if r.get('time') else ''))
    return ' · '.join(bits)


app.jinja_env.filters['result_text'] = result_text
app.jinja_env.globals['ld'] = _ld


def utc_time(t):
    """Server-rendered time text: '00:00 UTC' (JavaScript replaces it with the
    visitor's local time). Crawlers that don't run JavaScript see an
    unambiguous timezone instead of a bare '00:00'."""
    return f"{t} UTC" if t and t != 'TBA' and ':' in str(t) else 'TBA'


def iso_utc(d, t=None):
    """Machine-readable value for <time datetime>: '2026-10-04T00:00Z', or the
    date alone when there is no start time."""
    start = _ld._start(d, t)
    return start.strftime('%Y-%m-%dT%H:%MZ') if start else (d or '')


app.jinja_env.filters['utc_time'] = utc_time
app.jinja_env.filters['iso_utc'] = iso_utc



def format_fight_date(date_str):
    """Format date from YYYY-MM-DD to 'Sat, Dec 06'"""
    if not date_str:
        return ''
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return date_obj.strftime('%a, %b %d')
    except:
        return date_str

def format_fight_time(time_str):
    """Format time from 24h to 12h with AM/PM"""
    if not time_str:
        return ''
    try:
        # Handle various time formats
        time_str = time_str.strip()
        
        # If already has AM/PM, return as is
        if 'AM' in time_str.upper() or 'PM' in time_str.upper():
            return time_str
        
        # Parse 24-hour format (e.g., "13:00" or "1:00")
        if ':' in time_str:
            time_obj = datetime.strptime(time_str, '%H:%M')
            return time_obj.strftime('%I:%M %p').lstrip('0')  # Remove leading zero
        
        return time_str
    except:
        return time_str

# Register Jinja2 filters
app.jinja_env.filters['format_date'] = format_fight_date
app.jinja_env.filters['format_time'] = format_fight_time

def load_fighter_database():
    """Load fighters.json and fighters_ufc.json from persistent data directory"""
    fighters_db = {}

    # Load general fighter database
    try:
        with open(data_path('fighters.json'), 'r', encoding='utf-8') as f:
            fighters_db.update(json.load(f))
    except:
        pass

    # Load UFC-specific database (from UFC.com scraper)
    try:
        with open(data_path('fighters_ufc.json'), 'r', encoding='utf-8') as f:
            ufc_db = json.load(f)
            # UFC database takes priority for UFC fighters
            fighters_db.update(ufc_db)
    except:
        pass

    return fighters_db

def get_fighter_image(fighter_name):
    """Image to display for a fighter: reviewed/manual overrides first, then the
    legacy fighters.json / fighters_ufc.json databases (see image_pipeline.py)."""
    return _images.image_for(fighter_name)

# ============================================================================
# AI FIGHT PREVIEW FUNCTIONS
# ============================================================================

def load_previews():
    """Load cached fight previews from persistent data directory"""
    try:
        with open(data_path('fight_previews.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load previews: {e}")
        return {}

def save_preview(preview_id, preview_data):
    """Save a fight preview to cache"""
    try:
        # Parse JSON if text contains structured data
        if 'text' in preview_data:
            try:
                parsed = json.loads(preview_data['text'])
                preview_data['parsed'] = parsed
            except:
                # Fallback if not valid JSON
                pass
        
        previews = load_previews()
        previews[preview_id] = preview_data
        with open(data_path('fight_previews.json'), 'w', encoding='utf-8') as f:
            json.dump(previews, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved preview: {preview_id}")
    except Exception as e:
        logger.error(f"Failed to save preview: {e}")

def generate_fight_preview(fighter1, fighter2, sport, is_title, weight_class=None):
    """Generate AI preview using Claude API"""
    
    if not ANTHROPIC_API_KEY:
        logger.warning("No Anthropic API key set - skipping preview generation")
        return None
    
    # Build the prompt
    title_context = "Title Fight: Yes" if is_title else "Title Fight: No"
    weight_info = f"Weight Class: {weight_class}" if weight_class else "Weight Class: Unknown"
    
    prompt = f"""Generate a brief fight preview in JSON format with this EXACT structure:

{{
  "context": "One punchy sentence (15 words max) - why this fight matters",
  "fighter1_edge": [
    "First key strength (10 words max)",
    "Second key strength (10 words max)"
  ],
  "fighter2_edge": [
    "First key strength (10 words max)",
    "Second key strength (10 words max)"
  ],
  "what_to_watch": "Two sentences max (25 words total) - key moments, rounds, or factors that will decide the fight. NO predictions."
}}

Fighter 1: {fighter1}
Fighter 2: {fighter2}
Sport: {sport}
{title_context}
{weight_info}

CRITICAL RULES:
- Total output under 100 words
- Respond ONLY with valid JSON, no other text
- Be specific and punchy
- No predictions or calling the winner
- Focus on what makes this fight interesting

Example good output:
{{
  "context": "Bantamweight title rematch after controversial decision",
  "fighter1_edge": [
    "Relentless wrestling pressure breaks opponents late",
    "Superior cardio outlasts elite competition"
  ],
  "fighter2_edge": [
    "Surgical striking slices through aggressive pressure",
    "Elite takedown defense neutralizes wrestling attacks"
  ],
  "what_to_watch": "Watch the opening two rounds—whoever controls distance there wins the mental battle. If Merab clinches early, it's a grind. If Yan stays at range, it's a striking clinic."
}}"""

    try:
        logger.info(f"Generating preview for {fighter1} vs {fighter2}...")
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            preview_text = response.json()['content'][0]['text']
            # Strip markdown code blocks if present
            preview_text = preview_text.replace('```json', '').replace('```', '').strip()
            logger.info("Preview generated successfully")
            return preview_text
        else:
            logger.error(f"API request failed: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Preview generation error: {e}")
        return None

def get_or_generate_preview(preview_id, fighter1, fighter2, sport, is_title, weight_class=None):
    """Get cached preview or generate new one"""
    
    # Check cache first
    previews = load_previews()
    
    if preview_id in previews:
        logger.info(f"Using cached preview for {preview_id}")
        return previews[preview_id]
    
    # Generate new preview
    preview_text = generate_fight_preview(fighter1, fighter2, sport, is_title, weight_class)
    
    if preview_text:
        preview_data = {
            'fighter1': fighter1,
            'fighter2': fighter2,
            'text': preview_text,
            'generated_at': datetime.now().isoformat(),
            'manual_override': False
        }
        save_preview(preview_id, preview_data)
        return preview_data
    
    return None

# ============================================================================

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
    words = [w for w in re.findall(r'\w{3,}', fold(name)) if w not in _NAME_SUFFIXES]
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
    sync_page_versions(fights, reason='scrape')


# ============================================================================
# INDEXNOW — notify search engines (Bing, Yandex, etc.) when content changes.
# Requires INDEXNOW_KEY env var; silently disabled otherwise.
# ============================================================================

INDEXNOW_KEY = os.environ.get('INDEXNOW_KEY', '')


def public_event_urls(fights):
    """All public page URLs, same set as the sitemap."""
    urls = ['https://fightschedule.live/',
            'https://fightschedule.live/ufc',
            'https://fightschedule.live/boxing']
    seen = set()
    for fight in fights:
        if fight.get('sport') == 'UFC' and fight.get('card_type') != 'Prelims':
            if fight['event_name'] in seen:
                continue
            seen.add(fight['event_name'])
            slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
            urls.append(f"https://fightschedule.live/event/{slug}")
        elif fight.get('sport') == 'Boxing' and fight.get('is_main_event'):
            slug = f"{_to_slug(fight['fighter1'])}-vs-{_to_slug(fight['fighter2'])}-{fight['date']}"
            if slug in seen:
                continue
            seen.add(slug)
            urls.append(f"https://fightschedule.live/boxing-event/{slug}")
    return urls


def ping_indexnow(urls):
    """Submit changed/removed URLs to IndexNow. Best-effort."""
    if not INDEXNOW_KEY or not urls:
        return
    try:
        urls = list(dict.fromkeys(urls))
        resp = requests.post(
            'https://api.indexnow.org/indexnow',
            json={
                'host': 'fightschedule.live',
                'key': INDEXNOW_KEY,
                'keyLocation': 'https://fightschedule.live/indexnow-key.txt',
                'urlList': urls[:500],
            },
            timeout=10,
        )
        logger.info(f"IndexNow ping: {resp.status_code} for {len(urls)} URLs")
    except Exception as e:
        logger.warning(f"IndexNow ping failed: {e}")


# ── Page versions: a content fingerprint per public URL so the sitemap's lastmod
# and IndexNow pings reflect real changes (result added, fighter swapped, time
# moved) rather than the fight date or "every scrape".
PAGE_VERSIONS_FILE = data_path('page_versions.json')
_versions_lock = threading.Lock()


def _load_versions():
    try:
        with open(PAGE_VERSIONS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _fight_signature(f):
    r = f.get('result') or {}
    return '|'.join(str(x) for x in (
        f.get('fighter1'), f.get('fighter2'), f.get('date'), f.get('time'), f.get('venue'),
        f.get('card_type'), f.get('weight_class'), f.get('streaming'),
        r.get('winner'), r.get('method'), r.get('round'), r.get('time'),
    ))


def _event_fingerprints(fights):
    """url -> sha1 of that event's fights (results included). Boxing undercards
    share their main event's URL via (venue, date)."""
    import hashlib
    fights = enrich_fights([dict(f) for f in fights])
    ufc_url, box_url = {}, {}
    for f in fights:
        if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims' and f['event_name'] not in ufc_url:
            slug = f"{f['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{f['date']}"
            ufc_url[f['event_name']] = f"https://fightschedule.live/event/{slug}"
        elif f.get('sport') == 'Boxing' and f.get('is_main_event'):
            slug = f"{_to_slug(f['fighter1'])}-vs-{_to_slug(f['fighter2'])}-{f['date']}"
            box_url[(f.get('venue'), f.get('date'))] = f"https://fightschedule.live/boxing-event/{slug}"
    groups = {}
    for f in fights:
        url = ufc_url.get(f.get('event_name')) if f.get('sport') == 'UFC' else box_url.get((f.get('venue'), f.get('date')))
        if url:
            groups.setdefault(url, []).append(_fight_signature(f))
    return {url: hashlib.sha1('\n'.join(sorted(sigs)).encode()).hexdigest() for url, sigs in groups.items()}


def sync_page_versions(fights, reason=''):
    """Compare current content with stored fingerprints; bump lastmod for changed
    pages, drop removed ones, and ping IndexNow with just those URLs."""
    if not fights:
        return {'changed': [], 'removed': []}
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    with _versions_lock, _locks.job_lock('versions', wait_seconds=15):
        stored = _load_versions()
        current = _event_fingerprints(fights + archived_fights(fights))
        changed = [u for u, h in current.items() if stored.get(u, {}).get('hash') != h]
        removed = [u for u in stored if u not in current]
        for u in changed:
            stored[u] = {'hash': current[u], 'lastmod': now}
        for u in removed:
            stored.pop(u, None)
        if changed or removed:
            _runs.write_json_atomic(PAGE_VERSIONS_FILE, stored)
    if changed or removed:
        logger.info(f"Page versions ({reason}): {len(changed)} changed, {len(removed)} removed")
        hubs = ['https://fightschedule.live/']
        if any('/event/' in u for u in changed + removed):
            hubs.append('https://fightschedule.live/ufc')
        if any('/boxing-event/' in u for u in changed + removed):
            hubs.append('https://fightschedule.live/boxing')
        ping_indexnow(changed + removed + hubs)
    return {'changed': changed, 'removed': removed}


def page_lastmod(url, fallback):
    return _load_versions().get(url, {}).get('lastmod', fallback)


@app.route('/indexnow-key.txt')
def indexnow_key_file():
    """Key file proving domain ownership to IndexNow."""
    if not INDEXNOW_KEY:
        abort(404)
    response = make_response(INDEXNOW_KEY)
    response.headers['Content-Type'] = 'text/plain'
    return response


# ============================================================================
# FIGHTER PROFILES — tale of the tape + results from Wikipedia, cached on the
# volume and refreshed in the background (see scrapers/fighter_profiles.py)
# ============================================================================

from scrapers import fighter_profiles as _wiki

PROFILES_FILE = data_path('fighter_profiles.json')
PROFILE_TTL_HOURS = 24 * 7      # re-check a known fighter weekly
RESULT_TTL_HOURS = 6            # ...but every 6h while one of their fights is recent
NEGATIVE_TTL_HOURS = 24 * 7     # retry unknown names weekly
PROFILE_JOB_MIN_INTERVAL_S = 10 * 60

_profiles_lock = threading.Lock()
_profiles_mem = {'mtime': None, 'data': {}}
_profile_job_state = {'last_start': 0.0, 'running': False}


def _profile_key(name):
    return _wiki._norm(name)


def load_profiles():
    """Profiles dict keyed by normalized name, cached in memory by file mtime."""
    try:
        mtime = os.path.getmtime(PROFILES_FILE)
    except OSError:
        return {}
    if _profiles_mem['mtime'] != mtime:
        try:
            with open(PROFILES_FILE) as f:
                _profiles_mem['data'] = json.load(f)
            _profiles_mem['mtime'] = mtime
        except Exception as e:
            logger.error(f"Error loading profiles: {e}")
            return _profiles_mem['data'] or {}
    return _profiles_mem['data']


def save_profiles(data):
    _runs.write_json_atomic(PROFILES_FILE, data)


def _hours_since(ts):
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except Exception:
        return 1e9


def _profile_work_list(fights, profiles):
    """Names to (re)fetch, most useful first: recent results, then soonest upcoming."""
    today = date.today()
    today_iso, recent_iso = today.isoformat(), (today - timedelta(days=4)).isoformat()
    wanted = {}
    for f in fights:
        d = f.get('date', '')
        for key in ('fighter1', 'fighter2'):
            name = f.get(key, '')
            if not name or name.upper() == 'TBA':
                continue
            k = _profile_key(name)
            entry = profiles.get(k)
            if recent_iso <= d < today_iso:
                # results pending: refresh often, and only for fighters with an article
                if entry and entry.get('title') and _hours_since(entry.get('fetched_at', '')) < RESULT_TTL_HOURS:
                    continue
                if entry and not entry.get('title') and _hours_since(entry.get('fetched_at', '')) < NEGATIVE_TTL_HOURS:
                    continue
                prio = (0, d)
            else:
                if entry and _hours_since(entry.get('fetched_at', '')) < (PROFILE_TTL_HOURS if entry.get('title') else NEGATIVE_TTL_HOURS):
                    continue
                prio = (1, d)
            if k not in wanted or prio < wanted[k][0]:
                wanted[k] = (prio, name, f.get('sport', 'Boxing'))
    return [(name, sport) for _, name, sport in sorted(wanted.values(), key=lambda x: x[0])]


def refresh_profiles(fights, max_fetch=150):
    """Background job: fetch/refresh Wikipedia profiles for fighters in the schedule."""
    if _profile_job_state['running']:
        return
    _profile_job_state['running'] = True
    _profile_job_state['last_start'] = time.time()
    lock = _locks.job_lock('profiles')
    if not lock.__enter__():
        lock.__exit__(None, None, None)
        _profile_job_state['running'] = False
        logger.info("Profile job already running in the other worker, skipping")
        return
    try:
        profiles = dict(load_profiles())
        work = _profile_work_list(fights, profiles)[:max_fetch]
        logger.info(f"Profile job: {len(work)} fighters to fetch")
        fetched = 0
        for name, sport in work:
            k = _profile_key(name)
            existing = profiles.get(k) or {}
            title = existing.get('title') or _wiki.resolve_title(name, sport)
            profile = _wiki.fetch_profile(title, sport) if title else None
            if title and profile is None and existing.get('profile'):
                profile = existing['profile']   # transient failure: keep what we had
            profiles[k] = {
                'name': name, 'sport': sport, 'title': title if profile else None,
                'profile': profile, 'fetched_at': datetime.now().isoformat(),
            }
            fetched += 1
            if fetched % 10 == 0:
                with _profiles_lock:
                    save_profiles(profiles)
            time.sleep(0.3)
        with _profiles_lock:
            save_profiles(profiles)
        logger.info(f"Profile job done: {fetched} fetched, {sum(1 for p in profiles.values() if p.get('title'))} with articles")
        if fetched:
            sync_page_versions(load_cache(max_age_hours=24 * 365) or [], reason='profiles')
        _images.autofill_new_fighters()
    except Exception as e:
        logger.error(f"Profile job failed: {e}", exc_info=True)
    finally:
        lock.__exit__(None, None, None)
        _profile_job_state['running'] = False


def _maybe_start_profile_job(fights):
    """Start a background profile refresh if there is work and none ran recently."""
    if _profile_job_state['running'] or time.time() - _profile_job_state['last_start'] < PROFILE_JOB_MIN_INTERVAL_S:
        return
    if _profile_work_list(fights, load_profiles()):
        threading.Thread(target=refresh_profiles, args=(fights,), daemon=True).start()


def _tape(profile_entry):
    """Slim tale-of-the-tape dict for templates, or None."""
    p = (profile_entry or {}).get('profile')
    if not p or not p.get('has_tape') and not p.get('record'):
        return None
    rec = p.get('record') or {}
    wins, losses, draws, total = rec.get('wins'), rec.get('losses'), rec.get('draws'), rec.get('total')
    if wins is not None and losses is None and total is not None:
        losses = max(0, total - wins - (draws or 0) - (rec.get('no_contests') or 0))
    record = None
    if wins is not None and losses is not None:
        record = f"{wins}-{losses}" + (f"-{draws}" if draws else '')
    # Prefer the birthplace country so the row reads "Brazil / South Africa" rather
    # than a mix of adjectives ("Filipino") and countries.
    nationality = None
    if p.get('birthplace'):
        nationality = p['birthplace'].split(',')[-1].strip()
        nationality = {'U.S.': 'United States', 'US': 'United States', 'USA': 'United States', 'UK': 'United Kingdom'}.get(nationality, nationality)
    if not nationality:
        nationality = p.get('nationality')
    return {
        'record': record, 'wins': wins, 'losses': losses, 'draws': draws,
        'ko_wins': rec.get('ko_wins'), 'sub_wins': rec.get('sub_wins'), 'dec_wins': rec.get('dec_wins'),
        'age': p.get('age'), 'height': p.get('height_text'), 'height_cm': p.get('height_cm'),
        'reach': p.get('reach_text'), 'reach_in': p.get('reach_in'),
        'stance': p.get('stance'), 'nationality': nationality, 'nickname': p.get('nickname'),
        'height_display': _height_display(p.get('height_cm')),
        'reach_display': _reach_display(p.get('reach_in'), p.get('reach_cm')),
        'url': p.get('url'),
    }


def _height_display(cm):
    if not cm:
        return None
    total_in = cm / 2.54
    ft, inch = int(total_in // 12), int(round(total_in % 12))
    if inch == 12:
        ft, inch = ft + 1, 0
    return f"{ft}'{inch}\" ({cm} cm)"


def _reach_display(inches, cm):
    if not inches and not cm:
        return None
    if inches and not cm:
        cm = int(round(inches * 2.54))
    if cm and not inches:
        inches = round(cm / 2.54)
    inches_s = str(int(inches)) if float(inches).is_integer() else f"{inches:g}"
    return f'{inches_s}" ({cm} cm)'


def _result_for(fight, profiles):
    """Winner/method/round for a completed fight, from either fighter's record table."""
    f1, f2, d = fight.get('fighter1', ''), fight.get('fighter2', ''), fight.get('date', '')
    for me, them in ((f1, f2), (f2, f1)):
        entry = profiles.get(_profile_key(me))
        row = _wiki.find_result((entry or {}).get('profile'), them, d) if entry else None
        if not row:
            continue
        res = (row.get('result') or '').lower()
        if res.startswith('win'):
            winner, loser, outcome = me, them, 'win'
        elif res.startswith('loss'):
            winner, loser, outcome = them, me, 'win'
        elif res.startswith('draw'):
            winner, loser, outcome = None, None, 'draw'
        elif 'nc' in res or 'no contest' in res:
            winner, loser, outcome = None, None, 'nc'
        else:
            continue
        return {
            'outcome': outcome, 'winner': winner, 'loser': loser,
            'method': row.get('method'), 'round': row.get('round'), 'time': row.get('time'),
            'notes': row.get('notes'), 'source_url': (entry.get('profile') or {}).get('url'),
        }
    return None


def enrich_fights(fights):
    """Attach fighter1_tape / fighter2_tape, is_past, and result (for past fights)."""
    profiles = load_profiles()
    today_iso = date.today().isoformat()
    grace_iso = (date.today() - timedelta(days=RESULT_GRACE_DAYS)).isoformat()
    for f in fights:
        for k in ('fighter1', 'fighter2'):
            if _images.is_rejected(f.get(k, '')):
                f[f'{k}_image'] = None
            else:
                f[f'{k}_image'] = _images.image_for(f.get(k, '')) or f.get(f'{k}_image')
        f['fighter1_tape'] = _tape(profiles.get(_profile_key(f.get('fighter1', ''))))
        f['fighter2_tape'] = _tape(profiles.get(_profile_key(f.get('fighter2', ''))))
        f['is_past'] = f.get('date', '') < today_iso
        f['result'] = _result_for(f, profiles) if f['is_past'] else None
        # Only call it "pending" while a result could realistically still land:
        # inside the grace window, with at least one fighter whose Wikipedia
        # record we can read.
        f['result_pending'] = bool(
            f['is_past'] and not f['result'] and f.get('date', '') >= grace_iso
            and any((profiles.get(_profile_key(f.get(k, ''))) or {}).get('title')
                    for k in ('fighter1', 'fighter2'))
        )
    return fights


_scrape_lock = threading.Lock()


# ── Results archive ─────────────────────────────────────────────────────────
# Completed fights are kept in their own file, separate from the cache that is
# rewritten every scrape. Sources stop listing a card once it has happened, so
# this archive is the only lasting record of past cards and their results.
# It is append-only (never pruned); the site shows the last RESULTS_WINDOW_DAYS.

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


# ── Last known-good data per source ─────────────────────────────────────────
# Written every time a source's scrape passes validation. When a source fails,
# its fights are carried forward from here, so the site keeps its upcoming
# schedule even if the cache has been cleared. No admin action deletes this.

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


def _refresh_cache(wait=False):
    """Run the full scrape and save the cache. Only one scrape runs at a time.
    With wait=False returns None immediately if another scrape is running;
    with wait=True blocks briefly so a cold-start request can use the result."""
    if wait:
        acquired = _scrape_lock.acquire(timeout=90)
    else:
        acquired = _scrape_lock.acquire(blocking=False)
    if not acquired:
        logger.info("Scrape already in progress in another thread, skipping")
        return None
    try:
        with _locks.job_lock('scrape', wait_seconds=90 if wait else 0) as got:
            if not got:
                logger.info("Scrape already in progress in the other worker, skipping")
                return None
            # The other worker may have just finished a scrape while we waited
            fresh = load_cache()
            if fresh:
                return fresh
            fights = _scrape_all_sources()
        if fights:
            threading.Thread(target=refresh_profiles, args=(fights,), daemon=True).start()
            threading.Thread(target=_images.fill_credits, daemon=True).start()
        return fights
    except Exception as e:
        logger.error(f"Background scrape failed: {e}", exc_info=True)
        return None
    finally:
        _scrape_lock.release()


def fetch_fights():
    """Fight data with tale-of-the-tape and results attached (see enrich_fights)."""
    fights = _fetch_fights_raw()
    _maybe_start_profile_job(fights)
    return enrich_fights(fights)


def archived_fights(live):
    """Finished fights older than the results window, from the archive. Their
    pages stay online (and in the sitemap) after they leave the lists, so
    links and search results for past fights keep working."""
    cutoff = _retention_cutoff_iso()
    seen = {_fight_key(f) for f in live}
    old = [dict(f) for f in load_results_archive()
           if f.get('date', '') < cutoff and _fight_key(f) not in seen]
    return normalize_ufc_cards(old) if old else []


def fights_for_pages():
    """Live fights plus archived ones: what fight pages and the sitemap use."""
    fights = fetch_fights()
    old = archived_fights(fights)
    return fights + enrich_fights(old) if old else fights


def _fetch_fights_raw():
    """Return fight data, preferring cache. Stale-while-revalidate: if the
    cache is expired but usable, serve it immediately and refresh in a
    background thread so visitors never wait on a scrape."""
    cached_fights = load_cache()
    if cached_fights:
        return cached_fights

    # Any surviving upcoming fights beat making the visitor wait on a scrape.
    # load_cache() strips past events, so an all-past cache falls through.
    stale_fights = load_cache(max_age_hours=24 * 365)
    if stale_fights:
        threading.Thread(target=_refresh_cache, daemon=True).start()
        logger.info(f"Serving {len(stale_fights)} stale fights while refreshing in background")
        return stale_fights

    # Nothing usable cached — scrape synchronously, waiting on any in-flight run
    fights = _refresh_cache(wait=True)
    if not fights:
        fights = load_cache(max_age_hours=24 * 365) or []
    return fights


FLOOR = {'UFC': 10, 'Boxing': 5}   # fewer fights than this = treat the scrape as failed


def _run_source(source, fn, log):
    """Run one scraper and write its run record. Returns (fights, status, record).
    status: 'ok' | 'partial' | 'failed' (see runs.py). fn may return a result
    dict or, in tests, a plain list."""
    started = time.time()
    try:
        result = fn()
    except Exception as e:
        logger.error(f"{source} scraper crashed: {e}", exc_info=True)
        result = {'fights': [], 'outcome': 'crash', 'diagnostics': {'error': f'{type(e).__name__}: {e}'}}
    if isinstance(result, list):
        result = {'fights': result, 'outcome': 'parsed' if result else 'empty', 'layout': None}
    fights = result.get('fights') or []
    outcome = result.get('outcome') or 'parsed'
    n = len(fights)
    checks = [
        {'name': 'fetched', 'ok': outcome not in ('http_error', 'crash'), 'detail': outcome},
        {'name': 'layout_known', 'ok': outcome != 'layout_unknown', 'detail': result.get('layout')},
        {'name': 'floor', 'ok': n >= FLOOR[source], 'detail': f'{n} fights, floor {FLOOR[source]}'},
    ]
    if source == 'UFC' and result.get('months'):
        failed = [m for m, i in result['months'].items() if i.get('error')]
        checks.append({'name': 'all_months', 'ok': not failed, 'detail': f'failed: {failed}' if failed else 'all months read'})
    # all_months is informational: a half-read ESPN is used (partial), not failed
    if not all(c['ok'] for c in checks if c['name'] != 'all_months'):
        status = 'failed'
    elif outcome == 'partial' or not all(c['ok'] for c in checks):
        status = 'partial'
    else:
        status = 'ok'
    counts = {'fights': n}
    if source == 'UFC' and result.get('months'):
        counts['months'] = {m: i.get('fights', 0) for m, i in result['months'].items()}
    if result.get('layouts'):
        counts['layouts'] = result['layouts']
    rec = _runs.write_run(source, status, outcome, counts=counts, checks=checks, layout=result.get('layout'),
                          snapshots=result.get('snapshots'), diagnostics=result.get('diagnostics'),
                          duration_s=round(time.time() - started, 1),
                          note='; '.join(f"{c['name']}: {c['detail']}" for c in checks if not c['ok']) or None)
    log(f"{source}: {status} ({outcome}), {n} fights, layout={result.get('layout')}, {rec['duration_s']}s")
    return fights, status, rec


def _scrape_all_sources():
    """Fetch upcoming UFC and Boxing fights from multiple sources"""
    # Open debug log file
    debug_log = open(data_path('data_sources_comparison.txt'), 'w', encoding='utf-8')
    
    def log(message):
        """Log to both console and file"""
        print(message)
        debug_log.write(message + '\n')
    
    # If no cache, fetch fresh data
    fights = []
    
    log("\n" + "="*60)
    log("FIGHT DATA SOURCES COMPARISON")
    log("="*60 + "\n")
    
    # 1. Scrape BoxingSchedule.co for boxing
    log("--- BOXINGSCHEDULE.CO ---")
    boxingschedule_fights, boxing_status, boxing_run = _run_source('Boxing', scrape_boxing_events, log)
    log(f"BoxingSchedule.co found: {len(boxingschedule_fights)} fights\n")
    for fight in boxingschedule_fights[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} {'[MAIN]' if fight.get('is_main_event') else ''}")
    if len(boxingschedule_fights) > 5:
        log(f"  ... and {len(boxingschedule_fights) - 5} more\n")
    
    
    # 2. Scrape MMA Fighting for UFC schedule
    log("\n--- ESPN UFC ---")
    mma_fighting_ufc, ufc_status, ufc_run = _run_source('UFC', scrape_ufc_events, log)
    log(f"ESPN UFC found: {len(mma_fighting_ufc)} fights\n")
    for fight in mma_fighting_ufc[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} - {fight['venue']}")
    if len(mma_fighting_ufc) > 5:
        log(f"  ... and {len(mma_fighting_ufc) - 5} more\n")
    
    
    # 4. Combine data
    log("\n" + "="*60)
    log("MERGING DATA...")
    log("="*60 + "\n")
    
    # Add BoxingSchedule.co fights
    fights.extend(boxingschedule_fights)
    
    
    # Add MMA Fighting UFC fights
    fights.extend(mma_fighting_ufc)
    
    # Sources can repeat a listing; keep one copy of each matchup per date.
    _seen = set()
    fights = [f for f in fights if not (_fight_key(f) in _seen or _seen.add(_fight_key(f)))]

    # VALIDATION: check each scraper independently. A single broken source
    # must never blank the whole site, so failed sports fall back to the last
    # known-good cached data for that sport instead of discarding everything.
    ufc_count = len(mma_fighting_ufc)
    boxing_count = len(boxingschedule_fights)

    # A run is usable when its record says ok or partial (fetched, known
    # layout, at least FLOOR fights). Step 3 of the robustness plan replaces
    # this with per-row and per-run checks against the last good run.
    ufc_ok = ufc_status != 'failed'
    boxing_ok = boxing_status != 'failed'
    try:
        import alerts as _alerts
        _alerts.report('UFC', ufc_ok, ufc_run.get('note') or f'{ufc_count} fights')
        _alerts.report('Boxing', boxing_ok, boxing_run.get('note') or f'{boxing_count} fights')
    except Exception as e:
        logger.warning(f"alerting failed: {e}")

    if not ufc_ok:
        log(f"\n[X] UFC scraper returned only {ufc_count} fights (expected 50+)")
        logger.error(f"SCRAPER FAILURE: UFC scraper returned only {ufc_count} fights")
    if not boxing_ok:
        log(f"\n[X] Boxing scraper returned only {boxing_count} fights (expected 10+)")
        logger.error(f"SCRAPER FAILURE: Boxing scraper returned only {boxing_count} fights")

    if ufc_ok:
        save_last_good('UFC', mma_fighting_ufc)
    if boxing_ok:
        save_last_good('Boxing', boxingschedule_fights)

    if not (ufc_ok and boxing_ok):
        # Carry forward the failed sport from the previous cache, or — if the
        # cache is gone (cleared, corrupted) — from the source's last good scrape
        previous = load_cache(max_age_hours=24 * 365) or []
        for sport, ok in (('UFC', ufc_ok), ('Boxing', boxing_ok)):
            if ok:
                continue
            carried = [f for f in previous if f.get('sport') == sport]
            origin = 'cache'
            if not carried:
                carried, origin = [dict(f) for f in load_last_good(sport)], 'last-good snapshot'
            _seen = set()
            carried = [f for f in carried if not (_fight_key(f) in _seen or _seen.add(_fight_key(f)))]
            fights = [f for f in fights if f.get('sport') != sport] + carried
            log(f"  -> carried forward {len(carried)} {sport} fights from the {origin}")
        if not ufc_ok and not boxing_ok:
            logger.error("SCRAPER FAILURE: both scrapers failed, serving cached data only")

    log(f"\n[OK] Validation: UFC={ufc_count} ({'ok' if ufc_ok else 'FAILED'}), "
        f"Boxing={boxing_count} ({'ok' if boxing_ok else 'FAILED'}), Total={len(fights)}\n")
    
    
    # 5. Fetch images for fights that don't have them yet
    log("\n--- FETCHING MISSING FIGHTER IMAGES ---\n")
    images_fetched = 0
    for fight in fights:
        if not fight.get('fighter1_image'):
            img = get_fighter_image(fight['fighter1'])
            if img:
                fight['fighter1_image'] = img
                images_fetched += 1
        if not fight.get('fighter2_image'):
            img = get_fighter_image(fight['fighter2'])
            if img:
                fight['fighter2_image'] = img
                images_fetched += 1
    
    log(f"Fetched {images_fetched} additional fighter images")
    
    # Sort fights by date
    fights.sort(key=lambda x: x['date'] if x['date'] else '9999-12-31')
    # Sources only list upcoming cards, so completed fights within the results
    # window are carried forward from the results archive (and the previous
    # cache, which also seeds the archive on first run), deduped by matchup.
    # Includes today: sources drop a card as soon as it ends, which is often
    # hours before UTC midnight (this is how UFC 331 was once lost).
    today = date.today().isoformat()
    cutoff = _retention_cutoff_iso()
    previous_cache = load_cache(max_age_hours=24 * 365) or []
    archive_results(previous_cache)
    seen_pairs = {_fight_key(f) for f in fights}
    carried_past = 0
    for f in load_results_archive() + previous_cache:
        if cutoff <= f.get('date', '') <= today:
            key = _fight_key(f)
            if key not in seen_pairs:
                fights.append(dict(f)); seen_pairs.add(key); carried_past += 1
    log(f"Carried forward {carried_past} completed fights for results")
    fights.sort(key=lambda x: x['date'] if x['date'] else '9999-12-31')
    fights = normalize_ufc_cards(fights)

    fights_before_filter = len(fights)
    fights = [f for f in fights if f.get('date', '') >= cutoff]
    
    # Keep all UFC fights (no filtering needed)
    fights_before_sport_filter = len(fights)
    # No filtering needed - trust the source curation
    
    log(f"Kept all {len(fights)} fights from trusted sources")
    
    # Count fights with images
    with_images = sum(1 for f in fights if f.get('fighter1_image') or f.get('fighter2_image'))
    log(f"Fights with at least one image: {with_images} ({with_images*100//len(fights) if fights else 0}%)\n")
    
    debug_log.close()
    print("\n✓ Debug comparison saved to: data_sources_comparison.txt\n")
    
    # Apply manual time overrides
    fights = apply_time_overrides(fights)
    
    # Save to cache
    if fights:
        save_cache(fights)
    
    return fights

@app.route('/persisted-fighters/<path:filename>')
def persisted_fighter_image(filename):
    """Serve fighter images stored in the persistent data volume."""
    fighters_dir = data_path('fighters')
    return send_from_directory(fighters_dir, filename)


_photo_thumb_cache = {}


def _photo_file(url):
    """Local file behind a fighter photo URL, or None for remote images."""
    bare = (url or '').split('?')[0]
    if bare.startswith('/persisted-fighters/'):
        return os.path.join(data_path('fighters'), bare[len('/persisted-fighters/'):])
    if bare.startswith('/static/'):
        return os.path.join(app.root_path, bare.lstrip('/'))
    return None


def _photo_thumb(path):
    """32px-wide greyscale thumbnail of a stored photo, cached by file mtime."""
    mtime = os.path.getmtime(path)
    cached = _photo_thumb_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        g = ImageOps.exif_transpose(im).convert('L')
        thumb = g.resize((32, max(1, round(g.height * 32 / g.width))))
    _photo_thumb_cache[path] = (mtime, thumb)
    return thumb


def _same_picture(url_a, url_b):
    """True when two fighter photos show the same picture. Saved photos are
    square crops, so the same source can be stored twice with different crops
    and bytes (e.g. one walkout photo saved for both fighters). Compare small
    greyscale thumbnails, sliding the shorter one along the taller one. Same
    picture scores ~3, different fighters 24+ on live data; the cut-off is 12."""
    if url_a.split('?')[0] == url_b.split('?')[0]:
        return True
    pa, pb = _photo_file(url_a), _photo_file(url_b)
    if not pa or not pb or not os.path.exists(pa) or not os.path.exists(pb):
        return False
    a, b = _photo_thumb(pa), _photo_thumb(pb)
    if a.height > b.height:
        a, b = b, a
    da = a.tobytes()
    best = 255.0
    for off in range(0, b.height - a.height + 1):
        db = b.crop((0, off, 32, off + a.height)).tobytes()
        best = min(best, sum(abs(x - y) for x, y in zip(da, db)) / len(da))
    return best < 12


def _two_distinct_photos(ev):
    a, b = ev.get('fighter1_image'), ev.get('fighter2_image')
    if not a or not b:
        return False
    for u in (a, b):
        f = _photo_file(u)
        if f and not os.path.exists(f):   # a photo that would render broken
            return False
    try:
        return not _same_picture(a, b)
    except Exception:
        return a.split('?')[0] != b.split('?')[0]


_NUMBERED_UFC = re.compile(r'^UFC \d+\b')


def _big_fights(events, today, limit=6, horizon_days=90):
    """Lead cards for the homepage: numbered UFC events, boxing title fights and
    big-name fights in the next `horizon_days`, soonest first -- only when both
    fighters have real, different photos (a lead card with silhouettes or one
    photo twice looks broken)."""
    horizon = (today + timedelta(days=horizon_days)).isoformat()
    today_iso = today.isoformat()
    window = [e for e in events if today_iso <= e['date'] <= horizon
              and e['fighter1'] != 'TBA' and e['fighter2'] != 'TBA']

    def is_big(e):
        if e['sport'] == 'UFC' and _NUMBERED_UFC.match(e.get('event_name') or ''):
            return True
        if e['sport'] == 'Boxing' and (e.get('weight_class') or '').startswith('Title'):
            return True
        return is_big_name_fight(e)

    big = [e for e in window if is_big(e) and _two_distinct_photos(e)][:limit]
    if not big:
        scored = sorted(window, key=lambda e: (-score_fight_for_featuring(
            dict(e, is_main_event=True), today), e['date']))
        big = [e for e in scored if _two_distinct_photos(e)][:1]
    return big


@app.route('/')
def home():
    logger.info("--> Home page accessed")
    fights = upcoming_only(fetch_fights())
    logger.info(f"  Rendering {len(fights)} upcoming fights")

    events = (_group_events_for_landing(fights, 'UFC')[0] +
              _group_events_for_landing(fights, 'Boxing')[0])
    events.sort(key=lambda e: (e['date'] or '9999',
                               e['time'] if e['time'] and ':' in str(e['time']) else '99:99'))
    for e in events:
        e['slug'] = e['path'].rsplit('/', 1)[-1]
    big = _big_fights(events, date.today())
    for e in big:
        logger.info(f"  Big fight: {e['fighter1']} vs {e['fighter2']} ({e['date']})")

    # Day sections as the server sees them (UTC). The browser regroups them by
    # the visitor's local day; crawlers and no-JS visitors get this grouping.
    days = []
    for e in events:
        if not days or days[-1]['date'] != e['date']:
            days.append({'date': e['date'], 'events': []})
        days[-1]['events'].append(e)

    # Every upcoming bout, for the search box
    search_fights = []
    for f in fights:
        if f.get('sport') == 'Boxing':
            path = f"/boxing-event/{_to_slug(f['fighter1'])}-vs-{_to_slug(f['fighter2'])}-{f['date']}"
            if not f.get('is_main_event'):
                main = next((e for e in events if e['sport'] == 'Boxing' and e['date'] == f['date']
                             and e['venue'] == f.get('venue', '')), None)
                path = main['path'] if main else path
        else:
            path = f"/event/{(f.get('event_name') or '').lower().replace(' ', '-').replace(':', '').replace(',', '')}-{f['date']}"
        search_fights.append({
            'fighter1': f.get('fighter1', ''), 'fighter2': f.get('fighter2', ''),
            'fighter1_image': f.get('fighter1_image') or get_fighter_image(f.get('fighter1', '')),
            'fighter2_image': f.get('fighter2_image') or get_fighter_image(f.get('fighter2', '')),
            'event_name': f.get('event_name') or '', 'venue': f.get('venue') or '',
            'date': f.get('date', ''), 'time': f.get('time'),
            'time_estimated': bool(f.get('time_estimated')), 'sport': f.get('sport', ''),
            'path': path,
        })

    return render_template('index.html', events=events, big=big, days=days,
                           search_fights=search_fights)

# ============================================================================
# SPORT LANDING PAGES — /ufc and /boxing
# ============================================================================

_MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December']


def _undercard(bouts, main, prelims_last=False):
    """The other bouts on the same card as `main`, in card order (UFC: main card
    before prelims)."""
    rest = [b for b in bouts if b is not main]
    if prelims_last:
        rest = [b for b in rest if b.get('card_type') != 'Prelims'] + \
               [b for b in rest if b.get('card_type') == 'Prelims']
    return [{'fighter1': b.get('fighter1', ''), 'fighter2': b.get('fighter2', ''),
             'weight_class': b.get('weight_class', ''), 'card_type': b.get('card_type') or '',
             'date': b.get('date'), 'time': b.get('time'),
             'result': b.get('result'), 'result_pending': b.get('result_pending', False)}
            for b in rest]


def _group_events_for_landing(fights, sport):
    """Build a per-event summary list for the /ufc or /boxing landing pages."""
    events = []
    if sport == 'UFC':
        seen = set()
        # Count all fights (incl. prelims) per event
        counts = {}
        bouts = {}
        for f in fights:
            if f.get('sport') == 'UFC':
                counts[f.get('event_name', '')] = counts.get(f.get('event_name', ''), 0) + 1
                bouts.setdefault(f.get('event_name', ''), []).append(f)
        for f in fights:
            if f.get('sport') != 'UFC' or f.get('card_type') == 'Prelims':
                continue
            name = f.get('event_name', '')
            if name in seen:
                continue
            seen.add(name)
            slug = f"{name.lower().replace(' ', '-').replace(':', '').replace(',', '')}-{f['date']}"
            events.append({
                'title': name,
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'fighter1_image': f.get('fighter1_image') or get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or get_fighter_image(f['fighter2']),
                'date': f['date'],
                'time': f.get('time'),
                'time_estimated': f.get('time_estimated', False),
                'venue': f.get('venue', ''),
                'location': f.get('location', ''),
                # UFC is on Paramount+ in the US (also Latin America and
                # Australia) since 2026; the UFC source names no broadcaster.
                'streaming': 'Paramount+',
                'fight_count': counts.get(name, 1),
                'sport': 'UFC',
                'undercard': _undercard(bouts.get(name, []), f, prelims_last=True),
                'weight_class': f.get('weight_class', ''),
                'event_name': f.get('event_name', ''),
                'path': f"/event/{slug}",
                'url': f"https://fightschedule.live/event/{slug}",
                'is_past': f.get('is_past', False),
                'result': f.get('result'),
                'result_pending': f.get('result_pending', False),
            })
    else:
        # Boxing: one entry per main event; count undercard via venue+date
        counts = {}
        bouts = {}
        for f in fights:
            if f.get('sport') == 'Boxing':
                key = (f.get('venue', ''), f.get('date', ''))
                counts[key] = counts.get(key, 0) + 1
                bouts.setdefault(key, []).append(f)
        for f in fights:
            if f.get('sport') != 'Boxing' or not f.get('is_main_event'):
                continue
            slug = f"{_to_slug(f['fighter1'])}-vs-{_to_slug(f['fighter2'])}-{f['date']}"
            events.append({
                'title': f"{f['fighter1']} vs {f['fighter2']}",
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'fighter1_image': f.get('fighter1_image') or get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or get_fighter_image(f['fighter2']),
                'date': f['date'],
                'time': f.get('time'),
                'time_estimated': f.get('time_estimated', False),
                'venue': f.get('venue', ''),
                'location': f.get('location', ''),
                'streaming': f.get('streaming', ''),
                'fight_count': counts.get((f.get('venue', ''), f.get('date', '')), 1),
                'sport': 'Boxing',
                'undercard': _undercard(bouts.get((f.get('venue', ''), f.get('date', '')), []), f),
                'weight_class': f.get('weight_class', ''),
                'event_name': f.get('event_name', ''),
                'path': f"/boxing-event/{slug}",
                'url': f"https://fightschedule.live/boxing-event/{slug}",
                'is_past': f.get('is_past', False),
                'result': f.get('result'),
                'result_pending': f.get('result_pending', False),
            })

    events.sort(key=lambda e: (e['date'] or '9999', e['time'] or '99:99'))

    # Group by month for display
    months = []
    for ev in events:
        try:
            y, m = int(ev['date'][:4]), int(ev['date'][5:7])
            label = f"{_MONTH_NAMES[m - 1]} {y}"
        except Exception:
            label = 'Upcoming'
        if not months or months[-1]['label'] != label:
            months.append({'label': label, 'events': []})
        months[-1]['events'].append(ev)

    return events, months


def _day_sections(events, newest_first=False):
    """[{'date', 'events'}] in list order; the browser regroups by local day."""
    key = lambda e: (e['date'] or '9999', e['time'] if e.get('time') and ':' in str(e['time']) else '99:99')
    days = []
    for e in sorted(events, key=key, reverse=newest_first):
        e.setdefault('slug', e['path'].rsplit('/', 1)[-1])
        if not days or days[-1]['date'] != e['date']:
            days.append({'date': e['date'], 'events': []})
        days[-1]['events'].append(e)
    return days


@app.route('/ufc')
def ufc_schedule():
    """UFC schedule landing page."""
    fights = fetch_fights()
    all_events, months = _group_events_for_landing(upcoming_only(fights), 'UFC')
    recent_events, recent_months = _group_events_for_landing(recent_results(fights), 'UFC')
    recent_months = [{'label': m['label'],
                      'events': sorted([e for e in m['events'] if e.get('result') or e.get('result_pending')],
                                       key=lambda e: e['date'], reverse=True)}
                     for m in reversed(recent_months)]
    recent_months = [m for m in recent_months if m['events']]
    now = datetime.now()
    page = {
        'sport': 'UFC',
        'title': f"UFC Schedule {now.year} — Upcoming UFC Events, Dates & Fight Cards",
        'heading': 'UFC Schedule',
        'tagline': 'every upcoming event with full fight cards',
        'breadcrumb': 'UFC Schedule',
        'meta_description': f"Full UFC schedule for {now.year}: every upcoming UFC event with dates, start times in your timezone, full fight cards, main events and venues. Updated daily.",
        'canonical_url': 'https://fightschedule.live/ufc',
        'intro': f"Every upcoming UFC event in one place — {len(all_events)} events with full fight cards, main card and prelim times shown in your local timezone.",
        'footer_text': "The UFC schedule is updated daily from live event data. Dates and times can shift as cards are finalized — subscribe to the calendar feed to stay current automatically.",
        'ics_path': '/calendar/ufc.ics',
        'placeholder': '/static/placeholder-fighter-mma.svg',
        'other_path': '/boxing',
        'other_label': 'boxing schedule',
    }
    days = _day_sections(all_events)
    recent_days = _day_sections([e for e in recent_events if e.get('result') or e.get('result_pending')], newest_first=True)
    return render_template('sport_schedule.html', page=page, months=months, all_events=all_events, recent_events=recent_events,
                           recent_months=recent_months, days=days, recent_days=recent_days)


@app.route('/boxing')
def boxing_schedule():
    """Boxing schedule landing page."""
    fights = fetch_fights()
    all_events, months = _group_events_for_landing(upcoming_only(fights), 'Boxing')
    recent_events, recent_months = _group_events_for_landing(recent_results(fights), 'Boxing')
    recent_months = [{'label': m['label'],
                      'events': sorted([e for e in m['events'] if e.get('result') or e.get('result_pending')],
                                       key=lambda e: e['date'], reverse=True)}
                     for m in reversed(recent_months)]
    recent_months = [m for m in recent_months if m['events']]
    now = datetime.now()
    page = {
        'sport': 'Boxing',
        'title': f"Boxing Schedule {now.year} — Upcoming Fights, Dates & Fight Cards",
        'heading': 'Boxing Schedule',
        'tagline': 'every upcoming fight night with undercards',
        'breadcrumb': 'Boxing Schedule',
        'meta_description': f"Full boxing schedule for {now.year}: every upcoming boxing match with dates, start times in your timezone, undercards, venues and where to watch. Updated daily.",
        'canonical_url': 'https://fightschedule.live/boxing',
        'intro': f"Every upcoming boxing event in one place — {len(all_events)} fight nights with main events, undercards and streaming info, times shown in your local timezone.",
        'footer_text': "The boxing schedule is updated daily from live event data. Dates and times can shift as promotions finalize cards — subscribe to the calendar feed to stay current automatically.",
        'ics_path': '/calendar/boxing.ics',
        'placeholder': '/static/placeholder-fighter-boxing.svg',
        'other_path': '/ufc',
        'other_label': 'UFC schedule',
    }
    days = _day_sections(all_events)
    recent_days = _day_sections([e for e in recent_events if e.get('result') or e.get('result_pending')], newest_first=True)
    return render_template('sport_schedule.html', page=page, months=months, all_events=all_events, recent_events=recent_events,
                           recent_months=recent_months, days=days, recent_days=recent_days)


@app.route('/results')
def results_page():
    """Results from the last 30 days, both sports, newest first."""
    past = recent_results(fetch_fights())
    events = (_group_events_for_landing(past, 'UFC')[0] +
              _group_events_for_landing(past, 'Boxing')[0])
    days = _day_sections(events, newest_first=True)
    return render_template('results.html', events=events, days=days)


@app.route('/event/<event_slug>')
def event_detail(event_slug):
    """Show detailed page for a specific event with full card"""
    logger.info(f"--> Event detail accessed: {event_slug}")
    fights = fights_for_pages()
    
    # Extract date from slug (last 10 chars: YYYY-MM-DD)
    # Slug format: "ufc-323-dvalishvili-vs-yan-2-2025-01-25"
    try:
        event_date = event_slug[-10:]  # Get last 10 characters (date)
        event_name_slug = event_slug[:-11]  # Everything except date and last hyphen
        logger.debug(f"  Parsed slug - date: {event_date}, name: {event_name_slug}")
    except:
        event_date = None
        event_name_slug = event_slug
        logger.debug(f"  Could not parse slug, using full: {event_slug}")
    
    # Group fights by event
    ufc_events = {}
    for fight in fights:
        if fight['sport'] == 'UFC':
            event_name = fight.get('event_name', '')
            if event_name not in ufc_events:
                ufc_events[event_name] = []
            ufc_events[event_name].append(fight)
    
    logger.debug(f"  Found {len(ufc_events)} UFC events")
    for name, fights_list in ufc_events.items():
        first_fight = fights_list[0] if fights_list else None
        if first_fight:
            logger.debug(f"    - {name}: DATE={first_fight['date']} ({len(fights_list)} fights)")
    
    # Find matching event by slug and date
    event_fights_list = None
    matched_event_name = None
    
    logger.debug(f"  Searching through {len(ufc_events)} events")
    
    # PRIORITY 1: Match by date (most reliable)
    if event_date:
        for event_name, fights_list in ufc_events.items():
            # Check if any fight in this event has matching date
            for fight in fights_list:
                if fight.get('date') == event_date:
                    event_fights_list = fights_list
                    matched_event_name = event_name
                    logger.info(f"  [OK] Matched by DATE: {matched_event_name} ({len(fights_list)} fights)")
                    break
            if event_fights_list:
                break
    
    # PRIORITY 2: Match by event name slug (fallback)
    if not event_fights_list:
        norm_url_slug = re.sub(r'[^a-z0-9-]', '', event_name_slug or '')
        for event_name, fights_list in ufc_events.items():
            # Create slug from this event name
            test_slug = event_name.lower().replace(' ', '-').replace(':', '').replace(',', '')
            test_slug = re.sub(r'[^a-z0-9-]', '', test_slug)

            # Check if slug matches (guard against empty name matching everything)
            if norm_url_slug and (test_slug in norm_url_slug or norm_url_slug in test_slug):
                event_fights_list = fights_list
                matched_event_name = event_name
                logger.info(f"  [OK] Matched by NAME: {matched_event_name}")
                break
    
    # No match — return a real 404. Falling back to another event made every
    # stale/mistyped URL render identical content, which search engines flag
    # as mass duplicate titles/descriptions.
    if not event_fights_list:
        logger.info(f"  [404] No UFC event matches slug: {event_slug}")
        abort(404)

    # Canonical URL enforcement: one URL per event. Slug variants (e.g. the
    # prelims date when a card crosses midnight UTC) 301 to the canonical slug.
    non_prelims = [f for f in event_fights_list if f.get('card_type') != 'Prelims'] or event_fights_list
    canonical_date = non_prelims[0].get('date')
    canonical_slug = f"{matched_event_name.lower().replace(' ', '-').replace(':', '').replace(',', '')}-{canonical_date}"
    if event_slug != canonical_slug:
        return redirect(f"/event/{canonical_slug}", code=301)


    # Separate main card and prelims
    main_card_fights = [f for f in event_fights_list if f.get('card_type') == 'Main Card']
    prelim_fights = [f for f in event_fights_list if f.get('card_type') == 'Prelims']
    
    logger.debug(f"  Main card fights: {len(main_card_fights)}, Prelims: {len(prelim_fights)}")
    
    # Get main event (first fight in main card)
    main_event_fight = main_card_fights[0] if main_card_fights else event_fights_list[0]
    
    logger.info(f"  Main event: {main_event_fight['fighter1']} vs {main_event_fight['fighter2']}")
    logger.info(f"  Event date: {main_event_fight['date']}, Time: {main_event_fight.get('time', 'TBA')}")
    logger.info(f"  Venue: {main_event_fight['venue']}")
    
    # Get weight class from first title fight
    weight_class = ''
    for fight in main_card_fights:
        if fight.get('weight_class') == 'Title':
            weight_class = 'Championship'
            break
    
    # Build event data structure
    event_data = {
        'event_name': matched_event_name,
        'date': main_event_fight['date'],
        'venue': main_event_fight['venue'],
        'main_event': {
            'fighter1': main_event_fight['fighter1'],
            'fighter2': main_event_fight['fighter2'],
            'fighter1_image': main_event_fight.get('fighter1_image') or get_fighter_image(main_event_fight['fighter1']),
            'fighter2_image': main_event_fight.get('fighter2_image') or get_fighter_image(main_event_fight['fighter2']),
            'weight_class': weight_class,
            'time': main_event_fight.get('time', 'TBA'),
            **{k: main_event_fight.get(k) for k in ('is_past', 'result', 'result_pending', 'fighter1_tape', 'fighter2_tape', 'sport', 'date')},
        },
        'main_card': [
            {
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'is_title': f.get('weight_class') == 'Title',
                'result': f.get('result'),
                'weight_class': '' if f.get('weight_class') == 'Title' else (f.get('weight_class') or ''),
                'fighter1_image': f.get('fighter1_image') or get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or get_fighter_image(f['fighter2']),
            }
            for f in main_card_fights
        ],
        'prelims': [
            {
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'result': f.get('result'),
                'weight_class': '' if f.get('weight_class') == 'Title' else (f.get('weight_class') or ''),
                'fighter1_image': f.get('fighter1_image') or get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or get_fighter_image(f['fighter2']),
            }
            for f in prelim_fights
        ],
        'main_card_time': main_card_fights[0].get('time', 'TBA') if main_card_fights else 'TBA',
        'prelim_time': prelim_fights[0].get('time', 'TBA') if prelim_fights else 'TBA'
    }
    
    # Load AI preview for main event
    preview = get_or_generate_preview(
        preview_id=event_slug,
        fighter1=main_event_fight['fighter1'],
        fighter2=main_event_fight['fighter2'],
        sport='UFC',
        is_title=(main_event_fight.get('weight_class') == 'Title'),
        weight_class=None  # UFC doesn't extract weight classes
    )
    
    event_data['preview'] = preview
    
    # SEO metadata
    event_data['page_title'], event_data['meta_description'] = fight_page_seo(
        'UFC', matched_event_name, event_data.get('date') or main_event_fight['date'], main_event_fight.get('venue'),
        main_event_fight.get('location'), bool(main_event_fight.get('is_past')))
    event_data['canonical_url'] = f"https://fightschedule.live/event/{event_slug}"
    
    return render_template('event_detail.html', event=event_data)

# ── Search titles and descriptions for fight pages ──────────────────────────
# Shaped like the searches people make ("X vs Y start time", "UFC 333 results").
# Kept under ~65 characters (titles) / ~160 (descriptions), where Google cuts.

TITLE_MAX = 65
DESC_MAX = 160


def _long_date(iso):
    """'2026-10-24' -> 'Saturday 24 October 2026' (the date in UTC)."""
    try:
        d = datetime.strptime(iso, '%Y-%m-%d')
    except (TypeError, ValueError):
        return iso or 'date TBA'
    return f"{d:%A} {d.day} {d:%B %Y}"


def _place_text(venue, location):
    """'London' + 'London' -> 'London'; drops TBA and repeats."""
    parts = []
    for x in (venue, location):
        x = (x or '').strip()
        if x and x.upper() != 'TBA' and not any(x.lower() in p.lower() for p in parts):
            parts = [p for p in parts if p.lower() not in x.lower()] + [x]
    return ', '.join(parts)


def _fit_title(*candidates):
    for c in candidates:
        if len(c) <= TITLE_MAX:
            return c
    return candidates[-1]


def _boxing_kind(weight_class):
    """'Title Heavyweight' -> 'heavyweight title fight'; 'Middleweight' -> 'middleweight bout'."""
    wc = (weight_class or '').strip()
    title = wc.startswith('Title')
    division = wc[5:].strip().lower() if title else wc.lower()
    return f"{division + ' ' if division else ''}{'title fight' if title else 'bout'}"


def fight_page_seo(sport, name, date_iso, venue, location, is_past, kind=None, streaming=None):
    """(page_title, meta_description) for a UFC event or boxing card page.
    name: 'UFC 333: Volkanovski vs. Evloev' or 'Daniel Dubois vs Fabio Wardley'."""
    when = _long_date(date_iso)
    place = _place_text(venue, location)
    sep = 'at' if sport == 'UFC' else 'in'

    def desc_fit(make):
        """The fullest description that fits ~160 characters: with the place, then without."""
        for at in ((f" {sep} {place}" if place else ''), ''):
            d = make(at)
            if len(d) <= DESC_MAX:
                return d
        return d

    if sport == 'UFC':
        if is_past:
            title = _fit_title(f"{name}: Results & Full Fight Card", f"{name}: Results", name)
            desc = desc_fit(lambda at: f"{name} results and the full fight card, {when}{at}.")
        else:
            title = _fit_title(f"{name}: Start Time, Date & Fight Card", f"{name}: Start Time & Card", name)
            desc = desc_fit(lambda at: f"{name}, {when}{at}. Start times in your time zone, full card and where to watch.")
    else:
        if is_past:
            title = _fit_title(f"{name}: Result & Full Card", f"{name}: Result", name)
            desc = desc_fit(lambda at: f"{name} result: {kind or 'bout'}, {when}{at}. Plus the full undercard.")
        else:
            title = _fit_title(f"{name}: Start Time, Date & Full Card", f"{name}: Start Time & Card", name)
            watch = f" ({streaming})" if streaming else ''
            desc = desc_fit(lambda at: f"{name}, {kind or 'bout'}, {when}{at}. Start time in your time zone, "
                                       f"full undercard and where to watch{watch}.")
    return title, desc


@app.route('/boxing-event/<event_slug>')
def boxing_event_detail(event_slug):
    """Show boxing event details using fighter names in URL"""
    logger.info(f"Boxing event accessed: {event_slug}")
    
    all_fights = fights_for_pages()
    boxing_fights = [f for f in all_fights if f.get('sport') == 'Boxing']
    
    # Parse slug: fighter1-vs-fighter2-YYYY-MM-DD
    parts = event_slug.rsplit('-', 3)
    if len(parts) >= 3:
        date_str = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
        fighter_slug = '-'.join(parts[:-3])
    else:
        return "Invalid event URL", 404
    
    # Find any fight matching this slug (not restricted to main event)
    target_fight = None
    for fight in boxing_fights:
        if fight['date'] == date_str:
            f1 = _to_slug(fight['fighter1'])
            f2 = _to_slug(fight['fighter2'])
            fight_slug = f"{f1}-vs-{f2}"
            if fight_slug == fighter_slug:
                target_fight = fight
                break

    if not target_fight:
        logger.warning(f"No boxing fight found for {event_slug}")
        return "Event not found", 404

    # Get all fights from same venue/date
    event_fights = [f for f in boxing_fights
                    if f['date'] == date_str and f['venue'] == target_fight['venue']]

    # Use the actual main event if available, otherwise fall back to the matched fight
    main_event_fight = next((f for f in event_fights if f.get('is_main_event')), target_fight)

    # Re-fetch images live from fighters.json so newly added images are always visible
    # (the cache may predate the image being added)
    for fight in event_fights:
        for key in ('fighter1', 'fighter2'):
            img_key = f'{key}_image'
            if not fight.get(img_key):
                img = get_fighter_image(fight[key])
                if img:
                    fight[img_key] = img

    logger.info(f"Found {len(event_fights)} fights for this event")
    
    event_fights_sorted = sorted(event_fights, key=lambda x: not x.get('is_main_event', False))
    undercard = event_fights_sorted[1:]
    
    logger.info(f"Main event: {main_event_fight['fighter1']} vs {main_event_fight['fighter2']}")
    
    # Build event data
    event_data = {
        'venue': main_event_fight['venue'],
        'location': main_event_fight['location'],
        'date': main_event_fight['date'],
        'time': main_event_fight.get('time', 'TBA'),
        'time_estimated': main_event_fight.get('time_estimated', False),
        'fight_count': len(event_fights),
        'streaming': main_event_fight.get('streaming'),  # Add streaming info
        'main_event': {
            'fighter1': main_event_fight['fighter1'],
            'fighter2': main_event_fight['fighter2'],
            'fighter1_image': main_event_fight.get('fighter1_image'),
            'fighter2_image': main_event_fight.get('fighter2_image'),
            **{k: main_event_fight.get(k) for k in ('is_past', 'result', 'result_pending', 'fighter1_tape', 'fighter2_tape', 'sport', 'date')},
        },
        'fights': [main_event_fight] + undercard
    }
    
    # Generate AI preview for main event
    # Create preview ID from sorted fighter names + date for consistency
    fighters_sorted = sorted([main_event_fight['fighter1'], main_event_fight['fighter2']])
    fighter1_slug = fighters_sorted[0].lower().replace(' ', '-').replace("'", '')
    fighter2_slug = fighters_sorted[1].lower().replace(' ', '-').replace("'", '')
    preview_id = f"boxing_{fighter1_slug}_{fighter2_slug}_{main_event_fight['date']}"
    
    preview = get_or_generate_preview(
        preview_id=preview_id,
        fighter1=main_event_fight['fighter1'],
        fighter2=main_event_fight['fighter2'],
        sport='Boxing',
        is_title=('Title' in main_event_fight.get('weight_class', '')),
        weight_class=main_event_fight.get('weight_class')
    )
    
    event_data['preview'] = preview
    
    # SEO metadata
    event_data['page_title'], event_data['meta_description'] = fight_page_seo(
        'Boxing', f"{main_event_fight['fighter1']} vs {main_event_fight['fighter2']}", main_event_fight['date'],
        main_event_fight.get('venue'), main_event_fight.get('location'), bool(main_event_fight.get('is_past')),
        kind=_boxing_kind(main_event_fight.get('weight_class')),
        streaming=_aff.clean_broadcaster(main_event_fight.get('streaming')) if main_event_fight.get('streaming') else None)
    event_data['canonical_url'] = f"https://fightschedule.live/boxing-event/{event_slug}"
    
    return render_template('boxing_event.html', event=event_data)

# ============================================================================
# SEO Routes
@app.route('/sitemap.xml')
def sitemap():
    """Generate dynamic sitemap"""
    from xml.sax.saxutils import escape as xml_escape
    fights = fights_for_pages()
    today = datetime.now().strftime('%Y-%m-%d')
    last_result = max((f['date'] for f in fights if f.get('is_past') and f.get('date')), default=today)

    pages = []
    versions = _load_versions()
    def newest(prefix):
        stamps = [v.get('lastmod', '') for u, v in versions.items() if prefix in u]
        return max(stamps)[:10] if stamps else today
    pages.append({'loc': 'https://fightschedule.live/', 'lastmod': newest('/'), 'changefreq': 'daily', 'priority': '1.0'})
    pages.append({'loc': 'https://fightschedule.live/ufc', 'lastmod': newest('/event/'), 'changefreq': 'daily', 'priority': '0.9'})
    pages.append({'loc': 'https://fightschedule.live/boxing', 'lastmod': newest('/boxing-event/'), 'changefreq': 'daily', 'priority': '0.9'})
    pages.append({'loc': 'https://fightschedule.live/results', 'lastmod': last_result, 'changefreq': 'daily', 'priority': '0.8'})
    pages.append({'loc': 'https://fightschedule.live/privacy', 'lastmod': PRIVACY_UPDATED.isoformat(), 'changefreq': 'yearly', 'priority': '0.3'})

    # UFC events — one URL per event (first non-prelim fight defines the
    # canonical date; must stay in sync with the redirect in event_detail)
    ufc_fights = [f for f in fights if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims']
    seen = set()
    for fight in ufc_fights:
        if fight['event_name'] in seen:
            continue
        seen.add(fight['event_name'])
        slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
        url = f"https://fightschedule.live/event/{slug}"
        pages.append({'loc': url, 'lastmod': versions.get(url, {}).get('lastmod', fight['date']), 'changefreq': 'daily', 'priority': '0.8'})

    # Boxing events - all main events
    boxing_fights = [f for f in fights if f.get('sport') == 'Boxing' and f.get('is_main_event')]
    seen = set()
    for fight in boxing_fights:
        # Must use the same slug rules as the boxing_event_detail matcher,
        # otherwise the sitemap emits URLs that 404 (e.g. names with periods)
        slug = f"{_to_slug(fight['fighter1'])}-vs-{_to_slug(fight['fighter2'])}-{fight['date']}"
        if slug not in seen:
            url = f"https://fightschedule.live/boxing-event/{slug}"
            pages.append({'loc': url, 'lastmod': versions.get(url, {}).get('lastmod', fight['date']), 'changefreq': 'daily', 'priority': '0.7'})
            seen.add(slug)

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for p in pages:
        loc = xml_escape(p['loc'])
        xml += f'  <url>\n    <loc>{loc}</loc>\n    <lastmod>{p["lastmod"]}</lastmod>\n    <changefreq>{p["changefreq"]}</changefreq>\n    <priority>{p["priority"]}</priority>\n  </url>\n'
    xml += '</urlset>'

    response = make_response(xml)
    response.headers['Content-Type'] = 'application/xml'
    return response

# ============================================================================
# ICS CALENDAR FEEDS
# ============================================================================

def _ics_escape(text):
    """Escape text for ICS format."""
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _build_calendar_events(fights):
    """Group fights into calendar events: one entry per fight card."""
    events = {}

    for fight in fights:
        if fight.get('sport') == 'UFC':
            key = ('ufc', fight.get('event_name', ''), )
            slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
            url = f"https://fightschedule.live/event/{slug}"
            title = fight.get('event_name') or f"{fight['fighter1']} vs {fight['fighter2']}"
        else:
            key = ('boxing', fight.get('venue', ''), fight.get('date', ''))
            main = fight if fight.get('is_main_event') else None
            url = None
            title = None

        ev = events.setdefault(key, {
            'sport': fight.get('sport'),
            'title': title,
            'url': url,
            'date': fight.get('date'),
            'time': None,
            'venue': fight.get('venue', ''),
            'location': fight.get('location', ''),
            'streaming': fight.get('streaming', ''),
            'fights': [],
        })
        ev['fights'].append(fight)

        # Earliest known start time wins; keep earliest date too (prelims can
        # start the previous UTC day)
        if fight.get('time') and fight['time'] != 'TBA':
            candidate = (fight.get('date', ''), fight['time'])
            current = (ev['date'] or '', ev['time'] or '99:99')
            if ev['time'] is None or candidate < current:
                ev['date'], ev['time'] = candidate

        # Boxing: title/url from the main event
        if fight.get('sport') == 'Boxing' and fight.get('is_main_event'):
            slug = f"{_to_slug(fight['fighter1'])}-vs-{_to_slug(fight['fighter2'])}-{fight['date']}"
            ev['title'] = f"{fight['fighter1']} vs {fight['fighter2']}"
            ev['url'] = f"https://fightschedule.live/boxing-event/{slug}"

    result = []
    for ev in events.values():
        if not ev['title']:
            first = ev['fights'][0]
            ev['title'] = f"{first['fighter1']} vs {first['fighter2']}"
        result.append(ev)
    result.sort(key=lambda e: (e['date'] or '9999', e['time'] or '99:99'))
    return result


def _render_ics(cal_events, cal_name):
    now_stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//fightschedule.live//Fight Schedule//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:{_ics_escape(cal_name)}',
        'X-WR-TIMEZONE:UTC',
    ]
    for ev in cal_events:
        if not ev['date']:
            continue
        date_compact = ev['date'].replace('-', '')
        uid_base = (ev['url'] or ev['title']).split('/')[-1]
        card_lines = []
        for f in ev['fights']:
            tag = f" ({f['card_type']})" if f.get('card_type') else ''
            card_lines.append(f"{f['fighter1']} vs {f['fighter2']}{tag}")
        desc = '\n'.join(card_lines)
        if ev.get('streaming'):
            desc += f"\nWatch on: {ev['streaming']}"
        if ev.get('url'):
            desc += f"\n{ev['url']}"

        lines.append('BEGIN:VEVENT')
        lines.append(f'UID:{uid_base}@fightschedule.live')
        lines.append(f'DTSTAMP:{now_stamp}')
        if ev['time'] and ev['time'] != 'TBA':
            start_compact = ev['time'].replace(':', '') + '00'
            lines.append(f'DTSTART:{date_compact}T{start_compact}Z')
            lines.append('DURATION:PT3H')
        else:
            lines.append(f'DTSTART;VALUE=DATE:{date_compact}')
        lines.append(f'SUMMARY:{_ics_escape(ev["title"])} ({ev["sport"]})')
        lines.append(f'DESCRIPTION:{_ics_escape(desc)}')
        location = ev.get('venue') or ev.get('location') or ''
        if location:
            lines.append(f'LOCATION:{_ics_escape(location)}')
        if ev.get('url'):
            lines.append(f'URL:{ev["url"]}')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    # RFC 5545 requires CRLF line endings
    return '\r\n'.join(lines) + '\r\n'


@app.route('/calendar.ics')
@app.route('/calendar/<sport>.ics')
def calendar_ics(sport=None):
    """Subscribable ICS calendar of upcoming fights (all, ufc, or boxing)."""
    if sport is not None and sport not in ('ufc', 'boxing'):
        abort(404)
    fights = upcoming_only(fetch_fights())
    if sport:
        fights = [f for f in fights if f.get('sport', '').lower() == sport]
        cal_name = f"{'UFC' if sport == 'ufc' else 'Boxing'} Schedule — fightschedule.live"
    else:
        cal_name = 'Fight Schedule — UFC & Boxing'

    ics = _render_ics(_build_calendar_events(fights), cal_name)
    response = make_response(ics)
    response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@app.route('/health')
def health():
    """200 when every source has a recent successful run, else 503. For an
    uptime monitor; the JSON body says what is wrong. Nothing here is secret."""
    h = _runs.health(extra={'lock_error': _locks.last_error,
                            'cache_age_hours': _cache_age_hours()})
    resp = jsonify(h)
    resp.status_code = 200 if h['healthy'] else 503
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _cache_age_hours():
    try:
        with open(CACHE_FILE) as fh:
            stamp = json.load(fh).get('timestamp')
        return round((datetime.now() - datetime.fromisoformat(stamp)).total_seconds() / 3600, 1)
    except Exception:
        return None


@app.route('/robots.txt')
def robots():
    """Generate robots.txt. AI search / training crawlers are welcome, but a
    crawler obeys only the most specific group naming it, so every group must
    carry the same disallows (admin, affiliate redirects, debug API)."""
    agents = ['*', 'GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-Web', 'anthropic-ai',
              'PerplexityBot', 'Google-Extended', 'Googlebot', 'Bytespider', 'CCBot', 'cohere-ai',
              'Amazonbot', 'YouBot', 'Meta-ExternalAgent']
    rules = 'Allow: /\nDisallow: /admin/\nDisallow: /go/\nDisallow: /api/\nDisallow: /health\n'
    groups = [f'User-agent: {ua}\n{rules}' for ua in agents]
    txt = groups[0] + '\n# AI search and training crawlers\n' + '\n'.join(groups[1:]) + \
        '\nSitemap: https://fightschedule.live/sitemap.xml\n'
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

@app.route('/llms.txt')
def llms_txt():
    """Plain-text guide for AI assistants and crawlers: what the site covers,
    how times work, and the current schedule and recent results with links.
    Generated from live data so it is never stale."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo('America/New_York')
    fights = fetch_fights()
    upcoming = upcoming_only(fights)
    past = recent_results(fights)

    def when(ev):
        start = _ld._start(ev['date'], ev.get('time'))
        if not start:
            return datetime.strptime(ev['date'], '%Y-%m-%d').strftime('%a %d %b %Y') + ', time TBA'
        utc = start.replace(tzinfo=ZoneInfo('UTC'))
        local = utc.astimezone(et)
        est = ' (estimated)' if ev.get('time_estimated') else ''
        return (f"{local.strftime('%a %d %b %Y, %I:%M %p').replace(' 0', ' ')} ET / "
                f"{utc.strftime('%H:%M')} UTC {utc.strftime('%a %d %b').replace(' 0', ' ')}{est}")

    def result_line(ev):
        r = ev.get('result') or {}
        if r.get('outcome') == 'win':
            how = ', '.join(x for x in (r.get('method'), f"round {r['round']}" if r.get('round') else None, r.get('time')) if x)
            return f"{r['winner']} def. {r['loser']}" + (f" ({how})" if how else '')
        if r.get('outcome') == 'draw':
            return 'Draw'
        if r.get('outcome') == 'nc':
            return 'No contest'
        return None

    lines = []
    for sport, label in (('UFC', 'UFC'), ('Boxing', 'Boxing')):
        evs, _ = _group_events_for_landing(upcoming, sport)
        lines.append(f"\n## Upcoming {label} events\n")
        if not evs:
            lines.append('- None listed right now.')
        for ev in evs[:15]:
            parts = [f"**{ev['title']}**" + (f" ({ev['fighter1']} vs {ev['fighter2']})" if sport == 'UFC' else ''),
                     when(ev), ev.get('venue') or 'venue TBA']
            if ev.get('weight_class'):
                parts.append(ev['weight_class'])
            if sport == 'UFC':
                parts.append('broadcast: Paramount+ (US, Latin America, Australia); UFC Fight Pass in most other countries')
            elif ev.get('streaming'):
                parts.append(f"broadcast: {ev['streaming']}")
            lines.append('- ' + ' — '.join(parts) + f" — {ev['url']}")
    results = []
    for sport in ('UFC', 'Boxing'):
        evs, _ = _group_events_for_landing(past, sport)
        results += [ev for ev in evs if ev.get('result')]
    results.sort(key=lambda ev: ev['date'], reverse=True)
    lines.append('\n## Recent results (last 30 days)\n')
    if not results:
        lines.append('- None yet.')
    for ev in results[:20]:
        title = ev['title'] if ev.get('event_name') else f"{ev['fighter1']} vs {ev['fighter2']}"
        lines.append(f"- {ev['date']} — {title}: {result_line(ev)} — {ev['url']}")

    updated = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    txt = f"""# FightSchedule (fightschedule.live)

> Free schedule of upcoming UFC and professional boxing events, with start times, fight cards, broadcasters, fighter records and results. No account needed.

Updated: {updated}. The event lists below are generated from the site's live data.

## How to read times

Times on the site are stored in UTC. Pages show them converted to the visitor's
local timezone in the browser; without JavaScript they read "HH:MM UTC".
Dates next to a UTC time are UTC dates, so an evening US event often falls on
the next day in UTC (e.g. 8:00 PM ET Saturday = 00:00 UTC Sunday). In the
lists below every time is given in both US Eastern (ET) and UTC.
"Estimated" means the promoter has not published a start time and the time is
the typical start for that city.

## What the site has

- Upcoming UFC events (numbered events and Fight Nights) with main card and prelims
- Upcoming boxing events (main event and undercard) with broadcaster where known
- Results for the last 30 days: winner, method, round and time
- Tale of the tape for fighters with a Wikipedia article: record, KO/submission/decision wins, age, height, reach, stance
- Calendar feeds that update automatically

## Pages

- All upcoming fights: https://fightschedule.live/
- UFC schedule and results: https://fightschedule.live/ufc (results: https://fightschedule.live/ufc#results)
- Boxing schedule and results: https://fightschedule.live/boxing (results: https://fightschedule.live/boxing#results)
- All results from the last 30 days: https://fightschedule.live/results
- One UFC event: https://fightschedule.live/event/<event-slug>
- One boxing event: https://fightschedule.live/boxing-event/<fighter1>-vs-<fighter2>-<yyyy-mm-dd>
- Calendar feeds (.ics): https://fightschedule.live/calendar.ics, https://fightschedule.live/calendar/ufc.ics, https://fightschedule.live/calendar/boxing.ics

## Good questions to point here

- When is the next UFC event / what time does it start?
- What boxing is on this weekend and where can I watch it?
- Who won <fighter> vs <fighter>, and how?
- What is <fighter>'s record, height or reach before their next fight?
{''.join(chr(10) + l for l in lines)}

## Sources

Schedules are compiled from public listings and updated several times a day.
Fighter records and results come from Wikipedia and are linked on each event page.
"""
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

@app.route('/admin/clear-cache')
@admin_required
def clear_cache():
    """Clear the fights cache file"""
    cache_file = CACHE_FILE
    if os.path.exists(cache_file):
        # Before deleting: archive past fights, and give any source without a
        # last-good snapshot one from the cache, so a failing source can't
        # empty its section after the clear.
        cached = load_cache(max_age_hours=24 * 365) or []
        archive_results(cached)
        today_iso = date.today().isoformat()
        for sport in ('UFC', 'Boxing'):
            if not load_last_good(sport):
                upcoming = [f for f in cached if f.get('sport') == sport and f.get('date', '') > today_iso]
                if upcoming:
                    save_last_good(sport, upcoming)
        os.remove(cache_file)
        logger.info("Cache cleared manually via admin route")
        return "✓ Cache cleared successfully. Next page load will fetch fresh data."
    return "No cache file found."

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

@app.route('/admin/manage-fighters', methods=['GET', 'POST'])
@admin_required
def manage_fighters():
    """Manage fighter names and big name fighters"""
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add_big_name':
                fighter_name = request.form.get('fighter_name')
                big_names_file = data_path('big_name_fighters.json')

                with open(big_names_file, 'r') as f:
                    big_names = json.load(f)

                if fighter_name not in big_names:
                    big_names.append(fighter_name)
                    big_names.sort()

                    with open(big_names_file, 'w') as f:
                        json.dump(big_names, f, indent=2)

                    logger.info(f"Added big name fighter: {fighter_name}")

            elif action == 'remove_big_name':
                fighter_name = request.form.get('fighter_name')
                big_names_file = data_path('big_name_fighters.json')

                with open(big_names_file, 'r') as f:
                    big_names = json.load(f)

                if fighter_name in big_names:
                    big_names.remove(fighter_name)

                    with open(big_names_file, 'w') as f:
                        json.dump(big_names, f, indent=2)

                    logger.info(f"Removed big name fighter: {fighter_name}")

            elif action == 'rename':
                old_name = request.form.get('old_name')
                new_name = request.form.get('new_name')
                sport = request.form.get('sport')

                json_file = data_path('fighters.json') if sport == 'Boxing' else data_path('fighters_ufc.json')

                with open(json_file, 'r', encoding='utf-8') as f:
                    fighters = json.load(f)

                if old_name in fighters:
                    fighters[new_name] = fighters.pop(old_name)

                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(fighters, f, indent=2, ensure_ascii=False)

                    logger.info(f"Renamed fighter: {old_name} → {new_name}")

            elif action == 'delete':
                fighter_name = request.form.get('fighter_name')
                sport = request.form.get('sport')

                json_file = data_path('fighters.json') if sport == 'Boxing' else data_path('fighters_ufc.json')

                with open(json_file, 'r', encoding='utf-8') as f:
                    fighters = json.load(f)

                if fighter_name in fighters:
                    del fighters[fighter_name]

                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(fighters, f, indent=2, ensure_ascii=False)

                    logger.info(f"Deleted fighter: {fighter_name}")
            
            return redirect('/admin/manage-fighters')
        
        # GET - show management page
        with open(data_path('fighters.json'), 'r', encoding='utf-8') as f:
            boxing = json.load(f)
        with open(data_path('fighters_ufc.json'), 'r', encoding='utf-8') as f:
            ufc = json.load(f)

        # Load big names, create if missing
        big_names_file = data_path('big_name_fighters.json')
        if os.path.exists(big_names_file):
            with open(big_names_file, 'r') as f:
                big_names_raw = json.load(f)
                # Ensure it's a list of strings, handle malformed data
                if isinstance(big_names_raw, list):
                    big_names = [item if isinstance(item, str) else str(item) for item in big_names_raw]
                else:
                    big_names = []
        else:
            big_names = []
        
        all_fighters = []
        for name, img in boxing.items():
            all_fighters.append({'name': name, 'sport': 'Boxing', 'image': img})
        for name, img in ufc.items():
            all_fighters.append({'name': name, 'sport': 'UFC', 'image': img})
        
        # Sort by name
        all_fighters.sort(key=lambda x: x['name'])
        
        return render_template('admin/manage_fighters.html', 
                              all_fighters=all_fighters, 
                              big_names=big_names)
    
    except Exception as e:
        logger.error(f"manage_fighters error: {e}", exc_info=True)
        return "An error occurred. Please try again.", 500

@app.route('/admin/download-jsons')
@admin_required
def download_jsons():
    """Download updated fighter JSONs as zip"""
    import zipfile
    from io import BytesIO
    
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        zip_file.write(data_path('fighters.json'), 'fighters.json')
        zip_file.write(data_path('fighters_ufc.json'), 'fighters_ufc.json')
    
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='fighters_updated.zip'
    )

# ============================================================================
# DEBUG DATA API — token-protected read-only access for remote diagnostics.
# Requires DEBUG_API_TOKEN env var to be set; returns 404 otherwise so the
# endpoint is invisible without the secret.
# ============================================================================

_DEBUG_PARTS = {
    'cache': 'fights_cache.json',
    'fighters': 'fighters.json',
    'fighters_ufc': 'fighters_ufc.json',
    'overrides': 'time_overrides.json',
    'profiles': 'fighter_profiles.json',
    'image_meta': 'image_meta.json',
    'results_archive': 'results_archive.json',
    'last_good': 'last_good.json',
}


@app.route('/api/debug/state', methods=['GET', 'POST'])
def debug_state():
    expected = os.environ.get('DEBUG_API_TOKEN', '')
    provided = request.args.get('token', '')
    if not expected or not hmac.compare_digest(provided, expected):
        abort(404)

    part = request.args.get('part')

    if part == 'scrape_test':
        # Run each scraper in isolation and report what it returns. Diagnostic
        # only: nothing is written to the cache.
        import traceback
        out = {}
        for name, fn in (('boxing', scrape_boxing_events), ('ufc', scrape_ufc_events)):
            started = datetime.now()
            try:
                got = fn()
                if isinstance(got, dict):
                    got = got.get('fights') or []
                dates = sorted(f.get('date', '') for f in got if f.get('date'))
                out[name] = {
                    'count': len(got),
                    'elapsed_seconds': round((datetime.now() - started).total_seconds(), 1),
                    'date_range': [dates[0], dates[-1]] if dates else None,
                    'upcoming_count': sum(1 for d in dates if d >= date.today().isoformat()),
                    'sample': got[:3],
                }
            except Exception as e:
                out[name] = {
                    'error': str(e),
                    'traceback': traceback.format_exc()[-2000:],
                    'elapsed_seconds': round((datetime.now() - started).total_seconds(), 1),
                }
        out['thresholds'] = {'ufc_min': 10, 'boxing_min': 5}
        return jsonify(out)

    if part == 'boxing_probe':
        # Fetch the boxing source directly and report what came back, so the
        # parser can be diagnosed without reaching the site from elsewhere.
        import traceback
        url = 'https://boxingschedule.co'
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            html = r.text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.content, 'html.parser')
            text = soup.get_text('\n', strip=True)
            marker_pos = html.find('\U0001F4C5')
            return jsonify({
                'status_code': r.status_code,
                'final_url': r.url,
                'content_length': len(html),
                'content_type': r.headers.get('content-type'),
                'p_with_data_start': len(soup.find_all('p', attrs={'data-start': True})),
                'any_data_start': len(soup.find_all(attrs={'data-start': True})),
                'calendar_emoji_count': html.count('\U0001F4C5'),
                'html_around_first_emoji': html[max(0, marker_pos - 400):marker_pos + 400] if marker_pos > -1 else None,
                'tag_histogram': {t: len(soup.find_all(t)) for t in ('p', 'div', 'li', 'tr', 'h2', 'h3', 'article', 'script')},
                'article_classes': sorted({' '.join(a.get('class', [])) for a in soup.find_all('article')}),
                'first_article_html': str(soup.find('article'))[:4000] if soup.find('article') else None,
                'event_articles': [str(x)[:9000] for x in soup.select('article.rsd-event, article.rs-card')[:2]],
                'second_article_html': str(soup.find_all('article')[1])[:2500] if len(soup.find_all('article')) > 1 else None,
                'text_head': text[:1500],
            })
        except Exception as e:
            return jsonify({'error': str(e), 'traceback': traceback.format_exc()[-1500:]})

    if part == 'profiles_refresh':
        # Kick the background profile job now (ignores the cooldown)
        if _profile_job_state['running']:
            return jsonify({'started': False, 'reason': 'already running'})
        fights = _fetch_fights_raw()
        pending = _profile_work_list(fights, load_profiles())
        threading.Thread(target=refresh_profiles, args=(fights,), daemon=True).start()
        return jsonify({'started': True, 'pending_fighters': len(pending)})

    if part == 'usage':
        return jsonify(_usage.stats(days=int(request.args.get('days', 30))))

    if part == 'check':
        # Run the named invariants over what the site is serving right now (read-only)
        import invariants as _inv
        fs = _fetch_fights_raw()
        checks = _inv.model_checks(fs)
        return jsonify({'fights': len(fs), 'healthy': all(c['ok'] for c in checks), 'checks': checks})

    if part == 'health':
        return jsonify(_runs.health(extra={'lock_error': _locks.last_error, 'cache_age_hours': _cache_age_hours()}))

    if part == 'run_log':
        # Recent run records per source, newest last
        src = request.args.get('source')
        sources = [src] if src else ['UFC', 'Boxing']
        return jsonify({s: _runs.list_runs(s, limit=int(request.args.get('limit', 20))) for s in sources})

    if part == 'snapshot':
        # Raw body of a saved source page: &file=<sidecar 'file'> or the newest for &source=
        rel = request.args.get('file')
        if not rel:
            snaps = _runs.list_snapshots(request.args.get('source') or 'Boxing', limit=1)
            if not snaps:
                return jsonify({'error': 'no snapshots yet'}), 404
            rel = snaps[0]['file']
        try:
            body = _runs.read_snapshot(rel)
        except Exception as e:
            return jsonify({'error': str(e)}), 404
        resp = make_response(body)
        resp.headers['Content-Type'] = 'application/json' if rel.endswith('.json.gz') else 'text/html; charset=utf-8'
        return resp

    if part == 'snapshots':
        src = request.args.get('source')
        sources = [src] if src else ['UFC', 'Boxing']
        return jsonify({s: _runs.list_snapshots(s, limit=int(request.args.get('limit', 20))) for s in sources})

    if part == 'versions':
        v = _load_versions()
        return jsonify({'tracked_urls': len(v), 'newest': sorted(v.items(), key=lambda kv: kv[1].get('lastmod', ''), reverse=True)[:15]})

    if part == 'image_probe':
        # What would each image source return for a fighter? Saves nothing.
        name = (request.args.get('name') or '')[:120]
        sport = 'UFC' if request.args.get('sport', '').lower() == 'ufc' else 'Boxing'
        if not name:
            return jsonify({'error': 'name required'}), 400
        titles = _images._profile_titles()
        return jsonify(_images.probe(name, sport, title=titles.get(_images.key(name))))

    if part == 'image_job':
        # Read the image job report; &start=dry launches a dry run (writes nothing).
        # Applying is admin-only (Review Images page).
        started = None
        if request.args.get('start') == 'dry':
            started = _images.start_job(apply=False)
        return jsonify({'started': started, 'job': _images.read_job(), 'settings': _images.read_settings()})

    if part == 'clicks':
        return jsonify(click_stats(int(request.args.get('days') or 30)))

    if part == 'backfill':
        # POST a JSON list of fights to merge into the cache, e.g. to restore a
        # card a source dropped. Past fights by default; &upcoming=1 also
        # restores future fights (and records them as that source's last-good
        # set so they survive while the source is down).
        if request.method != 'POST':
            return jsonify({'error': 'POST a JSON list of fights'}), 405
        allow_upcoming = request.args.get('upcoming') == '1'
        incoming = request.get_json(silent=True) or []
        today_iso, cutoff = date.today().isoformat(), _retention_cutoff_iso()
        current = load_cache(max_age_hours=24 * 365) or []
        seen = {(tuple(sorted([f['fighter1'].lower(), f['fighter2'].lower()])), f.get('date')) for f in current}
        added = []
        for f in incoming:
            if not isinstance(f, dict) or not all(f.get(k) for k in ('fighter1', 'fighter2', 'date', 'sport')):
                continue
            if f['date'] < cutoff or (f['date'] > today_iso and not allow_upcoming):
                continue
            k = (tuple(sorted([f['fighter1'].lower(), f['fighter2'].lower()])), f['date'])
            if k in seen:
                continue
            seen.add(k)
            current.append({key: f.get(key) for key in ('fighter1', 'fighter2', 'date', 'time', 'venue', 'location', 'sport',
                                                        'event_name', 'weight_class', 'card_type', 'rounds', 'is_main_event',
                                                        'streaming', 'time_estimated') if key in f})
            added.append(f"{f['fighter1']} vs {f['fighter2']} ({f['date']})")
        if added:
            current.sort(key=lambda x: x.get('date') or '9999-12-31')
            save_cache(current, keep_timestamp=True)
            if allow_upcoming:
                for sport in ('UFC', 'Boxing'):
                    future = [f for f in incoming if isinstance(f, dict) and f.get('sport') == sport and (f.get('date') or '') > today_iso]
                    if future:
                        save_last_good(sport, future, merge=True)
            threading.Thread(target=refresh_profiles, args=(current,), daemon=True).start()
        if added:
            sports = {f.get('sport') for f in incoming if isinstance(f, dict)}
            _runs.write_run(sports.pop() if len(sports) == 1 else 'mixed', 'manual', 'backfill',
                            counts={'fights': len(added)}, note='debug API backfill')
        return jsonify({'added': added, 'total_now': len(current)})

    if part == 'page_probe':
        # Structure of a candidate schedule page (fixed list of hosts) to design a fallback parser.
        pages = {
            'espn_boxing': 'https://www.espn.com/boxing/schedule',
            'sky_boxing': 'https://www.skysports.com/boxing-schedule',
            'boxing_schedule_com': 'https://boxing-schedule.com/',
            'dazn_schedule': 'https://www.dazn.com/en-US/news/boxing/boxing-schedule',
        }
        which = request.args.get('which', '')
        if which not in pages:
            return jsonify({'error': f'which must be one of {sorted(pages)}'}), 400
        from bs4 import BeautifulSoup
        from collections import Counter
        try:
            r = requests.get(pages[which], headers={'User-Agent': _ESPN_UA if False else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}, timeout=25)
            soup = BeautifulSoup(r.text, 'html.parser')
            for t in soup(['script', 'style', 'noscript', 'svg']):
                t.decompose()
            classes = Counter(c for el in soup.find_all(True) for c in (el.get('class') or []))
            text = soup.get_text('\n', strip=True)
            vs_lines = [l for l in text.split('\n') if re.search(r'\bvs\.?\b', l, re.I)][:15]
            body = str(soup.body)[:12000] if soup.body else r.text[:12000]
            return jsonify({'url': pages[which], 'status': r.status_code, 'length': len(r.text),
                            'top_classes': classes.most_common(40), 'vs_lines': vs_lines,
                            'text_head': text[:2500], 'body_head': body})
        except Exception as e:
            return jsonify({'url': pages[which], 'error': str(e)[:300]})

    if part == 'alert_test':
        import alerts as _alerts
        return jsonify({'enabled': _alerts.enabled(), 'sent': _alerts.send('[fightschedule.live] test alert', 'Alerting works.')})

    if part == 'scrape_log':
        path = data_path('data_sources_comparison.txt')
        if not os.path.exists(path):
            return jsonify({'error': 'no scrape log yet'}), 404
        with open(path, encoding='utf-8', errors='replace') as f:
            body = f.read()
        resp = make_response(body[-20000:])
        resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return resp

    if part:
        filename = _DEBUG_PARTS.get(part)
        if not filename:
            return jsonify({'error': f'unknown part, valid: {sorted(_DEBUG_PARTS)}'}), 400
        path = data_path(filename)
        if not os.path.exists(path):
            return jsonify({'error': f'{filename} does not exist'}), 404
        with open(path) as f:
            return jsonify(json.load(f))

    # Default: summary overview
    summary = {'files': {}}
    for name, filename in _DEBUG_PARTS.items():
        path = data_path(filename)
        if os.path.exists(path):
            stat = os.stat(path)
            summary['files'][name] = {
                'size_bytes': stat.st_size,
                'modified_utc': datetime.utcfromtimestamp(stat.st_mtime).isoformat() + 'Z',
            }
        else:
            summary['files'][name] = None

    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        fights = cache.get('fights', [])
        by_sport = {}
        pairs = {}
        for fight in fights:
            by_sport[fight.get('sport', '?')] = by_sport.get(fight.get('sport', '?'), 0) + 1
            key = ' vs '.join(sorted([fight.get('fighter1', '').lower(), fight.get('fighter2', '').lower()]))
            pairs[key] = pairs.get(key, 0) + 1
        dupes = {k: v for k, v in pairs.items() if v > 1}
        with_images = sum(1 for f_ in fights if f_.get('fighter1_image') or f_.get('fighter2_image'))
        summary['cache'] = {
            'timestamp': cache.get('timestamp'),
            'total_fights': len(fights),
            'by_sport': by_sport,
            'duplicate_matchups': dupes,
            'fights_with_any_image': with_images,
            'sample_fight': fights[0] if fights else None,
        }
    except Exception as e:
        summary['cache'] = {'error': str(e)}

    summary['persisted_fighter_images'] = []
    fighters_dir = data_path('fighters')
    if os.path.isdir(fighters_dir):
        summary['persisted_fighter_images'] = sorted(os.listdir(fighters_dir))

    return jsonify(summary)


# ============================================================================
# AFFILIATE / STREAMING LINKS — see affiliates.py
# ============================================================================

import affiliates as _aff

CLICKS_FILE = data_path('clicks.jsonl')
_clicks_lock = threading.Lock()


# Globals (not context processors) so imported macros in _watch.html can use them
def brand_logo(key):
    """Official logo for a watch service, if one has been added as
    static/brands/<key>.svg (from the service's affiliate/brand kit)."""
    for ext in ('svg', 'png'):
        if os.path.exists(os.path.join(app.root_path, 'static', 'brands', f'{key}.{ext}')):
            return f'/static/brands/{key}.{ext}'
    return None


def photo_credits(sport, m):
    """Credits for the two hero photos on a fight page: a list of
    {'credit': …, 'who': surname or None}. Same credit for both → one entry."""
    out = []
    for side in ('fighter1', 'fighter2'):
        img = m.get(f'{side}_image') if hasattr(m, 'get') else None
        c = _images.credit_for(m.get(side), sport, shown=img) if img else None
        out.append((c, (m.get(side) or '').split()[-1] if m.get(side) else None))
    known = [(c, who) for c, who in out if c]
    if not known:
        return []
    if len(known) == 2 and known[0][0] == known[1][0]:
        return [{'credit': known[0][0], 'who': None}]
    return [{'credit': c, 'who': who} for c, who in known]


app.jinja_env.globals.update({
    'photo_credits': photo_credits,
    'brand_logo': brand_logo,
    'provider_key': _aff.resolve_provider,
    'provider_name': _aff.provider_name,
    'clean_broadcaster': _aff.clean_broadcaster,
})



from admin_setup_simple import csrf as _csrf
_csrf.exempt(debug_state)

_BOT_UA = re.compile(r'bot|crawl|spider|slurp|preview|fetch|scrap|headless|python|curl|wget|httpclient|'
                     r'axios|node-fetch|go-http|java/|okhttp|facebookexternalhit|embedly|whatsapp|telegram|'
                     r'discord|slack|skype|monitor|uptime|lighthouse|pagespeed|google-read-aloud|mediapartners|'
                     r'gptbot|claude|anthropic|perplexity|bytespider|ccbot|cohere|amazonbot|youbot|meta-external',
                     re.IGNORECASE)


def _is_bot(ua):
    """Best-effort: empty user agents and known crawler / tool signatures."""
    return (not ua) or bool(_BOT_UA.search(ua))


def _from_this_site(req):
    """Did this request come from a page on fightschedule.live (or a local dev
    server)? Scripts hitting endpoints directly send no Referer/Origin."""
    src = req.headers.get('Origin') or req.headers.get('Referer') or ''
    host = req.host.split(':')[0]
    return bool(re.match(r'https?://(www\.)?' + re.escape(host) + r'(:\d+)?(/|$)', src))


@app.after_request
def _count_page_view(resp):
    """One usage record per HTML page served to a browser. Cookie-free; no IP."""
    try:
        if (request.method == 'GET' and resp.status_code == 200
                and resp.mimetype == 'text/html'
                and not request.path.startswith(('/admin', '/api', '/static', '/go/', '/health'))):
            ua = request.headers.get('User-Agent') or ''
            _usage.record('view', _usage.page_type(request.path), bot=_is_bot(ua),
                          lang=(request.headers.get('Accept-Language') or '').strip())
    except Exception:
        pass
    return resp


@app.route('/api/t', methods=['POST'])
def usage_beacon():
    """Tap counter. Body: {"name": "card", "page": "/ufc", "detail": "UFC"}.
    Always 204; invalid or oversized bodies are dropped silently."""
    try:
        if request.content_length and request.content_length > 600:
            return '', 204
        data = request.get_json(force=True, silent=True) or {}
        name, detail = data.get('name'), data.get('detail')
        if not _usage.valid_tap(name, detail):
            return '', 204
        ua = request.headers.get('User-Agent') or ''
        _usage.record('tap', _usage.page_type(str(data.get('page') or request.headers.get('Referer') or '')),
                      name=name, detail=detail or None, bot=_is_bot(ua),
                      lang=(request.headers.get('Accept-Language') or '').strip(),
                      referer_ok=_from_this_site(request))
    except Exception:
        pass
    resp = make_response('', 204)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


_csrf.exempt(usage_beacon)


@app.route('/go/<provider>')
def go_provider(provider):
    """Redirect to a streaming provider and log the click (server-side, ad-blocker proof)."""
    url = _aff.affiliate_url(provider, request.args.get('event', '')[:120])
    if not url:
        abort(404)
    try:
        ua = (request.headers.get('User-Agent') or '')[:200]
        lang = (request.headers.get('Accept-Language') or '').split(',')[0].split(';')[0].strip()[:12] or None
        record = {
            'ts': datetime.utcnow().isoformat() + 'Z',
            'bot': _is_bot(ua),
            'ua': ua,
            'lang': lang,
            'provider': provider,
            'event': request.args.get('event', '')[:120],
            'sport': request.args.get('sport', '')[:10],
            'placement': request.args.get('p', '')[:20],
            'referer': (request.headers.get('Referer') or '')[:200],
            'affiliate': _aff.is_affiliate_configured(provider),
        }
        with _clicks_lock:
            with open(CLICKS_FILE, 'a') as f:
                f.write(json.dumps(record) + '\n')
    except Exception as e:
        logger.warning(f"click log failed: {e}")
    resp = redirect(url, code=302)
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return resp


def click_stats(days=30):
    """Aggregate clicks.jsonl by provider / day for the debug API."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    by_provider, by_day, by_event, total = {}, {}, {}, 0
    kinds = {'human': 0, 'bot': 0, 'unknown (before user agents were logged)': 0}
    human_provider, human_lang, bot_agents = {}, {}, {}
    # 'Real' = not a known bot, the browser sent a language, AND the click came
    # from a page on this site (Referer). A visitor tapping a watch link always
    # sends both; scripts hitting /go/ directly usually send neither referer
    # nor language (61 of 63 'browser-like' clicks on 2026-10-01 had no referer).
    real = {'total': 0, 'by_day': {}, 'by_placement': {}, 'by_provider': {}, 'by_page': {}, 'by_sport': {}}

    def _bump(d, k):
        d[k] = d.get(k, 0) + 1

    def _page(ref):
        path = re.sub(r'^https?://[^/]+', '', ref or '').split('?')[0].split('#')[0]
        if path in ('', '/'):
            return 'homepage'
        for prefix, name in (('/results', 'results'), ('/ufc', 'ufc page'), ('/boxing-event/', 'boxing fight page'),
                             ('/boxing', 'boxing page'), ('/event/', 'ufc fight page')):
            if path.startswith(prefix):
                return name
        return 'other'
    if os.path.exists(CLICKS_FILE):
        with open(CLICKS_FILE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('ts', '') < cutoff:
                    continue
                total += 1
                if 'bot' not in r:
                    kinds['unknown (before user agents were logged)'] += 1
                elif r['bot']:
                    kinds['bot'] += 1
                    agent = (r.get('ua') or '(empty)')[:60]
                    bot_agents[agent] = bot_agents.get(agent, 0) + 1
                else:
                    kinds['human'] += 1
                    human_provider[r.get('provider')] = human_provider.get(r.get('provider'), 0) + 1
                    lg = r.get('lang') or '(none)'
                    human_lang[lg] = human_lang.get(lg, 0) + 1
                    if r.get('lang') and re.match(r'https?://(www\.)?fightschedule\.live/', r.get('referer') or ''):
                        real['total'] += 1
                        _bump(real['by_day'], r['ts'][:10])
                        _bump(real['by_placement'], r.get('placement') or '(not tagged)')
                        _bump(real['by_provider'], r.get('provider'))
                        _bump(real['by_page'], _page(r.get('referer')))
                        _bump(real['by_sport'], r.get('sport') or '-')
                by_provider[r.get('provider')] = by_provider.get(r.get('provider'), 0) + 1
                by_day[r['ts'][:10]] = by_day.get(r['ts'][:10], 0) + 1
                by_event[r.get('event') or '-'] = by_event.get(r.get('event') or '-', 0) + 1
    return {'days': days, 'total': total, 'by_kind': kinds, 'human_by_provider': human_provider,
            'human_languages': sorted(human_lang.items(), key=lambda kv: -kv[1])[:15],
            'bot_agents': sorted(bot_agents.items(), key=lambda kv: -kv[1])[:15],
            'by_provider': by_provider, 'by_day': dict(sorted(by_day.items())),
            'top_events': sorted(by_event.items(), key=lambda kv: -kv[1])[:20],
            'configured_affiliates': [k for k in _aff.PROVIDERS if _aff.is_affiliate_configured(k)],
            'real_clicks': {**real, 'by_day': dict(sorted(real['by_day'].items()))}}


# Date of the last change to the privacy policy: shown on the page and used
# as its sitemap lastmod. Update it whenever templates/privacy.html changes.
PRIVACY_UPDATED = date(2026, 10, 2)


@app.route('/privacy')
def privacy():
    """Privacy and cookie policy page"""
    return render_template('privacy.html', updated=f"{PRIVACY_UPDATED.day} {PRIVACY_UPDATED:%B %Y}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    logger.info(f"Debug mode: {app.debug}")
    logger.info(f"Cache duration: {CACHE_DURATION.seconds//3600} hours")
    app.run(host='0.0.0.0', port=port, debug=False)
