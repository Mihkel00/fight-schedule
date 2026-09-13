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


def _parse_legacy(soup):
    """Pre-2026 boxingschedule.co layout: <p data-start> date headers followed by <ul> of bouts."""
    fights = []
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
    
    return fights


ET_ZONE = ZoneInfo('America/New_York')

_WC_PATTERN = r'(super [a-z]+weight|light [a-z]+weight|junior [a-z]+weight|heavyweight|middleweight|welterweight|lightweight|featherweight|bantamweight|flyweight|cruiserweight|minimumweight|strawweight)'


def _parse_bout_detail(detail):
    """'12-round bout, WBC welterweight championship held by Garcia' -> (rounds, weight_class)."""
    rounds_match = re.search(r'(\d+)[-\s]round', detail, re.IGNORECASE)
    rounds = rounds_match.group(1) if rounds_match else None
    is_title = bool(re.search(r'championship|\btitle\b|\bbelt\b', detail, re.IGNORECASE))
    weight_class = ''
    wc_match = re.search(_WC_PATTERN, detail, re.IGNORECASE)
    if wc_match:
        weight_class = wc_match.group(1).title()
        if is_title:
            weight_class = f"Title {weight_class}"
    return rounds, weight_class


def _split_vs(text):
    """'Ryan Garcia vs. Conor Benn' -> ('Ryan Garcia', 'Conor Benn') or None."""
    parts = re.split(r'\s+vs\.?\s+', text.strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    f1 = re.sub(r'\s+\d+$', '', parts[0].strip())
    f2 = re.sub(r'\s+\d+$', '', parts[1].strip())
    if not f1 or not f2:
        return None
    return f1, f2


def _parse_cards(soup):
    """2026+ boxingschedule.co layout: one <article class="rs-card"> per event."""
    fights = []
    for card in soup.select('article.rs-card'):
        try:
            # Date: ISO from <time datetime>, else parse the visible text
            event_date = None
            time_el = card.select_one('time[datetime]')
            if time_el and re.match(r'\d{4}-\d{2}-\d{2}', time_el.get('datetime', '')):
                event_date = time_el['datetime'][:10]
            elif time_el:
                try:
                    event_date = datetime.strptime(time_el.get_text(strip=True), '%A, %B %d, %Y').strftime('%Y-%m-%d')
                except ValueError:
                    pass
            if not event_date:
                continue
            date_obj = datetime.strptime(event_date, '%Y-%m-%d')

            venue_el = card.select_one('.rs-venue')
            venue = venue_el.get_text(strip=True) if venue_el else 'TBA'

            bc_el = card.select_one('.rs-broadcast')
            streaming = None
            if bc_el:
                bc = bc_el.get_text(' ', strip=True)
                bc = re.sub(r'^\s*live\s+on\s+', '', bc, flags=re.IGNORECASE).strip()
                if bc and 'unconfirmed' not in bc.lower():
                    streaming = bc

            # Start time: "7:00 pm ET / 12:00 am UK (Sun, Sep 13) · Estimated event start time"
            fight_date, fight_time, time_estimated = event_date, None, False
            t_el = card.select_one('.rs-time')
            t_text = t_el.get_text(' ', strip=True) if t_el else ''
            m = re.search(r'(\d{1,2}:\d{2})\s*([ap]m)\s*ET', t_text, re.IGNORECASE)
            if m:
                local = datetime.strptime(f"{m.group(1)} {m.group(2).upper()}", '%I:%M %p')
                et_dt = datetime(date_obj.year, date_obj.month, date_obj.day, local.hour, local.minute, tzinfo=ET_ZONE)
                utc_dt = et_dt.astimezone(UTC_ZONE)
                # Store the UTC date alongside the UTC time so client-side timezone
                # conversion (date + 'T' + time + 'Z') is exact, same as the UFC scraper.
                fight_date, fight_time = utc_dt.strftime('%Y-%m-%d'), utc_dt.strftime('%H:%M')
            else:
                est, was_est = estimate_time_from_venue(venue)
                if est:
                    fight_time, time_estimated = est, True

            bouts = []
            h3 = card.find('h3')
            if h3:
                pair = _split_vs(h3.get_text(' ', strip=True))
                if pair:
                    md = card.select_one('.rs-main-detail')
                    bouts.append((pair, md.get_text(' ', strip=True) if md else ''))
            for li in card.select('.rs-undercard li'):
                strong = li.find('strong')
                span = li.find('span')
                name_text = strong.get_text(' ', strip=True) if strong else li.get_text(' ', strip=True)
                pair = _split_vs(name_text)
                if pair:
                    bouts.append((pair, span.get_text(' ', strip=True) if span else ''))

            for idx, ((f1, f2), detail) in enumerate(bouts):
                rounds, weight_class = _parse_bout_detail(detail)
                fights.append({
                    'fighter1': f1,
                    'fighter2': f2,
                    'date': fight_date,
                    'time': fight_time or 'TBA',
                    'time_estimated': time_estimated if fight_time else False,
                    'venue': venue,
                    'location': venue,
                    'sport': 'Boxing',
                    'weight_class': weight_class,
                    'rounds': rounds,
                    'is_main_event': (idx == 0),
                    'streaming': streaming,
                })
        except Exception as e:
            print(f"Error parsing boxing card: {e}")
            continue
    return fights


def scrape_boxing_events():
    """
    Scrape boxing schedule from BoxingSchedule.co.

    Tries the current <article class="rs-card"> layout first and falls back to
    the legacy <p data-start> layout, so a redesign in either direction still
    yields data.

    Returns list of fight dicts:
        fighter1, fighter2, date (YYYY-MM-DD), time (HH:MM UTC or 'TBA'),
        time_estimated, venue, location, sport='Boxing', weight_class,
        rounds, is_main_event, streaming
    """
    try:
        print("Scraping BoxingSchedule.co...")
        response = requests.get("https://boxingschedule.co", headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if response.status_code != 200:
            print(f"BoxingSchedule.co error: Status {response.status_code}")
            return []
        soup = BeautifulSoup(response.content, 'html.parser')

        fights = _parse_cards(soup)
        layout = 'rs-card'
        if not fights:
            fights = _parse_legacy(soup)
            layout = 'legacy'
        if not fights:
            print(f"BoxingSchedule.co: 0 fights parsed — page is {len(response.content)} bytes, "
                  f"{len(soup.select('article.rs-card'))} rs-card articles, "
                  f"{len(soup.find_all('p', attrs={'data-start': True}))} legacy date paragraphs")
        else:
            print(f"BoxingSchedule.co Total: Found {len(fights)} fights via {layout} layout")
        return fights
    except Exception as e:
        print(f"Error in BoxingSchedule.co scraper: {e}")
        return []
        traceback.print_exc()
        return []
