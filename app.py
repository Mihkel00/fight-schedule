from flask import Flask, render_template
import os
import requests
from datetime import datetime, timedelta
import json

app = Flask(__name__)

# Cache file path
CACHE_FILE = 'fights_cache.json'
CACHE_DURATION = timedelta(hours=6)  # Refresh every 6 hours

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

def fetch_fights():
    """Fetch upcoming UFC and Boxing fights from TheSportsDB API"""
    # Try loading from cache first
    cached_fights = load_cache()
    if cached_fights is not None:
        return cached_fights
    
    # If no cache, fetch from API
    fights = []
    
    # API key (using free tier key '123')
    api_key = '123'
    
    # Fetch UFC events (League ID: 4443)
    ufc_url = f'https://www.thesportsdb.com/api/v1/json/{api_key}/eventsnextleague.php?id=4443'
    try:
        print("Fetching UFC events from API...")
        response = requests.get(ufc_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"UFC API Response: {data}")  # Debug print
            if data.get('events'):
                for event in data['events'][:15]:  # Limit to 15 events
                    print(f"Event data: {event}")  # Debug print each event
                    fights.append({
                        'fighter1': event.get('strHomeTeam') or event.get('strEvent', 'TBA').split(' vs ')[0] if ' vs ' in event.get('strEvent', '') else 'TBA',
                        'fighter2': event.get('strAwayTeam') or event.get('strEvent', 'TBA').split(' vs ')[1] if ' vs ' in event.get('strEvent', '') and len(event.get('strEvent', '').split(' vs ')) > 1 else 'TBA',
                        'date': event.get('dateEvent', ''),
                        'time': event.get('strTime', ''),
                        'venue': event.get('strVenue', 'TBA'),
                        'location': event.get('strCity', '') + ', ' + event.get('strCountry', ''),
                        'sport': 'UFC'
                    })
        else:
            print(f"UFC API error: Status {response.status_code}")
    except Exception as e:
        print(f"Error fetching UFC events: {e}")
    
    # Fetch Boxing events (League ID: 4445)
    boxing_url = f'https://www.thesportsdb.com/api/v1/json/{api_key}/eventsnextleague.php?id=4445'
    try:
        print("Fetching Boxing events from API...")
        response = requests.get(boxing_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"Boxing API Response: {data}")  # Debug print
            if data.get('events'):
                for event in data['events'][:15]:  # Limit to 15 events
                    print(f"Event data: {event}")  # Debug print each event
                    fights.append({
                        'fighter1': event.get('strHomeTeam') or event.get('strEvent', 'TBA').split(' vs ')[0] if ' vs ' in event.get('strEvent', '') else 'TBA',
                        'fighter2': event.get('strAwayTeam') or event.get('strEvent', 'TBA').split(' vs ')[1] if ' vs ' in event.get('strEvent', '') and len(event.get('strEvent', '').split(' vs ')) > 1 else 'TBA',
                        'date': event.get('dateEvent', ''),
                        'time': event.get('strTime', ''),
                        'venue': event.get('strVenue', 'TBA'),
                        'location': event.get('strCity', '') + ', ' + event.get('strCountry', ''),
                        'sport': 'Boxing'
                    })
        else:
            print(f"Boxing API error: Status {response.status_code}")
    except Exception as e:
        print(f"Error fetching Boxing events: {e}")
    
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
