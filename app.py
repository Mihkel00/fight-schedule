from flask import Flask, render_template
import os
import requests
from datetime import datetime, timedelta
import json
import re

app = Flask(__name__)

# Your Premium API Key
API_KEY = '891686'

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
    
    # Check local database first
    fighters_db = load_fighter_database()
    if fighter_name in fighters_db:
        cached_url = fighters_db[fighter_name]
        if cached_url:
            print(f"Using cached image for {fighter_name}")
            return cached_url
        
    try:
        # Fallback to API search
        url = f'https://www.thesportsdb.com/api/v1/json/{API_KEY}/searchplayers.php?p={fighter_name}'
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            players = data.get('player', [])
            
            if players and len(players) > 0:
                # Return first match's image
                player = players[0]
                # Try different image fields (cutout is best, thumb is backup)
                return player.get('strCutout') or player.get('strThumb') or player.get('strFanart1')
                    
    except Exception as e:
        print(f"Error fetching image for {fighter_name}: {e}")
    
    return None

def scrape_boxlive_boxing():
    """Scrape Box.Live for complete boxing schedule"""
    fights = []
    
    try:
        print("Scraping Box.Live Boxing schedule...")
        url = 'https://box.live/upcoming-fights-schedule/'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"Box.Live scrape failed: {response.status_code}")
            return fights
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all fight cards (both main and undercard)
        fight_cards = soup.find_all('footer', class_='schedule-card__header')
        
        for card in fight_cards:
            try:
                # Find fighter names (last-name spans)
                fighter_names = card.find_all('span', class_='last-name')
                
                if len(fighter_names) >= 2:
                    fighter1 = fighter_names[0].get_text(strip=True)
                    fighter2 = fighter_names[1].get_text(strip=True)
                    
                    # Skip if too short
                    if len(fighter1) < 2 or len(fighter2) < 2:
                        continue
                    
                    # Try to find date from parent card
                    # (This is simplified - dates are in the main card header)
                    
                    fights.append({
                        'fighter1': fighter1,
                        'fighter2': fighter2,
                        'date': '',  # Will get from parent if possible
                        'time': '',
                        'venue': 'TBA',
                        'location': 'TBA',
                        'sport': 'Boxing',
                        'event_name': f'{fighter1} vs {fighter2}'
                    })
                    
                    print(f"Box.Live: Added {fighter1} vs {fighter2}")
                    
            except Exception as e:
                continue
        
        print(f"Box.Live Boxing: Found {len(fights)} fights")
        
    except Exception as e:
        print(f"Error scraping Box.Live: {e}")
    
    return fights

def scrape_espn_boxing():
    """Scrape ESPN boxing schedule for complete fight cards"""
    fights = []
    
    try:
        print("Scraping ESPN Boxing schedule...")
        url = 'https://www.espn.com/boxing/story/_/id/12508267/boxing-schedule'
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            print(f"ESPN Boxing scrape failed: {response.status_code}")
            return fights
            
        # Parse with regex - looking for patterns like "Fighter1 vs. Fighter2, X rounds"
        content = response.text
        
        # Extract date and fight patterns
        import re
        
        # Pattern: "Dec. 27: Location (Broadcaster)" followed by fights
        date_pattern = r'([A-Z][a-z]{2}\.\s+\d{1,2}):\s+([^(]+)\s+\(([^)]+)\)'
        fight_pattern = r'([A-Za-z\s\'\-\.]+)\s+vs\.?\s+([A-Za-z\s\'\-\.]+),\s+(\d+)\s+rounds'
        
        lines = content.split('\n')
        current_date = None
        current_location = None
        current_broadcaster = None
        
        for line in lines:
            # Check for date line
            date_match = re.search(date_pattern, line)
            if date_match:
                current_date = date_match.group(1).strip()
                current_location = date_match.group(2).strip()
                current_broadcaster = date_match.group(3).strip()
                continue
            
            # Check for fight line
            fight_match = re.search(fight_pattern, line)
            if fight_match and current_date:
                fighter1 = fight_match.group(1).strip()
                fighter2 = fight_match.group(2).strip()
                
                # Skip if names are too short (likely parsing error)
                if len(fighter1) < 3 or len(fighter2) < 3:
                    continue
                
                # Convert "Dec. 27" to "2025-12-27" format
                date_parts = current_date.replace('.', '').split()
                month_map = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 
                            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}
                month = month_map.get(date_parts[0], '01')
                day = date_parts[1].zfill(2)
                date_str = f'2025-{month}-{day}'
                
                fights.append({
                    'fighter1': fighter1,
                    'fighter2': fighter2,
                    'date': date_str,
                    'time': '',
                    'venue': current_location,
                    'location': current_location,
                    'sport': 'Boxing',
                    'event_name': f'{fighter1} vs {fighter2}',
                    'broadcaster': current_broadcaster
                })
                
                print(f"ESPN: Added {fighter1} vs {fighter2}")
        
        print(f"ESPN Boxing: Found {len(fights)} fights")
        
    except Exception as e:
        print(f"Error scraping ESPN Boxing: {e}")
    
    return fights

