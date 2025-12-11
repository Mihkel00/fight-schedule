"""
UFC Event Scraper - MMA Fighting
Scrapes UFC fight schedules from mmafighting.com
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re


def convert_et_to_utc(time_et_str):
    """Convert ET time to UTC (ET is UTC-5 in EST, UTC-4 in EDT)"""
    try:
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
        
        # ET is typically UTC-5 (EST) or UTC-4 (EDT)
        # For simplicity, using EST (UTC-5). Add 5 hours to get UTC
        utc_hour = (hour + 5) % 24
        
        return f"{utc_hour:02d}:00"
    except:
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
                
                # Extract times
                main_card_time = None
                if 'main card' in details_text.lower():
                    main_card_match = re.search(r'main card.*?(\d+\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                    if main_card_match:
                        main_card_time = convert_et_to_utc(main_card_match.group(1))
                
                prelim_time = None
                if 'prelim' in details_text.lower() and 'early' not in details_text.lower():
                    prelim_match = re.search(r'prelim(?:s|inary card)?.*?(\d+\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                    if prelim_match:
                        prelim_time = convert_et_to_utc(prelim_match.group(1))
                
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
                                    fights.append({
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
                                    # Calculate prelim time if not found (2 hours before main card)
                                    calculated_prelim_time = prelim_time
                                    if not prelim_time and main_card_time:
                                        try:
                                            main_hour = int(main_card_time.split(':')[0])
                                            prelim_hour = (main_hour - 2) % 24
                                            calculated_prelim_time = f"{prelim_hour:02d}:00"
                                        except:
                                            calculated_prelim_time = main_card_time
                                    
                                    fights.append({
                                        'fighter1': fighters[0].strip(),
                                        'fighter2': fighters[1].strip(),
                                        'date': date_formatted,
                                        'time': calculated_prelim_time or main_card_time,
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
