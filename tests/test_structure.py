"""The app is split into modules (see app.py). These tests keep the split honest:
every page address still exists, app.<name> still reads through to the owning
module, and patching through app is refused (it would silently do nothing)."""
import pytest

import app as A
import pipeline

ROUTES = [
    ('/', 'home', 'GET'),
    ('/api/debug/state', 'debug_state', 'GET,POST'),
    ('/api/t', 'usage_beacon', 'POST'),
    ('/boxing', 'boxing_schedule', 'GET'),
    ('/boxing-event/<event_slug>', 'boxing_event_detail', 'GET'),
    ('/calendar.ics', 'calendar_ics', 'GET'),
    ('/calendar/<sport>.ics', 'calendar_ics', 'GET'),
    ('/event/<event_slug>', 'event_detail', 'GET'),
    ('/go/<provider>', 'go_provider', 'GET'),
    ('/health', 'health', 'GET'),
    ('/indexnow-key.txt', 'indexnow_key_file', 'GET'),
    ('/llms.txt', 'llms_txt', 'GET'),
    ('/persisted-fighters/<path:filename>', 'persisted_fighter_image', 'GET'),
    ('/privacy', 'privacy', 'GET'),
    ('/results', 'results_page', 'GET'),
    ('/robots.txt', 'robots', 'GET'),
    ('/sitemap.xml', 'sitemap', 'GET'),
    ('/ufc', 'ufc_schedule', 'GET'),
    ('/admin/clear-cache', 'clear_cache', 'GET'),
    ('/admin/download-jsons', 'download_jsons', 'GET'),
    ('/admin/manage-fighters', 'manage_fighters', 'GET,POST'),
]


def test_every_page_address_still_exists():
    have = {(r.rule, r.endpoint, ','.join(sorted(m for m in r.methods if m not in ('HEAD', 'OPTIONS'))))
            for r in A.app.url_map.iter_rules()}
    missing = [r for r in ROUTES if r not in have]
    assert not missing, missing


def test_app_names_read_through_to_their_module():
    assert A.fetch_fights is pipeline.fetch_fights
    assert A.CACHE_FILE.endswith('fights_cache.json')
    with pytest.raises(AttributeError):
        A.no_such_thing


def test_patching_through_app_is_refused():
    with pytest.raises(AttributeError, match='lives in pipeline.py'):
        A._refresh_cache = lambda wait=False: None
    with pytest.raises(AttributeError, match='lives in pipeline.py'):   # imported helper, not owned
        A.scrape_ufc_events = lambda: None


def test_env_file_is_loaded_before_anything_reads_it():
    """admin_setup_simple reads ADMIN_PASSWORD at import; load_dotenv() must
    run before any import in core.py (2026-10-11, MISTAKES.md)."""
    import ast
    import os
    src = open(os.path.join(os.path.dirname(A.__file__), 'core.py')).read()
    body = ast.parse(src).body
    call = next(i for i, n in enumerate(body) if isinstance(n, ast.Expr) and 'load_dotenv()' in ast.unparse(n))
    first_other_import = next(i for i, n in enumerate(body) if isinstance(n, (ast.Import, ast.ImportFrom))
                              and 'dotenv' not in ast.unparse(n))
    assert call < first_other_import
