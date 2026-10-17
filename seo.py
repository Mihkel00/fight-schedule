"""
Search-engine plumbing: page versions and IndexNow, sitemap, robots.txt,
llms.txt, and search titles/descriptions for fight pages.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import json
import locks as _locks
import os
import requests
import runs as _runs
import structured_data as _ld
import threading
from datetime import datetime
from flask import abort, make_response
from core import app, data_path, logger
import fight_store
import formatting
import pipeline
import profile_store
import site_pages
import design
import preview_service


INDEXNOW_KEY = os.environ.get('INDEXNOW_KEY', '')


def public_event_urls(fights):
    """All public page URLs, same set as the sitemap."""
    urls = ['https://fightschedule.live/',
            'https://fightschedule.live/ufc',
            'https://fightschedule.live/boxing']
    seen = set()
    for fight in fights:
        if fight.get('sport') == 'UFC' and fight.get('card_type') != 'Prelims':
            if fight['event_name'] in seen:
                continue
            seen.add(fight['event_name'])
            slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
            urls.append(f"https://fightschedule.live/event/{slug}")
        elif fight.get('sport') == 'Boxing' and fight.get('is_main_event'):
            slug = f"{formatting._to_slug(fight['fighter1'])}-vs-{formatting._to_slug(fight['fighter2'])}-{fight['date']}"
            if slug in seen:
                continue
            seen.add(slug)
            urls.append(f"https://fightschedule.live/boxing-event/{slug}")
    return urls


def ping_indexnow(urls):
    """Submit changed/removed URLs to IndexNow. Best-effort."""
    if not INDEXNOW_KEY or not urls:
        return
    try:
        urls = list(dict.fromkeys(urls))
        resp = requests.post(
            'https://api.indexnow.org/indexnow',
            json={
                'host': 'fightschedule.live',
                'key': INDEXNOW_KEY,
                'keyLocation': 'https://fightschedule.live/indexnow-key.txt',
                'urlList': urls[:500],
            },
            timeout=10,
        )
        logger.info(f"IndexNow ping: {resp.status_code} for {len(urls)} URLs")
    except Exception as e:
        logger.warning(f"IndexNow ping failed: {e}")


# ── Page versions: a content fingerprint per public URL so the sitemap's lastmod
# and IndexNow pings reflect real changes (result added, fighter swapped, time
# moved) rather than the fight date or "every scrape".
PAGE_VERSIONS_FILE = data_path('page_versions.json')


_versions_lock = threading.Lock()


def _load_versions():
    try:
        with open(PAGE_VERSIONS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _fight_signature(f):
    r = f.get('result') or {}
    return '|'.join(str(x) for x in (
        f.get('fighter1'), f.get('fighter2'), f.get('date'), f.get('time'), f.get('venue'),
        f.get('card_type'), f.get('weight_class'), f.get('streaming'),
        r.get('winner'), r.get('method'), r.get('round'), r.get('time'),
    ))


def _event_fingerprints(fights):
    """url -> sha1 of that event's fights (results included). Boxing undercards
    share their main event's URL via (venue, date)."""
    import hashlib
    fights = profile_store.enrich_fights([dict(f) for f in fights])
    ufc_url, box_url = {}, {}
    for f in fights:
        if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims' and f['event_name'] not in ufc_url:
            slug = f"{f['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{f['date']}"
            ufc_url[f['event_name']] = f"https://fightschedule.live/event/{slug}"
        elif f.get('sport') == 'Boxing' and f.get('is_main_event'):
            slug = f"{formatting._to_slug(f['fighter1'])}-vs-{formatting._to_slug(f['fighter2'])}-{f['date']}"
            box_url[(f.get('venue'), f.get('date'))] = f"https://fightschedule.live/boxing-event/{slug}"
    groups = {}
    for f in fights:
        url = ufc_url.get(f.get('event_name')) if f.get('sport') == 'UFC' else box_url.get((f.get('venue'), f.get('date')))
        if url:
            groups.setdefault(url, []).append(_fight_signature(f))
    return {url: hashlib.sha1('\n'.join(sorted(sigs)).encode()).hexdigest() for url, sigs in groups.items()}


