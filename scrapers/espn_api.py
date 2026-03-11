"""
ESPN Hidden API Client
Fetches UFC/MMA and Boxing data from ESPN's undocumented public API.
This is a temporary exploration module to evaluate ESPN as a data source.

Endpoint documentation sourced from:
- https://github.com/pseudo-r/Public-ESPN-API
- https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b

Three API layers:
  Site API  - high-level: scoreboard, news, athlete profiles
             https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/{resource}
  Web API   - MMA-specific: fightcenter (replaces /summary which 404s for MMA)
             https://site.web.api.espn.com/apis/common/v3/sports/mma/{league}/fightcenter/{eventId}
  Core API  - detailed: events, competitions, competitors, stats, calendar
             https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/{resource}
"""

import requests
import logging

logger = logging.getLogger('fight_schedule')

SITE_URL = "https://site.api.espn.com/apis/site/v2/sports"
WEB_URL = "https://site.web.api.espn.com/apis/common/v3/sports"
CORE_URL = "https://sports.core.api.espn.com/v2/sports"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
TIMEOUT = 15


def _get(url, params=None):
    """Make a GET request and return JSON, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"ESPN API error for {url}: {e}")
        return None


# ============================================================================
# SITE API - High-level endpoints (scoreboard, news, athletes)
# Pattern: site.api.espn.com/apis/site/v2/sports/{sport}/{league}/{resource}
# ============================================================================

def fetch_mma_scoreboard(dates=None):
    """
    Fetch MMA/UFC scoreboard (upcoming and recent events).
    dates: optional, format YYYYMMDD or YYYYMMDD-YYYYMMDD range (max 13 months)
    The response also includes a 'calendar' array with ISO dates of all events.
    """
    params = {}
    if dates:
        params['dates'] = dates
    return _get(f"{SITE_URL}/mma/ufc/scoreboard", params=params or None)


def fetch_mma_news():
    """Fetch latest MMA/UFC news."""
    return _get(f"{SITE_URL}/mma/ufc/news")


def fetch_mma_athlete(athlete_id):
    """Fetch MMA athlete profile from Site API."""
    return _get(f"{SITE_URL}/mma/ufc/athletes/{athlete_id}")


# ============================================================================
# WEB API - MMA-specific endpoints (fightcenter)
# MMA uses fightcenter instead of the /summary endpoint that other sports have.
# Pattern: site.web.api.espn.com/apis/common/v3/sports/mma/{league}/fightcenter/{eventId}
# ============================================================================

def fetch_fightcenter(event_id, league='ufc'):
    """
    Fetch FightCenter data for an MMA event.
    This is the MMA-specific replacement for the /summary endpoint.
    Returns detailed fight card data including fighter info, odds, and results.
    """
    return _get(f"{WEB_URL}/mma/{league}/fightcenter/{event_id}")


# ============================================================================
# CORE API - Detailed endpoints (events, competitions, stats, calendar)
# Pattern: sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/{resource}
# ============================================================================

def fetch_core_leagues(sport='mma'):
    """List all leagues for a sport (discover available league slugs)."""
    return _get(f"{CORE_URL}/{sport}/leagues")


def fetch_core_calendar(sport='mma', league='ufc'):
    """Fetch event calendar from Core API."""
    return _get(f"{CORE_URL}/{sport}/leagues/{league}/calendar")


def fetch_core_season(sport='mma', league='ufc'):
    """Fetch current season info."""
    return _get(f"{CORE_URL}/{sport}/leagues/{league}/season")


def fetch_core_event(event_id, sport='mma', league='ufc'):
    """Fetch detailed event info from Core API."""
    return _get(f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}")


def fetch_core_competition(event_id, competition_id, sport='mma', league='ufc'):
    """Fetch individual fight/competition detail from Core API."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}"
    )


def fetch_core_competitor(event_id, competition_id, competitor_id,
                          sport='mma', league='ufc'):
    """Fetch individual competitor detail for a fight."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}/competitors/{competitor_id}"
    )


def fetch_core_competitor_stats(event_id, competition_id, competitor_id,
                                sport='mma', league='ufc'):
    """Fetch competitor statistics for a specific fight."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}/competitors/{competitor_id}/statistics"
    )


def fetch_core_competition_odds(event_id, competition_id,
                                sport='mma', league='ufc'):
    """Fetch betting odds for a fight."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}/odds"
    )


def fetch_core_competition_broadcasts(event_id, competition_id,
                                      sport='mma', league='ufc'):
    """Fetch broadcast info for a fight."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}/broadcasts"
    )


