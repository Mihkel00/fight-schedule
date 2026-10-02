"""
UFC Event Scraper — ESPN MMA API (JSON).
"""

import requests
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


_SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard'
_EVENT = 'https://site.api.espn.com/apis/site/v2/sports/mma/ufc/event/{id}'


def _snapshot(label, url, status, body, error=None):
    """Save what ESPN sent (see runs.py). Never raises."""
    try:
        import runs
        return runs.save_snapshot('UFC', label, url, status, body, error=error, ext='json')
    except Exception:
        return None


def fetch(url, label, params=None):
    """One HTTP request to ESPN. Returns {'label', 'url', 'status', 'data', 'error',
    'snapshot'}; data is the parsed JSON or None. The raw body is saved either way."""
    status, body, error, data = None, b'', None, None
    try:
        resp = requests.get(url, params=params, headers={'User-Agent': _ESPN_UA}, timeout=15)
        status, body = resp.status_code, resp.content
        if resp.status_code != 200:
            error = f'HTTP {resp.status_code}'
        else:
            try:
                data = resp.json()
            except ValueError as e:
                error = f'not JSON: {e}'
    except Exception as e:
        error = f'{type(e).__name__}: {e}'
    snap = _snapshot(label, resp.url if status is not None else url, status, body, error)
    return {'label': label, 'url': url, 'status': status, 'data': data, 'error': error,
            'snapshot': snap.get('file') if snap else None}


def _competitor_name(c):
    ath = c.get('athlete', {})
    return ath.get('displayName', ath.get('shortName', ''))


def _competition_to_fight(comp, event_name, fallback_date, fallback_venue, fallback_location):
    """One ESPN competition -> fight dict, or None if it has no two named fighters."""
    competitors = comp.get('competitors', [])
    if len(competitors) < 2:
        return None
    f1, f2 = _competitor_name(competitors[0]), _competitor_name(competitors[1])
    if not f1 or not f2:
        return None
    comp_dt = _parse_iso(comp.get('date', ''))
    venue_name, location = _venue_parts(comp.get('venue'))
    if not venue_name:
        venue_name, location = fallback_venue, fallback_location
    weight_class = ''
    for c in competitors:
        wc = c.get('athlete', {}).get('weightClass', {})
        weight_class = wc.get('text', '') if isinstance(wc, dict) else (wc if isinstance(wc, str) else '')
        if weight_class:
            break
    return {
        'fighter1': f1,
        'fighter2': f2,
        'date': comp_dt.strftime('%Y-%m-%d') if comp_dt else fallback_date,
        'time': comp_dt.strftime('%H:%M') if comp_dt else None,
        'venue': venue_name,
        'location': location or venue_name,
        'sport': 'UFC',
        'event_name': event_name,
        'weight_class': weight_class,
        'card_type': _card_type(comp),
    }


def parse_event(event, month, fetch_detail=True):
    """Fights of one scoreboard event. Falls back to the event-detail endpoint
    when the scoreboard carries no competitors. Returns (fights, detail_fetch)."""
    event_id = str(event.get('id', ''))
    event_name = event.get('name', event.get('shortName', ''))
    event_dt = _parse_iso(event.get('date', ''))
    fallback_date = event_dt.strftime('%Y-%m-%d') if event_dt else f'{month[:4]}-{month[4:]}-01'
    comps = event.get('competitions', [])
    venue_obj = (comps[0] if comps else {}).get('venue') or event.get('venue') or {}
    fallback_venue, fallback_location = _venue_parts(venue_obj)

    fights = [f for f in (_competition_to_fight(c, event_name, fallback_date, fallback_venue, fallback_location) for c in comps) if f]
    detail = None
    if not fights and event_id and fetch_detail:
        detail = fetch(_EVENT.format(id=event_id), f'event-{event_id}')
        data = detail['data'] or {}
        comps = data.get('competitions') or ((data.get('events') or [{}])[0].get('competitions') if data.get('events') else []) or []
        fights = [f for f in (_competition_to_fight(c, event_name, fallback_date, fallback_venue, fallback_location) for c in comps) if f]
    return fights, detail


def months_to_fetch(now=None, count=6):
    now = now or datetime.now(UTC_ZONE)
    out = []
    for i in range(count):
        total = now.month - 1 + i
        out.append(f'{now.year + total // 12}{total % 12 + 1:02d}')
    return out


def _dedup(fights):
    """Remove duplicate fights (same two names), keeping the first occurrence.
    ESPN returns the same event in more than one monthly query."""
    seen, out = set(), []
    for f in fights:
        key = tuple(sorted([f['fighter1'].lower(), f['fighter2'].lower()]))
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def scrape_ufc(months=None):
    """Fetch and parse the UFC schedule from ESPN.

    Returns a result dict:
        fights      list of fight dicts (may be empty)
        outcome     'parsed' | 'partial' | 'http_error' | 'layout_unknown'
        layout      'espn-scoreboard'
        months      {month: {'status', 'error', 'events', 'ufc_events', 'fights'}}
        snapshots   saved raw responses
        diagnostics counts that explain the outcome
    'partial' means some months failed; what was read is still returned.
    """
    months = months or months_to_fetch()
    per_month, snapshots, all_fights, seen_events = {}, [], [], set()
    for month in months:
        r = fetch(_SCOREBOARD, f'scoreboard-{month}', params={'dates': month})
        if r['snapshot']:
            snapshots.append(r['snapshot'])
        info = {'status': r['status'], 'error': r['error'], 'events': 0, 'ufc_events': 0, 'fights': 0, 'shape_ok': None}
        per_month[month] = info
        if r['data'] is None:
            print(f"ESPN schedule error for {month}: {r['error']}")
            continue
        info['shape_ok'] = isinstance(r['data'], dict) and 'events' in r['data']
        events = r['data'].get('events', []) if isinstance(r['data'], dict) else []
        info['events'] = len(events)
        for event in events:
            event_id = str(event.get('id', ''))
            if event_id in seen_events:
                continue
            seen_events.add(event_id)
            event_name = event.get('name', event.get('shortName', ''))
            if 'UFC' not in event_name.upper():
                continue
            info['ufc_events'] += 1
            fights, detail = parse_event(event, month)
            if detail and detail['snapshot']:
                snapshots.append(detail['snapshot'])
            info['fights'] += len(fights)
            all_fights.extend(fights)

    fetched = [m for m, i in per_month.items() if i['status'] == 200 and i['error'] is None]
    failed = [m for m in per_month if m not in fetched]
    if not fetched:
        outcome = 'http_error'
    elif not any(i['shape_ok'] for i in per_month.values()):
        outcome = 'layout_unknown'
    elif failed:
        outcome = 'partial'
    else:
        outcome = 'parsed'
    unique = _dedup(all_fights)
    print(f"ESPN API: {outcome}; {len(fetched)}/{len(months)} months read; {len(unique)} UFC fights ({len(all_fights) - len(unique)} dupes removed)")
    return {
        'fights': unique, 'outcome': outcome, 'layout': 'espn-scoreboard', 'months': per_month,
        'snapshots': snapshots,
        'diagnostics': {'months_ok': fetched, 'months_failed': failed, 'raw_fights': len(all_fights),
                        'events_seen': len(seen_events)},
    }


def scrape_ufc_events():
    """Backward-compatible wrapper: just the list of fights."""
    return scrape_ufc()['fights']