def sync_page_versions(fights, reason=''):
    """Compare current content with stored fingerprints; bump lastmod for changed
    pages, drop removed ones, and ping IndexNow with just those URLs."""
    if not fights:
        return {'changed': [], 'removed': []}
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    with _versions_lock, _locks.job_lock('versions', wait_seconds=15):
        stored = _load_versions()
        current = _event_fingerprints(fights + fight_store.archived_fights(fights))
        changed = [u for u, h in current.items() if stored.get(u, {}).get('hash') != h]
        removed = [u for u in stored if u not in current]
        for u in changed:
            stored[u] = {'hash': current[u], 'lastmod': now}
        for u in removed:
            stored.pop(u, None)
        if changed or removed:
            _runs.write_json_atomic(PAGE_VERSIONS_FILE, stored)
    if changed or removed:
        logger.info(f"Page versions ({reason}): {len(changed)} changed, {len(removed)} removed")
        hubs = ['https://fightschedule.live/']
        if any('/event/' in u for u in changed + removed):
            hubs.append('https://fightschedule.live/ufc')
        if any('/boxing-event/' in u for u in changed + removed):
            hubs.append('https://fightschedule.live/boxing')
        ping_indexnow(changed + removed + hubs)
    return {'changed': changed, 'removed': removed}


def page_lastmod(url, fallback):
    return _load_versions().get(url, {}).get('lastmod', fallback)


@app.route('/indexnow-key.txt')
def indexnow_key_file():
    """Key file proving domain ownership to IndexNow."""
    if not INDEXNOW_KEY:
        abort(404)
    response = make_response(INDEXNOW_KEY)
    response.headers['Content-Type'] = 'text/plain'
    return response


TITLE_MAX = 65


DESC_MAX = 160


def _long_date(iso):
    """'2026-10-24' -> 'Saturday 24 October 2026' (the date in UTC)."""
    try:
        d = datetime.strptime(iso, '%Y-%m-%d')
    except (TypeError, ValueError):
        return iso or 'date TBA'
    return f"{d:%A} {d.day} {d:%B %Y}"


def _place_text(venue, location):
    """'London' + 'London' -> 'London'; drops TBA and repeats."""
    parts = []
    for x in (venue, location):
        x = (x or '').strip()
        if x and x.upper() != 'TBA' and not any(x.lower() in p.lower() for p in parts):
            parts = [p for p in parts if p.lower() not in x.lower()] + [x]
    return ', '.join(parts)


def _fit_title(*candidates):
    for c in candidates:
        if len(c) <= TITLE_MAX:
            return c
    return candidates[-1]


def _boxing_kind(weight_class):
    """'Title Heavyweight' -> 'heavyweight title fight'; 'Middleweight' -> 'middleweight bout'."""
    wc = (weight_class or '').strip()
    title = wc.startswith('Title')
    division = wc[5:].strip().lower() if title else wc.lower()
    return f"{division + ' ' if division else ''}{'title fight' if title else 'bout'}"


