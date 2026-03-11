"""
ESPN Hidden API Client
Fetches UFC/MMA and Boxing data from ESPN's undocumented public API.
This is a temporary exploration module to evaluate ESPN as a data source.
"""

import requests
import logging

logger = logging.getLogger('fight_schedule')

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
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


def fetch_mma_scoreboard():
    """Fetch MMA/UFC scoreboard (upcoming and recent events)."""
    return _get(f"{BASE_URL}/mma/ufc/scoreboard")


def fetch_boxing_scoreboard():
    """Fetch Boxing scoreboard (upcoming and recent events)."""
    return _get(f"{BASE_URL}/boxing/scoreboard")


def fetch_mma_event(event_id):
    """Fetch detailed info for a specific MMA event."""
    return _get(f"{BASE_URL}/mma/ufc/summary", params={"event": event_id})


def fetch_boxing_event(event_id):
    """Fetch detailed info for a specific boxing event."""
    return _get(f"{BASE_URL}/boxing/summary", params={"event": event_id})


def fetch_mma_calendar():
    """Fetch MMA event calendar (list of event dates/IDs)."""
    return _get(f"{BASE_URL}/mma/ufc/calendar")


def fetch_boxing_calendar():
    """Fetch boxing event calendar."""
    return _get(f"{BASE_URL}/boxing/calendar")


def fetch_mma_news():
    """Fetch latest MMA/UFC news."""
    return _get(f"{BASE_URL}/mma/ufc/news")


def fetch_boxing_news():
    """Fetch latest boxing news."""
    return _get(f"{BASE_URL}/boxing/news")


def fetch_event_detail_core(sport, league, event_id):
    """
    Fetch event detail from the core API (more detailed data).
    sport: 'mma' or 'boxing'
    league: 'ufc' or league slug
    """
    return _get(f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}")


def fetch_competition_detail(sport, league, event_id, competition_id):
    """Fetch individual fight/competition detail from core API."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}"
    )


def fetch_competitor_detail(sport, league, event_id, competition_id, competitor_id):
    """Fetch individual competitor stats for a fight."""
    return _get(
        f"{CORE_URL}/{sport}/leagues/{league}/events/{event_id}"
        f"/competitions/{competition_id}/competitors/{competitor_id}"
    )


def fetch_athlete(sport, athlete_id):
    """Fetch athlete profile."""
    return _get(f"{BASE_URL}/{sport}/athletes/{athlete_id}")


def _resolve_ref(ref_url):
    """Resolve a $ref URL from ESPN API responses."""
    if not ref_url:
        return None
    return _get(ref_url)


def fetch_all_espn_data():
    """
    Fetch all available ESPN data for both MMA and Boxing.
    Returns a dict with all the raw data for display on the /espn page.
    """
    data = {
        'mma_scoreboard': None,
        'boxing_scoreboard': None,
        'mma_calendar': None,
        'boxing_calendar': None,
        'mma_news': None,
        'boxing_news': None,
        'mma_events_detail': [],
        'boxing_events_detail': [],
        'errors': [],
    }

    # Fetch scoreboards (main source of upcoming fights)
    data['mma_scoreboard'] = fetch_mma_scoreboard()
    if not data['mma_scoreboard']:
        data['errors'].append('Failed to fetch MMA scoreboard')

    data['boxing_scoreboard'] = fetch_boxing_scoreboard()
    if not data['boxing_scoreboard']:
        data['errors'].append('Failed to fetch Boxing scoreboard')

    # Fetch calendars
    data['mma_calendar'] = fetch_mma_calendar()
    if not data['mma_calendar']:
        data['errors'].append('Failed to fetch MMA calendar')

    data['boxing_calendar'] = fetch_boxing_calendar()
    if not data['boxing_calendar']:
        data['errors'].append('Failed to fetch Boxing calendar')

    # Fetch news
    data['mma_news'] = fetch_mma_news()
    data['boxing_news'] = fetch_boxing_news()

    # For each event in the MMA scoreboard, fetch detailed event summary
    if data['mma_scoreboard'] and 'events' in data['mma_scoreboard']:
        for event in data['mma_scoreboard']['events'][:5]:  # Limit to 5 events
            event_id = event.get('id')
            if event_id:
                detail = fetch_mma_event(event_id)
                if detail:
                    data['mma_events_detail'].append(detail)

    # Same for boxing
    if data['boxing_scoreboard'] and 'events' in data['boxing_scoreboard']:
        for event in data['boxing_scoreboard']['events'][:5]:
            event_id = event.get('id')
            if event_id:
                detail = fetch_boxing_event(event_id)
                if detail:
                    data['boxing_events_detail'].append(detail)

    return data
