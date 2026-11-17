"""
Fighter profiles (tale of the tape) and fight results from Wikipedia.

Every notable boxer / MMA fighter has a Wikipedia article with:
  - an infobox: height, reach, stance, date of birth, nationality, record
  - a "Professional boxing record" / "Mixed martial arts record" table:
    one row per fight with result, opponent, method, round/time, date

Usage:
    title   = resolve_title("Conor Benn", "Boxing")       # -> "Conor Benn" or None
    profile = fetch_profile(title, "Boxing")             # -> dict (see parse_profile)
    result  = find_result(profile, "Ryan Garcia", "2026-09-12")

Only exact title matches are accepted so obscure names never get someone
else's stats. Callers are expected to cache results (see app.py).
"""

import re
import unicodedata
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup

_API = 'https://en.wikipedia.org/w/api.php'
_UA = {'User-Agent': 'FightScheduleBot/1.0 (https://fightschedule.live)'}

_SPORT_HINT = {'Boxing': 'boxer', 'UFC': 'mixed martial artist'}


class WikiUnavailable(Exception):
    """Wikipedia did not answer (rate limit, error page, timeout). Not the same as "no article":
    callers must not cache it as a miss."""


def _api(params, timeout=15):
    try:
        r = requests.get(_API, params={**params, 'format': 'json'}, headers=_UA, timeout=timeout)
    except requests.RequestException as e:
        raise WikiUnavailable(str(e)) from e
    if r.status_code != 200:
        raise WikiUnavailable(f'HTTP {r.status_code}')
    try:
        return r.json()
    except ValueError as e:
        raise WikiUnavailable('not JSON') from e


# Letters that Unicode decomposition does not split into base + accent, so `_norm`
# deletes them ("Michał Cieślak" -> "micha cieslak"). Applied only when comparing
# names (`_loose`): `_norm` also builds stored profile and photo keys, which must not change.
_FOLD = str.maketrans({'ł': 'l', 'Ł': 'L', 'ø': 'o', 'Ø': 'O', 'đ': 'd', 'Đ': 'D', 'ß': 'ss',
                       'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE', 'ı': 'i', 'þ': 'th', 'Þ': 'Th',
                       'ð': 'd', 'Ð': 'D'})


def _norm(s):
    """Lowercase, strip diacritics/punctuation, collapse spaces."""
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r"[^a-z0-9 ]", ' ', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def _loose(s):
    """`_norm` without spaces, so punctuation inside a name does not matter:
    "M'billi" == "Mbilli", "O'Malley" == "OMalley", "Jean-Pierre" == "Jean Pierre",
    "Michał" == "Michal"."""
    return _norm((s or '').translate(_FOLD)).replace(' ', '')


