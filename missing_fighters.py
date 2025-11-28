"""
Identify fighters without images and rank by frequency

This script analyzes your current fight schedule and shows:
1. Which fighters are missing images
2. How many times they appear on the schedule
3. Sorted by frequency (most common first)

Usage:
    python missing_fighters.py
"""

import json
from collections import Counter

def load_fighter_database():
    """Load both fighter databases"""
    fighters_db = {}
    
    # Load boxing database
    try:
        with open('fighters.json', 'r', encoding='utf-8') as f:
            fighters_db.update(json.load(f))
    except:
        pass
    
    # Load UFC database
    try:
        with open('fighters_ufc.json', 'r', encoding='utf-8') as f:
            fighters_db.update(json.load(f))
    except:
        pass
    
    return fighters_db

def analyze_missing_fighters():
    """Analyze the current fight cache and identify missing fighters"""
    
    # Load fighter database
    fighters_db = load_fighter_database()
    
    # Load fight cache
    try:
        with open('fights_cache.json', 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            fights = cache_data.get('fights', [])
    except FileNotFoundError:
        print("❌ fights_cache.json not found. Run the app first to generate fight data.")
        return
    
    # Track missing fighters
    missing_fighters = []
    
    for fight in fights:
        fighter1 = fight.get('fighter1')
        fighter2 = fight.get('fighter2')
        sport = fight.get('sport', 'Boxing')
        
        # Check fighter1 - missing from DB or has no valid image URL
        if fighter1 and fighter1 != 'TBA':
            if fighter1 not in fighters_db or not fighters_db.get(fighter1):
                missing_fighters.append({
                    'name': fighter1,
                    'sport': sport,
                    'fight': f"{fighter1} vs {fighter2}",
                    'date': fight.get('date', 'Unknown')
                })
        
        # Check fighter2 - missing from DB or has no valid image URL
        if fighter2 and fighter2 != 'TBA':
            if fighter2 not in fighters_db or not fighters_db.get(fighter2):
                missing_fighters.append({
                    'name': fighter2,
                    'sport': sport,
                    'fight': f"{fighter1} vs {fighter2}",
                    'date': fight.get('date', 'Unknown')
                })
    
    # Count frequency
    fighter_counts = Counter([f['name'] for f in missing_fighters])
    
    # Write results to file
    output_file = "missing_fighters_report.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Header with instructions
        f.write("="*70 + "\n")
        f.write("MISSING FIGHTER IMAGES REPORT\n")
        f.write("="*70 + "\n\n")
        
        f.write(f"Generated: {fights[0].get('date', 'Unknown') if fights else 'Unknown'}\n")
        f.write(f"Total fights analyzed: {len(fights)}\n")
        f.write(f"Unique fighters missing images: {len(fighter_counts)}\n")
        f.write(f"Total missing image slots: {len(missing_fighters)}\n\n")
        
        # Image requirements
        f.write("="*70 + "\n")
        f.write("IMAGE REQUIREMENTS\n")
        f.write("="*70 + "\n\n")
        f.write("FORMAT: PNG or JPG\n")
        f.write("SIZE: Any (will be displayed at ~200-300px)\n")
        f.write("ASPECT RATIO: Square or portrait recommended\n")
        f.write("BACKGROUND: Light/white background preferred (matches existing)\n")
        f.write("QUALITY: Official promotional photos work best\n\n")
        
        f.write("HOW TO FIND IMAGES:\n")
        f.write("1. Google: '[Fighter Name] official photo' or '[Fighter Name] UFC/boxing'\n")
        f.write("2. Right-click image > 'Copy image address'\n")
        f.write("3. Use the command below with that URL\n\n")
        
        # Example usage
        f.write("="*70 + "\n")
        f.write("HOW TO ADD IMAGES\n")
        f.write("="*70 + "\n\n")
        f.write("COMMAND FORMAT:\n")
        f.write("python add_fighter_image.py \"Fighter Name\" \"IMAGE_URL\" sport\n\n")
        f.write("EXAMPLES:\n")
        f.write("python add_fighter_image.py \"Isaac Cruz\" \"https://example.com/cruz.jpg\" boxing\n")
        f.write("python add_fighter_image.py \"Jon Jones\" \"https://ufc.com/jones.png\" ufc\n\n")
        
        # Breakdown by sport
        ufc_missing = [f for f in missing_fighters if f['sport'] == 'UFC']
        boxing_missing = [f for f in missing_fighters if f['sport'] != 'UFC']
        
        f.write("="*70 + "\n")
        f.write("BREAKDOWN BY SPORT\n")
        f.write("="*70 + "\n\n")
        f.write(f"UFC fighters missing: {len(set(f['name'] for f in ufc_missing))}\n")
        f.write(f"Boxing fighters missing: {len(set(f['name'] for f in boxing_missing))}\n\n")
        
        # List fighters in priority order
        f.write("="*70 + "\n")
        f.write("MISSING FIGHTERS (RANKED BY FREQUENCY)\n")
        f.write("="*70 + "\n\n")
        
        for fighter_name, count in fighter_counts.most_common():
            fighter_info = next(f for f in missing_fighters if f['name'] == fighter_name)
            sport = fighter_info['sport']
            sport_label = 'ufc' if sport == 'UFC' else 'boxing'
            
            f.write(f"{fighter_name}\n")
            f.write(f"  Sport: {sport}\n")
            f.write(f"  Appears in: {count} fight(s)\n")
            
            # Show fights this fighter appears in
            fighter_fights = [ff for ff in missing_fighters if ff['name'] == fighter_name]
            for fight in fighter_fights[:3]:
                f.write(f"  - {fight['date']}: {fight['fight']}\n")
            
            f.write(f"  COMMAND: python add_fighter_image.py \"{fighter_name}\" \"IMAGE_URL\" {sport_label}\n\n")
        
        f.write("="*70 + "\n")
        f.write("END OF REPORT\n")
        f.write("="*70 + "\n")
    
    print(f"\n✅ Report saved to: {output_file}")
    print(f"   Found {len(fighter_counts)} fighters missing images\n")

if __name__ == "__main__":
    analyze_missing_fighters()
