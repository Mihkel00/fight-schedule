"""
UFC Event Scraper
Primary: ESPN MMA API (stable JSON)
Fallback: mmafighting.com HTML scraping
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

ET_ZONE = ZoneInfo('America/New_York')
UTC_ZONE = ZoneInfo('UTC')

_ESPN_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


def convert_et_to_utc(time_et_str, event_date=None):
    """Convert ET time string (e.g. '10 p.m. ET') to UTC datetime."""
    try:
        time_match = re.search(r'(\d+)(?::(\d+))?\s*(a\.m\.|p\.m\.)', time_et_str.lower())
        if not time_match:
            return None

        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        am_pm = time_match.group(3)

        if am_pm == 'p.m.' and hour != 12:
            hour += 12
        elif am_pm == 'a.m.' and hour == 12:
            hour = 0

        if event_date:
            try:
                ref_date = datetime.strptime(event_date, '%Y-%m-%d').date()
            except ValueError:
                ref_date = datetime.now(UTC_ZONE).date()
        else:
            ref_date = datetime.now(UTC_ZONE).date()

        et_dt = datetime(ref_date.year, ref_date.month, ref_date.day,
                         hour, minute, tzinfo=ET_ZONE)
        return et_dt.astimezone(UTC_ZONE)
    except Exception:
        return None


def _parse_iso(dt_str):
    """Parse ISO 8601 datetime string to UTC-aware datetime, or None."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00')).astimezone(UTC_ZONE)
    except Exception:
        return None


def _venue_parts(venue_obj):
    """Return (venue_name, location) from an ESPN venue dict."""
    if not venue_obj:
        return '', ''
    name = venue_obj.get('fullName', venue_obj.get('name', ''))
    addr = venue_obj.get('address', {})
    city = addr.get('city', '')
    state = addr.get('state', addr.get('country', ''))
    location = ', '.join(p for p in [city, state] if p)
    return name, location


def _card_type(comp):
    """Guess 'Main Card' or 'Prelims' from a competition dict."""
    text = (comp.get('type') or {}).get('text', '')
    if not text:
        text = (comp.get('type') or {}).get('description', '')
    tl = text.lower()
    if 'prelim' in tl or 'early' in tl:
        return 'Prelims'
    return 'Main Card'