def _strip_refs(text):
    """Remove Wikipedia citation markers like [ 1 ] and collapse whitespace."""
    text = re.sub(r'\[\s*\d+\s*\]', '', text or '')
    text = re.sub(r'\[\s*[a-z]\s*\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ── title resolution ─────────────────────────────────────────────────────────

def resolve_title(name, sport):
    """Find the Wikipedia article for a fighter. Returns a title or None.

    Accepts a search hit only if its title (ignoring a parenthetical such as
    "(boxer)", and ignoring punctuation and spacing inside the name) equals
    the fighter's name, so unknown fighters return None rather than a wrong
    article. When no search hit matches, the name is tried as a title (which
    follows redirects such as "Christian Mbilli" -> "Christian M'billi").
    Raises WikiUnavailable when Wikipedia does not answer, so a refusal is never
    mistaken for "no article".
    """
    hint = _SPORT_HINT.get(sport, '')
    j = _api({'action': 'query', 'list': 'search', 'srsearch': f'{name} {hint}'.strip(), 'srlimit': 5})
    titles = [h.get('title', '') for h in j.get('query', {}).get('search', [])]
    found = _matching_title(name, titles)
    if found:
        return found
    direct = _direct_title(name)
    if direct and _matching_title(name, [direct]):
        return direct
    return _renamed_article(name, sport, titles, direct)


_SUFFIXES = ('jr', 'sr', 'ii', 'iii')
_NICK = re.compile(r'\s*[“"]([^”"]+)[”"]\s*')


def _surname(name):
    toks = [t for t in _norm(re.sub(r'\s*\([^)]*\)\s*$', '', name or '').translate(_FOLD)).split()
            if t not in _SUFFIXES]
    return toks[-1] if toks else ''


def _renamed_article(name, sport, titles, direct):
    """The fighter's article under a different title than the schedule's name, accepted only when
    it has the same surname AND is a fighter's page (it has a fight-record table):
      - the page the name redirects to ("Shara Magomedov" -> "Sharabutdin Magomedov"),
      - the name plus a suffix ("Brian Norman" -> "Brian Norman Jr."),
      - a nickname written inside the name ('James "Jazza" Dickens' -> "Jazza Dickens").
    A redirect to anything else ("Tyrone McKenna" -> "The Mighty Celt", a film) is rejected."""
    want = _loose(name)
    candidates = [direct] if direct else []
    candidates += [t for t in titles
                   if any(_loose(re.sub(r'\s*\([^)]*\)\s*$', '', t)) == want + sfx for sfx in _SUFFIXES)]
    nick = _NICK.search(name or '')
    if nick:
        rest = _NICK.sub(' ', name).split()
        for variant in (' '.join(rest), f'{nick.group(1)} {rest[-1]}' if rest else ''):
            if variant:
                candidates += [t for t in titles if _matching_title(variant, [t])]
                d = _direct_title(variant)
                if d:
                    candidates.append(d)
    seen = set()
    for title in candidates:
        if title in seen or _surname(title) != _surname(name):
            continue
        seen.add(title)
        profile = fetch_profile(title, sport)
        if profile and profile.get('fights'):
            return profile.get('title') or title
    return None


def _matching_title(name, titles):
    want = _loose(name)
    if not want:
        return None
    for title in titles:
        base = _loose(re.sub(r'\s*\([^)]*\)\s*$', '', title))
        paren = re.search(r'\(([^)]*)\)\s*$', title)
        if base == want:
            # "Ryan Garcia" or "Ryan Garcia (boxer)" — but not "Ryan Garcia (politician)"
            if paren and not re.search(r'boxer|fighter|martial|kickboxer|wrestler', paren.group(1), re.I):
                continue
            return title
    return None


def _direct_title(name):
    """The canonical title the name itself leads to (following redirects), or None."""
    j = _api({'action': 'query', 'titles': name, 'redirects': 1})
    for page in j.get('query', {}).get('pages', {}).values():
        if 'missing' not in page and page.get('title'):
            return page['title']
    return None


# ── profile parsing ──────────────────────────────────────────────────────────

_DATE_FORMATS = ('%d %b %Y', '%d %B %Y', '%B %d, %Y', '%b %d, %Y', '%Y-%m-%d')


def _parse_date(text):
    text = _strip_refs(text).replace('\xa0', ' ')
    text = re.sub(r'\s*\(.*?\)\s*', ' ', text).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _cm_from_height(text):
    m = re.search(r'\((\d{2,3})\s*cm\)', text) or re.search(r'\((\d\.\d{2})\s*m\)', text)
    if not m:
        return None
    v = float(m.group(1))
    return int(round(v * 100)) if v < 3 else int(v)


def _inches(text):
    m = re.search(r'(\d{2,3}(?:\.\d)?)\s*in\b', text)
    return float(m.group(1)) if m else None


def _parse_infobox(soup):
    ib = soup.find('table', class_='infobox')
    if not ib:
        return {}
    out = {'record': {}}
    section = None   # 'wins' / 'losses' / 'draws' for the "By knockout" sub-rows
    for tr in ib.find_all('tr'):
        th, td = tr.find('th'), tr.find('td')
        if not th:
            continue
        label = _strip_refs(th.get_text(' ', strip=True)).replace('\xa0', ' ')
        if not td:
            continue
        value = _strip_refs(td.get_text(' ', strip=True)).replace('\xa0', ' ')
        low = label.lower()

        if low == 'born':
            m = re.search(r'\(\s*(\d{4}-\d{2}-\d{2})\s*\)', value)
            if m:
                out['dob'] = m.group(1)
            place = re.sub(r'.*?\(age\s*\d+\)\s*', '', value) if '(age' in value else ''
            if place:
                out['birthplace'] = place.strip()
        elif low == 'height':
            out['height_text'] = value
            out['height_cm'] = _cm_from_height(value)
        elif low == 'reach':
            out['reach_text'] = value
            out['reach_in'] = _inches(value)
            m = re.search(r'\((\d{2,3})\s*cm\)', value)
            out['reach_cm'] = int(m.group(1)) if m else None
        elif low == 'stance':
            out['stance'] = value
        elif low == 'nationality':
            out['nationality'] = value
        elif low in ('division', 'weight'):
            out.setdefault('division', value)
        elif low in ('nickname', 'other names'):
            out.setdefault('nickname', value)
        elif low in ('total fights', 'total'):
            out['record']['total'] = _int(value)
        elif low == 'wins':
            out['record']['wins'] = _int(value); section = 'wins'
        elif low == 'losses':
            out['record']['losses'] = _int(value); section = 'losses'
        elif low == 'draws':
            out['record']['draws'] = _int(value); section = 'draws'
        elif low in ('no contests', 'no contest'):
            out['record']['no_contests'] = _int(value)
        elif low in ('win by ko', 'wins by ko', 'by knockout') and section in (None, 'wins'):
            out['record']['ko_wins'] = _int(value)
        elif low == 'by submission' and section == 'wins':
            out['record']['sub_wins'] = _int(value)
        elif low == 'by decision' and section == 'wins':
            out['record']['dec_wins'] = _int(value)

    if out.get('dob'):
        try:
            b = date.fromisoformat(out['dob']); t = date.today()
            out['age'] = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
        except ValueError:
            pass
    return out


def _int(text):
    m = re.search(r'\d+', text or '')
    return int(m.group()) if m else None


def _find_record_table(soup):
    """The fight-by-fight record table: headers contain Result/Res. and Opponent."""
    for t in soup.find_all('table', class_='wikitable'):
        rows = t.find_all('tr')
        if not rows:
            continue
        headers = [_norm(c.get_text(' ', strip=True)) for c in rows[0].find_all(['th', 'td'])]
        if any(h in ('result', 'res') for h in headers) and 'opponent' in headers:
            return t, headers
    return None, None


def _parse_record_rows(table, headers):
    idx = {h: i for i, h in enumerate(headers)}
    col_result = idx.get('result', idx.get('res'))
    col_opp = idx.get('opponent')
    col_method = idx.get('type', idx.get('method'))
    col_round_time = idx.get('round time')      # boxing: "2 (12), 1:25"
    col_round = idx.get('round')
    col_time = idx.get('time')
    col_date = idx.get('date')
    col_event = idx.get('event')
    col_notes = idx.get('notes')
    col_rec = idx.get('record')

    fights = []
    for tr in table.find_all('tr')[1:]:
        cells = [_strip_refs(c.get_text(' ', strip=True)).replace('\xa0', ' ') for c in tr.find_all(['td', 'th'])]
        if len(cells) < 4 or col_result is None or col_result >= len(cells):
            continue

        def cell(i):
            return cells[i] if i is not None and i < len(cells) else ''

        rnd, tm = None, None
        if col_round_time is not None:
            m = re.match(r'(\d+)\s*(?:\((\d+)\))?\s*,?\s*(\d+:\d+)?', cell(col_round_time))
            if m:
                rnd, tm = m.group(1), m.group(3)
        else:
            rnd, tm = cell(col_round) or None, cell(col_time) or None

        fights.append({
            'result': cell(col_result),
            'opponent': cell(col_opp),
            'method': cell(col_method),
            'round': rnd,
            'time': tm,
            'date': _parse_date(cell(col_date)),
            'event': cell(col_event) or None,
            'record_after': cell(col_rec) or None,
            'notes': cell(col_notes) or None,
        })
    return fights


def parse_profile(html, title=None, sport=None):
    """Parse a Wikipedia article's rendered HTML into a profile dict."""
    soup = BeautifulSoup(html, 'html.parser')
    profile = _parse_infobox(soup)
    table, headers = _find_record_table(soup)
    profile['fights'] = _parse_record_rows(table, headers) if table else []
    profile['title'] = title
    profile['sport'] = sport
    profile['url'] = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}" if title else None
    profile['has_tape'] = any(profile.get(k) for k in ('height_cm', 'reach_in', 'stance', 'dob'))
    return profile


