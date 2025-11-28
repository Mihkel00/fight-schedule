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
        
        # Check fighter1
        if fighter1 and fighter1 != 'TBA' and fighter1 not in fighters_db:
            missing_fighters.append({
                'name': fighter1,
                'sport': sport,
                'fight': f"{fighter1} vs {fighter2}",
                'date': fight.get('date', 'Unknown')
            })
        
        # Check fighter2
        if fighter2 and fighter2 != 'TBA' and fighter2 not in fighters_db:
            missing_fighters.append({
                'name': fighter2,
                'sport': sport,
                'fight': f"{fighter1} vs {fighter2}",
                'date': fight.get('date', 'Unknown')
            })
    
    # Count frequency
    fighter_counts = Counter([f['name'] for f in missing_fighters])
    
    # Print results
    print("\n" + "="*70)
    print("MISSING FIGHTER IMAGES REPORT")
    print("="*70)
    print(f"\nTotal fights analyzed: {len(fights)}")
    print(f"Unique fighters missing images: {len(fighter_counts)}")
    print(f"Total missing image slots: {len(missing_fighters)}")
    print("\n" + "-"*70)
    print("MOST FREQUENT MISSING FIGHTERS (prioritize these for manual addition)")
    print("-"*70 + "\n")
    
    # Group by fighter and show details
    for fighter_name, count in fighter_counts.most_common():
        # Get first occurrence for details
        fighter_info = next(f for f in missing_fighters if f['name'] == fighter_name)
        sport = fighter_info['sport']
        
        print(f"🥊 {fighter_name}")
        print(f"   Sport: {sport}")
        print(f"   Appears in: {count} fight(s)")
        
        # Show all fights this fighter appears in
        fighter_fights = [f for f in missing_fighters if f['name'] == fighter_name]
        for fight in fighter_fights[:3]:  # Show max 3 fights
            print(f"   - {fight['date']}: {fight['fight']}")
        
        print()
    
    # Summary by sport
    print("-"*70)
    print("BREAKDOWN BY SPORT")
    print("-"*70 + "\n")
    
    ufc_missing = [f for f in missing_fighters if f['sport'] == 'UFC']
    boxing_missing = [f for f in missing_fighters if f['sport'] != 'UFC']
    
    print(f"UFC fighters missing: {len(set(f['name'] for f in ufc_missing))}")
    print(f"Boxing fighters missing: {len(set(f['name'] for f in boxing_missing))}")
    
    # Suggest commands
    print("\n" + "="*70)
    print("TO ADD IMAGES MANUALLY:")
    print("="*70)
    print("\nTop 5 priorities:\n")
    
    for i, (fighter_name, count) in enumerate(fighter_counts.most_common(5), 1):
        fighter_info = next(f for f in missing_fighters if f['name'] == fighter_name)
        sport = 'ufc' if fighter_info['sport'] == 'UFC' else 'boxing'
        print(f'{i}. python add_fighter_image.py "{fighter_name}" "IMAGE_URL" {sport}')
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    analyze_missing_fighters()
