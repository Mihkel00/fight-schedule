"""
Manual Time Override Tool
Allows you to manually set accurate fight times for specific fights

Usage:
    python set_fight_time.py

Interactive mode:
    1. Shows upcoming fights without accurate times
    2. Lets you select a fight
    3. Enter the correct time in UK timezone
    4. Saves to time_overrides.json

Example flow:
    > python set_fight_time.py
    1. Carlos Canizales vs Thammanoon Niyomtrong - 2025-12-04 (Current: TBA)
    2. Jai Tapu Opetaia vs Huseyin Cinkara - 2025-12-06 (Current: TBA)
    
    Select fight number (or 'q' to quit): 1
    Enter correct time (HH:MM format, UK timezone): 21:00
    ✓ Time saved: Carlos Canizales vs Thammanoon Niyomtrong → 21:00 UK
"""

import json
from datetime import datetime

def load_cache():
    """Load fights from cache"""
    try:
        with open('fights_cache.json', 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            return cache_data.get('fights', [])
    except FileNotFoundError:
        print("❌ fights_cache.json not found. Run the app first.")
        return []

def load_time_overrides():
    """Load existing time overrides"""
    try:
        with open('time_overrides.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_time_overrides(overrides):
    """Save time overrides to file"""
    with open('time_overrides.json', 'w', encoding='utf-8') as f:
        json.dump(overrides, f, indent=2, ensure_ascii=False)

def get_fight_key(fight):
    """Generate unique key for a fight"""
    return f"{fight['fighter1']} vs {fight['fighter2']}|{fight['date']}"

def validate_time(time_str):
    """Validate time format (HH:MM)"""
    try:
        datetime.strptime(time_str, '%H:%M')
        return True
    except:
        return False

def show_fights_needing_times():
    """Display fights that need accurate times"""
    fights = load_cache()
    overrides = load_time_overrides()
    
    if not fights:
        return []
    
    # Filter to fights that need times (boxing without times or with TBA)
    needs_time = []
    for fight in fights:
        if fight['sport'] == 'Boxing':
            fight_key = get_fight_key(fight)
            current_time = overrides.get(fight_key, fight.get('time', ''))
            
            # Include if time is missing, TBA, or clearly wrong
            if not current_time or current_time == 'TBA' or len(current_time) < 4:
                needs_time.append(fight)
    
    return needs_time

def interactive_mode():
    """Interactive CLI for setting fight times"""
    print("\n" + "="*70)
    print("MANUAL FIGHT TIME OVERRIDE TOOL")
    print("="*70 + "\n")
    
    fights = show_fights_needing_times()
    
    if not fights:
        print("✓ All fights have times set!")
        return
    
    print(f"Found {len(fights)} fights needing accurate times:\n")
    
    # Display fights
    for i, fight in enumerate(fights, 1):
        current_time = fight.get('time', 'TBA')
        print(f"{i}. {fight['fighter1']} vs {fight['fighter2']}")
        print(f"   Date: {fight['date']}")
        print(f"   Venue: {fight['venue']}")
        print(f"   Current time: {current_time if current_time else 'TBA'}\n")
    
    overrides = load_time_overrides()
    
    while True:
        print("\n" + "-"*70)
        choice = input("Select fight number (or 'q' to quit, 'l' to list again): ").strip().lower()
        
        if choice == 'q':
            print("\n✓ Saved time overrides to time_overrides.json")
            print("  Run app.py to see updated times\n")
            break
        
        if choice == 'l':
            interactive_mode()
            return
        
        try:
            fight_idx = int(choice) - 1
            if fight_idx < 0 or fight_idx >= len(fights):
                print("❌ Invalid fight number")
                continue
        except ValueError:
            print("❌ Please enter a number")
            continue
        
        selected_fight = fights[fight_idx]
        
        print(f"\n📅 {selected_fight['fighter1']} vs {selected_fight['fighter2']}")
        print(f"   Date: {selected_fight['date']}")
        print(f"   Venue: {selected_fight['venue']}")
        
        # Get time input
        while True:
            time_input = input("\nEnter correct time (HH:MM format, UK timezone, or 'b' to go back): ").strip()
            
            if time_input.lower() == 'b':
                break
            
            if validate_time(time_input):
                fight_key = get_fight_key(selected_fight)
                overrides[fight_key] = time_input
                save_time_overrides(overrides)
                
                print(f"\n✓ Time saved: {selected_fight['fighter1']} vs {selected_fight['fighter2']} → {time_input} UK")
                
                # Remove from list
                fights.pop(fight_idx)
                
                if not fights:
                    print("\n✓ All fights now have times!")
                    print("  Saved to time_overrides.json\n")
                    return
                
                break
            else:
                print("❌ Invalid format. Use HH:MM (e.g., 21:00 or 03:30)")

def bulk_add_mode():
    """Add multiple times from a list"""
    print("\n" + "="*70)
    print("BULK TIME OVERRIDE MODE")
    print("="*70 + "\n")
    print("Format: Fighter1 vs Fighter2|YYYY-MM-DD|HH:MM")
    print("Example: Carlos Canizales vs Thammanoon Niyomtrong|2025-12-04|21:00\n")
    print("Enter fights (one per line, empty line to finish):\n")
    
    overrides = load_time_overrides()
    added = 0
    
    while True:
        line = input().strip()
        
        if not line:
            break
        
        try:
            # Parse: Fighter1 vs Fighter2|Date|Time
            parts = line.split('|')
            if len(parts) != 3:
                print(f"❌ Invalid format: {line}")
                continue
            
            matchup = parts[0].strip()
            date = parts[1].strip()
            time = parts[2].strip()
            
            if not validate_time(time):
                print(f"❌ Invalid time format: {time}")
                continue
            
            fight_key = f"{matchup}|{date}"
            overrides[fight_key] = time
            added += 1
            
            print(f"✓ Added: {matchup} → {time}")
            
        except Exception as e:
            print(f"❌ Error parsing line: {e}")
    
    if added > 0:
        save_time_overrides(overrides)
        print(f"\n✓ Saved {added} time override(s) to time_overrides.json\n")
    else:
        print("\n❌ No times added\n")

def view_overrides():
    """View all current time overrides"""
    overrides = load_time_overrides()
    
    if not overrides:
        print("\nNo time overrides set yet.\n")
        return
    
    print("\n" + "="*70)
    print("CURRENT TIME OVERRIDES")
    print("="*70 + "\n")
    
    for fight_key, time in sorted(overrides.items()):
        print(f"{fight_key} → {time} UK")
    
    print(f"\nTotal overrides: {len(overrides)}\n")

def main():
    """Main menu"""
    print("\n" + "="*70)
    print("FIGHT TIME OVERRIDE TOOL")
    print("="*70 + "\n")
    print("1. Interactive mode (set times one by one)")
    print("2. Bulk add mode (paste multiple times)")
    print("3. View current overrides")
    print("4. Quit\n")
    
    choice = input("Select option: ").strip()
    
    if choice == '1':
        interactive_mode()
    elif choice == '2':
        bulk_add_mode()
    elif choice == '3':
        view_overrides()
    elif choice == '4':
        print("\n✓ Goodbye!\n")
    else:
        print("❌ Invalid choice")
        main()

if __name__ == "__main__":
    main()
