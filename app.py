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

def get_fighter_image(fighter_name):
    """Search for fighter by name and return their image URL"""
    if not fighter_name or fighter_name == 'TBA':
        return None
        
    try:
        # Search for player by name
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
            return cache_data['fights']
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
                                fighter2 = parts[1].strip()
                                # Remove trailing numbers (like "Yan 2" -> "Yan")
                                fighter2 = re.sub(r'\s+\d+$', '', fighter2).strip()
                        elif ' vs. ' in clean_name.lower():
                            parts = clean_name.split(' vs. ')
                            if len(parts) >= 2:
                                fighter1 = parts[0].strip()
                                fighter2 = parts[1].strip()
                                # Remove trailing numbers
                                fighter2 = re.sub(r'\s+\d+$', '', fighter2).strip()
                    
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
    """Fetch upcoming UFC and Boxing fights"""
    # Try loading from cache first
    cached_fights = load_cache()
    if cached_fights is not None:
        return cached_fights
    
    # If no cache, fetch fresh data
    fights = []
    
    # Fetch UFC events
    ufc_fights = fetch_ufc_events()
    fights.extend(ufc_fights)
    
    # Fetch Boxing events
    boxing_fights = fetch_boxing_events()
    fights.extend(boxing_fights)
    
    # Sort fights by date
    fights.sort(key=lambda x: x['date'] if x['date'] else '9999-12-31')
    
    # Save to cache
    if fights:
        save_cache(fights)
    
    return fights

@app.route('/')
def home():
    fights = fetch_fights()
    return render_template('index.html', fights=fights)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