def fight_page_seo(sport, name, date_iso, venue, location, is_past, kind=None, streaming=None):
    """(page_title, meta_description) for a UFC event or boxing card page.
    name: 'UFC 333: Volkanovski vs. Evloev' or 'Daniel Dubois vs Fabio Wardley'."""
    when = _long_date(date_iso)
    place = _place_text(venue, location)
    sep = 'at' if sport == 'UFC' else 'in'

    def desc_fit(make):
        """The fullest description that fits ~160 characters: with the place, then without."""
        for at in ((f" {sep} {place}" if place else ''), ''):
            d = make(at)
            if len(d) <= DESC_MAX:
                return d
        return d

    if sport == 'UFC':
        if is_past:
            title = _fit_title(f"{name}: Results & Full Fight Card", f"{name}: Results", name)
            desc = desc_fit(lambda at: f"{name} results and the full fight card, {when}{at}.")
        else:
            title = _fit_title(f"{name}: Start Time, Date & Fight Card", f"{name}: Start Time & Card", name)
            desc = desc_fit(lambda at: f"{name}, {when}{at}. Start times in your time zone, full card and where to watch.")
    else:
        if is_past:
            title = _fit_title(f"{name}: Result & Full Card", f"{name}: Result", name)
            desc = desc_fit(lambda at: f"{name} result: {kind or 'bout'}, {when}{at}. Plus the full undercard.")
        else:
            title = _fit_title(f"{name}: Start Time, Date & Full Card", f"{name}: Start Time & Card", name)
            watch = f" ({streaming})" if streaming else ''
            desc = desc_fit(lambda at: f"{name}, {kind or 'bout'}, {when}{at}. Start time in your time zone, "
                                       f"full undercard and where to watch{watch}.")
    return title, desc


def page_worth_indexing(main, n_other, preview_entry):
    """The sitemap's side of design.worth_indexing: the main event's stored tapes, the other bouts on the
    card, and whether a checked preview is on file (a grounded entry that passed its check)."""
    has_tape = bool(main.get('fighter1_tape') or main.get('fighter2_tape'))
    has_preview = bool(preview_entry and preview_entry.get('grounded') and preview_entry.get('ok'))
    return design.worth_indexing(main, n_other, has_tape, has_preview)


# ============================================================================
# SEO Routes
@app.route('/sitemap.xml')
def sitemap():
    """Generate dynamic sitemap"""
    from xml.sax.saxutils import escape as xml_escape
    fights = pipeline.fights_for_pages()
    today = datetime.now().strftime('%Y-%m-%d')
    last_result = max((f['date'] for f in fights if f.get('is_past') and f.get('date')), default=today)

    pages = []
    versions = _load_versions()
    def newest(prefix):
        stamps = [v.get('lastmod', '') for u, v in versions.items() if prefix in u]
        return max(stamps)[:10] if stamps else today
    pages.append({'loc': 'https://fightschedule.live/', 'lastmod': newest('/'), 'changefreq': 'daily', 'priority': '1.0'})
    pages.append({'loc': 'https://fightschedule.live/ufc', 'lastmod': newest('/event/'), 'changefreq': 'daily', 'priority': '0.9'})
    pages.append({'loc': 'https://fightschedule.live/boxing', 'lastmod': newest('/boxing-event/'), 'changefreq': 'daily', 'priority': '0.9'})
    pages.append({'loc': 'https://fightschedule.live/results', 'lastmod': last_result, 'changefreq': 'daily', 'priority': '0.8'})
    pages.append({'loc': 'https://fightschedule.live/privacy', 'lastmod': site_pages.PRIVACY_UPDATED.isoformat(), 'changefreq': 'yearly', 'priority': '0.3'})

    # UFC events — one URL per event (first non-prelim fight defines the
    # canonical date; must stay in sync with the redirect in event_detail)
    previews = preview_service.load_previews()
    ufc_fights = [f for f in fights if f.get('sport') == 'UFC' and f.get('card_type') != 'Prelims']
    ufc_counts = {}
    for f in fights:
        if f.get('sport') == 'UFC':
            ufc_counts[f.get('event_name')] = ufc_counts.get(f.get('event_name'), 0) + 1
    seen = set()
    for fight in ufc_fights:
        if fight['event_name'] in seen:
            continue
        seen.add(fight['event_name'])
        slug = f"{fight['event_name'].lower().replace(' ', '-').replace(':', '').replace(',', '')}-{fight['date']}"
        url = f"https://fightschedule.live/event/{slug}"
        if not page_worth_indexing(fight, ufc_counts.get(fight['event_name'], 1) - 1, previews.get(slug)):
            continue
        pages.append({'loc': url, 'lastmod': versions.get(url, {}).get('lastmod', fight['date']), 'changefreq': 'daily', 'priority': '0.8'})

    # Boxing events - all main events
    boxing_fights = [f for f in fights if f.get('sport') == 'Boxing' and f.get('is_main_event')]
    box_counts = {}
    for f in fights:
        if f.get('sport') == 'Boxing':
            k = (f.get('venue', ''), f.get('date', ''))
            box_counts[k] = box_counts.get(k, 0) + 1
    seen = set()
    for fight in boxing_fights:
        # Must use the same slug rules as the boxing_event_detail matcher,
        # otherwise the sitemap emits URLs that 404 (e.g. names with periods)
        slug = f"{formatting._to_slug(fight['fighter1'])}-vs-{formatting._to_slug(fight['fighter2'])}-{fight['date']}"
        pid = preview_service.boxing_preview_id(fight['fighter1'], fight['fighter2'], fight['date'])
        if not page_worth_indexing(fight, box_counts.get((fight.get('venue', ''), fight.get('date', '')), 1) - 1, previews.get(pid)):
            continue
        if slug not in seen:
            url = f"https://fightschedule.live/boxing-event/{slug}"
            pages.append({'loc': url, 'lastmod': versions.get(url, {}).get('lastmod', fight['date']), 'changefreq': 'daily', 'priority': '0.7'})
            seen.add(slug)

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for p in pages:
        loc = xml_escape(p['loc'])
        xml += f'  <url>\n    <loc>{loc}</loc>\n    <lastmod>{p["lastmod"]}</lastmod>\n    <changefreq>{p["changefreq"]}</changefreq>\n    <priority>{p["priority"]}</priority>\n  </url>\n'
    xml += '</urlset>'

    response = make_response(xml)
    response.headers['Content-Type'] = 'application/xml'
    return response


