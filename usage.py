"""
Cookie-free usage counting: page views and taps on page elements.

Nothing that identifies a person is stored — no cookie, no IP address, no
user id. Each record is: when, what (view or tap), which page type, which
element, and two fields used only to separate people from scripts (a bot flag
derived from the user agent, and whether the browser sent a language). The
same model as Plausible / Fathom: aggregate counts, not tracking.

Records go to DATA_DIR/usage.jsonl, one JSON object per line, trimmed to the
newest ~200k lines. stats() aggregates them for the debug API.

"Real" = not a known bot, the browser sent Accept-Language, and (for taps)
the beacon came from a page on this site. The same rule as the watch-link log.
"""

import json
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
USAGE_FILE = os.path.join(DATA_DIR, 'usage.jsonl')
MAX_LINES = 200_000
_lock = threading.Lock()
_writes = 0

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
_DETAIL = re.compile(r'^[\w .+:/-]{0,60}$')

PAGE_TYPES = (('/results', 'results'), ('/ufc', 'ufc page'), ('/boxing-event/', 'boxing fight page'),
              ('/boxing', 'boxing page'), ('/event/', 'ufc fight page'), ('/privacy', 'privacy'))

# Taps the page reports (see static/js/list.js). Anything else is dropped.
TAP_NAMES = {'card', 'big_card', 'filter', 'undercard_open', 'undercard_close', 'full_card', 'watch',
             'calendar_add', 'calendar_feed', 'nav', 'search_open', 'search', 'tab', 'crumb', 'foot_link',
             'rail_scroll'}


def page_type(path_or_url):
    path = re.sub(r'^https?://[^/]+', '', path_or_url or '').split('?')[0].split('#')[0]
    if path in ('', '/'):
        return 'homepage'
    for prefix, name in PAGE_TYPES:
        if path.startswith(prefix):
            return name
    return 'other'


def record(kind, page, name=None, detail=None, bot=False, lang=None, referer_ok=True):
    """Append one record. Never raises."""
    global _writes
    rec = {'ts': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'kind': kind, 'page': page,
           'name': name, 'detail': detail, 'bot': bool(bot), 'lang': bool(lang), 'ref': bool(referer_ok)}
    try:
        with _lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(USAGE_FILE, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(rec) + '\n')
            _writes += 1
            if _writes % 5000 == 0:
                _trim()
    except Exception:
        pass
    return rec


def _trim():
    try:
        with open(USAGE_FILE, encoding='utf-8') as fh:
            lines = fh.readlines()
        if len(lines) > MAX_LINES:
            tmp = USAGE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                fh.writelines(lines[-MAX_LINES // 2:])
            os.replace(tmp, USAGE_FILE)
    except Exception:
        pass


def valid_tap(name, detail):
    return bool(name) and name in TAP_NAMES and (detail is None or (isinstance(detail, str) and _DETAIL.match(detail)))


def is_real(rec):
    return not rec.get('bot') and rec.get('lang') and rec.get('ref', True)


def stats(days=30):
    """Views and taps per page type, per element, per day — real visitors
    only, with the bot/script counts shown separately so nothing is hidden."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    views = defaultdict(int)          # page -> n
    views_day = defaultdict(int)      # day -> n
    taps = defaultdict(int)           # (page, name, detail) -> n
    taps_by_name = defaultdict(int)
    taps_day = defaultdict(int)
    dropped = {'bot': 0, 'no_language': 0, 'not_from_site': 0}
    total = 0
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE, encoding='utf-8') as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('ts', '') < cutoff:
                    continue
                total += 1
                if r.get('bot'):
                    dropped['bot'] += 1
                    continue
                if not r.get('lang'):
                    dropped['no_language'] += 1
                    continue
                if not r.get('ref', True):
                    dropped['not_from_site'] += 1
                    continue
                day = r['ts'][:10]
                if r['kind'] == 'view':
                    views[r['page']] += 1
                    views_day[day] += 1
                elif r['kind'] == 'tap':
                    taps[(r['page'], r['name'], r.get('detail'))] += 1
                    taps_by_name[r['name']] += 1
                    taps_day[day] += 1
    rates = {}
    for page, n in views.items():
        per = defaultdict(int)
        for (p, name, _d), k in taps.items():
            if p == page:
                per[name] += k
        rates[page] = {'views': n, 'taps': dict(sorted(per.items(), key=lambda kv: -kv[1])),
                       'tap_rate_pct': {name: round(100.0 * k / n, 1) for name, k in per.items()}}
    return {
        'days': days,
        'records': total,
        'dropped': dropped,
        'views_by_page': dict(sorted(views.items(), key=lambda kv: -kv[1])),
        'views_by_day': dict(sorted(views_day.items())),
        'taps_by_name': dict(sorted(taps_by_name.items(), key=lambda kv: -kv[1])),
        'taps_by_day': dict(sorted(taps_day.items())),
        'taps_detail': sorted(({'page': p, 'name': n, 'detail': d, 'count': k} for (p, n, d), k in taps.items()),
                              key=lambda x: -x['count'])[:60],
        'per_page': rates,
    }
