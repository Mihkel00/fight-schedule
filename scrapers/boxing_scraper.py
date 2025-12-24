"""
Boxing Event Scraper - BoxingSchedule.co
Scrapes boxing fight schedules from boxingschedule.co
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re


def scrape_boxing_events():
    """
    Scrape boxing schedule from BoxingSchedule.co
    
    Returns:
        list: List of fight dictionaries with standardized format:
            {
                'fighter1': str,
                'fighter2': str,
                'date': str (YYYY-MM-DD),
                'time': str (HH:MM UTC) or 'TBA',
                'venue': str,
                'location': str,
                'sport': 'Boxing',
                'weight_class': str,
                'rounds': str or None,
                'is_main_event': bool,
                'streaming': str or None
            }
    """
    fights = []
    
    try:
        print("Scraping BoxingSchedule.co...")
        
        url = "https://boxingschedule.co"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"BoxingSchedule.co error: Status {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all paragraphs with data-start (these are date headers)
        date_paragraphs = soup.find_all('p', attrs={'data-start': True})
        
        for para in date_paragraphs:
            strong = para.find('strong')
            if not strong:
                continue
                
            text = strong.get_text(strip=True)
            
            # Check if this is a date header (starts with 📅)
            if not text.startswith('📅'):
                continue
            
            # Parse date
            date_match = re.search(r'📅\s+([A-Za-z]+\s+\d+)', text)
            if not date_match:
                continue
                
            date_str = date_match.group(1)
            year = datetime.now().year
            try:
                # Parse date with current year first
                date_obj = datetime.strptime(f"{date_str} {year}", "%B %d %Y")
                
                # If parsed date is more than 60 days in the past, assume it's next year
                # This handles December → January rollover
                if (datetime.now() - date_obj).days > 60:
                    year += 1
                    date_obj = datetime.strptime(f"{date_str} {year}", "%B %d %Y")
                
                current_date = date_obj.strftime("%Y-%m-%d")
            except:
                continue
            
            # Extract venue
            venue_match = re.search(r':\s+([^|]+)', text)
            current_venue = venue_match.group(1).strip() if venue_match else 'TBA'
            
            # Extract UK time
            uk_time_match = re.search(r'UK London:\s+(\d+:\d+\s+[AP]M)', text)
            current_uk_time = None
            if uk_time_match:
                uk_time_str = uk_time_match.group(1)
                try:
                    time_obj = datetime.strptime(uk_time_str, "%I:%M %p")
                    current_uk_time = time_obj.strftime("%H:%M")
                except:
                    pass
            
            # Extract streaming
            streaming_match = re.search(r'live on ([^🇺]+)', text)
            current_streaming = streaming_match.group(1).strip() if streaming_match else None
            
            # Find next ul sibling
            next_ul = para.find_next_sibling('ul')
            if not next_ul:
                continue
            
            # Parse fights
            fight_items = next_ul.find_all('li')
            
            for idx, li in enumerate(fight_items):
                try:
                    fight_text = li.get_text(strip=True)
                    
                    if ' vs. ' not in fight_text and ' vs ' not in fight_text:
                        continue
                    
                    # Split fighters
                    vs_split = fight_text.replace(' vs. ', ' vs ').split(' vs ')
                    if len(vs_split) < 2:
                        continue
                    
                    # Clean fighter names (remove trailing numbers)
                    fighter1 = re.sub(r'\s+\d+$', '', vs_split[0].strip())
                    rest = vs_split[1]
                    
                    # Extract fighter2 (before first comma)
                    if ',' in rest:
                        fighter2 = rest.split(',')[0].strip()
                        details = ','.join(rest.split(',')[1:])
                    else:
                        fighter2 = rest.strip()
                        details = ''
                    
                    # Parse rounds
                    rounds_match = re.search(r'(\d+)\s+rds?', details)
                    rounds = rounds_match.group(1) if rounds_match else None
                    
                    # Check if title
                    is_title = 'title' in details.lower()
                    
                    # Parse weight class
                    weight_class = ''
                    wc_pattern = r'(heavyweight|middleweight|welterweight|lightweight|featherweight|bantamweight|flyweight|cruiserweight|super [a-z]+|light [a-z]+|junior [a-z]+)'
                    wc_match = re.search(wc_pattern, details, re.IGNORECASE)
                    if wc_match:
                        weight_class = wc_match.group(1).title()
                        if is_title:
                            weight_class = f"Title {weight_class}"
                    
                    fight_data = {
                        'fighter1': fighter1,
                        'fighter2': fighter2,
                        'date': current_date,
                        'time': current_uk_time or 'TBA',
                        'venue': current_venue,
                        'location': current_venue,
                        'sport': 'Boxing',
                        'weight_class': weight_class,
                        'rounds': rounds,
                        'is_main_event': (idx == 0),
                        'streaming': current_streaming
                    }
                    
                    fights.append(fight_data)
                    print(f"BoxingSchedule.co: Added {fighter1} vs {fighter2} ({current_date}) {'[MAIN]' if idx == 0 else ''}")
                
                except Exception as e:
                    print(f"Error parsing fight: {e}")
                    continue
        
        print(f"BoxingSchedule.co Total: Found {len(fights)} fights")
        return fights
        
    except Exception as e:
        print(f"Error in BoxingSchedule.co scraper: {e}")
        import traceback
        traceback.print_exc()
        return []