def _fetch_espn_event_fights(event_id, event_name, fallback_date, fallback_venue, fallback_location):
    """Fetch individual fights for a UFC event from ESPN."""
    fights = []
    try:
        resp = requests.get(
            f'https://site.api.espn.com/apis/site/v2/sports/mma/ufc/event/{event_id}',
            headers={'User-Agent': _ESPN_UA},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ESPN event detail error for {event_id}: {e}")
        return fights

    competitions = data.get('competitions', [])
    if not competitions:
        competitions = data.get('events', [{}])[0].get('competitions', []) if data.get('events') else []

    for comp in competitions:
        comp_dt = _parse_iso(comp.get('date', ''))
        comp_date = comp_dt.strftime('%Y-%m-%d') if comp_dt else fallback_date
        comp_time = comp_dt.strftime('%H:%M') if comp_dt else None

        venue_obj = comp.get('venue')
        venue_name, location = _venue_parts(venue_obj)
        if not venue_name:
            venue_name, location = fallback_venue, fallback_location

        card_type = _card_type(comp)

        competitors = comp.get('competitors', [])
        if len(competitors) < 2:
            continue

        def get_name(c):
            ath = c.get('athlete', {})
            return ath.get('displayName', ath.get('shortName', ''))

        f1 = get_name(competitors[0])
        f2 = get_name(competitors[1])
        if not f1 or not f2:
            continue

        weight_class = ''
        for c in competitors:
            wc = c.get('athlete', {}).get('weightClass', {})
            if isinstance(wc, dict):
                weight_class = wc.get('text', '')
            elif isinstance(wc, str):
                weight_class = wc
            if weight_class:
                break

        fights.append({
            'fighter1': f1,
            'fighter2': f2,
            'date': comp_date,
            'time': comp_time,
            'venue': venue_name,
            'location': location or venue_name,
            'sport': 'UFC',
            'event_name': event_name,
            'weight_class': weight_class,
            'card_type': card_type,
        })

    return fights


def _scrape_espn():
    """Fetch UFC schedule from ESPN API. Returns list of fight dicts."""
    all_fights = []
    now = datetime.now(UTC_ZONE)

    # Fetch current month + next 5 months
    months = []
    for i in range(6):
        total_months = now.month - 1 + i
        y = now.year + total_months // 12
        m = total_months % 12 + 1
        months.append(f'{y}{m:02d}')

    events_seen = set()

    for month in months:
        try:
            resp = requests.get(
                'https://site.api.espn.com/apis/site/v2/sports/mma/ufc/schedule',
                params={'dates': month},
                headers={'User-Agent': _ESPN_UA},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"ESPN schedule error for {month}: {e}")
            continue

        events = data.get('events', [])

        for event in events:
            event_id = str(event.get('id', ''))
            if event_id in events_seen:
                continue
            events_seen.add(event_id)

            event_name = event.get('name', event.get('shortName', ''))
            if 'UFC' not in event_name.upper():
                continue

            # Event-level date
            event_dt = _parse_iso(event.get('date', ''))
            fallback_date = event_dt.strftime('%Y-%m-%d') if event_dt else f'{month[:4]}-{month[4:]}-01'

            # Venue from first competition or event level
            comps = event.get('competitions', [])
            first_comp = comps[0] if comps else {}
            venue_obj = first_comp.get('venue') or event.get('venue') or {}
            fallback_venue, fallback_location = _venue_parts(venue_obj)

            print(f"ESPN: {event_name} — {fallback_date}")

            # If the event already has competitions with competitors, use them directly
            inline_fights = []
            for comp in comps:
                competitors = comp.get('competitors', [])
                if len(competitors) >= 2:
                    comp_dt = _parse_iso(comp.get('date', ''))
                    comp_date = comp_dt.strftime('%Y-%m-%d') if comp_dt else fallback_date
                    comp_time = comp_dt.strftime('%H:%M') if comp_dt else None

                    v_obj = comp.get('venue') or venue_obj
                    v_name, v_loc = _venue_parts(v_obj)
                    if not v_name:
                        v_name, v_loc = fallback_venue, fallback_location

                    card_type = _card_type(comp)

                    def get_name(c):
                        ath = c.get('athlete', {})
                        return ath.get('displayName', ath.get('shortName', ''))

                    f1 = get_name(competitors[0])
                    f2 = get_name(competitors[1])
                    if not f1 or not f2:
                        continue

                    weight_class = ''
                    for c in competitors:
                        wc = c.get('athlete', {}).get('weightClass', {})
                        if isinstance(wc, dict):
                            weight_class = wc.get('text', '')
                        elif isinstance(wc, str):
                            weight_class = wc
                        if weight_class:
                            break

                    inline_fights.append({
                        'fighter1': f1,
                        'fighter2': f2,
                        'date': comp_date,
                        'time': comp_time,
                        'venue': v_name,
                        'location': v_loc or v_name,
                        'sport': 'UFC',
                        'event_name': event_name,
                        'weight_class': weight_class,
                        'card_type': card_type,
                    })

            if inline_fights:
                all_fights.extend(inline_fights)
            elif event_id:
                # Fetch full fight card via event detail endpoint
                detail_fights = _fetch_espn_event_fights(
                    event_id, event_name, fallback_date, fallback_venue, fallback_location
                )
                all_fights.extend(detail_fights)

    # Deduplicate by (fighter1, fighter2, date) — ESPN can return the same
    # event across multiple monthly queries with different IDs.
    seen_fights = set()
    unique_fights = []
    for f in all_fights:
        key = (f['fighter1'].lower(), f['fighter2'].lower(), f['date'])
        if key not in seen_fights:
            seen_fights.add(key)
            unique_fights.append(f)

    print(f"ESPN API: Found {len(unique_fights)} UFC fights ({len(all_fights) - len(unique_fights)} dupes removed)")
    return unique_fights


def _scrape_mmafighting():
    """Fallback: scrape UFC schedule from mmafighting.com (brittle HTML)."""
    fights = []

    try:
        print("Fallback: scraping mmafighting.com...")
        resp = requests.get(
            'https://www.mmafighting.com/schedule',
            headers={'User-Agent': _ESPN_UA},
            timeout=10,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Try a few known class patterns; site uses CSS-in-JS so these may change
        date_elems = (
            soup.find_all('h1', class_='_5ae48f1') or
            soup.find_all('h2', class_=re.compile(r'schedule.*date', re.I)) or
            soup.find_all('h1', class_=re.compile(r'_[0-9a-f]+'))
        )

        for date_elem in date_elems:
            date_text = date_elem.get_text(strip=True)
            try:
                date_obj = datetime.strptime(date_text, '%B %d, %Y')
                date_formatted = date_obj.strftime('%Y-%m-%d')
            except Exception:
                continue

            current = date_elem.parent.parent
            event_containers = current.find_next_siblings('div', class_='duet--layout--page-header')

            for ec in event_containers:
                event_link = ec.find('a', class_=re.compile(r'_[0-9a-f]+'))
                if not event_link:
                    continue
                event_name = event_link.get_text(strip=True)
                if 'UFC' not in event_name:
                    continue

                event_details = ec.find('p')
                details_text = event_details.get_text(strip=True) if event_details else ''
                venue = details_text.split('•')[0].strip() if '•' in details_text else ''

                main_card_utc_dt = None
                mc_match = re.search(r'main card.*?(\d+(?::\d+)?\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                if mc_match:
                    main_card_utc_dt = convert_et_to_utc(mc_match.group(1), date_formatted)

                prelim_utc_dt = None
                pl_match = re.search(r'prelim.*?(\d+(?::\d+)?\s*(?:a\.m\.|p\.m\.)\s*ET)', details_text, re.IGNORECASE)
                if pl_match:
                    prelim_utc_dt = convert_et_to_utc(pl_match.group(1), date_formatted)

                def fmt(utc_dt):
                    if utc_dt is None:
                        return date_formatted, None
                    return utc_dt.strftime('%Y-%m-%d'), utc_dt.strftime('%H:%M')

                fight_container = ec.find_next_sibling('div')
                if not fight_container:
                    continue

                for fight_card in fight_container.find_all('div', class_=re.compile(r'_[0-9a-f]+')):
                    fight_link = fight_card.find('a')
                    if not fight_link:
                        continue
                    fight_text = fight_link.get_text(strip=True)
                    fighters = fight_text.split(' vs ')
                    if len(fighters) != 2:
                        continue

                    f1 = re.sub(r'\s+\d+$', '', fighters[0].strip())
                    f2 = re.sub(r'\s+\d+$', '', fighters[1].strip())

                    # Determine card type based on position — simplified
                    mc_date, mc_time = fmt(main_card_utc_dt)
                    fights.append({
                        'fighter1': f1,
                        'fighter2': f2,
                        'date': mc_date,
                        'time': mc_time,
                        'venue': venue,
                        'location': venue,
                        'sport': 'UFC',
                        'event_name': event_name,
                        'weight_class': '',
                        'card_type': 'Main Card',
                    })

    except Exception as e:
        print(f"mmafighting.com scrape error: {e}")

    print(f"mmafighting.com: Found {len(fights)} UFC fights")
    return fights


def scrape_ufc_events():
    """
    Scrape UFC schedule. Tries ESPN API first, falls back to mmafighting.com.

    Returns list of fight dicts:
        fighter1, fighter2, date (YYYY-MM-DD), time (HH:MM UTC or None),
        venue, location, sport='UFC', event_name, weight_class, card_type
    """
    fights = _scrape_espn()

    if len(fights) < 5:
        print(f"ESPN returned only {len(fights)} fights — trying mmafighting.com fallback")
        fallback = _scrape_mmafighting()
        if len(fallback) > len(fights):
            fights = fallback

    return fights
