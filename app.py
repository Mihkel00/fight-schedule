from flask import Flask, render_template, request, redirect, make_response
from flask_compress import Compress
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
import os
import requests
from datetime import datetime, timedelta
import json
import re
import logging
from logging.handlers import RotatingFileHandler
from admin_setup_simple import setup_admin
from admin_models import BigNameFighter
import markdown
from bs4 import BeautifulSoup

# Import scrapers
from scrapers import scrape_ufc_events, scrape_boxing_events

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/fighters'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size
Compress(app)  # Enable gzip compression for all responses

# Setup Flask-Admin
admin = setup_admin(app)

@app.before_request
def redirect_www():
    """Redirect www to non-www for canonical URLs"""
    if request.host.startswith('www.'):
        return redirect(request.url.replace('www.', '', 1), code=301)

# ============================================================================
# LOGGING SETUP
# ============================================================================
# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Set up logging to both file and console
logger = logging.getLogger('fight_schedule')
logger.setLevel(logging.DEBUG)

# File handler (rotates at 10MB, keeps 3 backup files)
file_handler = RotatingFileHandler('logs/app.log', maxBytes=10*1024*1024, backupCount=3)
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

# Cache file path
CACHE_FILE = 'fights_cache.json'
CACHE_DURATION = timedelta(hours=6)  # Refresh every 6 hours

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
    """Load fighters.json and fighters_ufc.json if they exist"""
    fighters_db = {}
    
    # Load general fighter database (from TheSportsDB)
    try:
        with open('fighters.json', 'r', encoding='utf-8') as f:
            fighters_db.update(json.load(f))
    except:
        pass
    
    # Load UFC-specific database (from UFC.com scraper)
    try:
        with open('fighters_ufc.json', 'r', encoding='utf-8') as f:
            ufc_db = json.load(f)
            # UFC database takes priority for UFC fighters
            fighters_db.update(ufc_db)
    except:
        pass
    
    return fighters_db

def get_fighter_image(fighter_name):
    """Search for fighter by name and return their image URL"""
    if not fighter_name or fighter_name == 'TBA':
        return None
    
    # Check local database only (no API fallback)
    fighters_db = load_fighter_database()
    if fighter_name in fighters_db:
        cached_url = fighters_db[fighter_name]
        if cached_url:
            print(f"Using cached image for {fighter_name}")
            return cached_url
    
    return None

# ============================================================================
# AI FIGHT PREVIEW FUNCTIONS
# ============================================================================

def load_previews():
    """Load cached fight previews from JSON file"""
    try:
        with open('data/fight_previews.json', 'r', encoding='utf-8') as f:
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
        with open('data/fight_previews.json', 'w', encoding='utf-8') as f:
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
    """Load manual time overrides from time_overrides.json"""
    try:
        with open('time_overrides.json', 'r', encoding='utf-8') as f:
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

def load_cache():
    """Load cached fight data if it exists and is fresh"""
    if not os.path.exists(CACHE_FILE):
        logger.debug("No cache file found")
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        # Check if cache is still fresh
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        age = datetime.now() - cache_time
        
        if age < CACHE_DURATION:
            logger.info(f"[OK] Using cached data from {cache_time.strftime('%Y-%m-%d %H:%M:%S')} (age: {age.seconds//60} minutes)")
            
            # Apply time overrides to cached data
            fights = cache_data['fights']
            fights = apply_time_overrides(fights)
            
            logger.info(f"  Loaded {len(fights)} fights from cache")
            return fights
        else:
            logger.info(f"[X] Cache expired (age: {age.seconds//3600} hours), fetching new data...")
            return None
    except Exception as e:
        logger.error(f"Error loading cache: {e}")
        return None

