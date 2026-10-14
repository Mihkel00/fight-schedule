"""
Design system presenter: the pure logic behind the approved redesign's markup
(templates/_ui.html macros, static/css/site.css, static/js/site.js).

The approved mocks (landing/hybrid4, pages/lists, pages/fight) computed these
in their build.py files; this is the same logic on production data:

  names       surnames (particles, family-first names), given names, fitted
              name sizes (per-letter widths of Big Shoulders 900 + side
              bearings), one shared size per pair
  photos      split-poster geometry and face crops from photos.photo_meta()
              (fallback geometry when a photo has no metadata yet)
  times       local start, day, night hints ("Fri–Sat night"), day counts,
              countdown, clock-change rows, all for a given zone. Pages
              render UTC (crawlers and no-JS visitors read UTC); site.js
              recomputes the same things in the visitor's zone.
  schedule    group headings (This week / Next week / Later / Further ahead),
              day sections, the hero fights' pointer rows
  results     method codes, winner-first sides, box-score row packing
  text        weight / title labels, venue -> city

Everything here is pure and never raises on odd data: a page must render
whatever the sources send. Templates reach it as `ds` (a Jinja global).
"""
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core import app, logger
import photos

UTC = timezone.utc

# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------
# Rendered width (em) of each uppercase letter in Big Shoulders 900 (opsz 72),
# measured in Chromium (scratchpad names/bigshoulders900_opsz72.json). Sums run
# ~7.5 % wide of the served font file, corrected by EMK where it matters.
_EM = {
    '0': .526, '1': .289, '2': .505, '3': .509, '4': .534, '5': .526, '6': .518, '7': .49, '8': .519, '9': .518,
    'A': .512, 'B': .502, 'C': .515, 'D': .519, 'E': .442, 'F': .434, 'G': .52, 'H': .523, 'I': .249, 'J': .484,
    'K': .523, 'L': .41, 'M': .839, 'N': .614, 'O': .526, 'P': .505, 'Q': .526, 'R': .505, 'S': .506, 'T': .436,
    'U': .525, 'V': .522, 'W': .862, 'X': .482, 'Y': .464, 'Z': .432, '-': .465, "'": .214, '’': .27, '.': .25,
    ' ': .22,
}
EMK = .935
# Side bearings (left, right) in em of the first / last letter, so the ink (not
# the advance box) lands on a grid edge (scratchpad landing/poster/bearings.json).
_BEAR = {
    'A': (.0175, .019), 'B': (.05, .0315), 'C': (.04, .03), 'D': (.05, .0385), 'E': (.05, .0265), 'F': (.05, .019),
    'G': (.04, .035), 'H': (.05, .05), 'I': (.05, .0485), 'J': (.02, .041), 'K': (.05, .008), 'L': (.05, .012),
    'M': (.05, .0485), 'N': (.05, .049), 'O': (.04, .0405), 'P': (.05, .027), 'Q': (.04, .0405), 'R': (.05, .0275),
    'S': (.0325, .031), 'T': (.005, .006), 'U': (.04, .0395), 'V': (.015, .0145), 'W': (.02, .019), 'X': (.0075, .009),
    'Y': (.0075, .0065), 'Z': (.015, .0145), 'Í': (.05, -.0315), "'": (.04, .039), '’': (.04, .0395),
    '-': (.03, .0295),
}
_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}
_PARTICLES = {'de', 'da', 'das', 'do', 'dos', 'van', 'von', 'la', 'del', 'della', 'di', 'le', 'der', 'den', 'ter', 'du'}
# Names written family name first (the surname is the first word).
FAMILY_FIRST = {'Wang Cong', 'Zhang Weili', 'Yan Xiaonan', 'Song Yadong', 'Li Jingliang', 'Zhang Mingyang',
                'Wu Yanan', 'Xiong Jingnan', 'Su Mudaerji', 'Kai Asakura', 'Rong Zhu'}
_NICK = re.compile(r'["“”‘’\'][^"“”‘’\']+["“”‘’\']')


def is_tba(name):
    return (name or '').strip().upper() in ('', 'TBA', 'TBD')


def _words(name):
    """Name words without nicknames, rematch numbers and suffixes."""
    cleaned = _NICK.sub(' ', name or '')
    cleaned = re.sub(r'\s+\d+$', '', cleaned).strip()
    parts = cleaned.split()
    while len(parts) > 1 and parts[-1].lower().strip(',') in _SUFFIXES:
        parts.pop()
    return parts


def surname(name):
    """Display surname: production's rule (formatting.surname: last word, minus
    nicknames, rematch numbers and suffixes) plus particles ('Alexy de la Cruz'
    -> 'de la Cruz') and family-first names ('Zhang Weili' -> 'Zhang')."""
    if is_tba(name):
        return 'TBA'
    name = name.strip()
    if name in FAMILY_FIRST:
        return name.split()[0]
    parts = _words(name)
    if not parts:
        return name
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in _PARTICLES:
        i -= 1
    return ' '.join(parts[i:])


def name_split(full):
    """(given, family) for a full name: 'Alexander Volkanovski' -> ('Alexander',
    'Volkanovski'); 'Christopher Guerrero-Martínez Jr.' -> ('Christopher',
    'Guerrero-Martínez Jr.') (the surname and what follows it stay together);
    family-first names and single names -> ('', full)."""
    if is_tba(full):
        return '', 'TBA'
    full = (full or '').strip()
    if full in FAMILY_FIRST:
        return '', full
    s = surname(full)
    i = full.rfind(s)
    if i <= 0:
        return '', full
    return full[:i].strip(), full[i:].strip()


def given_name(full):
    return name_split(full)[0]


def name_em(text):
    """Rendered width of `text` in em (uppercase, Big Shoulders 900); unknown
    letters by their base letter (accents), else 0.8 of an M."""
    total = 0.0
    for ch in (text or '').upper():
        if ch in _EM:
            total += _EM[ch]
            continue
        base = unicodedata.normalize('NFD', ch)[0]
        total += _EM.get(base, _EM['M'] * 0.8)
    return total


