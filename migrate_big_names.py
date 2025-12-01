"""
Migrate Big-Name Fighters from app.py to JSON

Run this once to convert the hardcoded list in app.py
to the JSON format used by the admin panel.
"""

import json
import os

# Your current big-name fighters from app.py (lines 49-113)
BIG_NAME_FIGHTERS = [
    # Top-ranked boxers
    'Naoya Inoue',
    'Terence Crawford',
    'Junto Nakatani',
    'Jaron Ennis',
    'Saul Alvarez',
    'Canelo Alvarez',
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

def migrate():
    """Convert list to JSON format"""
    
    # Create data directory
    os.makedirs('data', exist_ok=True)
    
    # Convert to JSON format
    json_data = []
    for name in BIG_NAME_FIGHTERS:
        # Categorize by name
        if name in ['Jake Paul', 'Logan Paul', 'Tommy Fury', 'KSI']:
            category = 'Celebrity'
        elif name in ['Tyson Fury', 'Anthony Joshua', 'Manny Pacquiao']:
            category = 'Legend'
        else:
            category = 'Champion'
        
        json_data.append({
            'name': name,
            'sport': 'Boxing',
            'notes': category
        })
    
    # Save to file
    filepath = 'data/big_name_fighters.json'
    with open(filepath, 'w') as f:
        json.dump(json_data, f, indent=2)
    
    print(f"[OK] Migrated {len(json_data)} fighters to {filepath}")
    print("\nNext steps:")
    print("1. Update app.py to use BigNameFighter model")
    print("2. Remove hardcoded BIG_NAME_FIGHTERS list from app.py (lines 49-113)")
    print("3. Update is_big_name_fight() function")
    print("\nSee FLASK_ADMIN_SETUP.md for details")

if __name__ == '__main__':
    migrate()