def save_cache(fights):
    """Save fight data to cache with timestamp"""
    try:
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'fights': fights
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
        logger.info(f"[OK] Cache saved: {len(fights)} fights at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        logger.error(f"Error saving cache: {e}")


def fetch_fights():
    """Fetch upcoming UFC and Boxing fights from multiple sources"""
    # Try loading from cache first
    cached_fights = load_cache()
    if cached_fights is not None:
        return cached_fights
    
    # Open debug log file
    debug_log = open('data_sources_comparison.txt', 'w', encoding='utf-8')
    
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
    boxingschedule_fights = scrape_boxing_events()
    log(f"BoxingSchedule.co found: {len(boxingschedule_fights)} fights\n")
    for fight in boxingschedule_fights[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} {'[MAIN]' if fight.get('is_main_event') else ''}")
    if len(boxingschedule_fights) > 5:
        log(f"  ... and {len(boxingschedule_fights) - 5} more\n")
    
    # 1b. Scrape BBC Sport for boxing (DISABLED FOR TESTING)
    log("--- BBC SPORT BOXING (DISABLED) ---")
    # bbc_boxing = scrape_bbc_boxing()
    bbc_boxing = []
    log(f"BBC Sport Boxing: DISABLED\n")
    
    # 2. Scrape MMA Fighting for UFC schedule
    log("\n--- MMA FIGHTING UFC ---")
    mma_fighting_ufc = scrape_ufc_events()
    log(f"MMA Fighting UFC found: {len(mma_fighting_ufc)} fights\n")
    for fight in mma_fighting_ufc[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} - {fight['venue']}")
    if len(mma_fighting_ufc) > 5:
        log(f"  ... and {len(mma_fighting_ufc) - 5} more\n")
    
    # 3. Fetch TheSportsDB for boxing images (DISABLED - poor data quality)
    log("\n--- THESPORTSDB BOXING (DISABLED) ---")
    # thesportsdb_boxing = fetch_boxing_events()
    thesportsdb_boxing = []
    log(f"TheSportsDB Boxing: DISABLED\n")
    
    # 4. Combine data
    log("\n" + "="*60)
    log("MERGING DATA...")
    log("="*60 + "\n")
    
    # Add BoxingSchedule.co fights
    fights.extend(boxingschedule_fights)
    
    # Add BBC Sport boxing fights
    fights.extend(bbc_boxing)
    
    # Add MMA Fighting UFC fights
    fights.extend(mma_fighting_ufc)
    
    # TheSportsDB merge disabled
    merged_count = 0
    new_from_tsd = 0
    
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
    
    # Filter out past fights
    from datetime import date
    today = date.today().isoformat()
    fights_before_filter = len(fights)
    fights = [f for f in fights if f.get('date', '') >= today]
    
    # Keep all UFC fights (no filtering needed)
    # Keep all boxing fights - BBC Sport already curates quality matches
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

@app.route('/')
def home():
    logger.info("--> Home page accessed")
    fights = fetch_fights()
    logger.info(f"  Rendering {len(fights)} fights")
    
    # Separate by sport and filter out prelims
    ufc_fights = [f for f in fights if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims']
    # Boxing: Only show main events (first fight per date/venue)
    boxing_fights = [f for f in fights if f.get('sport') == 'Boxing' and f.get('is_main_event') == True]
    
    # FEATURED FIGHTS
    featured_fights = []
    
    # UFC Featured: Next title fight OR first UFC event
    ufc_featured = None
    for fight in ufc_fights:
        if fight.get('weight_class') == 'Title':
            ufc_featured = fight
            break
    if not ufc_featured and ufc_fights:
        ufc_featured = ufc_fights[0]
    
    if ufc_featured:
        featured_fights.append(ufc_featured)
        logger.info(f"  Featured UFC: {ufc_featured['fighter1']} vs {ufc_featured['fighter2']}")
    
    # Boxing Featured: Next big-name fight
    boxing_featured = None
    for fight in boxing_fights:
        if is_big_name_fight(fight):
            boxing_featured = fight
            break
    
    if boxing_featured:
        featured_fights.append(boxing_featured)
        logger.info(f"  Featured Boxing: {boxing_featured['fighter1']} vs {boxing_featured['fighter2']}")
    
    # Remove featured from main lists
    featured_ids = {id(f) for f in featured_fights}
    ufc_fights = [f for f in ufc_fights if id(f) not in featured_ids]
    boxing_fights = [f for f in boxing_fights if id(f) not in featured_ids]
    
    # Limit horizontal scroll sections (show more fights)
    ufc_scroll = ufc_fights[:12]
    boxing_scroll = boxing_fights[:12]
    
    # Coming up soon: Everything else
    coming_soon = ufc_fights[12:] + boxing_fights[12:]
    coming_soon = sorted(coming_soon, key=lambda x: x['date'])[:20]  # Show 20 max
    
    logger.info(f"  Sections: Featured={len(featured_fights)}, UFC={len(ufc_scroll)}, Boxing={len(boxing_scroll)}, Coming Soon={len(coming_soon)}")
    
    # Dynamically load fighter images (always fresh from JSON)
    all_fights_to_display = featured_fights + ufc_scroll + boxing_scroll + coming_soon
    for fight in all_fights_to_display:
        if not fight.get('fighter1_image'):
            img = get_fighter_image(fight['fighter1'])
            if img:
                fight['fighter1_image'] = img
        if not fight.get('fighter2_image'):
            img = get_fighter_image(fight['fighter2'])
            if img:
                fight['fighter2_image'] = img
    
    return render_template('index.html', 
                         featured_fights=featured_fights,
                         ufc_fights=ufc_scroll,
                         boxing_fights=boxing_scroll,
                         coming_soon=coming_soon)

@app.route('/event/<event_slug>')
def event_detail(event_slug):
    """Show detailed page for a specific event with full card"""
    logger.info(f"--> Event detail accessed: {event_slug}")
    fights = fetch_fights()
    
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
        for event_name, fights_list in ufc_events.items():
            # Create slug from this event name
            test_slug = event_name.lower().replace(' ', '-').replace(':', '').replace(',', '')
            test_slug = re.sub(r'[^a-z0-9-]', '', test_slug)
            
            # Check if slug matches
            if test_slug in event_name_slug or event_name_slug in test_slug:
                event_fights_list = fights_list
                matched_event_name = event_name
                logger.info(f"  [OK] Matched by NAME: {matched_event_name}")
                break
    
    # PRIORITY 3: Fallback to first event (last resort)
    if not event_fights_list and ufc_events:
        matched_event_name = list(ufc_events.keys())[0]
        event_fights_list = ufc_events[matched_event_name]
        logger.warning(f"  [!] No match found, using first event: {matched_event_name}")
    
    if not ufc_events:
        # Fallback to dummy data if no UFC events
        event_fights = {
            'event_name': 'No UFC Events Found',
            'date': '2025-01-01',
            'venue': 'TBA',
            'main_event': {
                'fighter1': 'TBA',
                'fighter2': 'TBA',
                'fighter1_image': '/static/placeholder-fighter-mma.png',
                'fighter2_image': '/static/placeholder-fighter-mma.png',
                'weight_class': 'TBA',
                'time': '00:00'
            },
            'main_card': [],
            'prelims': []
        }
        return render_template('event_detail.html', event=event_fights)
    
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
            'fighter1_image': main_event_fight.get('fighter1_image') or '/static/placeholder-fighter-mma.png',
            'fighter2_image': main_event_fight.get('fighter2_image') or '/static/placeholder-fighter-mma.png',
            'weight_class': weight_class,
            'time': main_event_fight.get('time', 'TBA')
        },
        'main_card': [
            {
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'is_title': f.get('weight_class') == 'Title'
            }
            for f in main_card_fights
        ],
        'prelims': [
            {
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2']
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
    
    return render_template('event_detail.html', event=event_data)

@app.route('/boxing-event/<event_slug>')
def boxing_event_detail(event_slug):
    """Show boxing event details grouped by venue and date"""
    logger.info(f"Boxing event accessed: {event_slug}")
    
    # Load all fights using fetch_fights
    all_fights = fetch_fights()
    
    # Filter to boxing only
    boxing_fights = [f for f in all_fights if f.get('sport') == 'Boxing']
    
    # Parse slug (format: venue-slug-YYYY-MM-DD)
    parts = event_slug.rsplit('-', 3)
    if len(parts) >= 3:
        date_str = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
    else:
        date_str = ''
    
    # Group fights by venue + date (with 1-day tolerance)
    from datetime import datetime, timedelta
    target_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else None
    
    # Find all fights at same venue within 1 day
    event_fights = []
    for fight in boxing_fights:
        if not target_date:
            continue
        
        fight_date = datetime.strptime(fight['date'], '%Y-%m-%d')
        date_diff = abs((fight_date - target_date).days)
        
        # Check if same venue and within 1 day
        venue_matches = False
        fight_venue_clean = fight.get('venue', '').lower().replace(',', '').replace('.', '')
        
        for part in event_slug.split('-'):
            if len(part) > 2 and part in fight_venue_clean:
                venue_matches = True
                break
        
        if venue_matches and date_diff <= 1:
            event_fights.append(fight)
    
    if not event_fights:
        logger.warning(f"No boxing fights found for {event_slug}")
        return "Event not found", 404
    
    logger.info(f"Found {len(event_fights)} fights for this event")
    
    # Fights are already in correct order from scraper (main event first)
    # Just sort by is_main_event flag to ensure main is first
    event_fights_sorted = sorted(event_fights, key=lambda x: not x.get('is_main_event', False))
    main_event_fight = event_fights_sorted[0]
    undercard = event_fights_sorted[1:]
    
    logger.info(f"Main event: {main_event_fight['fighter1']} vs {main_event_fight['fighter2']}")
    
    # Build event data
    event_data = {
        'venue': main_event_fight['venue'],
        'location': main_event_fight['location'],
        'date': main_event_fight['date'],
        'time': main_event_fight.get('time', 'TBA'),
        'fight_count': len(event_fights),
        'streaming': main_event_fight.get('streaming'),  # Add streaming info
        'main_event': {
            'fighter1': main_event_fight['fighter1'],
            'fighter2': main_event_fight['fighter2'],
            'fighter1_image': main_event_fight.get('fighter1_image'),
            'fighter2_image': main_event_fight.get('fighter2_image'),
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
    
    return render_template('boxing_event.html', event=event_data)

# SEO Routes
@app.route('/sitemap.xml')
def sitemap():
    """Generate dynamic sitemap"""
    from datetime import datetime
    fights = fetch_fights()
    
    pages = []
    pages.append({'loc': 'https://fightschedule.live/', 'lastmod': datetime.now().strftime('%Y-%m-%d'), 'changefreq': 'daily', 'priority': '1.0'})
    
    # UFC events
    ufc_fights = [f for f in fights if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims']
    seen = set()
    for fight in ufc_fights:
        slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
        if slug not in seen:
            pages.append({'loc': f"https://fightschedule.live/event/{slug}", 'lastmod': fight['date'], 'changefreq': 'weekly', 'priority': '0.8'})
            seen.add(slug)
    
    # Boxing events
    boxing_fights = [f for f in fights if f.get('sport') == 'Boxing']
    seen = set()
    for fight in boxing_fights[:20]:
        venue_slug = fight['venue'].lower().replace(' ', '-').replace(',', '').replace('.', '').replace("'", '')
        slug = f"{venue_slug}-{fight['date']}"
        if slug not in seen:
            pages.append({'loc': f"https://fightschedule.live/boxing-event/{slug}", 'lastmod': fight['date'], 'changefreq': 'weekly', 'priority': '0.7'})
            seen.add(slug)
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for p in pages:
        xml += f'  <url>\n    <loc>{p["loc"]}</loc>\n    <lastmod>{p["lastmod"]}</lastmod>\n    <changefreq>{p["changefreq"]}</changefreq>\n    <priority>{p["priority"]}</priority>\n  </url>\n'
    xml += '</urlset>'
    
    response = make_response(xml)
    response.headers['Content-Type'] = 'application/xml'
    return response

@app.route('/robots.txt')
def robots():
    """Generate robots.txt"""
    txt = "User-agent: *\nAllow: /\nSitemap: https://fightschedule.live/sitemap.xml\n"
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain'
    return response

@app.route('/admin/clear-cache')
def clear_cache():
    """Clear the fights cache file"""
    cache_file = 'fights_cache.json'
    if os.path.exists(cache_file):
        os.remove(cache_file)
        logger.info("Cache cleared manually via admin route")
        return "✓ Cache cleared successfully. Next page load will fetch fresh data."
    return "No cache file found."

@app.route('/admin/upload-images', methods=['GET', 'POST'])
def upload_fighter_images():
    """Admin interface for uploading fighter images"""
    from werkzeug.utils import secure_filename
    from r2_storage import upload_fighter_image, is_r2_enabled
    
    if request.method == 'POST':
        fighter_name = request.form.get('fighter_name')
        sport = request.form.get('sport', 'UFC')
        
        if 'image' not in request.files:
            return "No file uploaded", 400
        
        file = request.files['image']
        if file.filename == '':
            return "No file selected", 400
        
        if file and fighter_name:
            # Generate filename from fighter name
            filename = fighter_name.lower().replace(' ', '-').replace("'", '')
            ext = os.path.splitext(file.filename)[1] or '.png'
            filename = filename + ext
            
            # Upload to R2 or save locally
            image_url = None
            if is_r2_enabled():
                file.seek(0)  # Reset file pointer
                image_url = upload_fighter_image(file.read(), filename)
            
            # Fallback to local if R2 fails or not configured
            if not image_url:
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.seek(0)  # Reset file pointer
                file.save(filepath)
                image_url = f'/static/fighters/{filename}'
                logger.info(f"Saved locally (R2 unavailable): {filename}")
            
            # Update JSON
            json_file = 'fighters.json' if sport == 'Boxing' else 'fighters_ufc.json'
            with open(json_file, 'r', encoding='utf-8') as f:
                fighters = json.load(f)
            
            fighters[fighter_name] = image_url
            
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(fighters, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Uploaded image for {fighter_name}: {image_url}")
            return redirect('/admin/upload-images')
    
    # GET - show missing fighters
    search_name = request.args.get('search', '').strip()
    show_all = request.args.get('show_all') == 'true'
    
    try:
        with open('fights_cache.json', 'r') as f:
            cache = json.load(f)
    except:
        return "No cache found. Visit homepage first to generate cache.", 404
    
    # Load databases
    with open('fighters.json', 'r', encoding='utf-8') as f:
        boxing = json.load(f)
    with open('fighters_ufc.json', 'r', encoding='utf-8') as f:
        ufc = json.load(f)
    
    all_fighters = {**boxing, **ufc}
    
    # If searching, show that fighter
    if search_name:
        sport = 'UFC' if search_name in ufc else 'Boxing'
        missing = [{
            'name': search_name,
            'sport': sport,
            'event': 'Search result',
            'has_image': all_fighters.get(search_name, '').startswith('/static/') if search_name in all_fighters else False
        }]
        return render_template('admin/upload_images.html', missing=missing, search_mode=True)
    
    # Find missing main event fighters
    missing = []
    for fight in cache.get('fights', []):
        if fight.get('is_main_event') or show_all:
            for fighter_key in ['fighter1', 'fighter2']:
                fighter = fight.get(fighter_key)
                if not fighter or fighter == 'TBA':
                    continue
                
                has_image = False
                if fighter in all_fighters:
                    url = all_fighters[fighter]
                    if url and url.startswith('/static/'):
                        has_image = True
                
                img_key = f'{fighter_key}_image'
                if fight.get(img_key) and fight.get(img_key).startswith('/static/'):
                    has_image = True
                
                if not has_image:
                    missing.append({
                        'name': fighter,
                        'sport': fight.get('sport', 'UFC'),
                        'event': f"{fight.get('venue')} - {fight.get('date')}"
                    })
    
    # Remove duplicates
    seen = set()
    unique_missing = []
    for f in missing:
        key = f['name']
        if key not in seen:
            seen.add(key)
            unique_missing.append(f)
    
    return render_template('admin/upload_images.html', missing=unique_missing)

@app.route('/admin/manage-fighters', methods=['GET', 'POST'])
def manage_fighters():
    """Manage fighter names and big name fighters"""
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add_big_name':
                fighter_name = request.form.get('fighter_name')
                big_names_file = 'data/big_name_fighters.json'
                
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
                big_names_file = 'data/big_name_fighters.json'
                
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
                
                json_file = 'fighters.json' if sport == 'Boxing' else 'fighters_ufc.json'
                
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
                
                json_file = 'fighters.json' if sport == 'Boxing' else 'fighters_ufc.json'
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    fighters = json.load(f)
                
                if fighter_name in fighters:
                    del fighters[fighter_name]
                    
                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(fighters, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"Deleted fighter: {fighter_name}")
            
            return redirect('/admin/manage-fighters')
        
        # GET - show management page
        with open('fighters.json', 'r', encoding='utf-8') as f:
            boxing = json.load(f)
        with open('fighters_ufc.json', 'r', encoding='utf-8') as f:
            ufc = json.load(f)
        
        # Load big names, create if missing
        big_names_file = 'data/big_name_fighters.json'
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
        import traceback
        error_details = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        logger.error(f"manage_fighters error: {error_details}")
        return f"<pre>{error_details}</pre>", 500

@app.route('/privacy')
def privacy():
    """Privacy and cookie policy page"""
    return render_template('privacy.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    logger.info(f"Debug mode: {app.debug}")
    logger.info(f"Cache duration: {CACHE_DURATION.seconds//3600} hours")
    app.run(host='0.0.0.0', port=port, debug=False)