def line_em(name):
    """(width of the widest line, broken) when a hyphenated name may break at
    its hyphen: only when that makes the line much narrower."""
    full = name_em(name)
    if '-' not in name:
        return full, False
    first, rest = name.split('-', 1)
    broken = max(name_em(first + '-'), name_em(rest))
    return (broken, True) if full * 0.62 > broken else (full, False)


def stacked_em(a, b):
    """Phone / narrow layout: one name per line -> (em, break_a, break_b)."""
    ea, ba = line_em(a)
    eb, bb = (0.0, False) if is_tba(b) else line_em(b)
    return round(max(ea, eb), 2), ba, bb


def one_line_em(a, b, vs_em=1.4):
    """Desktop layout: 'NAME vs NAME' on one line (TBA counts half)."""
    eb = name_em('TBA') * 0.5 if is_tba(b) else name_em(b)
    return round(name_em(a) + eb + vs_em, 2)


def bearing(name, side):
    """Side bearing in em of the first (side 0) or last (side 1) letter."""
    s = (name or '').strip().upper()
    if not s:
        return 0.0
    ch = s[0] if side == 0 else s[-1]
    v = _BEAR.get(ch) or _BEAR.get(unicodedata.normalize('NFD', ch)[0]) or (.04, .04)
    return v[side]


def name_view(s):
    """One surname for the poster lockup: {'text', 'tba', 'parts', 'style'}.
    A hyphenated name that may break is two parts ('Guerrero-', 'Martínez'):
    the phone breaks it, the desktop line does not."""
    if s == 'TBA' or is_tba(s):
        return {'text': 'TBA', 'tba': True, 'parts': None, 'style': ''}
    if '-' in s and line_em(s)[1]:
        a, b = s.split('-', 1)
        return {'text': s, 'tba': False, 'parts': (a + '-', b),
                'style': f'--lsb:{bearing(a, 0)};--rsb:{bearing(b, 1)}'}
    return {'text': s, 'tba': False, 'parts': None, 'style': f'--lsb:{bearing(s, 0)};--rsb:{bearing(s, 1)}'}


def card_names(s1, s2, tba2):
    """fit.py's rule for a poster card: one line, or stacked (one name per
    line) when that is much larger. Decided for a reference card on each layout
    (desktop: 612 px of type, phone: 326 px) -> (stack_desktop, stack_phone,
    stacked_em, lines)."""
    ol = one_line_em(s1, 'TBA' if tba2 else s2, vs_em=.55 / EMK) * EMK
    st, b1, b2 = stacked_em(s1, 'TBA' if tba2 else s2)
    st *= EMK
    nl = 2 + int(b1) + int(b2)

    def choose(iw, cap1, cap2, hblock):
        one = min(cap1, iw / ol / 1.03)
        stk = min(cap2, iw / st / 1.03, hblock / (nl * .86 + .3))
        return int(stk >= 1.35 * one)
    return choose(612, 96, 84, 156), choose(326, 52, 52, 120), round(st, 3), nl


def pair_fit(e):
    """Fitted names for a poster: the two surnames, one shared size (the CSS
    takes the numbers and the card's own width): {'n1', 'n2', 'tba2', 'e1',
    'e2', 'em_stack', 'est', 'nl', 'sd', 'sp'}."""
    s1 = surname(e.get('fighter1'))
    tba2 = is_tba(e.get('fighter2'))
    s2 = 'TBA' if tba2 else surname(e.get('fighter2'))
    e1 = name_em(s1) * EMK
    e2 = (name_em('TBA') * .5 if tba2 else name_em(s2)) * EMK
    em_stack = stacked_em(s1, s2)[0]
    sd, sp, est, nl = card_names(s1, s2, tba2)
    return {'n1': name_view(s1), 'n2': name_view(s2), 's1': s1, 's2': s2, 'tba2': tba2,
            'e1': round(e1, 3), 'e2': round(e2, 3), 'em_stack': em_stack, 'est': est, 'nl': nl, 'sd': sd, 'sp': sp}


def list_em(e):
    """--em-s of a table row: the stacked width of its pair (phone names fit)."""
    return stacked_em(surname(e.get('fighter1')), surname(e.get('fighter2')))[0]


def box_em(a, b):
    """--em-s of a box score: the wider of the two surnames."""
    return round(max(name_em(surname(a)), name_em(surname(b))), 2)


def full_em(full):
    """Width of a full name (given + family) in em, as the fight card sets it."""
    g, f = name_split(full)
    return round(name_em((g + ' ' + f).strip()) * EMK, 2)


def title_order(e):
    """The pair in the order the event title names it ('UFC 334: Gane vs.
    Hokit'): fighter1 / fighter2 (and their photos) are swapped when the title
    names them the other way round. Returns a new dict (never mutates)."""
    t = (e.get('title') or e.get('event_name') or '').split(':', 1)[-1]
    parts = re.split(r'\s+vs\.?\s+', t.strip(), maxsplit=1)
    if len(parts) != 2 or is_tba(e.get('fighter2')):
        return e
    a, b = (surname(x.strip()).lower() for x in parts)
    s1, s2 = surname(e.get('fighter1')).lower(), surname(e.get('fighter2')).lower()
    if (a, b) == (s2, s1) and s1 != s2:
        return dict(e, fighter1=e.get('fighter2'), fighter2=e.get('fighter1'),
                    fighter1_image=e.get('fighter2_image'), fighter2_image=e.get('fighter1_image'))
    return e