@app.route('/robots.txt')
def robots():
    """Generate robots.txt. AI search / training crawlers are welcome, but a
    crawler obeys only the most specific group naming it, so every group must
    carry the same disallows (admin, affiliate redirects, debug API)."""
    agents = ['*', 'GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'Claude-Web', 'anthropic-ai',
              'PerplexityBot', 'Google-Extended', 'Googlebot', 'Bytespider', 'CCBot', 'cohere-ai',
              'Amazonbot', 'YouBot', 'Meta-ExternalAgent']
    rules = 'Allow: /\nDisallow: /admin/\nDisallow: /go/\nDisallow: /api/\nDisallow: /health\n'
    groups = [f'User-agent: {ua}\n{rules}' for ua in agents]
    txt = groups[0] + '\n# AI search and training crawlers\n' + '\n'.join(groups[1:]) + \
        '\nSitemap: https://fightschedule.live/sitemap.xml\n'
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@app.route('/llms.txt')
def llms_txt():
    """Plain-text guide for AI assistants and crawlers: what the site covers,
    how times work, and the current schedule and recent results with links.
    Generated from live data so it is never stale."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo('America/New_York')
    fights = pipeline.fetch_fights()
    upcoming = fight_store.upcoming_only(fights)
    past = fight_store.recent_results(fights)

    def when(ev):
        start = _ld._start(ev['date'], ev.get('time'))
        if not start:
            return datetime.strptime(ev['date'], '%Y-%m-%d').strftime('%a %d %b %Y') + ', time TBA'
        utc = start.replace(tzinfo=ZoneInfo('UTC'))
        local = utc.astimezone(et)
        est = ' (estimated)' if ev.get('time_estimated') else ''
        return (f"{local.strftime('%a %d %b %Y, %I:%M %p').replace(' 0', ' ')} ET / "
                f"{utc.strftime('%H:%M')} UTC {utc.strftime('%a %d %b').replace(' 0', ' ')}{est}")

    def result_line(ev):
        r = ev.get('result') or {}
        if r.get('outcome') == 'win':
            how = ', '.join(x for x in (r.get('method'), f"round {r['round']}" if r.get('round') else None, r.get('time')) if x)
            return f"{r['winner']} def. {r['loser']}" + (f" ({how})" if how else '')
        if r.get('outcome') == 'draw':
            return 'Draw'
        if r.get('outcome') == 'nc':
            return 'No contest'
        return None

    lines = []
    for sport, label in (('UFC', 'UFC'), ('Boxing', 'Boxing')):
        evs, _ = site_pages._group_events_for_landing(upcoming, sport)
        lines.append(f"\n## Upcoming {label} events\n")
        if not evs:
            lines.append('- None listed right now.')
        for ev in evs[:15]:
            parts = [f"**{ev['title']}**" + (f" ({ev['fighter1']} vs {ev['fighter2']})" if sport == 'UFC' else ''),
                     when(ev), ev.get('venue') or 'venue TBA']
            if ev.get('weight_class'):
                parts.append(ev['weight_class'])
            if sport == 'UFC':
                parts.append('broadcast: Paramount+ (US, Latin America, Australia); UFC Fight Pass in most other countries')
            elif ev.get('streaming'):
                parts.append(f"broadcast: {ev['streaming']}")
            lines.append('- ' + ' — '.join(parts) + f" — {ev['url']}")
    results = []
    for sport in ('UFC', 'Boxing'):
        evs, _ = site_pages._group_events_for_landing(past, sport)
        results += [ev for ev in evs if ev.get('result')]
    results.sort(key=lambda ev: ev['date'], reverse=True)
    lines.append('\n## Recent results (last 30 days)\n')
    if not results:
        lines.append('- None yet.')
    for ev in results[:20]:
        title = ev['title'] if ev.get('event_name') else f"{ev['fighter1']} vs {ev['fighter2']}"
        lines.append(f"- {ev['date']} — {title}: {result_line(ev)} — {ev['url']}")

    updated = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    txt = f"""# FightSchedule (fightschedule.live)

