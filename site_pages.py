"""
Visitor pages: homepage, results, UFC/boxing pages, fight pages, privacy.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import affiliates as _aff
import os
import re
from datetime import date, datetime, timedelta
from flask import abort, redirect, render_template, request
from core import app, logger
import design
import fight_store
import formatting
import photos
import pipeline
import preview_service
import seo


_NUMBERED_UFC = re.compile(r'^UFC \d+\b')


def _big_fights(events, today, limit=6, horizon_days=90):
    """Lead cards for the homepage: numbered UFC events, boxing title fights and
    big-name fights in the next `horizon_days`, soonest first -- only when both
    fighters have real, different photos (a lead card with silhouettes or one
    photo twice looks broken)."""
    horizon = (today + timedelta(days=horizon_days)).isoformat()
    today_iso = today.isoformat()
    window = [e for e in events if today_iso <= e['date'] <= horizon
              and e['fighter1'] != 'TBA' and e['fighter2'] != 'TBA']

    def is_big(e):
        if e['sport'] == 'UFC' and _NUMBERED_UFC.match(e.get('event_name') or ''):
            return True
        if e['sport'] == 'Boxing' and (e.get('weight_class') or '').startswith('Title'):
            return True
        return fight_store.is_big_name_fight(e)

    big = [e for e in window if is_big(e) and photos._two_distinct_photos(e)][:limit]
    if not big:
        scored = sorted(window, key=lambda e: (-fight_store.score_fight_for_featuring(
            dict(e, is_main_event=True), today), e['date']))
        big = [e for e in scored if photos._two_distinct_photos(e)][:1]
    return big


def _hero_and_schedule(events, limit=2, ids=('lead', 'lead2')):
    """The next big fights for a page's poster cards (design.hero_fights) and
    ONE schedule table of `events`, with the poster fights' rows as pointer
    lines ("Featured above"). Server-rendered in UTC; site.js regroups it."""
    bigs = design.hero_fights(events, limit=limit)
    sch = design.schedule(events, lead_keys={design.event_key(b): hid for b, hid in zip(bigs, ids)})
    return bigs, sch


# The home's "Latest results" covers the last 10 days (the full 30 are on /results).
HOME_RESULTS_DAYS = 10


@app.route('/')
def home():
    logger.info("--> Home page accessed")
    all_fights = pipeline.fetch_fights()
    fights = fight_store.upcoming_only(all_fights)
    logger.info(f"  Rendering {len(fights)} upcoming fights")

    events = (_group_events_for_landing(fights, 'UFC')[0] +
              _group_events_for_landing(fights, 'Boxing')[0])
    events.sort(key=lambda e: (e['date'] or '9999',
                               e['time'] if e['time'] and ':' in str(e['time']) else '99:99'))
    for e in events:
        e['slug'] = e['path'].rsplit('/', 1)[-1]
    big = _big_fights(events, date.today())     # the ItemList's order, as before the redesign
    for e in big:
        logger.info(f"  Big fight: {e['fighter1']} vs {e['fighter2']} ({e['date']})")
    bigs, sch = _hero_and_schedule(events)

    past = fight_store.recent_results(all_fights)
    cutoff = (date.today() - timedelta(days=HOME_RESULTS_DAYS)).isoformat()
    recent = [e for e in (_group_events_for_landing(past, 'UFC')[0] + _group_events_for_landing(past, 'Boxing')[0])
              if (e['date'] or '') >= cutoff]

    # Every upcoming bout, for the search box
    search_fights = []
    for f in fights:
        if f.get('sport') == 'Boxing':
            path = f"/boxing-event/{formatting._to_slug(f['fighter1'])}-vs-{formatting._to_slug(f['fighter2'])}-{f['date']}"
            if not f.get('is_main_event'):
                main = next((e for e in events if e['sport'] == 'Boxing' and e['date'] == f['date']
                             and e['venue'] == f.get('venue', '')), None)
                path = main['path'] if main else path
        else:
            path = f"/event/{(f.get('event_name') or '').lower().replace(' ', '-').replace(':', '').replace(',', '')}-{f['date']}"
        search_fights.append({
            'fighter1': f.get('fighter1', ''), 'fighter2': f.get('fighter2', ''),
            'fighter1_image': f.get('fighter1_image') or photos.get_fighter_image(f.get('fighter1', '')),
            'fighter2_image': f.get('fighter2_image') or photos.get_fighter_image(f.get('fighter2', '')),
            'event_name': f.get('event_name') or '', 'venue': f.get('venue') or '',
            'date': f.get('date', ''), 'time': f.get('time'),
            'time_estimated': bool(f.get('time_estimated')), 'sport': f.get('sport', ''),
            'path': path,
        })

    return render_template('index.html', events=events, big=big, bigs=bigs, sch=sch, recent=recent,
                           recent_days=HOME_RESULTS_DAYS, search_fights=search_fights)


_MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December']


def _undercard(bouts, main, prelims_last=False):
    """The other bouts on the same card as `main`, in card order (UFC: main card
    before prelims)."""
    rest = [b for b in bouts if b is not main]
    if prelims_last:
        rest = [b for b in rest if b.get('card_type') != 'Prelims'] + \
               [b for b in rest if b.get('card_type') == 'Prelims']
    return [{'fighter1': b.get('fighter1', ''), 'fighter2': b.get('fighter2', ''),
             'weight_class': b.get('weight_class', ''), 'card_type': b.get('card_type') or '',
             'date': b.get('date'), 'time': b.get('time'),
             'result': b.get('result'), 'result_pending': b.get('result_pending', False)}
            for b in rest]


def _group_events_for_landing(fights, sport):
    """Build a per-event summary list for the /ufc or /boxing landing pages."""
    events = []
    if sport == 'UFC':
        seen = set()
        # Count all fights (incl. prelims) per event
        counts = {}
        bouts = {}
        for f in fights:
            if f.get('sport') == 'UFC':
                counts[f.get('event_name', '')] = counts.get(f.get('event_name', ''), 0) + 1
                bouts.setdefault(f.get('event_name', ''), []).append(f)
        for f in fights:
            if f.get('sport') != 'UFC' or f.get('card_type') == 'Prelims':
                continue
            name = f.get('event_name', '')
            if name in seen:
                continue
            seen.add(name)
            slug = f"{name.lower().replace(' ', '-').replace(':', '').replace(',', '')}-{f['date']}"
            events.append({
                'title': name,
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'fighter1_image': f.get('fighter1_image') or photos.get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or photos.get_fighter_image(f['fighter2']),
                'date': f['date'],
                'time': f.get('time'),
                'time_estimated': f.get('time_estimated', False),
                'venue': f.get('venue', ''),
                'location': f.get('location', ''),
                # UFC is on Paramount+ in the US (also Latin America and
                # Australia) since 2026; the UFC source names no broadcaster.
                'streaming': 'Paramount+',
                'fight_count': counts.get(name, 1),
                'sport': 'UFC',
                'undercard': _undercard(bouts.get(name, []), f, prelims_last=True),
                'weight_class': f.get('weight_class', ''),
                'event_name': f.get('event_name', ''),
                'path': f"/event/{slug}",
                'url': f"https://fightschedule.live/event/{slug}",
                'is_past': f.get('is_past', False),
                'result': f.get('result'),
                'result_pending': f.get('result_pending', False),
            })
    else:
        # Boxing: one entry per main event; count undercard via venue+date
        counts = {}
        bouts = {}
        for f in fights:
            if f.get('sport') == 'Boxing':
                key = (f.get('venue', ''), f.get('date', ''))
                counts[key] = counts.get(key, 0) + 1
                bouts.setdefault(key, []).append(f)
        for f in fights:
            if f.get('sport') != 'Boxing' or not f.get('is_main_event'):
                continue
            slug = f"{formatting._to_slug(f['fighter1'])}-vs-{formatting._to_slug(f['fighter2'])}-{f['date']}"
            events.append({
                'title': f"{f['fighter1']} vs {f['fighter2']}",
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'fighter1_image': f.get('fighter1_image') or photos.get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or photos.get_fighter_image(f['fighter2']),
                'date': f['date'],
                'time': f.get('time'),
                'time_estimated': f.get('time_estimated', False),
                'venue': f.get('venue', ''),
                'location': f.get('location', ''),
                'streaming': f.get('streaming', ''),
                'fight_count': counts.get((f.get('venue', ''), f.get('date', '')), 1),
                'sport': 'Boxing',
                'undercard': _undercard(bouts.get((f.get('venue', ''), f.get('date', '')), []), f),
                'weight_class': f.get('weight_class', ''),
                'event_name': f.get('event_name', ''),
                'path': f"/boxing-event/{slug}",
                'url': f"https://fightschedule.live/boxing-event/{slug}",
                'is_past': f.get('is_past', False),
                'result': f.get('result'),
                'result_pending': f.get('result_pending', False),
            })

    events.sort(key=lambda e: (e['date'] or '9999', e['time'] or '99:99'))

    # Group by month for display
    months = []
    for ev in events:
        try:
            y, m = int(ev['date'][:4]), int(ev['date'][5:7])
            label = f"{_MONTH_NAMES[m - 1]} {y}"
        except Exception:
            label = 'Upcoming'
        if not months or months[-1]['label'] != label:
            months.append({'label': label, 'events': []})
        months[-1]['events'].append(ev)

    return events, months


def _day_sections(events, newest_first=False):
    """[{'date', 'events'}] in list order; the browser regroups by local day."""
    key = lambda e: (e['date'] or '9999', e['time'] if e.get('time') and ':' in str(e['time']) else '99:99')
    days = []
    for e in sorted(events, key=key, reverse=newest_first):
        e.setdefault('slug', e['path'].rsplit('/', 1)[-1])
        if not days or days[-1]['date'] != e['date']:
            days.append({'date': e['date'], 'events': []})
        days[-1]['events'].append(e)
    return days


def _sport_page_parts(fights, sport, all_events):
    """The redesign's parts of a sport page: the poster cards and the schedule
    table; with nothing listed, the other sport's next big fight for the
    "nothing here" message (none -> the message alone)."""
    bigs, sch = _hero_and_schedule(all_events)
    other = []
    if not all_events:
        other_sport = 'Boxing' if sport == 'UFC' else 'UFC'
        other = design.hero_fights(_group_events_for_landing(fight_store.upcoming_only(fights), other_sport)[0], limit=1)
    return {'bigs': bigs, 'sch': sch, 'other': other,
            'refresh_hours': int(fight_store.CACHE_DURATION.total_seconds() // 3600)}


@app.route('/ufc')
def ufc_schedule():
    """UFC schedule landing page."""
    fights = pipeline.fetch_fights()
    all_events = _group_events_for_landing(fight_store.upcoming_only(fights), 'UFC')[0]
    recent_events = _group_events_for_landing(fight_store.recent_results(fights), 'UFC')[0]
    now = datetime.now()
    page = {
        'sport': 'UFC',
        'title': f"UFC Schedule {now.year} — Upcoming UFC Events, Dates & Fight Cards",
        'heading': 'UFC Schedule',
        'tagline': 'every upcoming event with full fight cards',
        'breadcrumb': 'UFC Schedule',
        'meta_description': f"Full UFC schedule for {now.year}: every upcoming UFC event with dates, start times in your timezone, full fight cards, main events and venues. Updated daily.",
        'canonical_url': 'https://fightschedule.live/ufc',
        'intro': f"Every upcoming UFC event in one place — {len(all_events)} events with full fight cards, main card and prelim times shown in your local timezone.",
        'footer_text': "The UFC schedule is updated daily from live event data. Dates and times can shift as cards are finalized — subscribe to the calendar feed to stay current automatically.",
        'ics_path': '/calendar/ufc.ics',
        'placeholder': '/static/placeholder-fighter-mma.svg',
        'other_path': '/boxing',
        'other_label': 'boxing schedule',
    }
    return render_template('sport_schedule.html', page=page, all_events=all_events, recent_events=recent_events,
                           **_sport_page_parts(fights, 'UFC', all_events))


@app.route('/boxing')
def boxing_schedule():
    """Boxing schedule landing page."""
    fights = pipeline.fetch_fights()
    all_events = _group_events_for_landing(fight_store.upcoming_only(fights), 'Boxing')[0]
    recent_events = _group_events_for_landing(fight_store.recent_results(fights), 'Boxing')[0]
    now = datetime.now()
    page = {
        'sport': 'Boxing',
        'title': f"Boxing Schedule {now.year} — Upcoming Fights, Dates & Fight Cards",
        'heading': 'Boxing Schedule',
        'tagline': 'every upcoming fight night with undercards',
        'breadcrumb': 'Boxing Schedule',
        'meta_description': f"Full boxing schedule for {now.year}: every upcoming boxing match with dates, start times in your timezone, undercards, venues and where to watch. Updated daily.",
        'canonical_url': 'https://fightschedule.live/boxing',
        'intro': f"Every upcoming boxing event in one place — {len(all_events)} fight nights with main events, undercards and streaming info, times shown in your local timezone.",
        'footer_text': "The boxing schedule is updated daily from live event data. Dates and times can shift as promotions finalize cards — subscribe to the calendar feed to stay current automatically.",
        'ics_path': '/calendar/boxing.ics',
        'placeholder': '/static/placeholder-fighter-boxing.svg',
        'other_path': '/ufc',
        'other_label': 'UFC schedule',
    }
    return render_template('sport_schedule.html', page=page, all_events=all_events, recent_events=recent_events,
                           **_sport_page_parts(fights, 'Boxing', all_events))


@app.route('/results')
def results_page():
    """Results from the last 30 days, both sports, newest first."""
    past = fight_store.recent_results(pipeline.fetch_fights())
    events = (_group_events_for_landing(past, 'UFC')[0] +
              _group_events_for_landing(past, 'Boxing')[0])
    days = _day_sections(events, newest_first=True)
    return render_template('results.html', events=events, days=days)


@app.route('/event/<event_slug>')
def event_detail(event_slug):
    """Show detailed page for a specific event with full card"""
    logger.info(f"--> Event detail accessed: {event_slug}")
    fights = pipeline.fights_for_pages()
    
    # Extract date from slug (last 10 chars: YYYY-MM-DD)
    # Slug format: "ufc-323-dvalishvili-vs-yan-2-2025-01-25"
    try:
        event_date = event_slug[-10:]  # Get last 10 characters (date)
        event_name_slug = event_slug[:-11]  # Everything except date and last hyphen
        logger.debug(f"  Parsed slug - date: {event_date}, name: {event_name_slug}")
    except:
        event_date = None
        event_name_slug = event_slug
        logger.debug(f"  Could not parse slug, using full: {event_slug}")
    
    # Group fights by event
    ufc_events = {}
    for fight in fights:
        if fight['sport'] == 'UFC':
            event_name = fight.get('event_name', '')
            if event_name not in ufc_events:
                ufc_events[event_name] = []
            ufc_events[event_name].append(fight)
    
    logger.debug(f"  Found {len(ufc_events)} UFC events")
    for name, fights_list in ufc_events.items():
        first_fight = fights_list[0] if fights_list else None
        if first_fight:
            logger.debug(f"    - {name}: DATE={first_fight['date']} ({len(fights_list)} fights)")
    
    # Find matching event by slug and date
    event_fights_list = None
    matched_event_name = None
    
    logger.debug(f"  Searching through {len(ufc_events)} events")
    
    # PRIORITY 1: Match by date (most reliable)
    if event_date:
        for event_name, fights_list in ufc_events.items():
            # Check if any fight in this event has matching date
            for fight in fights_list:
                if fight.get('date') == event_date:
                    event_fights_list = fights_list
                    matched_event_name = event_name
                    logger.info(f"  [OK] Matched by DATE: {matched_event_name} ({len(fights_list)} fights)")
                    break
            if event_fights_list:
                break
    
    # PRIORITY 2: Match by event name slug (fallback)
    if not event_fights_list:
        norm_url_slug = re.sub(r'[^a-z0-9-]', '', event_name_slug or '')
        for event_name, fights_list in ufc_events.items():
            # Create slug from this event name
            test_slug = event_name.lower().replace(' ', '-').replace(':', '').replace(',', '')
            test_slug = re.sub(r'[^a-z0-9-]', '', test_slug)

            # Check if slug matches (guard against empty name matching everything)
            if norm_url_slug and (test_slug in norm_url_slug or norm_url_slug in test_slug):
                event_fights_list = fights_list
                matched_event_name = event_name
                logger.info(f"  [OK] Matched by NAME: {matched_event_name}")
                break
    
    # No match — return a real 404. Falling back to another event made every
    # stale/mistyped URL render identical content, which search engines flag
    # as mass duplicate titles/descriptions.
    if not event_fights_list:
        logger.info(f"  [404] No UFC event matches slug: {event_slug}")
        abort(404)

    # Canonical URL enforcement: one URL per event. Slug variants (e.g. the
    # prelims date when a card crosses midnight UTC) 301 to the canonical slug.
    non_prelims = [f for f in event_fights_list if f.get('card_type') != 'Prelims'] or event_fights_list
    canonical_date = non_prelims[0].get('date')
    canonical_slug = f"{matched_event_name.lower().replace(' ', '-').replace(':', '').replace(',', '')}-{canonical_date}"
    if event_slug != canonical_slug:
        return redirect(f"/event/{canonical_slug}", code=301)


    # Separate main card and prelims
    main_card_fights = [f for f in event_fights_list if f.get('card_type') == 'Main Card']
    prelim_fights = [f for f in event_fights_list if f.get('card_type') == 'Prelims']
    
    logger.debug(f"  Main card fights: {len(main_card_fights)}, Prelims: {len(prelim_fights)}")
    
    # Get main event (first fight in main card)
    main_event_fight = main_card_fights[0] if main_card_fights else event_fights_list[0]
    
    logger.info(f"  Main event: {main_event_fight['fighter1']} vs {main_event_fight['fighter2']}")
    logger.info(f"  Event date: {main_event_fight['date']}, Time: {main_event_fight.get('time', 'TBA')}")
    logger.info(f"  Venue: {main_event_fight['venue']}")
    
    # Get weight class from first title fight
    weight_class = ''
    for fight in main_card_fights:
        if fight.get('weight_class') == 'Title':
            weight_class = 'Championship'
            break
    
    # Build event data structure
    event_data = {
        'event_name': matched_event_name,
        'date': main_event_fight['date'],
        'venue': main_event_fight['venue'],
        'main_event': {
            'fighter1': main_event_fight['fighter1'],
            'fighter2': main_event_fight['fighter2'],
            'fighter1_image': main_event_fight.get('fighter1_image') or photos.get_fighter_image(main_event_fight['fighter1']),
            'fighter2_image': main_event_fight.get('fighter2_image') or photos.get_fighter_image(main_event_fight['fighter2']),
            'weight_class': weight_class,
            'time': main_event_fight.get('time', 'TBA'),
            **{k: main_event_fight.get(k) for k in ('is_past', 'result', 'result_pending', 'fighter1_tape', 'fighter2_tape', 'sport', 'date')},
        },
        'main_card': [
            {
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'is_title': f.get('weight_class') == 'Title',
                'result': f.get('result'),
                'weight_class': '' if f.get('weight_class') == 'Title' else (f.get('weight_class') or ''),
                'fighter1_image': f.get('fighter1_image') or photos.get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or photos.get_fighter_image(f['fighter2']),
            }
            for f in main_card_fights
        ],
        'prelims': [
            {
                'fighter1': f['fighter1'],
                'fighter2': f['fighter2'],
                'result': f.get('result'),
                'weight_class': '' if f.get('weight_class') == 'Title' else (f.get('weight_class') or ''),
                'fighter1_image': f.get('fighter1_image') or photos.get_fighter_image(f['fighter1']),
                'fighter2_image': f.get('fighter2_image') or photos.get_fighter_image(f['fighter2']),
            }
            for f in prelim_fights
        ],
        'main_card_time': main_card_fights[0].get('time', 'TBA') if main_card_fights else 'TBA',
        'prelim_time': prelim_fights[0].get('time', 'TBA') if prelim_fights else 'TBA'
    }
    
    # Load AI preview for main event
    preview = preview_service.get_or_generate_preview(
        preview_id=event_slug,
        fighter1=main_event_fight['fighter1'],
        fighter2=main_event_fight['fighter2'],
        sport='UFC',
        is_title=(main_event_fight.get('weight_class') == 'Title'),
        weight_class=None,  # UFC doesn't extract weight classes
        fight_date=main_event_fight['date']
    )
    
    event_data['preview'] = preview
    
    # SEO metadata
    event_data['page_title'], event_data['meta_description'] = seo.fight_page_seo(
        'UFC', matched_event_name, event_data.get('date') or main_event_fight['date'], main_event_fight.get('venue'),
        main_event_fight.get('location'), bool(main_event_fight.get('is_past')))
    event_data['canonical_url'] = f"https://fightschedule.live/event/{event_slug}"
    
    return render_template('event_detail.html', event=event_data)


@app.route('/boxing-event/<event_slug>')
def boxing_event_detail(event_slug):
    """Show boxing event details using fighter names in URL"""
    logger.info(f"Boxing event accessed: {event_slug}")
    
    all_fights = pipeline.fights_for_pages()
    boxing_fights = [f for f in all_fights if f.get('sport') == 'Boxing']
    
    # Parse slug: fighter1-vs-fighter2-YYYY-MM-DD
    parts = event_slug.rsplit('-', 3)
    if len(parts) >= 3:
        date_str = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
        fighter_slug = '-'.join(parts[:-3])
    else:
        return "Invalid event URL", 404
    
    # Find any fight matching this slug (not restricted to main event)
    target_fight = None
    for fight in boxing_fights:
        if fight['date'] == date_str:
            f1 = formatting._to_slug(fight['fighter1'])
            f2 = formatting._to_slug(fight['fighter2'])
            fight_slug = f"{f1}-vs-{f2}"
            if fight_slug == fighter_slug:
                target_fight = fight
                break

    if not target_fight:
        logger.warning(f"No boxing fight found for {event_slug}")
        return "Event not found", 404

    # Get all fights from same venue/date
    event_fights = [f for f in boxing_fights
                    if f['date'] == date_str and f['venue'] == target_fight['venue']]

    # Use the actual main event if available, otherwise fall back to the matched fight
    main_event_fight = next((f for f in event_fights if f.get('is_main_event')), target_fight)

    # Re-fetch images live from fighters.json so newly added images are always visible
    # (the cache may predate the image being added)
    for fight in event_fights:
        for key in ('fighter1', 'fighter2'):
            img_key = f'{key}_image'
            if not fight.get(img_key):
                img = photos.get_fighter_image(fight[key])
                if img:
                    fight[img_key] = img

    logger.info(f"Found {len(event_fights)} fights for this event")
    
    event_fights_sorted = sorted(event_fights, key=lambda x: not x.get('is_main_event', False))
    undercard = event_fights_sorted[1:]
    
    logger.info(f"Main event: {main_event_fight['fighter1']} vs {main_event_fight['fighter2']}")
    
    # Build event data
    event_data = {
        'venue': main_event_fight['venue'],
        'location': main_event_fight['location'],
        'date': main_event_fight['date'],
        'time': main_event_fight.get('time', 'TBA'),
        'time_estimated': main_event_fight.get('time_estimated', False),
        'fight_count': len(event_fights),
        'streaming': main_event_fight.get('streaming'),  # Add streaming info
        'main_event': {
            'fighter1': main_event_fight['fighter1'],
            'fighter2': main_event_fight['fighter2'],
            'fighter1_image': main_event_fight.get('fighter1_image'),
            'fighter2_image': main_event_fight.get('fighter2_image'),
            **{k: main_event_fight.get(k) for k in ('is_past', 'result', 'result_pending', 'fighter1_tape', 'fighter2_tape', 'sport', 'date')},
        },
        'fights': [main_event_fight] + undercard
    }
    
    # Generate AI preview for main event
    # Create preview ID from sorted fighter names + date for consistency
    preview_id = preview_service.boxing_preview_id(main_event_fight['fighter1'], main_event_fight['fighter2'], main_event_fight['date'])
    
    preview = preview_service.get_or_generate_preview(
        preview_id=preview_id,
        fighter1=main_event_fight['fighter1'],
        fighter2=main_event_fight['fighter2'],
        sport='Boxing',
        is_title=('Title' in main_event_fight.get('weight_class', '')),
        weight_class=main_event_fight.get('weight_class'),
        fight_date=main_event_fight['date']
    )
    
    event_data['preview'] = preview
    
    # SEO metadata
    event_data['page_title'], event_data['meta_description'] = seo.fight_page_seo(
        'Boxing', f"{main_event_fight['fighter1']} vs {main_event_fight['fighter2']}", main_event_fight['date'],
        main_event_fight.get('venue'), main_event_fight.get('location'), bool(main_event_fight.get('is_past')),
        kind=seo._boxing_kind(main_event_fight.get('weight_class')),
        streaming=_aff.clean_broadcaster(main_event_fight.get('streaming')) if main_event_fight.get('streaming') else None)
    event_data['canonical_url'] = f"https://fightschedule.live/boxing-event/{event_slug}"
    
    return render_template('boxing_event.html', event=event_data)


# Globals (not context processors) so imported macros in _watch.html can use them
def brand_logo(key):
    """Official logo for a watch service, if one has been added as
    static/brands/<key>.svg (from the service's affiliate/brand kit)."""
    for ext in ('svg', 'png'):
        if os.path.exists(os.path.join(app.root_path, 'static', 'brands', f'{key}.{ext}')):
            return f'/static/brands/{key}.{ext}'
    return None


app.jinja_env.globals.update({
    'photo_credits': photos.photo_credits,
    'brand_logo': brand_logo,
    'provider_key': _aff.resolve_provider,
    'provider_name': _aff.provider_name,
    'clean_broadcaster': _aff.clean_broadcaster,
})


# Date of the last change to the privacy policy: shown on the page and used
# as its sitemap lastmod. Update it whenever templates/privacy.html changes.
PRIVACY_UPDATED = date(2026, 10, 6)


@app.route('/privacy')
def privacy():
    """Privacy and cookie policy page"""
    return render_template('privacy.html', updated=f"{PRIVACY_UPDATED.day} {PRIVACY_UPDATED:%B %Y}")


# Addresses whose 404 stays the plain one: files, feeds, redirects, the API and admin (a missing photo or a bad
# token needs no page).
_PLAIN_404 = ('/static/', '/persisted-fighters/', '/api/', '/go/', '/admin', '/calendar', '/health',
              '/indexnow-key.txt')


def _not_found_parts():
    """The next big fight and this week's schedule for the 404 page; ([], None) if anything goes wrong."""
    try:
        fights = fight_store.upcoming_only(pipeline.fetch_fights())
        events = _group_events_for_landing(fights, 'UFC')[0] + _group_events_for_landing(fights, 'Boxing')[0]
        bigs = design.hero_fights(events, limit=1)
        sch = design.schedule(events, lead_keys={design.event_key(b): 'lead' for b in bigs}, only=('week',))
        return bigs, sch
    except Exception as exc:
        logger.warning(f"404 page: no schedule ({exc})")
        return [], None


@app.errorhandler(404)
def not_found(e):
    """A page address that does not exist: the site's own "Not on the card" page (status 404, noindex) with the
    next big fight and this week's fights. Files, feeds, the API and admin keep the plain 404."""
    if request.method not in ('GET', 'HEAD') or request.path.startswith(_PLAIN_404):
        return e
    try:
        bigs, sch = _not_found_parts()
        path = request.path if len(request.path) <= 120 else request.path[:119] + '…'
        return render_template('404.html', path=path, bigs=bigs, sch=sch), 404
    except Exception as exc:          # the error page itself must never fail
        logger.error(f"404 page failed: {exc}", exc_info=True)
        return e
