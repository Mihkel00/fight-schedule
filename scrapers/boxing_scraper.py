"""
Boxing Event Scraper - BoxingSchedule.co
Scrapes boxing fight schedules from boxingschedule.co
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
import re

UK_ZONE = ZoneInfo('Europe/London')
UTC_ZONE = ZoneInfo('UTC')

# Regional default main card start times (UTC) based on typical boxing broadcast schedules
# These are used as fallbacks when the scraper can't extract a specific time
REGIONAL_DEFAULT_TIMES_UTC = {
    'US': '02:00',       # ~9 PM ET / 6 PM PT
    'USA': '02:00',
    'UK': '22:00',       # ~10 PM GMT
    'England': '22:00',
    'Scotland': '22:00',
    'Wales': '22:00',
    'Ireland': '22:00',
    'Japan': '10:00',    # ~7 PM JST
    'Australia': '10:00', # ~8 PM AEST
    'Mexico': '03:00',   # ~9 PM CT
    'Germany': '21:00',  # ~10 PM CET
    'France': '21:00',
    'Italy': '21:00',
    'Spain': '21:00',
    'Monaco': '21:00',
    'UAE': '17:00',      # ~9 PM GST
    'Saudi Arabia': '17:00',
    'Puerto Rico': '01:00',  # ~9 PM AST
    'Canada': '02:00',
    'South Africa': '19:00', # ~9 PM SAST
    'Philippines': '12:00',  # ~8 PM PHT
    'Thailand': '13:00',     # ~8 PM ICT
    'China': '12:00',        # ~8 PM CST
}


def estimate_time_from_venue(venue_text):
    """
    Estimate a UTC start time based on the venue/location country or region.
    Returns (time_str, True) if estimated, or (None, False) if can't estimate.
    """
    if not venue_text:
        return None, False

    for region, utc_time in REGIONAL_DEFAULT_TIMES_UTC.items():
        # Use word boundary matching to avoid partial matches (e.g., "US" in "AMUS")
        if re.search(r'\b' + re.escape(region) + r'\b', venue_text, re.IGNORECASE):
            return utc_time, True

    # Check for US state abbreviations and city patterns
    us_state_pattern = r',\s*[A-Z]{2}\s*$|,\s*(California|Texas|New York|Florida|Nevada|Arizona|Georgia|Ohio|Pennsylvania|Illinois|Massachusetts|Connecticut|New Jersey|Louisiana|Missouri|Alabama|Tennessee|Colorado|Michigan|Minnesota|Wisconsin|Indiana|Maryland|Virginia|North Carolina|South Carolina|Oklahoma|Oregon|Washington|Kentucky|Iowa|Arkansas|Mississippi|Kansas|Nebraska|Utah|Hawaii|Idaho|Montana|Wyoming|Maine|Vermont|New Hampshire|Rhode Island|Delaware|West Virginia|New Mexico|Alaska|South Dakota|North Dakota)'
    if re.search(us_state_pattern, venue_text, re.IGNORECASE):
        return '02:00', True

    return None, False


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
                'time_estimated': bool (True if time was estimated from venue region),
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
            
            # Extract time using multiple regex patterns (site format varies)
            current_uk_time = None
            time_is_estimated = False

            # Try multiple time patterns in priority order
            time_patterns = [
                # "UK London: 10:00 PM" or "UK London: 2:30 AM"
                (r'UK\s*(?:London)?[:\s]+(\d{1,2}:\d{2}\s*[AP]M)', 'uk'),
                # "🇬🇧 10:00 PM" or flag followed by time
                (r'🇬🇧\s*(\d{1,2}:\d{2}\s*[AP]M)', 'uk'),
                # "Time: 10:00 PM" or "Start: 10:00 PM"
                (r'(?:Time|Start)[:\s]+(\d{1,2}:\d{2}\s*[AP]M)', 'uk'),
                # "ET: 5:00 PM" or "EST: 5:00 PM" - US Eastern
                (r'(?:ET|EST|Eastern)[:\s]+(\d{1,2}:\d{2}\s*[AP]M)', 'et'),
                # "PT: 2:00 PM" or "PST: 2:00 PM" - US Pacific
                (r'(?:PT|PST|Pacific)[:\s]+(\d{1,2}:\d{2}\s*[AP]M)', 'pt'),
                # "CT: 4:00 PM" or "CST: 4:00 PM" - US Central
                (r'(?:CT|CST|Central)[:\s]+(\d{1,2}:\d{2}\s*[AP]M)', 'ct'),
                # Bare time at end like "| 10:00 PM" or "– 10:00 PM"
                (r'[|–—-]\s*(\d{1,2}:\d{2}\s*[AP]M)', 'uk'),
                # Any standalone 12-hour time as last resort
                (r'(\d{1,2}:\d{2}\s*[AP]M)', 'uk'),
            ]

            tz_map = {
                'uk': UK_ZONE,
                'et': ZoneInfo('America/New_York'),
                'pt': ZoneInfo('America/Los_Angeles'),
                'ct': ZoneInfo('America/Chicago'),
            }

            for pattern, tz_key in time_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_str = match.group(1).strip()
                    try:
                        time_obj = datetime.strptime(time_str, "%I:%M %p")
                        local_tz = tz_map[tz_key]
                        local_dt = datetime(date_obj.year, date_obj.month, date_obj.day,
                                            time_obj.hour, time_obj.minute, tzinfo=local_tz)
                        utc_dt = local_dt.astimezone(UTC_ZONE)
                        current_uk_time = utc_dt.strftime("%H:%M")
                        print(f"  Time extracted via pattern '{pattern}': {time_str} -> {current_uk_time} UTC")
                        break
                    except Exception:
                        continue

            # Fallback: estimate time from venue/location region
            if not current_uk_time:
                estimated_time, was_estimated = estimate_time_from_venue(current_venue)
                if estimated_time:
                    current_uk_time = estimated_time
                    time_is_estimated = True
                    print(f"  Time estimated from venue '{current_venue}': ~{estimated_time} UTC")
            
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
                        'time_estimated': time_is_estimated if current_uk_time else False,
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