# ---------------------------------------------------------------------------
# photos (contract: photos.photo_meta(path) -> dict | None)
# ---------------------------------------------------------------------------
CAP = 1.25           # a hero photo is never shown wider than 1.25x its file (zoom out, never up)
REF_CARD_H = 520     # the desktop card height a file must cover to count as "tall enough"
FALLBACK = {'ex': .5, 'ey': .33, 'em': .08}   # no metadata: face assumed centred, photo covering its half
NO_CAP_W = 4000      # no metadata: no upscale cap (the photo covers its half)
DISC_Z_MAX = 4.5     # a face needing more zoom than this is not a usable round crop
DISC_MIN_PX = 20     # nor is a face under 20 px tall in its file
DISC_Z_DEFAULT = 1.3


def _num(v, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:                      # NaN
        return None
    if lo is not None and x < lo:
        return None
    if hi is not None and x > hi:
        return None
    return x


def photo_meta(path):
    """photos.photo_meta(path), or None: no metadata yet, the photo pipeline not
    deployed, or any error. Never raises, never blocks a page."""
    if not path:
        return None
    fn = getattr(photos, 'photo_meta', None)
    if fn is None:
        return None
    try:
        m = fn(path)
    except Exception as exc:   # a broken metadata file must not take a page down
        logger.warning(f"photo_meta({path!r}) failed: {exc}")
        return None
    return m if isinstance(m, dict) else None


def _meta_view(path):
    """Validated metadata with the fallback filled in: {'known', 'face', 'w',
    'h', 'ex', 'ey', 'em', 'box_h', 'crown', 'b', 'c', 'backdrop', 'cut', 'x0', 'x1'}."""
    m = photo_meta(path) or {}
    w, h = _num(m.get('w'), 1), _num(m.get('h'), 1)
    known = bool(w and h)
    face = bool(m.get('face')) and known
    ex, ey, em = (_num(m.get(k), 0, 1) for k in ('ex', 'ey', 'em'))
    if not (face and ex is not None and ey is not None and em):
        face, ex, ey, em = False, FALLBACK['ex'], FALLBACK['ey'], FALLBACK['em']
    x0, x1 = _num(m.get('x0'), 0, 1), _num(m.get('x1'), 0, 1)
    x0 = 0.0 if x0 is None else x0
    x1 = 1.0 if x1 is None else x1
    if x1 - x0 < .2:                # a nonsense curation range: show the whole photo
        x0, x1 = 0.0, 1.0
    bd = m.get('backdrop') if m.get('backdrop') in ('ko', 'lt') else None
    return {'known': known, 'face': face, 'w': w, 'h': h, 'ex': ex, 'ey': ey, 'em': em,
            'box_h': _num(m.get('box_h'), 0, 1) if face else None, 'crown': _num(m.get('crown'), 0, 1),
            'b': _num(m.get('b'), .3, 2), 'c': _num(m.get('c'), .3, 2), 'backdrop': bd, 'cut': bool(m.get('cut')),
            'x0': x0, 'x1': x1}


def _r(x, n=4):
    return f'{round(x, n):g}'


def poster_half(path):
    """One half of the split poster for the photo at `path`, or None (the half
    is the plain card surface). {'src', 'cls', 'style', 'copies'}:
      cls     'cut' (transparent cut-out), 'ko' / 'lt' (white / light backdrop),
              'sh' (file too short for the card: its own rows stretched),
              'cr' / 'cl' (curated right / left edge), 'nometa' (fallback geometry)
      style   the CSS numbers (.ph in site.css computes size and place from them)
      copies  the blurred backfill copies ('bf', 'bf bt', 'bf bb')"""
    if not path:
        return None
    v = _meta_view(path)
    ar = (v['w'] / v['h']) if v['known'] else 1.0
    sw = v['w'] if v['known'] else NO_CAP_W
    short = int(v['known'] and v['h'] * CAP < .85 * REF_CARD_H)
    kind = 'cut' if v['cut'] else (v['backdrop'] or '')
    style = (f'--ar:{_r(ar)};--ex:{_r(v["ex"])};--ey:{_r(v["ey"])};--em:{_r(v["em"])};--sw:{_r(sw, 1)};'
             f'--x0:{_r(v["x0"])};--x1:{_r(v["x1"])};--sh:{short}')
    if v['b'] is not None and v['c'] is not None:
        style += f';--b:{_r(v["b"], 3)};--c:{_r(v["c"], 3)}'
    if v['crown'] is not None:
        style += f';--cy:{_r(v["crown"])}'
    sh = short and kind in ('', 'lt')
    cls = [kind, 'sh' if sh else '', 'cr' if v['x1'] < 1 else '', 'cl' if v['x0'] > 0 else '',
           '' if v['known'] else 'nometa']
    copies = []
    if kind in ('', 'lt'):
        copies = ['bf', 'bf bt', 'bf bb'] if sh else ['bf']
    return {'src': path, 'cls': ' '.join(c for c in cls if c), 'style': style, 'copies': copies}


def face_crop(path):
    """A round face crop: None (the quiet grey disc: no photo, or no usable face
    in it) or {'src', 'style', 'tone'} (tone: 'ko' / 'lt' / '')."""
    if not path:
        return None
    v = _meta_view(path)
    tone = v['backdrop'] or ''
    if not v['face']:
        # no metadata or no face found: the photo with a cautious centred crop
        return {'src': path, 'style': f'--px:.5;--py:{_r(FALLBACK["ey"] + .45 * FALLBACK["em"], 3)};'
                                      f'--z:{DISC_Z_DEFAULT}', 'tone': tone}
    w, h = v['w'], v['h']
    hd = v['box_h'] or v['em'] * 2.8
    fx, fy = v['ex'], v['ey'] + .45 * v['em']
    if w >= h:
        r = w / h
        px, py = fx * r - (r - 1) / 2, fy
    else:
        r = h / w
        px, py = fx, fy * r - (r - 1) / 2
    z_need = .55 / (hd * max(1, h / w))
    if z_need > DISC_Z_MAX or hd * h < DISC_MIN_PX:
        return None
    z = min(DISC_Z_MAX, max(1.1, z_need))
    # the zoomed photo must still cover the disc: a face near the file's edge (a close-up's chin at the bottom) is
    # shown off-centre rather than leaving a grey band in the disc (site.css .face img: translate + scale(z))
    px, py = (min(max(v, .5 / z), 1 - .5 / z) for v in (px, py))
    return {'src': path, 'style': f'--px:{_r(px, 3)};--py:{_r(py, 3)};--z:{_r(z, 2)}', 'tone': tone}


def poster_photos(e):
    """(left half, right half, number of photos) for an event's main pair. A TBA
    opponent has no half; the same picture twice keeps it on the first named."""
    a = e.get('fighter1_image') or None
    b = None if is_tba(e.get('fighter2')) else (e.get('fighter2_image') or None)
    if a and b and a.split('?')[0] == b.split('?')[0]:
        b = None
    p1, p2 = poster_half(a), poster_half(b)
    return p1, p2, len([p for p in (p1, p2) if p])


# ---------------------------------------------------------------------------
# times
# ---------------------------------------------------------------------------
_DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def zone(tz=None):
    """A tzinfo for `tz` (None / 'UTC' -> UTC, an IANA name, or a tzinfo)."""
    if tz is None or tz == 'UTC':
        return UTC
    if isinstance(tz, str):
        try:
            return ZoneInfo(tz)
        except Exception:
            return UTC
    return tz


def now_utc():
    return datetime.now(UTC)


def utc_start(date_iso, t):
    """Aware UTC start from the stored date + 'HH:MM', or None (TBA, missing)."""
    if not date_iso or not t or not isinstance(t, str) or not re.match(r'^\d{1,2}:\d{2}', t.strip()):
        return None
    try:
        hh, mm = t.strip()[:5].split(':')[:2]
        d = date.fromisoformat(str(date_iso)[:10])
        return datetime(d.year, d.month, d.day, int(hh), int(mm[:2]), tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def start_of(e):
    return utc_start(e.get('date'), e.get('time'))


def local_start(e, tz=None):
    s = start_of(e)
    return s.astimezone(zone(tz)) if s else None


def local_day(e, tz=None):
    """The event's calendar day in `tz` (its stored date when it has no time)."""
    s = local_start(e, tz)
    if s:
        return s.date()
    try:
        return date.fromisoformat(str(e.get('date'))[:10])
    except (ValueError, TypeError):
        return None


def today_in(tz=None, now=None):
    return (now or now_utc()).astimezone(zone(tz)).date()


def hm(dt):
    return dt.strftime('%H:%M') if dt else ''


def day_short(d):
    """'Sat 17 Oct'."""
    return f'{_DAYS[d.weekday()]} {d.day} {d.strftime("%b")}' if d else ''


def night_hint(dt):
    """A start between 00:00 and 05:59 is the night between two days:
    'Thu–Fri night' agrees with the date it is listed under and still says
    "stay up on Thursday"."""
    if dt and dt.hour < 6:
        return f'{_DAYS[(dt.weekday() - 1) % 7]}–{_DAYS[dt.weekday()]} night'
    return ''


def night_day(e, tz=None):
    """The evening an event belongs to (00:00-05:59 counts for the day before):
    used for the week groups only, so one night is never split in two."""
    s, d = local_start(e, tz), local_day(e, tz)
    if d is None:
        return None
    return d - timedelta(days=1) if (s and s.hour < 6) else d


def rel_day(day, today):
    """The one day count, everywhere: calendar days from today to the day."""
    if not day or not today:
        return ''
    n = (day - today).days
    if n == 0:
        return 'Today'
    if n == 1:
        return 'Tomorrow'
    if n > 1:
        return f'in {n} days'
    if n == -1:
        return 'Yesterday'
    return f'{-n} days ago'


def countdown(start, now=None):
    """The hours countdown, only inside the last 24 hours: 'in 9 h 12 min',
    'in 42 min', 'starting now'; '' further out or without a time."""
    if not start:
        return ''
    mins = int((start - (now or now_utc())).total_seconds() // 60)
    if mins <= 0:
        return 'starting now'
    if mins >= 1440:
        return ''
    h, m = divmod(mins, 60)
    return f'in {h} h {m} min' if h else f'in {m} min'


def gmt(minutes):
    """'GMT+3', 'GMT−4' (a real minus), 'GMT+5:30'."""
    sign = '+' if minutes >= 0 else '−'
    h, m = divmod(abs(int(minutes)), 60)
    return f'GMT{sign}{h}' + (f':{m:02d}' if m else '')


def tz_label(tz=None, at=None):
    """'UTC', or the zone's city with its offset: 'Tallinn (GMT+3)'."""
    z = zone(tz)
    if z is UTC:
        return 'UTC'
    at = (at or now_utc()).astimezone(z)
    city = str(getattr(z, 'key', z)).split('/')[-1].replace('_', ' ')
    return f'{city} ({gmt(at.utcoffset().total_seconds() // 60)})'


def prelim_start(e):
    """UTC start of a UFC card's prelims (its first Prelims bout), or None."""
    if e.get('sport') != 'UFC':
        return None
    starts = [utc_start(u.get('date'), u.get('time')) for u in (e.get('undercard') or [])
              if u.get('card_type') == 'Prelims']
    starts = [s for s in starts if s]
    main = start_of(e)
    starts = [s for s in starts if not main or s < main]
    return min(starts) if starts else None


def time_notes(e, tz=None, est=None, live=False):
    """The one line under a time, as parts: [('est', 'Estimated'), ('night',
    'Fri–Sat night'), ('prelims', utc_dt)] or [('since', utc_dt)] when live."""
    s = local_start(e, tz)
    if not s:
        return []
    if live:
        return [('since', start_of(e))]
    est = e.get('time_estimated') if est is None else est
    out = []
    if est:
        out.append(('est', 'Estimated'))
    if night_hint(s):
        out.append(('night', night_hint(s)))
    p = prelim_start(e)
    if p:
        out.append(('prelims', p))
    return out


# fight state: how long a card counts as "on" after its start
LIVE_HOURS = {'UFC': 3.5, 'Boxing': 5.0}


def fight_state(e, now=None):
    """'' (not started or no time), 'prelims' (UFC prelims on), 'live' (main
    card under way) or 'done' (past the live window: just finished, result to
    come). A past or decided fight is 'done'."""
    if e.get('result') or e.get('is_past'):
        return 'done'
    now = now or now_utc()
    s = start_of(e)
    if not s:
        return ''
    if now < s:
        p = prelim_start(e)
        return 'prelims' if (p and p <= now) else ''
    if now < s + timedelta(hours=LIVE_HOURS.get(e.get('sport'), 4.0)):
        return 'live'
    return 'done'


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------
# ESPN gives UFC events an arena name only; the pages show the city. Every
# arena in the production data (2026-10) is here; "<arena> in <city>" is read
# by rule.
VENUE_CITY = {
    'Etihad Arena': 'Abu Dhabi', 'Madison Square Garden': 'New York', 'Meta APEX': 'Las Vegas',
    'Meta Apex': 'Las Vegas', 'UFC APEX': 'Las Vegas', 'T-Mobile Arena': 'Las Vegas', 'Rogers Place': 'Edmonton',
    'Delta Center': 'Salt Lake City', 'Crypto.com Arena': 'Los Angeles', 'ABHA Arena': 'Abha',
}


def _venue_city(v):
    if v in VENUE_CITY:
        return VENUE_CITY[v]
    m = re.match(r'^(.+?) in ([A-Z][^,]+)$', v)
    if m:
        return m.group(2).strip()
    return None


def place(e):
    """The event's place as shown: the city for a known arena, the source's
    location otherwise, without trailing punctuation."""
    v = (e.get('location') or e.get('venue') or '').strip()
    if v.upper() in ('TBA', 'TBD'):
        return ''
    v = _venue_city(v) or v
    v = v.rstrip(' :;,')
    last = v.split()[-1] if v else ''
    if last.endswith('.') and len(last) > 7:
        v = v[:-1]
    return v


def city(e):
    """The city for tight lines: 'Coliseo Roberto Clemente, San Juan, Puerto
    Rico' -> 'San Juan'; 'Las Vegas, Nevada' -> 'Las Vegas'."""
    parts = [x.strip() for x in place(e).split(',') if x.strip()]
    if not parts:
        return ''
    return parts[-2] if len(parts) >= 3 else parts[0]


def place_line(e):
    """Arena and city for a fight page: 'Etihad Arena · Abu Dhabi',
    'Coliseo Roberto Clemente · San Juan, Puerto Rico', 'London'."""
    v = (e.get('venue') or e.get('location') or '').strip()
    c = _venue_city(v)
    if c:
        arena = re.sub(r' in [A-Z][^,]+$', '', v)
        return f'{arena} · {c}'
    parts = [x.strip() for x in v.rstrip(' :;,').split(',') if x.strip()]
    if len(parts) >= 3:
        return f'{parts[0]} · {", ".join(parts[1:])}'
    return place(e)


def weight_label(w):
    """'Title Junior Middleweight' -> 'Jr middleweight title'."""
    w = (w or '').strip()
    if not w or w.lower() == 'title':
        return 'Title fight' if w else ''
    title = w.lower().startswith('title ')
    w = (w[6:] if title else w).strip().capitalize()
    w = re.sub(r'^Junior ', 'Jr ', w)
    return w + (' title' if title else '')


def event_label(e):
    """UFC -> the event ('UFC 333', 'UFC Fight Night'); boxing -> 'Boxing'."""
    if e.get('sport') == 'UFC':
        return (e.get('event_name') or e.get('title') or 'UFC').split(':')[0].strip() or 'UFC'
    return 'Boxing'


def kick_text(e):
    """What the sport bar cannot say: the event for UFC ('UFC 333'), the weight
    or title for boxing ('Heavyweight title'), or ''."""
    if e.get('sport') == 'UFC':
        return event_label(e)
    return weight_label(e.get('weight_class'))


def fights_n(n):
    """One form for the size of a card, site-wide: '5\u00a0fights'."""
    n = int(n or 0)
    return f'{n}\u00a0fight{"s" if n != 1 else ""}'


def card_size(e):
    return max(int(e.get('fight_count') or 0), len(e.get('undercard') or []) + 1)


def event_key(e):
    """The event's slug (its URL's last part): the /go/ links' event= value."""
    return (e.get('slug') or (e.get('path') or '').rsplit('/', 1)[-1])


def sport_class(e):
    return 'ufc' if e.get('sport') == 'UFC' else 'boxing'


# ---------------------------------------------------------------------------
# the hero: which fights, and what a card shows
# ---------------------------------------------------------------------------
def hero_fights(events, today=None, tz=None, now=None, sport=None, limit=2):
    """The next big fights for the poster cards: site_pages._big_fights' rules
    (numbered UFC events, boxing title fights, big names; both photos real and
    different), not yet finished, soonest first, at most `limit`."""
    import site_pages      # late: site_pages renders with this module
    now = now or now_utc()
    today = today or today_in(tz, now)
    pool = [e for e in events if not sport or e.get('sport') == sport]
    try:
        big = site_pages._big_fights(pool, today)
    except Exception as exc:
        logger.warning(f"hero_fights: {exc}")
        return []
    big = [e for e in big if fight_state(e, now) != 'done' and (local_day(e, tz) or today) >= today]
    big.sort(key=lambda e: (start_of(e) or datetime.combine(local_day(e, tz) or today, datetime.max.time(), UTC)))
    return big[:limit]


def hero_view(e, kind='c1', tz=None, now=None, sport_said=False):
    """Everything a poster card shows, from one event. kind: 'c1' / 'c2' (the
    two cards) or 'solo' (the one big fight). sport_said: the page already
    names the sport (/boxing), so a boxing card's small line does not start
    with "Boxing" ("Heavyweight title · London"; the mock's drop_sport_word)."""
    now = now or now_utc()
    e = title_order(e)
    names = pair_fit(e)
    p1, p2, n_ph = poster_photos(e)
    state = fight_state(e, now)
    live = state in ('live', 'prelims')
    s = local_start(e, tz)
    day = local_day(e, tz)
    today = today_in(tz, now)
    sc = sport_class(e)
    kt = kick_text(e)
    c = city(e)
    if kind == 'solo':
        first = kt or ('UFC' if sc == 'ufc' else 'Boxing')
        rest = ([c] if c else []) + ([fights_n(card_size(e))] if card_size(e) > 1 else [])
    elif sc == 'ufc':
        first, rest = kt or 'UFC', ([c] if c else [])
    else:
        first, rest = 'Boxing', ([kt] if kt else []) + ([c] if c else [])
    if sport_said and sc == 'boxing' and first == 'Boxing' and rest:
        first, rest = rest[0], rest[1:]
    sd = 1 if (kind != 'solo' and n_ph == 0) else names['sd']
    cls = ['rc', 'lead', 'hero', 'card' if kind != 'solo' else 'solo', kind if kind != 'solo' else '', sc, f'n{n_ph}',
           'is-live' if live else '', 'tba2' if names['tba2'] else '', 'sd' if (kind != 'solo' and sd) else '',
           'sp' if (kind != 'solo' and names['sp']) else '', 'l-ph' if p1 else 'l-none', 'r-ph' if p2 else 'r-none']
    style = f'--e1:{names["e1"]};--e2:{names["e2"]};--em-stack:{names["em_stack"]}'
    if kind != 'solo':
        style += f';--est:{names["est"]};--nl:{names["nl"]}'
    return {
        'e': e, 'kind': kind, 'sport': sc, 'cls': ' '.join(x for x in cls if x), 'style': style,
        'names': names, 'p1': p1, 'p2': p2, 'n_photos': n_ph, 'state': state, 'live': live,
        'day': day, 'day_text': day_short(day), 'rel': rel_day(day, today),
        'countdown': countdown(start_of(e), now) if (s and not live) else '',
        'notes': time_notes(e, tz, live=state == 'live') if state != 'prelims' else [('main', start_of(e))],
        'what_first': first, 'what_rest': rest, 'has_time': bool(s),
    }


# ---------------------------------------------------------------------------
# the schedule table
# ---------------------------------------------------------------------------
GROUPS = (
    # id, heading, first day, end day (exclusive), sub-heading, prefix, "No fights listed ..."
    ('week', 'This week', 0, 7, '', 'w', 'this week'),
    ('next', 'Next week', 7, 14, '', 'n', 'next week'),
    ('later', 'Later', 14, None, '', 'l', 'later'),
    ('ahead', 'Further ahead', None, None, 'headline events only', 'a', 'further ahead'),
)


def offset_minutes(dt, tz=None):
    return int(dt.astimezone(zone(tz)).utcoffset().total_seconds() // 60)


def transition(a, b, tz=None):
    """The UTC instant between a and b (aware datetimes) at which the zone's
    offset changes, to the minute."""
    z = zone(tz)
    t0, t1 = a, b
    o0 = t0.astimezone(z).utcoffset()
    while (t1 - t0) > timedelta(minutes=1):
        mid = t0 + (t1 - t0) / 2
        if mid.astimezone(z).utcoffset() == o0:
            t0 = mid
        else:
            t1 = mid
    return t1.replace(second=0, microsecond=0)


def clock_change(prev, e, tz=None, outside=False):
    """A dated row when the zone's clock changes between two timed events:
    {'kind': 'dst', 'outside', 'from', 'to', 'word', 'date_text', 'hm', 'gmt',
    'at'} or None."""
    a, b = start_of(prev), start_of(e)
    if not a or not b or b <= a:
        return None
    oa, ob = offset_minutes(a, tz), offset_minutes(b, tz)
    if oa == ob:
        return None
    at = transition(a, b, tz)
    old = at.astimezone(timezone(timedelta(minutes=oa)))
    d = abs(ob - oa)
    by = 'an hour' if d == 60 else (f'{d // 60} hours' if d % 60 == 0 else f'{d} minutes')
    return {'kind': 'dst', 'outside': outside, 'from': oa, 'to': ob, 'word': 'back' if ob < oa else 'forward',
            'by': by, 'date_text': day_short(old.date()), 'hm': hm(old), 'gmt': gmt(ob), 'at': at,
            'day': at.astimezone(zone(tz)).date()}


def _sort_key(e, tz):
    s = local_start(e, tz)
    d = local_day(e, tz) or date.max
    return (d, s is None, s.timestamp() if s else 0)


def schedule(events, today=None, tz=None, now=None, lead_keys=None, ptr='line', only=None, beyond_keys=()):
    """ONE table for every upcoming event from today, as data for the
    schedule macro: {'groups': [...], 'count': n}. Rows grouped by local day,
    days under This week (today + 6) / Next week (the 7 after) / Later; an event
    from 00:00 to 05:59 joins the group of the evening before. Events in
    `beyond_keys` (listed beyond the full listing) go under Further ahead.
    `lead_keys` {event key: hero card id}: those rows become one-line pointers
    ('Featured above'), or are left out with ptr='drop'.
    A group: {'id', 'name', 'sub', 'prefix', 'when', 'blocks', 'count'}; a block
    is a day {'kind': 'day', 'date', 'iso', 'full', 'dm', 'short', 'rel',
    'soon', 'rows'} or a clock change between days {'kind': 'dst', ...}; a row is
    {'kind': 'ev', 'e'} / {'kind': 'ptr', 'e', 'hid'} / a clock change inside
    the day."""
    now = now or now_utc()
    today = today or today_in(tz, now)
    leads = dict(lead_keys or {})
    beyond = set(beyond_keys or ())
    evs = sorted([title_order(x) for x in events if local_day(x, tz) and local_day(x, tz) >= today],
                 key=lambda x: _sort_key(x, tz))      # an event without a date is not listed

    def off(x):
        nd = night_day(x, tz)
        return max(0, (nd - today).days) if nd else 10 ** 6

    plan = []
    for gid, name, a, b, sub, prefix, when in GROUPS:
        if only and gid not in only:
            continue
        if gid == 'ahead':
            items = [x for x in evs if event_key(x) in beyond]
        else:
            items = [x for x in evs if event_key(x) not in beyond and a <= off(x) and (b is None or off(x) < b)]
        if not items and gid in ('later', 'ahead'):
            continue
        plan.append({'id': gid, 'name': name, 'sub': sub, 'prefix': prefix, 'when': when, 'items': items,
                     'a': a, 'b': b, 'blocks': [], 'count': len(items)})

    def group_of(d):
        k = (d - today).days
        for g in plan:
            if g['id'] != 'ahead' and g['a'] <= k and (g['b'] is None or k < g['b']):
                return g
        return None

    prev = None
    for g in plan:
        by = {}
        for x in g['items']:
            by.setdefault(local_day(x, tz), []).append(x)
        for d in sorted(by):
            first = next((x for x in by[d] if start_of(x)), None)
            if prev is not None and first is not None:
                chg = clock_change(prev, first, tz, outside=True)
                if chg:
                    home = group_of(chg['day'])
                    (home if (home and home is not g) else g)['blocks'].append(chg)
                prev = first
            rows = []
            for x in by[d]:
                if prev is not None and start_of(x) and x is not first:
                    chg = clock_change(prev, x, tz)
                    if chg:
                        rows.append(chg)
                k = event_key(x)
                if k in leads:
                    if ptr == 'line':
                        rows.append({'kind': 'ptr', 'e': x, 'hid': leads[k]})
                else:
                    rows.append({'kind': 'ev', 'e': x})
                if start_of(x):
                    prev = x
            if ptr == 'drop' and not any(r['kind'] == 'ev' for r in rows):
                continue
            n = (d - today).days
            g['blocks'].append({'kind': 'day', 'date': d, 'iso': d.isoformat(), 'full': d.strftime('%A'),
                                'dm': f'{d.day} {d.strftime("%B")}', 'short': day_short(d), 'rel': rel_day(d, today),
                                'soon': 0 <= n <= 1, 'rows': rows})
    for g in plan:
        del g['items'], g['a'], g['b']
    return {'groups': plan, 'count': sum(g['count'] for g in plan), 'today': today}


def row_view(e, tz=None, now=None):
    """A schedule row's parts: {'e', 'sport', 'live', 'notes', 'kick', 'where',
    'where_short', 'em_s', 'tba2', 'cls'}."""
    now = now or now_utc()
    e = title_order(e)
    state = fight_state(e, now)
    live = state == 'live'
    where = place(e)
    short = city(e)
    if len(where) > 30:
        where = short
    sc = sport_class(e)
    kt = kick_text(e)
    cls = ['ev', sc, 'is-live' if live else '', 'has-uc' if e.get('undercard') else '',
           'tba2' if is_tba(e.get('fighter2')) else '', '' if kt else 'nokick']
    return {'e': e, 'sport': sc, 'live': live, 'notes': time_notes(e, tz, live=live), 'kick': kt,
            'where': where, 'where_short': short if short != where else '', 'em_s': list_em(e),
            'tba2': is_tba(e.get('fighter2')), 'cls': ' '.join(x for x in cls if x)}


def undercard_groups(e, results=False):
    """The undercard <details>: [{'name', 'start' (UTC dt or None), 'bouts',
    'cont', 'note'}]. UFC: Main card / Prelims; boxing: Undercard. In a schedule
    a single group of more than six bouts runs on in a second column
    ('Undercard, cont.'); in results each group says how many have a result."""
    uc = e.get('undercard') or []
    if not uc:
        return []
    if e.get('sport') == 'UFC':
        main = [x for x in uc if x.get('card_type') != 'Prelims']
        pre = [x for x in uc if x.get('card_type') == 'Prelims']
        groups = ([{'name': 'Main card', 'start': start_of(e), 'bouts': main}] if main else []) + \
                 ([{'name': 'Prelims', 'start': prelim_start(e), 'bouts': pre}] if pre else [])
    else:
        groups = [{'name': 'Undercard', 'start': None, 'bouts': uc}]
    for g in groups:
        g['cont'], g['note'] = False, ''
        if results:
            nres = sum(1 for x in g['bouts'] if x.get('result'))
            g['note'] = f'{nres} of {len(g["bouts"])} with a result' if nres < len(g['bouts']) else ''
    if not results and len(groups) == 1 and len(groups[0]['bouts']) > 6:
        g = groups[0]
        h = (len(g['bouts']) + 1) // 2
        groups = [dict(g, bouts=g['bouts'][:h]), dict(g, name=f'{g["name"]}, cont.', bouts=g['bouts'][h:], cont=True)]
    k = 0
    for g in groups:
        g['k0'] = k
        k += len(g['bouts'])
    return groups


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
ROW_SPAN = {4: 3, 3: 4, 2: 6, 1: 12}
_CODE_WORDS = {'UD': 'Unanimous decision', 'SD': 'Split decision', 'MD': 'Majority decision',
               'TD': 'Technical decision', 'DEC': 'Decision', 'PTS': 'Points decision', 'KO': 'Knockout',
               'TKO': 'Technical knockout', 'SUB': 'Submission', 'RTD': 'Retirement', 'DQ': 'Disqualification'}


def method_parts(r):
    """A result's method as (code, detail, words): ('SUB', 'R5 2:46',
    'Rear-naked choke'), ('UD', '12 rds', 'Unanimous decision'),
    ('DRAW', '5 rds', 'Majority draw'), ('NC', 'R2 1:12', 'No contest (...)').
    Unknown methods keep their words and an empty code. None without a result."""
    if not r or not isinstance(r, dict):
        return None
    m = (r.get('method') or '').strip()
    rd, tm = r.get('round'), r.get('time')
    detail = f'R{rd} {tm}' if (rd and tm) else (f'{rd} rds' if rd else '')
    inner = m[m.find('(') + 1:m.find(')')].strip() if ('(' in m and ')' in m) else ''
    head = (m.split('(')[0].strip() if m else '').lower()
    outcome = r.get('outcome')
    if outcome == 'draw':
        kind = inner or (head.replace('draw', '').strip() if 'draw' in head else '')
        return 'DRAW', detail, (kind.capitalize() + ' draw') if kind and kind != 'decision' else 'Draw'
    if outcome == 'nc':
        return 'NC', detail, 'No contest' + (f' ({inner})' if inner else '')
    up = m.upper()
    if head.startswith('submission') or up == 'SUB':
        return 'SUB', detail, inner.capitalize() if inner else 'Submission'
    if head.startswith('technical decision'):
        return 'TD', detail, 'Technical decision'
    if head.startswith('decision'):
        code = {'unanimous': 'UD', 'split': 'SD', 'majority': 'MD', 'technical': 'TD'}.get(inner.lower(), 'DEC')
        return code, detail, (inner.capitalize() + ' decision') if inner else 'Decision'
    if head.startswith('tko') or head.startswith('ko'):
        code = 'TKO' if head.startswith('tko') else 'KO'
        return code, detail, _CODE_WORDS[code] + (f' ({inner.lower()})' if inner else '')
    if head.startswith('disqualification') or up == 'DQ':
        return 'DQ', detail, 'Disqualification' + (f' ({inner})' if inner else '')
    if head.startswith('retirement') or head.startswith('corner') or up == 'RTD':
        return 'RTD', detail, 'Retirement' + (f' ({inner})' if inner else '')
    if head.startswith('points') or up == 'PTS':
        return 'PTS', detail, 'Points decision'
    if up in _CODE_WORDS:
        return up, detail, _CODE_WORDS[up]
    return '', detail, m


def result_sides(e):
    """The two lines of a box score, winner first: [{'name', 'img', 'won',
    'lost', 'second'}] ('second': the event's fighter2, for production's 'av b'
    classes). Draws, no contests and pending results keep the card's order."""
    r = e.get('result') or {}
    win = r.get('outcome') == 'win'
    w1 = win and r.get('winner') == e.get('fighter1')
    w2 = win and r.get('winner') == e.get('fighter2')
    a = {'name': e.get('fighter1'), 'img': e.get('fighter1_image'), 'won': w1, 'lost': w2, 'second': False}
    b = {'name': e.get('fighter2'), 'img': e.get('fighter2_image'), 'won': w2, 'lost': w1, 'second': True}
    return [b, a] if w2 else [a, b]


def result_text(e):
    """The box score's screen-reader sentence: 'Brendan Allen won, Rear-naked
    choke, R5 2:46.' / 'Majority draw, 12 rds.' / ''."""
    r = e.get('result')
    mp = method_parts(r)
    if not mp:
        return ''
    code, detail, words = mp
    tail = f', {detail}' if detail else ''
    if r.get('outcome') == 'win' and r.get('winner'):
        return f'{r["winner"]} won, {words or code}{tail}.'
    return f'{words or code}{tail}.'


def bout_result(u):
    """One undercard bout's result for a results list: {'kind': 'win' | 'draw' |
    'nc' | 'none', 'first', 'second', 'code', 'detail', 'words'} (winner first)."""
    r = u.get('result')
    a, b = u.get('fighter1'), u.get('fighter2')
    mp = method_parts(r)
    if r and mp and r.get('outcome') == 'win' and r.get('winner') in (a, b):
        w, l = (a, b) if r['winner'] == a else (b, a)
        return {'kind': 'win', 'first': w, 'second': l, 'code': mp[0], 'detail': mp[1], 'words': mp[2]}
    if r and mp and r.get('outcome') in ('draw', 'nc'):
        return {'kind': r['outcome'], 'first': a, 'second': b, 'code': mp[0], 'detail': mp[1], 'words': mp[2]}
    return {'kind': 'none', 'first': a, 'second': b, 'code': '', 'detail': '', 'words': ''}


def pack(k):
    """Box scores per row: all in one row up to four; more -> the fewest rows of
    at most four, balanced, the rows with fewer (wider) cards first, so the
    newest results get the widest cards and no row ends in a hole."""
    if k <= 0:
        return []
    if k <= 4:
        return [k]
    r = -(-k // 4)
    base, extra = divmod(k, r)
    return [base] * (r - extra) + [base + 1] * extra


def results_rows(items):
    """[(item, span)] for box scores on the 12-column grid: span 3 / 4 / 6 / 12
    by how many share the item's row (pack())."""
    out, i = [], 0
    for n in pack(len(items)):
        out += [(x, ROW_SPAN[n]) for x in items[i:i + n]]
        i += n
    return out


def newest_first(items, tz=None):
    """Results order: newest local day first, timed before untimed, latest first."""
    def k(x):
        s = local_start(x, tz)
        return (local_day(x, tz) or date.min, s is not None, s.timestamp() if s else 0)
    return sorted(items, key=k, reverse=True)


def results_split(items, tz=None):
    """(decided, pending, no_record): box scores, the Result pending rows (no
    result yet, inside the grace window: the event's result_pending flag) and
    the older fights with no result on record (folded into one line)."""
    evs = newest_first(items, tz)
    decided = [x for x in evs if x.get('result')]
    pending = [x for x in evs if not x.get('result') and x.get('result_pending')]
    none = [x for x in evs if not x.get('result') and not x.get('result_pending')]
    return decided, pending, none


app.jinja_env.globals['ds'] = sys.modules[__name__]
