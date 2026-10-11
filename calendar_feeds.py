"""
Subscribable .ics calendar feeds.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
from datetime import datetime
from flask import abort, make_response
from core import app
import fight_store
import formatting
import pipeline


def _ics_escape(text):
    """Escape text for ICS format."""
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _build_calendar_events(fights):
    """Group fights into calendar events: one entry per fight card."""
    events = {}

    for fight in fights:
        if fight.get('sport') == 'UFC':
            key = ('ufc', fight.get('event_name', ''), )
            slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
            url = f"https://fightschedule.live/event/{slug}"
            title = fight.get('event_name') or f"{fight['fighter1']} vs {fight['fighter2']}"
        else:
            key = ('boxing', fight.get('venue', ''), fight.get('date', ''))
            main = fight if fight.get('is_main_event') else None
            url = None
            title = None

        ev = events.setdefault(key, {
            'sport': fight.get('sport'),
            'title': title,
            'url': url,
            'date': fight.get('date'),
            'time': None,
            'venue': fight.get('venue', ''),
            'location': fight.get('location', ''),
            'streaming': fight.get('streaming', ''),
            'fights': [],
        })
        ev['fights'].append(fight)

        # Earliest known start time wins; keep earliest date too (prelims can
        # start the previous UTC day)
        if fight.get('time') and fight['time'] != 'TBA':
            candidate = (fight.get('date', ''), fight['time'])
            current = (ev['date'] or '', ev['time'] or '99:99')
            if ev['time'] is None or candidate < current:
                ev['date'], ev['time'] = candidate

        # Boxing: title/url from the main event
        if fight.get('sport') == 'Boxing' and fight.get('is_main_event'):
            slug = f"{formatting._to_slug(fight['fighter1'])}-vs-{formatting._to_slug(fight['fighter2'])}-{fight['date']}"
            ev['title'] = f"{fight['fighter1']} vs {fight['fighter2']}"
            ev['url'] = f"https://fightschedule.live/boxing-event/{slug}"

    result = []
    for ev in events.values():
        if not ev['title']:
            first = ev['fights'][0]
            ev['title'] = f"{first['fighter1']} vs {first['fighter2']}"
        result.append(ev)
    result.sort(key=lambda e: (e['date'] or '9999', e['time'] or '99:99'))
    return result


def _render_ics(cal_events, cal_name):
    now_stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//fightschedule.live//Fight Schedule//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:{_ics_escape(cal_name)}',
        'X-WR-TIMEZONE:UTC',
    ]
    for ev in cal_events:
        if not ev['date']:
            continue
        date_compact = ev['date'].replace('-', '')
        uid_base = (ev['url'] or ev['title']).split('/')[-1]
        card_lines = []
        for f in ev['fights']:
            tag = f" ({f['card_type']})" if f.get('card_type') else ''
            card_lines.append(f"{f['fighter1']} vs {f['fighter2']}{tag}")
        desc = '\n'.join(card_lines)
        if ev.get('streaming'):
            desc += f"\nWatch on: {ev['streaming']}"
        if ev.get('url'):
            desc += f"\n{ev['url']}"

        lines.append('BEGIN:VEVENT')
        lines.append(f'UID:{uid_base}@fightschedule.live')
        lines.append(f'DTSTAMP:{now_stamp}')
        if ev['time'] and ev['time'] != 'TBA':
            start_compact = ev['time'].replace(':', '') + '00'
            lines.append(f'DTSTART:{date_compact}T{start_compact}Z')
            lines.append('DURATION:PT3H')
        else:
            lines.append(f'DTSTART;VALUE=DATE:{date_compact}')
        lines.append(f'SUMMARY:{_ics_escape(ev["title"])} ({ev["sport"]})')
        lines.append(f'DESCRIPTION:{_ics_escape(desc)}')
        location = ev.get('venue') or ev.get('location') or ''
        if location:
            lines.append(f'LOCATION:{_ics_escape(location)}')
        if ev.get('url'):
            lines.append(f'URL:{ev["url"]}')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    # RFC 5545 requires CRLF line endings
    return '\r\n'.join(lines) + '\r\n'


@app.route('/calendar.ics')
@app.route('/calendar/<sport>.ics')
def calendar_ics(sport=None):
    """Subscribable ICS calendar of upcoming fights (all, ufc, or boxing)."""
    if sport is not None and sport not in ('ufc', 'boxing'):
        abort(404)
    fights = fight_store.upcoming_only(pipeline.fetch_fights())
    if sport:
        fights = [f for f in fights if f.get('sport', '').lower() == sport]
        cal_name = f"{'UFC' if sport == 'ufc' else 'Boxing'} Schedule — fightschedule.live"
    else:
        cal_name = 'Fight Schedule — UFC & Boxing'

    ics = _render_ics(_build_calendar_events(fights), cal_name)
    response = make_response(ics)
    response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response
