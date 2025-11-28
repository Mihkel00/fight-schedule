"""
One-time script to build fighters.json database from TheSportsDB API
Run this to populate initial fighter image database
"""

import json
import requests
from time import sleep

# Your Premium API Key
API_KEY = '891686'

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
                image_url = player.get('strCutout') or player.get('strThumb') or player.get('strFanart1')
                if image_url:
                    print(f"✓ Found image for {fighter_name}")
                    return image_url
                else:
                    print(f"✗ No image available for {fighter_name}")
                    return None
        
        print(f"✗ No results for {fighter_name}")
        return None
        
    except Exception as e:
        print(f"✗ Error fetching image for {fighter_name}: {e}")
        return None

def load_fights_from_cache():
    """Load fights from cache file"""
    try:
        with open('fights_cache.json', 'r') as f:
            cache_data = json.load(f)
            return cache_data.get('fights', [])
    except Exception as e:
        print(f"Error loading cache: {e}")
        return []

def build_fighter_database():
    """Build fighters.json from current fight data"""
    print("\n" + "="*60)
    print("BUILDING FIGHTER IMAGE DATABASE")
    print("="*60 + "\n")
    
    # Load current fights
    print("Loading fights from cache...")
    fights = load_fights_from_cache()
    
    if not fights:
        print("No fights found in cache. Run the main app first to populate cache.")
        return
    
    print(f"Found {len(fights)} fights in cache\n")
    
    # Extract unique fighter names
    all_fighters = set()
    for fight in fights:
        fighter1 = fight.get('fighter1')
        fighter2 = fight.get('fighter2')
        
        if fighter1 and fighter1 != 'TBA':
            all_fighters.add(fighter1)
        if fighter2 and fighter2 != 'TBA':
            all_fighters.add(fighter2)
    
    print(f"Found {len(all_fighters)} unique fighters\n")
    print("Querying TheSportsDB API for images...")
    print("(This may take a few minutes...)\n")
    
    # Query API for each fighter
    fighters_db = {}
    found_count = 0
    
    for i, name in enumerate(sorted(all_fighters), 1):
        print(f"[{i}/{len(all_fighters)}] {name}... ", end='')
        
        img_url = get_fighter_image(name)
        fighters_db[name] = img_url
        
        if img_url:
            found_count += 1
        
        # Rate limiting - don't hammer the API
        sleep(0.5)
    
    # Save to fighters.json
    print(f"\n\nSaving to fighters.json...")
    with open('fighters.json', 'w', encoding='utf-8') as f:
        json.dump(fighters_db, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print("DATABASE BUILD COMPLETE")
    print("="*60)
    print(f"Total fighters: {len(fighters_db)}")
    print(f"Images found: {found_count} ({found_count*100//len(fighters_db) if fighters_db else 0}%)")
    print(f"Missing images: {len(fighters_db) - found_count}")
    print(f"\nDatabase saved to: fighters.json")
    print("="*60 + "\n")

if __name__ == '__main__':
    build_fighter_database()
