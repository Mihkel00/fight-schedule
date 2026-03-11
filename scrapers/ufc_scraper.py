"""
UFC Event Scraper - MMA Fighting
Scrapes UFC fight schedules from mmafighting.com
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
import re

ET_ZONE = ZoneInfo('America/New_York')
UTC_ZONE = ZoneInfo('UTC')


def convert_et_to_utc(time_et_str, event_date=None):
    """Convert ET time to UTC, handling EST/EDT automatically via zoneinfo.

    Args:
        time_et_str: Time string like "10 p.m. ET" or "6:30 p.m. ET"
        event_date: Optional date string (YYYY-MM-DD) for accurate DST lookup.
                    Falls back to today if not provided.

    Returns:
        datetime (UTC, timezone-aware) or None. The date component may differ
        from event_date when the ET time crosses midnight into the next UTC day.
    """
    try:
        time_match = re.search(r'(\d+)(?::(\d+))?\s*(a\.m\.|p\.m\.)', time_et_str.lower())
        if not time_match:
            return None

        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        am_pm = time_match.group(3)

        # Convert to 24-hour format
        if am_pm == 'p.m.' and hour != 12:
            hour += 12
        elif am_pm == 'a.m.' and hour == 12:
            hour = 0

        # Use event date for accurate DST determination, fall back to today
        if event_date:
            try:
                ref_date = datetime.strptime(event_date, '%Y-%m-%d').date()
            except ValueError:
                ref_date = datetime.now(UTC_ZONE).date()
        else:
            ref_date = datetime.now(UTC_ZONE).date()

        # Build timezone-aware ET datetime, then convert to UTC
        et_dt = datetime(ref_date.year, ref_date.month, ref_date.day,
                         hour, minute, tzinfo=ET_ZONE)
        return et_dt.astimezone(UTC_ZONE)
    except Exception:
        return None


def scrape_ufc_events():
    """
    Scrape UFC schedule from MMA Fighting
    
    Returns:
        list: List of fight dictionaries with standardized format:
            {
                'fighter1': str,
                'fighter2': str,
                'date': str (YYYY-MM-DD),
                'time': str (HH:MM UTC) or None,
                'venue': str,
                'location': str,
                'sport': 'UFC',
                'event_name': str,
                'weight_class': str,
                'card_type': 'Main Card' or 'Prelims'
            }
    """
    fights = []
    
    try:
        print("Scraping MMA Fighting schedule...")
        
        url = "https://www.mmafighting.com/schedule"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all event dates
        event_dates = soup.find_all('h1', class_='_5ae48f1')
        
        for date_elem in event_dates:
            date_text = date_elem.get_text(strip=True)
            
            # Parse date
            try:
                date_obj = datetime.strptime(date_text, "%B %d, %Y")
                date_formatted = date_obj.strftime("%Y-%m-%d")
            except:
                continue
            
            current = date_elem.parent.parent
            event_containers = current.find_next_siblings('div', class_='duet--layout--page-header')
            
            for event_container in event_containers:
                if not event_container.find('a', class_='_5ae48f6'):
                    continue
                
                # Extract event details
                event_link = event_container.find('a', class_='_5ae48f6')
                event_name = event_link.get_text(strip=True) if event_link else ''
                
                # Only include UFC events
                if 'UFC' not in event_name:
                    continue
                
                event_details = event_container.find('p', class_='ls9zuh3')
                details_text = event_details.get_text(strip=True) if event_details else ''
                
                venue = details_text.split('•')[0].strip() if '•' in details_text else ''
                
                # Extract times — convert_et_to_utc returns a UTC datetime so the
                # date is also correct when ET crosses midnight into the next UTC day.
                main_card_utc_dt = None
                if 'main card' in details_text.lower():
                    main_card_match = re.search(r'main card.*?(\d+(?::\d+)?\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                    if main_card_match:
                        main_card_utc_dt = convert_et_to_utc(main_card_match.group(1), event_date=date_formatted)

                prelim_utc_dt = None
                if 'prelim' in details_text.lower() and 'early' not in details_text.lower():
                    prelim_match = re.search(r'prelim(?:s|inary card)?.*?(\d+(?::\d+)?\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                    if prelim_match:
                        prelim_utc_dt = convert_et_to_utc(prelim_match.group(1), event_date=date_formatted)

                # Helper to extract (date_str, time_str) from a UTC datetime
                def fmt(utc_dt):
                    if utc_dt is None:
                        return date_formatted, None
                    return utc_dt.strftime('%Y-%m-%d'), utc_dt.strftime('%H:%M')
                
                print(f"MMA Fighting: {event_name} - {date_formatted}")
                
                # Find fight sections
                fight_sections_container = event_container.find_next_sibling('div', class_='_5ae48f5')
                
                if not fight_sections_container:
                    continue
                
                # Process Main Card
                main_card_section = fight_sections_container.find('h1', string=re.compile('Main Card', re.IGNORECASE))
                if main_card_section:
                    fight_cards = main_card_section.parent.parent.find_next_sibling('div')
                    if fight_cards:
                        for fight_card in fight_cards.find_all('div', class_='_5vdhue0'):
                            is_title = fight_card.find('span', class_='_153sp3o2') is not None
                            
                            fight_link = fight_card.find('a', class_='_1ngvuhm0')
                            if fight_link:
                                fight_text = fight_link.get_text(strip=True)
                                fighters = fight_text.split(' vs ')
                                
                                if len(fighters) == 2:
                                    # Clean fighter names (remove trailing numbers like "Lopes 2")
                                    fighter1 = re.sub(r'\s+\d+$', '', fighters[0].strip())
                                    fighter2 = re.sub(r'\s+\d+$', '', fighters[1].strip())

                                    main_date, main_time = fmt(main_card_utc_dt)
                                    fights.append({
                                        'fighter1': fighter1,
                                        'fighter2': fighter2,
                                        'date': main_date,
                                        'time': main_time,
                                        'venue': venue,
                                        'location': venue,
                                        'sport': 'UFC',
                                        'event_name': event_name,
                                        'weight_class': 'Title' if is_title else '',
                                        'card_type': 'Main Card'
                                    })
                
                # Process Preliminary Card
                prelim_section = fight_sections_container.find('h1', string=re.compile('Preliminary Card', re.IGNORECASE))
                if prelim_section:
                    fight_cards = prelim_section.parent.parent.find_next_sibling('div')
                    if fight_cards:
                        for fight_card in fight_cards.find_all('div', class_='_5vdhue0'):
                            fight_link = fight_card.find('a', class_='_1ngvuhm0')
                            if fight_link:
                                fight_text = fight_link.get_text(strip=True)
                                fighters = fight_text.split(' vs ')
                                
                                if len(fighters) == 2:
                                    # Clean fighter names (remove trailing numbers)
                                    fighter1 = re.sub(r'\s+\d+$', '', fighters[0].strip())
                                    fighter2 = re.sub(r'\s+\d+$', '', fighters[1].strip())

                                    # Determine prelim UTC datetime: scraped or estimated (-2h from main card)
                                    resolved_prelim_utc_dt = prelim_utc_dt
                                    if not resolved_prelim_utc_dt and main_card_utc_dt:
                                        from datetime import timedelta
                                        resolved_prelim_utc_dt = main_card_utc_dt - timedelta(hours=2)

                                    prelim_date, prelim_time = fmt(resolved_prelim_utc_dt)
                                    fights.append({
                                        'fighter1': fighter1,
                                        'fighter2': fighter2,
                                        'date': prelim_date,
                                        'time': prelim_time,
                                        'venue': venue,
                                        'location': venue,
                                        'sport': 'UFC',
                                        'event_name': event_name,
                                        'weight_class': '',
                                        'card_type': 'Prelims'
                                    })
        
        print(f"MMA Fighting: Found {len(fights)} UFC fights")
        
    except Exception as e:
        print(f"Error scraping MMA Fighting: {e}")
    
    return fights
