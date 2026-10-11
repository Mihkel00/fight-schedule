"""
Text helpers and Jinja filters: slugs, surnames, results, dates and times.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import re
import structured_data as _ld
import unicodedata
from datetime import datetime
from core import app


def _to_slug(name):
    """Convert a fighter name to a URL slug, stripping diacritics and punctuation."""
    normalized = unicodedata.normalize('NFD', name)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return ascii_name.lower().replace(' ', '-').replace("'", '').replace('.', '')


_NAME_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}


def surname(name):
    """Display surname: 'Julio Cesar Chavez Jr.' -> 'Chavez', 'Isaac "Pitbull" Cruz' -> 'Cruz'."""
    if not name:
        return ''
    # drop quoted nicknames and trailing rematch numbers ("Lopes 2")
    cleaned = re.sub(r'[\"“”‘’\'][^\"“”‘’\']+[\"“”‘’\']', ' ', name)
    cleaned = re.sub(r'\s+\d+$', '', cleaned).strip()
    parts = cleaned.split()
    while len(parts) > 1 and parts[-1].lower().strip(',') in _NAME_SUFFIXES:
        parts.pop()
    return parts[-1] if parts else name


app.jinja_env.filters['surname'] = surname


def result_text(r):
    """One-line result: 'Inoue wins · UD · 12 rounds', 'Walker wins · KO · Round 2'."""
    if not r:
        return ''
    if r.get('outcome') == 'draw':
        return 'Draw' + (f" · {r['method']}" if r.get('method') else '')
    if r.get('outcome') != 'win':
        return 'No contest'
    bits = [f"{surname(r.get('winner'))} wins"]
    method = r.get('method') or ''
    if method:
        bits.append(method)
    rnd = r.get('round')
    if rnd:
        decision = method.upper() in ('UD', 'SD', 'MD', 'TD', 'DECISION') or 'DEC' in method.upper()
        bits.append(f"{rnd} rounds" if decision else f"Round {rnd}" + (f", {r['time']}" if r.get('time') else ''))
    return ' · '.join(bits)


app.jinja_env.filters['result_text'] = result_text


app.jinja_env.globals['ld'] = _ld


def utc_time(t):
    """Server-rendered time text: '00:00 UTC' (JavaScript replaces it with the
    visitor's local time). Crawlers that don't run JavaScript see an
    unambiguous timezone instead of a bare '00:00'."""
    return f"{t} UTC" if t and t != 'TBA' and ':' in str(t) else 'TBA'


def iso_utc(d, t=None):
    """Machine-readable value for <time datetime>: '2026-10-04T00:00Z', or the
    date alone when there is no start time."""
    start = _ld._start(d, t)
    return start.strftime('%Y-%m-%dT%H:%MZ') if start else (d or '')


app.jinja_env.filters['utc_time'] = utc_time


app.jinja_env.filters['iso_utc'] = iso_utc


def format_fight_date(date_str):
    """Format date from YYYY-MM-DD to 'Sat, Dec 06'"""
    if not date_str:
        return ''
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return date_obj.strftime('%a, %b %d')
    except:
        return date_str


def format_fight_time(time_str):
    """Format time from 24h to 12h with AM/PM"""
    if not time_str:
        return ''
    try:
        # Handle various time formats
        time_str = time_str.strip()
        
        # If already has AM/PM, return as is
        if 'AM' in time_str.upper() or 'PM' in time_str.upper():
            return time_str
        
        # Parse 24-hour format (e.g., "13:00" or "1:00")
        if ':' in time_str:
            time_obj = datetime.strptime(time_str, '%H:%M')
            return time_obj.strftime('%I:%M %p').lstrip('0')  # Remove leading zero
        
        return time_str
    except:
        return time_str


# Register Jinja2 filters
app.jinja_env.filters['format_date'] = format_fight_date


app.jinja_env.filters['format_time'] = format_fight_time