def scrape_espn_ufc():
    """Scrape ESPN UFC schedule"""
    fights = []
    
    try:
        print("Scraping ESPN UFC schedule...")
        url = 'https://www.espn.com/mma/schedule/_/league/ufc'
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            print(f"ESPN UFC scrape failed: {response.status_code}")
            return fights
        
        content = response.text
        
        # Pattern for UFC events: "UFC 311: Makhachev vs. Moicano" or "UFC Fight Night: Name vs Name"
        import re
        event_pattern = r'UFC\s+(?:\d+|Fight Night):\s+([A-Za-z\s\'\-\.]+)\s+vs\.?\s+([A-Za-z\s\'\-\.]+)'
        
        # Also extract dates like "Jan 18"
        date_venue_pattern = r'([A-Z][a-z]{2}\s+\d{1,2})\s+\|[^\|]+\|([^\|]+)'
        
        for match in re.finditer(event_pattern, content):
            fighter1 = match.group(1).strip()
            fighter2 = match.group(2).strip()
            
            # Skip if names are too short
            if len(fighter1) < 3 or len(fighter2) < 3:
                continue
            
            # Try to find the date for this fight (rough approximation)
            # For now, we'll leave date blank and let TheSportsDB fill it
            fights.append({
                'fighter1': fighter1,
                'fighter2': fighter2,
                'date': '',
                'time': '',
                'venue': 'TBA',
                'location': 'TBA',
                'sport': 'UFC',
                'event_name': f'{fighter1} vs {fighter2}'
            })
            
            print(f"ESPN UFC: Added {fighter1} vs {fighter2}")
        
        print(f"ESPN UFC: Found {len(fights)} fights")
        
    except Exception as e:
        print(f"Error scraping ESPN UFC: {e}")
    
    return fights

