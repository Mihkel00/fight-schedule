"""
fightschedule.live — entry point (gunicorn app:app).

The code lives in modules; importing them registers every route on the one
Flask app created in core.py:

  core            app object, data directory, seeding, logging, admin
  formatting      text helpers and Jinja filters
  fight_store     fight data storage and rules (cache, archive, card order)
  profile_store   Wikipedia fighter profiles and results
  pipeline        scraping, validation, fetch_fights()
  photos          fighter photos and credits
  preview_service AI previews (storage, model call)
  seo             sitemap, robots, llms.txt, IndexNow, page titles
  site_pages      visitor pages
  calendar_feeds  .ics feeds
  ops             /health, admin tools, debug API
  tracking        usage counts and /go/ redirects

`app.<name>` still reads any of those names (scripts and tests use it).
Setting one here is refused: patch the owning module instead, otherwise the
change would silently not apply.
"""
import os
import sys
import types

import core
import formatting
import fight_store
import profile_store
import pipeline
import photos
import preview_service
import seo
import site_pages
import calendar_feeds
import ops
import tracking

from core import app, logger  # noqa: F401  (gunicorn app:app)

# Which module owns each name (used to forward `app.<name>` and to refuse patches).
_OWNED = {
    'core': (
        'load_dotenv', 'DATA_DIR', 'data_path', '_seed_data_files', 'app', 'inject_current_date', 'admin',
        'admin_required', 'redirect_www', 'log_dir', 'logger', 'file_handler', 'console_handler',
        'formatter',
    ),
    'formatting': (
        '_to_slug', '_NAME_SUFFIXES', 'surname', 'result_text', 'utc_time', 'iso_utc', 'format_fight_date',
        'format_fight_time',
    ),
    'fight_store': (
        'BIG_NAME_FIGHTERS', 'CACHE_FILE', 'CACHE_DURATION', 'RESULTS_WINDOW_DAYS', 'RESULT_GRACE_DAYS',
        '_retention_cutoff_iso', 'upcoming_only', 'recent_results', 'load_time_overrides', 'get_fight_key',
        'apply_time_overrides', 'is_big_name_fight', 'score_fight_for_featuring', '_EPOCH', '_bout_start',
        '_name_in_text', '_named_in_title', 'normalize_ufc_cards', 'load_cache', 'save_cache',
        'RESULTS_ARCHIVE_FILE', '_fight_key', 'load_results_archive', 'archive_results', 'LAST_GOOD_FILE',
        'load_last_good', 'save_last_good', '_ARCHIVE_FIELDS', 'archived_fights',
    ),
    'profile_store': (
        'PROFILES_FILE', 'PROFILE_TTL_HOURS', 'RESULT_TTL_HOURS', 'NEGATIVE_TTL_HOURS',
        'PROFILE_JOB_MIN_INTERVAL_S', '_profiles_lock', '_profiles_mem', '_profile_job_state',
        '_profile_key', 'load_profiles', 'save_profiles', '_hours_since', '_profile_work_list',
        'refresh_profiles', '_maybe_start_profile_job', '_tape', '_height_display', '_reach_display',
        '_result_for', 'enrich_fights',
    ),
    'pipeline': (
        '_scrape_lock', '_refresh_cache', 'fetch_fights', 'fights_for_pages', '_fetch_fights_raw', 'FLOOR',
        '_run_source', '_scrape_all_sources',
    ),
    'photos': (
        'load_fighter_database', 'get_fighter_image', 'persisted_fighter_image', '_photo_thumb_cache',
        '_photo_file', '_photo_thumb', '_same_picture', '_two_distinct_photos', 'photo_credits',
    ),
    'preview_service': (
        'ANTHROPIC_API_KEY', 'load_previews', 'save_preview', 'PREVIEW_MODEL', '_preview_jobs',
        '_preview_jobs_lock', '_call_preview_model', '_make_grounded_preview', 'boxing_preview_id',
        'get_or_generate_preview',
    ),
    'seo': (
        'INDEXNOW_KEY', 'public_event_urls', 'ping_indexnow', 'PAGE_VERSIONS_FILE', '_versions_lock',
        '_load_versions', '_fight_signature', '_event_fingerprints', 'sync_page_versions', 'page_lastmod',
        'indexnow_key_file', 'TITLE_MAX', 'DESC_MAX', '_long_date', '_place_text', '_fit_title',
        '_boxing_kind', 'fight_page_seo', 'sitemap', 'robots', 'llms_txt',
    ),
    'site_pages': (
        '_NUMBERED_UFC', '_big_fights', 'home', '_MONTH_NAMES', '_undercard', '_group_events_for_landing',
        '_day_sections', 'ufc_schedule', 'boxing_schedule', 'results_page', 'event_detail',
        'boxing_event_detail', 'brand_logo', 'PRIVACY_UPDATED', 'privacy',
    ),
    'calendar_feeds': (
        '_ics_escape', '_build_calendar_events', '_render_ics', 'calendar_ics',
    ),
    'ops': (
        'health', '_cache_age_hours', 'clear_cache', 'ALLOWED_IMAGE_EXTENSIONS', 'manage_fighters',
        'download_jsons', '_DEBUG_PARTS', 'debug_state',
    ),
    'tracking': (
        'CLICKS_FILE', '_clicks_lock', '_BOT_UA', '_is_bot', '_from_this_site', '_count_page_view',
        'usage_beacon', 'go_provider', 'click_stats',
    ),
}
_OWNERS = {name: mod for mod, names in _OWNED.items() for name in names}
_MODULES = {m.__name__: m for m in (core, formatting, fight_store, profile_store, pipeline, photos, preview_service,
                                    seo, site_pages, calendar_feeds, ops, tracking)}


class _AppModule(types.ModuleType):
    def __getattr__(self, name):
        owner = _OWNERS.get(name)
        if owner:
            return getattr(_MODULES[owner], name)
        for m in _MODULES.values():          # imported helpers (date, json, ...)
            if hasattr(m, name):
                return getattr(m, name)
        raise AttributeError(f"module 'app' has no attribute {name!r}")

    def __setattr__(self, name, value):
        if name in _OWNERS:
            raise AttributeError(f'{name} lives in {_OWNERS[name]}.py; set it there')
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _AppModule

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    logger.info(f"Debug mode: {app.debug}")
    logger.info(f"Cache duration: {fight_store.CACHE_DURATION.seconds//3600} hours")
    app.run(host='0.0.0.0', port=port, debug=False)
