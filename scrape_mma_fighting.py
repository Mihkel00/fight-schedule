"""
Scrape UFC schedule from MMA Fighting
- Complete cards (main card + prelims + early prelims)
- Accurate event times in ET (converted to UK)
- Title fight indicators
- All fighter matchups

Usage: python scrape_mma_fighting.py
Output: ufc_schedule.json
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import re
import time

def convert_et_to_uk(time_et_str):
    """Convert ET time to UK time
    ET is GMT-5, UK is GMT (or GMT+1 in summer, but we'll use GMT for simplicity)
    """
    try:
        # Extract time from string like "10 p.m. ET" or "8 p.m. ET"
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
        
        # Format as HH:MM
        return f"{uk_hour:02d}:00"
        
    except:
        return None

def scrape_mma_fighting():
    """Scrape MMA Fighting schedule page"""
    
    url = "https://www.mmafighting.com/schedule"
    
    print("Scraping MMA Fighting schedule...")
    print(f"URL: {url}\n")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching page: {e}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    fights = []
    
    # Find all event sections
    # Each event has date, event info, and fight cards
    event_dates = soup.find_all('h1', class_='_5ae48f1')  # Date headers
    
    for date_elem in event_dates:
        date_text = date_elem.get_text(strip=True)
        
        # Parse date (e.g., "December 7, 2025")
        try:
            date_obj = datetime.strptime(date_text, "%B %d, %Y")
            date_formatted = date_obj.strftime("%Y-%m-%d")
        except:
            continue
        
        # Find all events on this date
        # Events are in divs after the date header
        current = date_elem.parent.parent
        
        # Find event details
        event_containers = current.find_next_siblings('div', class_='duet--layout--page-header')
        
        for event_container in event_containers:
            # Check if this is an event header (not a section header)
            if not event_container.find('a', class_='_5ae48f6'):
                continue
            
            # Extract event name and details
            event_link = event_container.find('a', class_='_5ae48f6')
            event_name = event_link.get_text(strip=True) if event_link else ''
            
            # Extract venue and time info
            event_details = event_container.find('p', class_='ls9zuh3')
            details_text = event_details.get_text(strip=True) if event_details else ''
            
            # Parse venue (text before •)
            venue = details_text.split('•')[0].strip() if '•' in details_text else ''
            
            # Extract main card time
            main_card_time = None
            if 'main card' in details_text.lower():
                main_card_match = re.search(r'main card.*?(\d+\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                if main_card_match:
                    main_card_time = convert_et_to_uk(main_card_match.group(1))
            
            # Extract prelim time
            prelim_time = None
            if 'prelim' in details_text.lower() and 'early' not in details_text.lower():
                prelim_match = re.search(r'prelim(?:s|inary card)?.*?(\d+\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                if prelim_match:
                    prelim_time = convert_et_to_uk(prelim_match.group(1))
            
            # Only include UFC events
            if 'UFC' not in event_name:
                continue
            
            print(f"\n=== {event_name} ===")
            print(f"Date: {date_formatted}")
            print(f"Venue: {venue}")
            print(f"Main card time (UK): {main_card_time}")
            
            # Find fight sections (Main Card, Preliminary Card)
            fight_sections_container = event_container.find_next_sibling('div', class_='_5ae48f5')
            
            if not fight_sections_container:
                continue
            
            # Process Main Card
            main_card_section = fight_sections_container.find('h1', string=re.compile('Main Card', re.IGNORECASE))
            if main_card_section:
                fight_cards = main_card_section.parent.parent.find_next_sibling('div')
                if fight_cards:
                    for fight_card in fight_cards.find_all('div', class_='_5vdhue0'):
                        # Check if title fight
                        is_title = fight_card.find('span', class_='_153sp3o2') is not None
                        
                        # Extract fighters
                        fight_link = fight_card.find('a', class_='_1ngvuhm0')
                        if fight_link:
                            fight_text = fight_link.get_text(strip=True)
                            fighters = fight_text.split(' vs ')
                            
                            if len(fighters) == 2:
                                fight_data = {
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
                                }
                                fights.append(fight_data)
                                
                                title_indicator = " [TITLE]" if is_title else ""
                                print(f"  Main Card: {fighters[0]} vs {fighters[1]}{title_indicator}")
            
            # Process Preliminary Card
            prelim_section = fight_sections_container.find('h1', string=re.compile('Preliminary Card', re.IGNORECASE))
            if prelim_section:
                fight_cards = prelim_section.parent.parent.find_next_sibling('div')
                if fight_cards:
                    for fight_card in fight_cards.find_all('div', class_='_5vdhue0'):
                        # Extract fighters
                        fight_link = fight_card.find('a', class_='_1ngvuhm0')
                        if fight_link:
                            fight_text = fight_link.get_text(strip=True)
                            fighters = fight_text.split(' vs ')
                            
                            if len(fighters) == 2:
                                fight_data = {
                                    'fighter1': fighters[0].strip(),
                                    'fighter2': fighters[1].strip(),
                                    'date': date_formatted,
                                    'time': prelim_time or main_card_time,  # Use prelim time if available
                                    'venue': venue,
                                    'location': venue,
                                    'sport': 'UFC',
                                    'event_name': event_name,
                                    'weight_class': '',
                                    'card_type': 'Prelims'
                                }
                                fights.append(fight_data)
                                
                                print(f"  Prelims: {fighters[0]} vs {fighters[1]}")
    
    print(f"\n\n=== SCRAPING COMPLETE ===")
    print(f"Total UFC fights found: {len(fights)}")
    print(f"Main card fights: {len([f for f in fights if f['card_type'] == 'Main Card'])}")
    print(f"Prelim fights: {len([f for f in fights if f['card_type'] == 'Prelims'])}")
    print(f"Title fights: {len([f for f in fights if 'Title' in f.get('weight_class', '')])}")
    
    return fights

if __name__ == "__main__":
    fights = scrape_mma_fighting()
    
    # Save to JSON
    if fights:
        with open('ufc_schedule.json', 'w', encoding='utf-8') as f:
            json.dump(fights, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Saved {len(fights)} UFC fights to ufc_schedule.json")
    else:
        print("\n❌ No fights found")