def fetch_profile(title, sport=None):
    """Fetch and parse the article for a resolved title. Returns dict, or None when the page
    does not exist or cannot be parsed. Raises WikiUnavailable when Wikipedia does not answer."""
    payload = _api({'action': 'parse', 'page': title, 'prop': 'text', 'redirects': 1}, timeout=20)
    if 'error' in payload:
        return None
    try:
        return parse_profile(payload['parse']['text']['*'], payload['parse'].get('title', title), sport)
    except Exception:
        return None


# ── results lookup ───────────────────────────────────────────────────────────

def _same_person(a, b):
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or _loose(a) == _loose(b):
        return True
    # surname + first-initial match handles "Jose Ramirez" vs "José Carlos Ramírez"
    ta, tb = na.split(), nb.split()
    return ta[-1] == tb[-1] and ta[0][0] == tb[0][0]


def find_result(profile, opponent, fight_date, tolerance_days=3):
    """Find the fight against `opponent` around `fight_date` in a profile's record.

    Returns e.g. {'result': 'Loss', 'method': 'TKO', 'round': '2', 'time': '1:25',
                  'date': '2026-09-12', 'notes': 'For WBC welterweight title'} or None.
    """
    if not profile or not fight_date:
        return None
    try:
        target = date.fromisoformat(fight_date)
    except ValueError:
        return None
    for f in profile.get('fights', []):
        if not f.get('date') or not _same_person(f.get('opponent'), opponent):
            continue
        try:
            delta = abs((date.fromisoformat(f['date']) - target).days)
        except ValueError:
            continue
        if delta <= tolerance_days:
            return f
    return None
