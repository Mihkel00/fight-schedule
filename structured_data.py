"""
Structured data (schema.org JSON-LD) for event pages and list pages.

Built as Python data and serialised with Jinja's |tojson, so fighter names
with quotes or backslashes can never break the markup (the old templates
hand-wrote JSON and HTML-escaped it). Fields follow Google's Event report:
startDate, endDate, description, location, performer, and organizer only
when it is actually known. `offers` is deliberately omitted — we have no
ticket data and will not invent it.
"""

from datetime import datetime, timedelta

BASE = 'https://fightschedule.live'
SPORT_NAME = {'UFC': 'Mixed Martial Arts', 'Boxing': 'Boxing'}
UFC_ORGANIZER = {'@type': 'Organization', 'name': 'UFC', 'url': 'https://www.ufc.com'}
SCHEDULED = 'https://schema.org/EventScheduled'
MIXED = 'https://schema.org/MixedEventAttendanceMode'

# Typical running time after the listed start; endDate is an estimate from this.
HOURS_UFC_MAIN_CARD = 4
HOURS_UFC_PRELIMS = 2
HOURS_BOXING_CARD = 4


def _abs(url):
    if not url:
        return None
    return BASE + url if url.startswith('/') else url


def _start(date, time):
    if not date or not time or time == 'TBA' or ':' not in str(time):
        return None
    try:
        h, m = str(time).split(':')[:2]
        return datetime.strptime(f'{date} {int(h):02d}:{int(m or 0):02d}', '%Y-%m-%d %H:%M')
    except ValueError:
        return None


def _dates(date, time, hours, day_offset=0):
    start = _start(date, time)
    if start is None:
        return {'startDate': date, 'endDate': date} if date else {}
    start += timedelta(days=day_offset)
    return {'startDate': start.strftime('%Y-%m-%dT%H:%M:00Z'),
            'endDate': (start + timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:00Z')}


def _person(name, image=None):
    p = {'@type': 'Person', 'name': name}
    # Same rule as before: git-tracked /static/ images are not advertised to Google
    if image and '/static/' not in image:
        p['image'] = _abs(image)
    return p


def _place(name, address):
    return {'@type': 'Place', 'name': name or 'TBA', 'address': address or name or 'TBA'}


def _bout(f1, f2, sport, dates, place, description, organizer=None):
    fighters = [_person(f1), _person(f2)]
    ev = {'@type': 'SportsEvent', 'name': f'{f1} vs {f2}', 'sport': SPORT_NAME[sport],
          'eventStatus': SCHEDULED, 'eventAttendanceMode': MIXED, **dates,
          'location': place, 'description': description,
          'competitor': fighters, 'performer': fighters}
    if organizer:
        ev['organizer'] = organizer
    return ev


def boxing_bout_description(f):
    wc = (f.get('weight_class') or '').strip()
    title = wc.startswith('Title ')
    division = (wc[6:] if title else wc).lower()
    rounds = f"{f['rounds']}-round " if f.get('rounds') else ''
    kind = 'title fight' if title else 'bout'
    text = f"{rounds}{division + ' ' if division else ''}{kind}".strip()
    return f"{f['fighter1']} vs {f['fighter2']}: {text[0].upper() + text[1:]}" if text else f"{f['fighter1']} vs {f['fighter2']}"


def ufc_event(event):
    me = event['main_event']
    fighters = [_person(me['fighter1'], me.get('fighter1_image')), _person(me['fighter2'], me.get('fighter2_image'))]
    place = _place(event.get('venue'), event.get('venue'))
    ld = {'@context': 'https://schema.org', '@type': 'SportsEvent',
          'name': event['event_name'], 'description': event.get('meta_description') or event['event_name'],
          'url': event.get('canonical_url'), 'sport': SPORT_NAME['UFC'],
          'eventStatus': SCHEDULED, 'eventAttendanceMode': MIXED,
          **_dates(event.get('date'), me.get('time'), HOURS_UFC_MAIN_CARD),
          'location': place, 'organizer': UFC_ORGANIZER,
          'competitor': fighters, 'performer': fighters}
    main_time, prelim_time = event.get('main_card_time'), event.get('prelim_time')
    # Prelims start before the main card; a later clock time means the previous UTC day
    prelim_offset = -1 if (_start(event.get('date'), prelim_time) and _start(event.get('date'), main_time)
                           and prelim_time > main_time) else 0
    subs = []
    for f in event.get('main_card') or []:
        desc = f"{'Main card title bout' if f.get('is_title') else 'Main card bout'} at {event['event_name']}"
        subs.append(_bout(f['fighter1'], f['fighter2'], 'UFC', _dates(event.get('date'), main_time, HOURS_UFC_MAIN_CARD),
                          place, desc, UFC_ORGANIZER))
    for f in event.get('prelims') or []:
        subs.append(_bout(f['fighter1'], f['fighter2'], 'UFC',
                          _dates(event.get('date'), prelim_time, HOURS_UFC_PRELIMS, prelim_offset),
                          place, f"Preliminary card bout at {event['event_name']}", UFC_ORGANIZER))
    if len(event.get('main_card') or []) > 1 or event.get('prelims'):
        ld['subEvent'] = subs
    return ld


def boxing_event(event):
    """Promoter is unknown, so no organizer (better absent than wrong)."""
    me = event['main_event']
    fighters = [_person(me['fighter1'], me.get('fighter1_image')), _person(me['fighter2'], me.get('fighter2_image'))]
    place = _place(event.get('venue'), event.get('location'))
    dates = _dates(event.get('date'), event.get('time'), HOURS_BOXING_CARD)
    ld = {'@context': 'https://schema.org', '@type': 'SportsEvent',
          'name': f"{me['fighter1']} vs {me['fighter2']}",
          'description': event.get('meta_description') or f"{me['fighter1']} vs {me['fighter2']}",
          'url': event.get('canonical_url'), 'sport': SPORT_NAME['Boxing'],
          'eventStatus': SCHEDULED, 'eventAttendanceMode': MIXED, **dates,
          'location': place, 'competitor': fighters, 'performer': fighters}
    fights = event.get('fights') or []
    if len(fights) > 1:
        ld['subEvent'] = [_bout(f['fighter1'], f['fighter2'], 'Boxing', dates, place, boxing_bout_description(f))
                          for f in fights]
    return ld


def breadcrumbs(*crumbs):
    """crumbs: (name, url_or_None) pairs."""
    items = []
    for i, (name, url) in enumerate(crumbs, 1):
        item = {'@type': 'ListItem', 'position': i, 'name': name}
        if url:
            item['item'] = _abs(url)
        items.append(item)
    return {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': items}


def item_list(name, urls):
    """Summary pages list links to the event pages (Google's summary + detail
    page pattern) instead of repeating thinner copies of each event."""
    seen, items = set(), []
    for u in urls:
        u = _abs(u)
        if u and u not in seen:
            seen.add(u)
            items.append({'@type': 'ListItem', 'position': len(items) + 1, 'url': u})
    return {'@context': 'https://schema.org', '@type': 'ItemList', 'name': name, 'itemListElement': items}