def fetch_core_athletes(sport='mma', league='ufc', page=1, limit=50):
    """Fetch athlete roster."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/athletes",
        params={'page': page, 'limit': limit}
    )


def fetch_core_rankings(sport='mma', league='ufc'):
    """Fetch rankings."""
    return _get(f"{CORE_URL}/{sport}/leagues/{league}/rankings")


def fetch_core_venues(sport='mma', league='ufc'):
    """Fetch venue list."""
    return _get(f"{CORE_URL}/{sport}/leagues/{league}/venues")


def _resolve_ref(ref_url):
    """Resolve a $ref URL from ESPN API responses (ESPN uses JSON references)."""
    if not ref_url:
        return None
    return _get(ref_url)


def _resolve_refs_in_list(items, max_resolve=20):
    """
    Resolve $ref URLs in a list of items.
    ESPN often returns lists where each item is just {"$ref": "url"}.
    """
    resolved = []
    for item in items[:max_resolve]:
        if isinstance(item, dict) and '$ref' in item:
            data = _resolve_ref(item['$ref'])
            if data:
                resolved.append(data)
        else:
            resolved.append(item)
    return resolved


# ============================================================================
# HIGH-LEVEL FETCH: gather all data for the /espn explorer page
# ============================================================================

def fetch_all_espn_data():
    """
    Fetch all available ESPN data for MMA/UFC.
    Boxing endpoints don't exist in ESPN's API (confirmed 404).
    Returns a dict with all the raw data for display on the /espn page.
    """
    from datetime import datetime, timedelta

    data = {
        'mma_scoreboard': None,
        'mma_scoreboard_upcoming': None,
        'mma_fightcenter': [],
        'mma_calendar': None,
        'mma_news': None,
        'mma_events_detail': [],
        'mma_leagues': None,
        'mma_rankings': None,
        'boxing_note': (
            'Boxing endpoints (scoreboard, news, calendar) all return 404. '
            'ESPN does not appear to have a boxing API. '
            'Boxing data will need to come from other sources.'
        ),
        'errors': [],
    }

    # 1. Scoreboard (Site API) - default (shows current/nearest event)
    data['mma_scoreboard'] = fetch_mma_scoreboard()
    if not data['mma_scoreboard']:
        data['errors'].append('Failed to fetch MMA scoreboard')

    # 2. Scoreboard with date range - next 60 days of events
    today = datetime.now()
    future = today + timedelta(days=60)
    date_range = f"{today.strftime('%Y%m%d')}-{future.strftime('%Y%m%d')}"
    data['mma_scoreboard_upcoming'] = fetch_mma_scoreboard(dates=date_range)
    if not data['mma_scoreboard_upcoming']:
        data['errors'].append(f'Failed to fetch MMA scoreboard for date range {date_range}')

    # 3. News (Site API)
    data['mma_news'] = fetch_mma_news()
    if not data['mma_news']:
        data['errors'].append('Failed to fetch MMA news')

    # 4. Calendar (Core API)
    data['mma_calendar'] = fetch_core_calendar()
    if not data['mma_calendar']:
        data['errors'].append('Failed to fetch MMA calendar (Core API)')

    # 5. Discover available MMA leagues
    data['mma_leagues'] = fetch_core_leagues('mma')

    # 6. Rankings
    data['mma_rankings'] = fetch_core_rankings()

    # 7. FightCenter - the richest endpoint for MMA event data
    #    Fetch for each event from the scoreboard
    event_ids_seen = set()
    all_events = []
    if data['mma_scoreboard'] and 'events' in data['mma_scoreboard']:
        all_events.extend(data['mma_scoreboard']['events'])
    if data['mma_scoreboard_upcoming'] and 'events' in data['mma_scoreboard_upcoming']:
        all_events.extend(data['mma_scoreboard_upcoming']['events'])

    for event in all_events:
        event_id = event.get('id')
        if not event_id or event_id in event_ids_seen:
            continue
        event_ids_seen.add(event_id)
        if len(data['mma_fightcenter']) >= 5:
            break

        fc = fetch_fightcenter(event_id)
        if fc:
            data['mma_fightcenter'].append({
                'event_id': event_id,
                'event_name': event.get('name', f'Event {event_id}'),
                'event_date': event.get('date', ''),
                'data': fc,
            })

    # 8. Core API event details (for comparison with fightcenter)
    for event in all_events[:3]:
        event_id = event.get('id')
        if not event_id:
            continue

        core_event = fetch_core_event(event_id)
        if not core_event:
            continue

        event_detail = {
            'core_event': core_event,
            'competitions': [],
        }

        # Resolve competition refs
        competitions_ref = core_event.get('competitions', {})
        if isinstance(competitions_ref, dict) and '$ref' in competitions_ref:
            comps_data = _resolve_ref(competitions_ref['$ref'])
            if comps_data and 'items' in comps_data:
                event_detail['competitions'] = _resolve_refs_in_list(
                    comps_data['items'], max_resolve=15
                )
        elif isinstance(competitions_ref, list):
            event_detail['competitions'] = _resolve_refs_in_list(
                competitions_ref, max_resolve=15
            )

        # For the first 3 competitions, also resolve competitor details
        for comp in event_detail['competitions'][:3]:
            if 'competitors' not in comp:
                continue
            competitors_data = comp.get('competitors', {})
            if isinstance(competitors_data, dict) and '$ref' in competitors_data:
                comps_list = _resolve_ref(competitors_data['$ref'])
                if comps_list and 'items' in comps_list:
                    comp['competitors_resolved'] = _resolve_refs_in_list(
                        comps_list['items'], max_resolve=4
                    )
            elif isinstance(competitors_data, list):
                comp['competitors_resolved'] = _resolve_refs_in_list(
                    competitors_data, max_resolve=4
                )

        data['mma_events_detail'].append(event_detail)

    # 9. Also try to discover boxing leagues (to see if boxing exists anywhere)
    data['boxing_leagues'] = fetch_core_leagues('boxing')

    return data
