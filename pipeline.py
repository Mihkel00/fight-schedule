"""
Getting fights: scrape both sources, validate per source, merge with
carried results, save; fetch_fights() for pages (stale-while-revalidate).

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import image_pipeline as _images
import locks as _locks
import runs as _runs
import threading
import time
from datetime import date
from scrapers import scrape_boxing as scrape_boxing_events, scrape_ufc as scrape_ufc_events
from core import data_path, logger
import fight_store
import photos
import profile_store


_scrape_lock = threading.Lock()


def _refresh_cache(wait=False):
    """Run the full scrape and save the cache. Only one scrape runs at a time.
    With wait=False returns None immediately if another scrape is running;
    with wait=True blocks briefly so a cold-start request can use the result."""
    if wait:
        acquired = _scrape_lock.acquire(timeout=90)
    else:
        acquired = _scrape_lock.acquire(blocking=False)
    if not acquired:
        logger.info("Scrape already in progress in another thread, skipping")
        return None
    try:
        with _locks.job_lock('scrape', wait_seconds=90 if wait else 0) as got:
            if not got:
                logger.info("Scrape already in progress in the other worker, skipping")
                return None
            # The other worker may have just finished a scrape while we waited
            fresh = fight_store.load_cache()
            if fresh:
                return fresh
            fights = _scrape_all_sources()
        if fights:
            threading.Thread(target=profile_store.refresh_profiles, args=(fights,), daemon=True).start()
            threading.Thread(target=_images.fill_credits, daemon=True).start()
        return fights
    except Exception as e:
        logger.error(f"Background scrape failed: {e}", exc_info=True)
        return None
    finally:
        _scrape_lock.release()


def fetch_fights():
    """Fight data with tale-of-the-tape and results attached (see enrich_fights)."""
    fights = _fetch_fights_raw()
    profile_store._maybe_start_profile_job(fights)
    return profile_store.enrich_fights(fights)


def fights_for_pages():
    """Live fights plus archived ones: what fight pages and the sitemap use."""
    fights = fetch_fights()
    old = fight_store.archived_fights(fights)
    return fights + profile_store.enrich_fights(old) if old else fights


def _fetch_fights_raw():
    """Return fight data, preferring cache. Stale-while-revalidate: if the
    cache is expired but usable, serve it immediately and refresh in a
    background thread so visitors never wait on a scrape."""
    cached_fights = fight_store.load_cache()
    if cached_fights:
        return cached_fights

    # Any surviving upcoming fights beat making the visitor wait on a scrape.
    # load_cache() strips past events, so an all-past cache falls through.
    stale_fights = fight_store.load_cache(max_age_hours=24 * 365)
    if stale_fights:
        threading.Thread(target=_refresh_cache, daemon=True).start()
        logger.info(f"Serving {len(stale_fights)} stale fights while refreshing in background")
        return stale_fights

    # Nothing usable cached — scrape synchronously, waiting on any in-flight run
    fights = _refresh_cache(wait=True)
    if not fights:
        fights = fight_store.load_cache(max_age_hours=24 * 365) or []
    return fights


FLOOR = {'UFC': 10, 'Boxing': 5}   # fewer fights than this = treat the scrape as failed


def _run_source(source, fn, log):
    """Run one scraper and write its run record. Returns (fights, status, record).
    status: 'ok' | 'partial' | 'failed' (see runs.py). fn may return a result
    dict or, in tests, a plain list."""
    started = time.time()
    try:
        result = fn()
    except Exception as e:
        logger.error(f"{source} scraper crashed: {e}", exc_info=True)
        result = {'fights': [], 'outcome': 'crash', 'diagnostics': {'error': f'{type(e).__name__}: {e}'}}
    if isinstance(result, list):
        result = {'fights': result, 'outcome': 'parsed' if result else 'empty', 'layout': None}
    fights = result.get('fights') or []
    outcome = result.get('outcome') or 'parsed'
    n = len(fights)
    checks = [
        {'name': 'fetched', 'ok': outcome not in ('http_error', 'crash'), 'detail': outcome},
        {'name': 'layout_known', 'ok': outcome != 'layout_unknown', 'detail': result.get('layout')},
        {'name': 'floor', 'ok': n >= FLOOR[source], 'detail': f'{n} fights, floor {FLOOR[source]}'},
    ]
    if source == 'UFC' and result.get('months'):
        failed = [m for m, i in result['months'].items() if i.get('error')]
        checks.append({'name': 'all_months', 'ok': not failed, 'detail': f'failed: {failed}' if failed else 'all months read'})
    # all_months is informational: a half-read ESPN is used (partial), not failed
    if not all(c['ok'] for c in checks if c['name'] != 'all_months'):
        status = 'failed'
    elif outcome == 'partial' or not all(c['ok'] for c in checks):
        status = 'partial'
    else:
        status = 'ok'
    counts = {'fights': n}
    if source == 'UFC' and result.get('months'):
        counts['months'] = {m: i.get('fights', 0) for m, i in result['months'].items()}
    if result.get('layouts'):
        counts['layouts'] = result['layouts']
    rec = _runs.write_run(source, status, outcome, counts=counts, checks=checks, layout=result.get('layout'),
                          snapshots=result.get('snapshots'), diagnostics=result.get('diagnostics'),
                          duration_s=round(time.time() - started, 1),
                          note='; '.join(f"{c['name']}: {c['detail']}" for c in checks if not c['ok']) or None)
    log(f"{source}: {status} ({outcome}), {n} fights, layout={result.get('layout')}, {rec['duration_s']}s")
    return fights, status, rec


def _scrape_all_sources():
    """Fetch upcoming UFC and Boxing fights from multiple sources"""
    # Open debug log file
    debug_log = open(data_path('data_sources_comparison.txt'), 'w', encoding='utf-8')
    
    def log(message):
        """Log to both console and file"""
        print(message)
        debug_log.write(message + '\n')
    
    # If no cache, fetch fresh data
    fights = []
    
    log("\n" + "="*60)
    log("FIGHT DATA SOURCES COMPARISON")
    log("="*60 + "\n")
    
    # 1. Scrape BoxingSchedule.co for boxing
    log("--- BOXINGSCHEDULE.CO ---")
    boxingschedule_fights, boxing_status, boxing_run = _run_source('Boxing', scrape_boxing_events, log)
    log(f"BoxingSchedule.co found: {len(boxingschedule_fights)} fights\n")
    for fight in boxingschedule_fights[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} {'[MAIN]' if fight.get('is_main_event') else ''}")
    if len(boxingschedule_fights) > 5:
        log(f"  ... and {len(boxingschedule_fights) - 5} more\n")
    
    
    # 2. Scrape MMA Fighting for UFC schedule
    log("\n--- ESPN UFC ---")
    mma_fighting_ufc, ufc_status, ufc_run = _run_source('UFC', scrape_ufc_events, log)
    log(f"ESPN UFC found: {len(mma_fighting_ufc)} fights\n")
    for fight in mma_fighting_ufc[:5]:
        log(f"  • {fight['fighter1']} vs {fight['fighter2']} - {fight['date']} - {fight['venue']}")
    if len(mma_fighting_ufc) > 5:
        log(f"  ... and {len(mma_fighting_ufc) - 5} more\n")
    
    
    # 4. Combine data
    log("\n" + "="*60)
    log("MERGING DATA...")
    log("="*60 + "\n")
    
    # Add BoxingSchedule.co fights
    fights.extend(boxingschedule_fights)
    
    
    # Add MMA Fighting UFC fights
    fights.extend(mma_fighting_ufc)
    
    # Sources can repeat a listing; keep one copy of each matchup per date.
    _seen = set()
    fights = [f for f in fights if not (fight_store._fight_key(f) in _seen or _seen.add(fight_store._fight_key(f)))]

    # VALIDATION: check each scraper independently. A single broken source
    # must never blank the whole site, so failed sports fall back to the last
    # known-good cached data for that sport instead of discarding everything.
    ufc_count = len(mma_fighting_ufc)
    boxing_count = len(boxingschedule_fights)

    # A run is usable when its record says ok or partial (fetched, known
    # layout, at least FLOOR fights). Step 3 of the robustness plan replaces
    # this with per-row and per-run checks against the last good run.
    ufc_ok = ufc_status != 'failed'
    boxing_ok = boxing_status != 'failed'
    try:
        import alerts as _alerts
        _alerts.report('UFC', ufc_ok, ufc_run.get('note') or f'{ufc_count} fights')
        _alerts.report('Boxing', boxing_ok, boxing_run.get('note') or f'{boxing_count} fights')
    except Exception as e:
        logger.warning(f"alerting failed: {e}")

    if not ufc_ok:
        log(f"\n[X] UFC scraper returned only {ufc_count} fights (expected 50+)")
        logger.error(f"SCRAPER FAILURE: UFC scraper returned only {ufc_count} fights")
    if not boxing_ok:
        log(f"\n[X] Boxing scraper returned only {boxing_count} fights (expected 10+)")
        logger.error(f"SCRAPER FAILURE: Boxing scraper returned only {boxing_count} fights")

    if ufc_ok:
        fight_store.save_last_good('UFC', mma_fighting_ufc)
    if boxing_ok:
        fight_store.save_last_good('Boxing', boxingschedule_fights)

    if not (ufc_ok and boxing_ok):
        # Carry forward the failed sport from the previous cache, or — if the
        # cache is gone (cleared, corrupted) — from the source's last good scrape
        previous = fight_store.load_cache(max_age_hours=24 * 365) or []
        for sport, ok in (('UFC', ufc_ok), ('Boxing', boxing_ok)):
            if ok:
                continue
            carried = [f for f in previous if f.get('sport') == sport]
            origin = 'cache'
            if not carried:
                carried, origin = [dict(f) for f in fight_store.load_last_good(sport)], 'last-good snapshot'
            _seen = set()
            carried = [f for f in carried if not (fight_store._fight_key(f) in _seen or _seen.add(fight_store._fight_key(f)))]
            fights = [f for f in fights if f.get('sport') != sport] + carried
            log(f"  -> carried forward {len(carried)} {sport} fights from the {origin}")
        if not ufc_ok and not boxing_ok:
            logger.error("SCRAPER FAILURE: both scrapers failed, serving cached data only")

    log(f"\n[OK] Validation: UFC={ufc_count} ({'ok' if ufc_ok else 'FAILED'}), "
        f"Boxing={boxing_count} ({'ok' if boxing_ok else 'FAILED'}), Total={len(fights)}\n")
    
    
    # 5. Fetch images for fights that don't have them yet
    log("\n--- FETCHING MISSING FIGHTER IMAGES ---\n")
    images_fetched = 0
    for fight in fights:
        if not fight.get('fighter1_image'):
            img = photos.get_fighter_image(fight['fighter1'])
            if img:
                fight['fighter1_image'] = img
                images_fetched += 1
        if not fight.get('fighter2_image'):
            img = photos.get_fighter_image(fight['fighter2'])
            if img:
                fight['fighter2_image'] = img
                images_fetched += 1
    
    log(f"Fetched {images_fetched} additional fighter images")
    
    # Sort fights by date
    fights.sort(key=lambda x: x['date'] if x['date'] else '9999-12-31')
    # Sources only list upcoming cards, so completed fights within the results
    # window are carried forward from the results archive (and the previous
    # cache, which also seeds the archive on first run), deduped by matchup.
    # Includes today: sources drop a card as soon as it ends, which is often
    # hours before UTC midnight (this is how UFC 331 was once lost).
    today = date.today().isoformat()
    cutoff = fight_store._retention_cutoff_iso()
    previous_cache = fight_store.load_cache(max_age_hours=24 * 365) or []
    fight_store.archive_results(previous_cache)
    seen_pairs = {fight_store._fight_key(f) for f in fights}
    carried_past = 0
    for f in fight_store.load_results_archive() + previous_cache:
        if cutoff <= f.get('date', '') <= today:
            key = fight_store._fight_key(f)
            if key not in seen_pairs:
                fights.append(dict(f)); seen_pairs.add(key); carried_past += 1
    log(f"Carried forward {carried_past} completed fights for results")
    fights.sort(key=lambda x: x['date'] if x['date'] else '9999-12-31')
    fights = fight_store.normalize_ufc_cards(fights)

    fights_before_filter = len(fights)
    fights = [f for f in fights if f.get('date', '') >= cutoff]
    
    # Keep all UFC fights (no filtering needed)
    fights_before_sport_filter = len(fights)
    # No filtering needed - trust the source curation
    
    log(f"Kept all {len(fights)} fights from trusted sources")
    
    # Count fights with images
    with_images = sum(1 for f in fights if f.get('fighter1_image') or f.get('fighter2_image'))
    log(f"Fights with at least one image: {with_images} ({with_images*100//len(fights) if fights else 0}%)\n")
    
    debug_log.close()
    print("\n✓ Debug comparison saved to: data_sources_comparison.txt\n")
    
    # Apply manual time overrides
    fights = fight_store.apply_time_overrides(fights)
    
    # Save to cache
    if fights:
        fight_store.save_cache(fights)
    
    return fights