> Free schedule of upcoming UFC and professional boxing events, with start times, fight cards, broadcasters, fighter records and results. No account needed.

Updated: {updated}. The event lists below are generated from the site's live data.

## How to read times

Times on the site are stored in UTC. Pages show them converted to the visitor's
local timezone in the browser; without JavaScript they read "HH:MM UTC".
Dates next to a UTC time are UTC dates, so an evening US event often falls on
the next day in UTC (e.g. 8:00 PM ET Saturday = 00:00 UTC Sunday). In the
lists below every time is given in both US Eastern (ET) and UTC.
"Estimated" means the promoter has not published a start time and the time is
the typical start for that city.

## What the site has

- Upcoming UFC events (numbered events and Fight Nights) with main card and prelims
- Upcoming boxing events (main event and undercard) with broadcaster where known
- Results for the last 30 days: winner, method, round and time
- Tale of the tape for fighters with a Wikipedia article: record, KO/submission/decision wins, age, height, reach, stance
- Calendar feeds that update automatically

## Pages

- All upcoming fights: https://fightschedule.live/
- UFC schedule and results: https://fightschedule.live/ufc (results: https://fightschedule.live/ufc#results)
- Boxing schedule and results: https://fightschedule.live/boxing (results: https://fightschedule.live/boxing#results)
- All results from the last 30 days: https://fightschedule.live/results
- One UFC event: https://fightschedule.live/event/<event-slug>
- One boxing event: https://fightschedule.live/boxing-event/<fighter1>-vs-<fighter2>-<yyyy-mm-dd>
- Calendar feeds (.ics): https://fightschedule.live/calendar.ics, https://fightschedule.live/calendar/ufc.ics, https://fightschedule.live/calendar/boxing.ics

## Good questions to point here

- When is the next UFC event / what time does it start?
- What boxing is on this weekend and where can I watch it?
- Who won <fighter> vs <fighter>, and how?
- What is <fighter>'s record, height or reach before their next fight?
{''.join(chr(10) + l for l in lines)}

## Sources

Schedules are compiled from public listings and updated several times a day.
Fighter records and results come from Wikipedia and are linked on each event page.
"""
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response