def scrape_bbc_boxing():
    """Scrape boxing fights from BBC Sport calendar"""
    fights = []
    
    try:
        print("Scraping BBC Sport Boxing calendar...")
        
        from bs4 import BeautifulSoup
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        
        # Get current month and next 2 months
        now = datetime.now()
        months_to_scrape = [
            now.strftime("%Y-%m"),
            (now + relativedelta(months=1)).strftime("%Y-%m"),
            (now + relativedelta(months=2)).strftime("%Y-%m")
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        for month in months_to_scrape:
            try:
                url = f'https://www.bbc.com/sport/boxing/calendar/{month}'
                print(f"Fetching {month}...")
                
                response = requests.get(url, headers=headers, timeout=15)
                
                if response.status_code != 200:
                    print(f"BBC Sport scrape failed for {month}: {response.status_code}")
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find all fight cards
                cards = soup.find_all('div', class_='ssrcss-dvz3gg-Card')
                
                # Extract year from month string
                year = int(month.split('-')[0])
                
                for card in cards:
                    try:
                        # Skip cancelled fights
                        if card.find('span', class_='ssrcss-1xk4umy-Label'):
                            continue
                        
                        # Extract date (e.g., "Saturday 22 November")
                        date_elem = card.find('span', class_='visually-hidden')
                        if not date_elem:
                            continue
                        date_text = date_elem.get_text(strip=True)
                        
                        # Extract fighters (hyphen-separated)
                        fighters_elem = card.find('li', class_='ssrcss-3wkvfu-EventName')
                        if not fighters_elem:
                            continue
                        fighters_text = fighters_elem.get_text(strip=True)
                        
                        # Split on hyphen
                        fighter_parts = fighters_text.split('-')
                        if len(fighter_parts) < 2:
                            continue
                        fighter1 = fighter_parts[0].strip()
                        fighter2 = fighter_parts[1].strip()
                        
                        # Skip if names too short
                        if len(fighter1) < 2 or len(fighter2) < 2:
                            continue
                        
                        # Extract venue
                        venue_elem = card.find('li', class_='ssrcss-1sjq6ac-VenueName')
                        venue = venue_elem.get_text(strip=True) if venue_elem else 'TBA'
                        
                        # Extract time and weight class
                        secondary = card.find_all('li', class_='ssrcss-8blldk-Secondary')
                        time_str = secondary[0].get_text(strip=True) if len(secondary) > 0 else ''
                        weight_class = secondary[1].get_text(strip=True) if len(secondary) > 1 else ''
                        
                        # Parse date using the year from URL
                        try:
                            date_with_year = f"{date_text} {year}"
                            parsed_date = datetime.strptime(date_with_year, "%A %d %B %Y")
                            date_formatted = parsed_date.strftime("%Y-%m-%d")
                        except:
                            date_formatted = ''
                        
                        fights.append({
                            'fighter1': fighter1,
                            'fighter2': fighter2,
                            'date': date_formatted,
                            'time': time_str,
                            'venue': venue,
                            'location': venue,
                            'sport': 'Boxing',
                            'event_name': f'{fighter1} vs {fighter2}',
                            'weight_class': weight_class
                        })
                        
                        print(f"BBC Sport: Added {fighter1} vs {fighter2} ({date_formatted})")
                        
                    except Exception as e:
                        print(f"Error parsing BBC card: {e}")
                        continue
                
                print(f"BBC Sport {month}: Found {len([f for f in fights if f['date'].startswith(month)])} fights")
                
            except Exception as e:
                print(f"Error scraping BBC Sport for {month}: {e}")
                continue
        
        print(f"BBC Sport Boxing Total: Found {len(fights)} fights across all months")
        
    except Exception as e:
        print(f"Error in BBC Sport scraper: {e}")
    
    return fights

def scrape_mma_fighting():
    """Scrape UFC schedule from MMA Fighting"""
    fights = []
    
    try:
        print("Scraping MMA Fighting schedule...")
        
        url = "https://www.mmafighting.com/schedule"
        
        from bs4 import BeautifulSoup
        import re
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        def convert_et_to_uk(time_et_str):
            """Convert ET time to UK time (ET is GMT-5)"""
            try:
                time_match = re.search(r'(\d+)\s*(a\.m\.|p\.m\.)', time_et_str.lower())
                if not time_match:
                    return None
                
                hour = int(time_match.group(1))
                am_pm = time_match.group(2)
                
                # Convert to 24-hour format
                if am_pm == 'p.m.' and hour != 12:
                    hour += 12
                elif am_pm == 'a.m.' and hour == 12:
                    hour = 0
                
                # ET is GMT-5, so add 5 hours to get UK time
                uk_hour = (hour + 5) % 24
                
                return f"{uk_hour:02d}:00"
            except:
                return None
        
        # Find all event dates
        event_dates = soup.find_all('h1', class_='_5ae48f1')
        
        for date_elem in event_dates:
            date_text = date_elem.get_text(strip=True)
            
            # Parse date
            try:
                date_obj = datetime.strptime(date_text, "%B %d, %Y")
                date_formatted = date_obj.strftime("%Y-%m-%d")
            except:
                continue
            
            current = date_elem.parent.parent
            event_containers = current.find_next_siblings('div', class_='duet--layout--page-header')
            
            for event_container in event_containers:
                if not event_container.find('a', class_='_5ae48f6'):
                    continue
                
                # Extract event details
                event_link = event_container.find('a', class_='_5ae48f6')
                event_name = event_link.get_text(strip=True) if event_link else ''
                
                # Only include UFC events
                if 'UFC' not in event_name:
                    continue
                
                event_details = event_container.find('p', class_='ls9zuh3')
                details_text = event_details.get_text(strip=True) if event_details else ''
                
                venue = details_text.split('•')[0].strip() if '•' in details_text else ''
                
                # Extract times
                main_card_time = None
                if 'main card' in details_text.lower():
                    main_card_match = re.search(r'main card.*?(\d+\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                    if main_card_match:
                        main_card_time = convert_et_to_uk(main_card_match.group(1))
                
                prelim_time = None
                if 'prelim' in details_text.lower() and 'early' not in details_text.lower():
                    prelim_match = re.search(r'prelim(?:s|inary card)?.*?(\d+\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                    if prelim_match:
                        prelim_time = convert_et_to_uk(prelim_match.group(1))
                
                print(f"MMA Fighting: {event_name} - {date_formatted}")
                
                # Find fight sections
                fight_sections_container = event_container.find_next_sibling('div', class_='_5ae48f5')
                
                if not fight_sections_container:
                    continue
                
                # Process Main Card
                main_card_section = fight_sections_container.find('h1', string=re.compile('Main Card', re.IGNORECASE))
                if main_card_section:
                    fight_cards = main_card_section.parent.parent.find_next_sibling('div')
                    if fight_cards:
                        for fight_card in fight_cards.find_all('div', class_='_5vdhue0'):
                            is_title = fight_card.find('span', class_='_153sp3o2') is not None
                            
                            fight_link = fight_card.find('a', class_='_1ngvuhm0')
                            if fight_link:
                                fight_text = fight_link.get_text(strip=True)
                                fighters = fight_text.split(' vs ')
                                
                                if len(fighters) == 2:
                                    fights.append({
                                        'fighter1': fighters[0].strip(),
                                        'fighter2': fighters[1].strip(),
                                        'date': date_formatted,
                                        'time': main_card_time,
                                        'venue': venue,
                                        'location': venue,
                                        'sport': 'UFC',
                                        'event_name': event_name,
                                        'weight_class': 'Title' if is_title else '',
                                        'card_type': 'Main Card'
                                    })
                
                # Process Preliminary Card
                prelim_section = fight_sections_container.find('h1', string=re.compile('Preliminary Card', re.IGNORECASE))
                if prelim_section:
                    fight_cards = prelim_section.parent.parent.find_next_sibling('div')
                    if fight_cards:
                        for fight_card in fight_cards.find_all('div', class_='_5vdhue0'):
                            fight_link = fight_card.find('a', class_='_1ngvuhm0')
                            if fight_link:
                                fight_text = fight_link.get_text(strip=True)
                                fighters = fight_text.split(' vs ')
                                
                                if len(fighters) == 2:
                                    # Calculate prelim time if not found (2 hours before main card)
                                    calculated_prelim_time = prelim_time
                                    if not prelim_time and main_card_time:
                                        try:
                                            main_hour = int(main_card_time.split(':')[0])
                                            prelim_hour = (main_hour - 2) % 24
                                            calculated_prelim_time = f"{prelim_hour:02d}:00"
                                        except:
                                            calculated_prelim_time = main_card_time
                                    
                                    fights.append({
                                        'fighter1': fighters[0].strip(),
                                        'fighter2': fighters[1].strip(),
                                        'date': date_formatted,
                                        'time': calculated_prelim_time or main_card_time,
                                        'venue': venue,
                                        'location': venue,
                                        'sport': 'UFC',
                                        'event_name': event_name,
                                        'weight_class': '',
                                        'card_type': 'Prelims'
                                    })
        
        print(f"MMA Fighting: Found {len(fights)} UFC fights")
        
    except Exception as e:
        print(f"Error scraping MMA Fighting: {e}")
    
    return fights

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

def load_cache():
    """Load cached fight data if it exists and is fresh"""
    if not os.path.exists(CACHE_FILE):
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            
        # Check if cache is still fresh
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        if datetime.now() - cache_time < CACHE_DURATION:
            print(f"Using cached data from {cache_time}")
            
            # Apply time overrides to cached data
            fights = cache_data['fights']
            fights = apply_time_overrides(fights)
            
            return fights
        else:
            print("Cache expired, fetching new data...")
            return None
    except Exception as e:
        print(f"Error loading cache: {e}")
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
        print(f"Cache updated at {datetime.now()}")
    except Exception as e:
        print(f"Error saving cache: {e}")

def fetch_ufc_events():
    """Fetch upcoming UFC events using TheSportsDB Premium API v1"""
    fights = []
    
    try:
        print("Fetching UFC events from TheSportsDB Premium API...")
        
        # V1 API endpoint - eventsnextleague works better
        url = f'https://www.thesportsdb.com/api/v1/json/{API_KEY}/eventsnextleague.php?id=4443'
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Debug: Print first event to see structure
            events = data.get('events', [])
            if events and len(events) > 0:
                print(f"\nDEBUG - First UFC event structure:")
                print(f"Keys available: {events[0].keys()}")
                print(f"strHomeTeam: {events[0].get('strHomeTeam')}")
                print(f"strAwayTeam: {events[0].get('strAwayTeam')}")
                print(f"strEvent: {events[0].get('strEvent')}")
                print(f"strThumb: {events[0].get('strThumb')}")
                print(f"strPoster: {events[0].get('strPoster')}")
                print(f"strSquare: {events[0].get('strSquare')}")
                print()
            
            print(f"Found {len(events)} UFC events")
            
            for event in events[:15]:  # Limit to 15 events
                try:
                    # Fighter names are in strEvent, not strHomeTeam/strAwayTeam
                    event_name = event.get('strEvent', '')
                    
                    # Parse fighters from event name
                    fighter1 = 'TBA'
                    fighter2 = 'TBA'
                    
                    if event_name:
                        # Remove UFC/event number prefix (e.g. "UFC 323: " or "UFC 323 ")
                        clean_name = event_name
                        if 'UFC' in event_name:
                            # Remove "UFC XXX: " or "UFC XXX "
                            parts = event_name.split(':', 1)
                            if len(parts) > 1:
                                clean_name = parts[1].strip()
                            else:
                                # No colon, try removing "UFC XXX " pattern
                                clean_name = re.sub(r'^UFC\s+\d+\s+', '', event_name).strip()
                        
                        # Now parse "Fighter1 vs Fighter2"
                        if ' vs ' in clean_name.lower():
                            parts = clean_name.split(' vs ')
                            if len(parts) >= 2:
                                fighter1 = parts[0].strip()
                                fighter2_raw = parts[1].strip()
                                # Only remove trailing numbers if they're event numbers (like "2" after "Yan 2")
                                # Keep if it's part of the name or if there's more content after
                                if re.match(r'^.+\s+\d+$', fighter2_raw):
                                    # Has trailing number - only remove if it looks like event number
                                    fighter2 = re.sub(r'\s+\d+$', '', fighter2_raw).strip()
                                else:
                                    fighter2 = fighter2_raw
                        elif ' vs. ' in clean_name.lower():
                            parts = clean_name.split(' vs. ')
                            if len(parts) >= 2:
                                fighter1 = parts[0].strip()
                                fighter2_raw = parts[1].strip()
                                if re.match(r'^.+\s+\d+$', fighter2_raw):
                                    fighter2 = re.sub(r'\s+\d+$', '', fighter2_raw).strip()
                                else:
                                    fighter2 = fighter2_raw
                        else:
                            # DEBUG: No "vs" found - print the raw event name
                            if venue and venue != 'TBA':
                                print(f"DEBUG TBA FIGHT: strEvent='{event_name}', venue={venue}, date={date_str}")
                    
                    # Extract event details
                    date_str = event.get('dateEvent', '')
                    time_str = event.get('strTime', '')
                    venue = event.get('strVenue', 'TBA')
                    city = event.get('strCity', '')
                    country = event.get('strCountry', '')
                    
                    location = f"{city}, {country}" if city and country else (city or country or 'TBA')
                    
                    # Fetch fighter images
                    print(f"Fetching images for {fighter1} and {fighter2}...")
                    fighter1_image = get_fighter_image(fighter1)
                    fighter2_image = get_fighter_image(fighter2)
                    
                    fights.append({
                        'fighter1': fighter1,
                        'fighter2': fighter2,
                        'fighter1_image': fighter1_image,
                        'fighter2_image': fighter2_image,
                        'date': date_str,
                        'time': time_str,
                        'venue': venue,
                        'location': location,
                        'sport': 'UFC',
                        'event_name': event_name
                    })
                    
                    print(f"Added: {fighter1} vs {fighter2}")
                    
                except Exception as e:
                    print(f"Error parsing UFC event: {e}")
                    continue
        else:
            print(f"UFC API error: Status {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
    except Exception as e:
        print(f"Error fetching UFC events: {e}")
    
    return fights

def fetch_boxing_events():
    """Fetch upcoming Boxing events using TheSportsDB Premium API v1"""
    fights = []
    
    try:
        print("Fetching Boxing events from TheSportsDB Premium API...")
        
        # V1 API endpoint
        url = f'https://www.thesportsdb.com/api/v1/json/{API_KEY}/eventsnextleague.php?id=4445'
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            events = data.get('events', [])
            print(f"Found {len(events)} Boxing events")
            
            for event in events[:15]:
                try:
                    # Fighter names are in strEvent, not strHomeTeam/strAwayTeam
                    event_name = event.get('strEvent', '')
                    
                    # Parse fighters from event name
                    fighter1 = 'TBA'
                    fighter2 = 'TBA'
                    
                    if event_name:
                        # For boxing, names are usually just "Fighter1 vs Fighter2"
                        clean_name = event_name
                        
                        # Parse "Fighter1 vs Fighter2"
                        if ' vs ' in clean_name.lower():
                            parts = clean_name.split(' vs ')
                            if len(parts) >= 2:
                                fighter1 = parts[0].strip()
                                fighter2 = parts[1].strip()
                                # Remove trailing numbers
                                fighter2 = re.sub(r'\s+\d+$', '', fighter2).strip()
                        elif ' vs. ' in clean_name.lower():
                            parts = clean_name.split(' vs. ')
                            if len(parts) >= 2:
                                fighter1 = parts[0].strip()
                                fighter2 = parts[1].strip()
                                # Remove trailing numbers
                                fighter2 = re.sub(r'\s+\d+$', '', fighter2).strip()
                        else:
                            # DEBUG: No "vs" found - print the raw event name
                            print(f"DEBUG TBA BOXING: strEvent='{event_name}'")
                    
                    date_str = event.get('dateEvent', '')
                    time_str = event.get('strTime', '')
                    venue = event.get('strVenue', 'TBA')
                    city = event.get('strCity', '')
                    country = event.get('strCountry', '')
                    
                    location = f"{city}, {country}" if city and country else (city or country or 'TBA')
                    
                    # Fetch fighter images
                    print(f"Fetching images for {fighter1} and {fighter2}...")
                    fighter1_image = get_fighter_image(fighter1)
                    fighter2_image = get_fighter_image(fighter2)
                    
                    fights.append({
                        'fighter1': fighter1,
                        'fighter2': fighter2,
                        'fighter1_image': fighter1_image,
                        'fighter2_image': fighter2_image,
                        'date': date_str,
                        'time': time_str,
                        'venue': venue,
                        'location': location,
                        'sport': 'Boxing',
                        'event_name': event_name
                    })
                    
                    print(f"Added: {fighter1} vs {fighter2}")
                    
                except Exception as e:
                    print(f"Error parsing Boxing event: {e}")
                    continue
        else:
            print(f"Boxing API error: Status {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
    except Exception as e:
        print(f"Error fetching Boxing events: {e}")
    
    return fights

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
    
    # 1. Scrape BBC Sport for boxing
    log("--- BBC SPORT BOXING ---")
    bbc_boxing = scrape_bbc_boxing()
    log(f"BBC Sport Boxing found: {len(bbc_boxing)} fights\n")
    for fight in bbc_boxing[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} - {fight['venue']}")
    if len(bbc_boxing) > 5:
        log(f"  ... and {len(bbc_boxing) - 5} more\n")
    
    # 2. Scrape MMA Fighting for UFC schedule
    log("\n--- MMA FIGHTING UFC ---")
    mma_fighting_ufc = scrape_mma_fighting()
    log(f"MMA Fighting UFC found: {len(mma_fighting_ufc)} fights\n")
    for fight in mma_fighting_ufc[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} - {fight['venue']}")
    if len(mma_fighting_ufc) > 5:
        log(f"  ... and {len(mma_fighting_ufc) - 5} more\n")
    
    # 3. Fetch TheSportsDB for boxing images (optional backup)
    log("\n--- THESPORTSDB BOXING ---")
    thesportsdb_boxing = fetch_boxing_events()
    log(f"TheSportsDB Boxing found: {len(thesportsdb_boxing)} fights\n")
    for fight in thesportsdb_boxing[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} - {fight['venue']}")
        if fight.get('fighter1_image'):
            log(f"    ✓ Has fighter images")
    if len(thesportsdb_boxing) > 5:
        log(f"  ... and {len(thesportsdb_boxing) - 5} more\n")
    
    # 4. Combine data
    log("\n" + "="*60)
    log("MERGING DATA...")
    log("="*60 + "\n")
    
    # Add BBC Sport boxing fights
    fights.extend(bbc_boxing)
    
    # Add MMA Fighting UFC fights
    fights.extend(mma_fighting_ufc)
    
    # Merge TheSportsDB boxing data (for images)
    merged_count = 0
    new_from_tsd = 0
    
    for tsd_fight in thesportsdb_boxing:
        # Check if this fight already exists
        exists = False
        for existing in fights:
            if (existing['fighter1'] == tsd_fight['fighter1'] and 
                existing['fighter2'] == tsd_fight['fighter2']):
                # Merge: Add images from TheSportsDB
                if tsd_fight.get('fighter1_image'):
                    existing['fighter1_image'] = tsd_fight['fighter1_image']
                if tsd_fight.get('fighter2_image'):
                    existing['fighter2_image'] = tsd_fight['fighter2_image']
                exists = True
                merged_count += 1
                break
        
        # If fight doesn't exist, add it from TheSportsDB
        if not exists:
            fights.append(tsd_fight)
            new_from_tsd += 1
    
    log(f"Merged images for {merged_count} fights")
    log(f"Added {new_from_tsd} new fights from TheSportsDB")
    
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
    
    # Filter to title fights only (championship bouts)
    fights_before_title_filter = len(fights)
    fights = [f for f in fights if 'Title' in f.get('weight_class', '') or f.get('sport') == 'UFC']
    
    log("\n" + "="*60)
    log(f"Filtered out {fights_before_filter - len(fights)} past fights")
    log(f"Filtered to {len(fights)} title fights (removed {fights_before_title_filter - len(fights)} non-title bouts)")
    log(f"FINAL RESULT: {len(fights)} upcoming championship fights")
    log("="*60)
    
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
    fights = fetch_fights()
    return render_template('index.html', fights=fights, fights_json=json.dumps(fights))

@app.route('/event/<event_slug>')
def event_detail(event_slug):
    """Show detailed page for a specific event with full card"""
    fights = fetch_fights()
    
    # Decode slug back to event name (basic version)
    # event_slug comes from URL like "ufc-323-dvalishvili-vs-yan-2"
    
    # For now, just find the first UFC event (we'll improve slug matching later)
    # Group fights by event
    ufc_events = {}
    for fight in fights:
        if fight['sport'] == 'UFC':
            event_name = fight.get('event_name', '')
            if event_name not in ufc_events:
                ufc_events[event_name] = []
            ufc_events[event_name].append(fight)
    
    # Get the first UFC event (for testing)
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
    
    # Get first event
    event_name = list(ufc_events.keys())[0]
    event_fights_list = ufc_events[event_name]
    
    # Separate main card and prelims
    main_card_fights = [f for f in event_fights_list if f.get('card_type') == 'Main Card']
    prelim_fights = [f for f in event_fights_list if f.get('card_type') == 'Prelims']
    
    # Get main event (first fight in main card)
    main_event_fight = main_card_fights[0] if main_card_fights else event_fights_list[0]
    
    # Get weight class from first title fight
    weight_class = ''
    for fight in main_card_fights:
        if fight.get('weight_class') == 'Title':
            weight_class = 'Championship'
            break
    
    # Build event data structure
    event_data = {
        'event_name': event_name,
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
    
    return render_template('event_detail.html', event=event_data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
