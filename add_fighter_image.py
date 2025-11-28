"""
Helper script to manually add fighter images to the database

Usage:
    python add_fighter_image.py "Fighter Name" "https://image-url.com/fighter.jpg" [sport]
    
    sport: "boxing" or "ufc" (default: boxing)

Example:
    python add_fighter_image.py "Isaac Cruz" "https://example.com/cruz.jpg" boxing
    python add_fighter_image.py "Jon Jones" "https://example.com/jones.jpg" ufc
"""

import json
import sys

def add_fighter_image(fighter_name, image_url, sport="boxing"):
    """Add or update fighter image in the appropriate database"""
    
    # Determine which file to update
    if sport.lower() == "ufc":
        file = "fighters_ufc.json"
    else:
        file = "fighters.json"
    
    # Load existing database
    try:
        with open(file, 'r', encoding='utf-8') as f:
            fighters = json.load(f)
    except FileNotFoundError:
        fighters = {}
        print(f"⚠️  {file} not found, creating new database")
    
    # Check if fighter already exists
    if fighter_name in fighters:
        old_url = fighters[fighter_name]
        print(f"⚠️  {fighter_name} already exists in {file}")
        print(f"   Old: {old_url}")
        print(f"   New: {image_url}")
        confirm = input("   Overwrite? (y/n): ")
        if confirm.lower() != 'y':
            print("❌ Cancelled")
            return
    
    # Add fighter
    fighters[fighter_name] = image_url
    
    # Save database
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(fighters, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Added {fighter_name} to {file}")
    print(f"   Image: {image_url}")
    print(f"   Total fighters in {file}: {len(fighters)}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    fighter_name = sys.argv[1]
    image_url = sys.argv[2]
    sport = sys.argv[3] if len(sys.argv) > 3 else "boxing"
    
    add_fighter_image(fighter_name, image_url, sport)
