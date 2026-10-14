"""
Operations: /health, admin tools, and the token-protected debug API.

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import hmac
import image_pipeline as _images
import json
import locks as _locks
import os
import re
import requests
import runs as _runs
import threading
import usage as _usage
from admin_setup_simple import csrf as _csrf
from bs4 import BeautifulSoup
from datetime import date, datetime
from flask import abort, jsonify, make_response, redirect, render_template, request, send_file
from scrapers import scrape_boxing as scrape_boxing_events, scrape_ufc as scrape_ufc_events
from core import admin_required, app, data_path, logger
import fight_store
import pipeline
import profile_store
import seo
import tracking


@app.route('/health')
def health():
    """200 when every source has a recent successful run, else 503. For an
    uptime monitor; the JSON body says what is wrong. Nothing here is secret."""
    h = _runs.health(extra={'lock_error': _locks.last_error,
                            'cache_age_hours': _cache_age_hours()})
    resp = jsonify(h)
    resp.status_code = 200 if h['healthy'] else 503
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _cache_age_hours():
    try:
        with open(fight_store.CACHE_FILE) as fh:
            stamp = json.load(fh).get('timestamp')
        return round((datetime.now() - datetime.fromisoformat(stamp)).total_seconds() / 3600, 1)
    except Exception:
        return None


@app.route('/admin/clear-cache')
@admin_required
def clear_cache():
    """Clear the fights cache file"""
    cache_file = fight_store.CACHE_FILE
    if os.path.exists(cache_file):
        # Before deleting: archive past fights, and give any source without a
        # last-good snapshot one from the cache, so a failing source can't
        # empty its section after the clear.
        cached = fight_store.load_cache(max_age_hours=24 * 365) or []
        fight_store.archive_results(cached)
        today_iso = date.today().isoformat()
        for sport in ('UFC', 'Boxing'):
            if not fight_store.load_last_good(sport):
                upcoming = [f for f in cached if f.get('sport') == sport and f.get('date', '') > today_iso]
                if upcoming:
                    fight_store.save_last_good(sport, upcoming)
        os.remove(cache_file)
        logger.info("Cache cleared manually via admin route")
        return "✓ Cache cleared successfully. Next page load will fetch fresh data."
    return "No cache file found."


ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


@app.route('/admin/manage-fighters', methods=['GET', 'POST'])
@admin_required
def manage_fighters():
    """Manage fighter names and big name fighters"""
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add_big_name':
                fighter_name = request.form.get('fighter_name')
                big_names_file = data_path('big_name_fighters.json')

                with open(big_names_file, 'r') as f:
                    big_names = json.load(f)

                if fighter_name not in big_names:
                    big_names.append(fighter_name)
                    big_names.sort()

                    with open(big_names_file, 'w') as f:
                        json.dump(big_names, f, indent=2)

                    logger.info(f"Added big name fighter: {fighter_name}")

            elif action == 'remove_big_name':
                fighter_name = request.form.get('fighter_name')
                big_names_file = data_path('big_name_fighters.json')

                with open(big_names_file, 'r') as f:
                    big_names = json.load(f)

                if fighter_name in big_names:
                    big_names.remove(fighter_name)

                    with open(big_names_file, 'w') as f:
                        json.dump(big_names, f, indent=2)

                    logger.info(f"Removed big name fighter: {fighter_name}")

            elif action == 'rename':
                old_name = request.form.get('old_name')
                new_name = request.form.get('new_name')
                sport = request.form.get('sport')

                json_file = data_path('fighters.json') if sport == 'Boxing' else data_path('fighters_ufc.json')

                with open(json_file, 'r', encoding='utf-8') as f:
                    fighters = json.load(f)

                if old_name in fighters:
                    fighters[new_name] = fighters.pop(old_name)

                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(fighters, f, indent=2, ensure_ascii=False)

                    logger.info(f"Renamed fighter: {old_name} → {new_name}")

            elif action == 'delete':
                fighter_name = request.form.get('fighter_name')
                sport = request.form.get('sport')

                json_file = data_path('fighters.json') if sport == 'Boxing' else data_path('fighters_ufc.json')

                with open(json_file, 'r', encoding='utf-8') as f:
                    fighters = json.load(f)

                if fighter_name in fighters:
                    del fighters[fighter_name]

                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(fighters, f, indent=2, ensure_ascii=False)

                    logger.info(f"Deleted fighter: {fighter_name}")
            
            return redirect('/admin/manage-fighters')
        
        # GET - show management page
        with open(data_path('fighters.json'), 'r', encoding='utf-8') as f:
            boxing = json.load(f)
        with open(data_path('fighters_ufc.json'), 'r', encoding='utf-8') as f:
            ufc = json.load(f)

        # Load big names, create if missing
        big_names_file = data_path('big_name_fighters.json')
        if os.path.exists(big_names_file):
            with open(big_names_file, 'r') as f:
                big_names_raw = json.load(f)
                # Ensure it's a list of strings, handle malformed data
                if isinstance(big_names_raw, list):
                    big_names = [item if isinstance(item, str) else str(item) for item in big_names_raw]
                else:
                    big_names = []
        else:
            big_names = []
        
        all_fighters = []
        for name, img in boxing.items():
            all_fighters.append({'name': name, 'sport': 'Boxing', 'image': img})
        for name, img in ufc.items():
            all_fighters.append({'name': name, 'sport': 'UFC', 'image': img})
        
        # Sort by name
        all_fighters.sort(key=lambda x: x['name'])
        
        return render_template('admin/manage_fighters.html', 
                              all_fighters=all_fighters, 
                              big_names=big_names)
    
    except Exception as e:
        logger.error(f"manage_fighters error: {e}", exc_info=True)
        return "An error occurred. Please try again.", 500


@app.route('/admin/download-jsons')
@admin_required
def download_jsons():
    """Download updated fighter JSONs as zip"""
    import zipfile
    from io import BytesIO
    
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        zip_file.write(data_path('fighters.json'), 'fighters.json')
        zip_file.write(data_path('fighters_ufc.json'), 'fighters_ufc.json')
    
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='fighters_updated.zip'
    )


_DEBUG_PARTS = {
    'cache': 'fights_cache.json',
    'fighters': 'fighters.json',
    'fighters_ufc': 'fighters_ufc.json',
    'overrides': 'time_overrides.json',
    'profiles': 'fighter_profiles.json',
    'image_meta': 'image_meta.json',
    'results_archive': 'results_archive.json',
    'last_good': 'last_good.json',
}


@app.route('/api/debug/state', methods=['GET', 'POST'])
def debug_state():
    expected = os.environ.get('DEBUG_API_TOKEN', '')
    provided = request.args.get('token', '')
    if not expected or not hmac.compare_digest(provided, expected):
        abort(404)

    part = request.args.get('part')

    if part == 'scrape_test':
        # Run each scraper in isolation and report what it returns. Diagnostic
        # only: nothing is written to the cache.
        import traceback
        out = {}
        for name, fn in (('boxing', scrape_boxing_events), ('ufc', scrape_ufc_events)):
            started = datetime.now()
            try:
                got = fn()
                if isinstance(got, dict):
                    got = got.get('fights') or []
                dates = sorted(f.get('date', '') for f in got if f.get('date'))
                out[name] = {
                    'count': len(got),
                    'elapsed_seconds': round((datetime.now() - started).total_seconds(), 1),
                    'date_range': [dates[0], dates[-1]] if dates else None,
                    'upcoming_count': sum(1 for d in dates if d >= date.today().isoformat()),
                    'sample': got[:3],
                }
            except Exception as e:
                out[name] = {
                    'error': str(e),
                    'traceback': traceback.format_exc()[-2000:],
                    'elapsed_seconds': round((datetime.now() - started).total_seconds(), 1),
                }
        out['thresholds'] = {'ufc_min': 10, 'boxing_min': 5}
        return jsonify(out)

    if part == 'boxing_probe':
        # Fetch the boxing source directly and report what came back, so the
        # parser can be diagnosed without reaching the site from elsewhere.
        import traceback
        url = 'https://boxingschedule.co'
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            html = r.text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.content, 'html.parser')
            text = soup.get_text('\n', strip=True)
            marker_pos = html.find('\U0001F4C5')
            return jsonify({
                'status_code': r.status_code,
                'final_url': r.url,
                'content_length': len(html),
                'content_type': r.headers.get('content-type'),
                'p_with_data_start': len(soup.find_all('p', attrs={'data-start': True})),
                'any_data_start': len(soup.find_all(attrs={'data-start': True})),
                'calendar_emoji_count': html.count('\U0001F4C5'),
                'html_around_first_emoji': html[max(0, marker_pos - 400):marker_pos + 400] if marker_pos > -1 else None,
                'tag_histogram': {t: len(soup.find_all(t)) for t in ('p', 'div', 'li', 'tr', 'h2', 'h3', 'article', 'script')},
                'article_classes': sorted({' '.join(a.get('class', [])) for a in soup.find_all('article')}),
                'first_article_html': str(soup.find('article'))[:4000] if soup.find('article') else None,
                'event_articles': [str(x)[:9000] for x in soup.select('article.rsd-event, article.rs-card')[:2]],
                'second_article_html': str(soup.find_all('article')[1])[:2500] if len(soup.find_all('article')) > 1 else None,
                'text_head': text[:1500],
            })
        except Exception as e:
            return jsonify({'error': str(e), 'traceback': traceback.format_exc()[-1500:]})

    if part == 'profiles_refresh':
        # Kick the background profile job now (ignores the cooldown)
        if profile_store._profile_job_state['running']:
            return jsonify({'started': False, 'reason': 'already running'})
        fights = pipeline._fetch_fights_raw()
        pending = profile_store._profile_work_list(fights, profile_store.load_profiles())
        threading.Thread(target=profile_store.refresh_profiles, args=(fights,), daemon=True).start()
        return jsonify({'started': True, 'pending_fighters': len(pending)})

    if part == 'usage':
        return jsonify(_usage.stats(days=int(request.args.get('days', 30))))

    if part == 'check':
        # Run the named invariants over what the site is serving right now (read-only)
        import invariants as _inv
        fs = pipeline._fetch_fights_raw()
        checks = _inv.model_checks(fs)
        return jsonify({'fights': len(fs), 'healthy': all(c['ok'] for c in checks), 'checks': checks})

    if part == 'health':
        return jsonify(_runs.health(extra={'lock_error': _locks.last_error, 'cache_age_hours': _cache_age_hours()}))

    if part == 'run_log':
        # Recent run records per source, newest last
        src = request.args.get('source')
        sources = [src] if src else ['UFC', 'Boxing']
        return jsonify({s: _runs.list_runs(s, limit=int(request.args.get('limit', 20))) for s in sources})

    if part == 'snapshot':
        # Raw body of a saved source page: &file=<sidecar 'file'> or the newest for &source=
        rel = request.args.get('file')
        if not rel:
            snaps = _runs.list_snapshots(request.args.get('source') or 'Boxing', limit=1)
            if not snaps:
                return jsonify({'error': 'no snapshots yet'}), 404
            rel = snaps[0]['file']
        try:
            body = _runs.read_snapshot(rel)
        except Exception as e:
            return jsonify({'error': str(e)}), 404
        resp = make_response(body)
        resp.headers['Content-Type'] = 'application/json' if rel.endswith('.json.gz') else 'text/html; charset=utf-8'
        return resp

    if part == 'snapshots':
        src = request.args.get('source')
        sources = [src] if src else ['UFC', 'Boxing']
        return jsonify({s: _runs.list_snapshots(s, limit=int(request.args.get('limit', 20))) for s in sources})

    if part == 'versions':
        v = seo._load_versions()
        return jsonify({'tracked_urls': len(v), 'newest': sorted(v.items(), key=lambda kv: kv[1].get('lastmod', ''), reverse=True)[:15]})

    if part == 'image_probe':
        # What would each image source return for a fighter? Saves nothing.
        name = (request.args.get('name') or '')[:120]
        sport = 'UFC' if request.args.get('sport', '').lower() == 'ufc' else 'Boxing'
        if not name:
            return jsonify({'error': 'name required'}), 400
        titles = _images._profile_titles()
        return jsonify(_images.probe(name, sport, title=titles.get(_images.key(name))))

    if part == 'image_job':
        # Read the image job report; &start=dry launches a dry run (writes nothing).
        # Applying is admin-only (Review Images page).
        started = None
        if request.args.get('start') == 'dry':
            started = _images.start_job(apply=False)
        return jsonify({'started': started, 'job': _images.read_job(), 'settings': _images.read_settings()})

    if part == 'clicks':
        return jsonify(tracking.click_stats(int(request.args.get('days') or 30)))

    if part == 'photo_meta':
        # Face/tone metadata for fighter photos: counts and the last backfill;
        # &path=<image path> shows one photo's entry; &start=1 measures every
        # photo that has none yet (in the background; see photo_analysis.py).
        import photo_analysis as _pa
        import photos as _photos
        out = {'started': None}
        if request.args.get('start') == '1':
            out['started'] = _pa.start_backfill(reason='debug API')
        path = (request.args.get('path') or '')[:300]
        if path:
            k = _pa.path_key(path)
            stored = (_pa.load_static().get(k) or _pa.load_store().get(k)) if k else None
            out['path'] = {'key': k, 'meta': _photos.photo_meta(path), 'stored': stored,
                           'override': _pa.override_for(k, (stored or {}).get('sha1')) if k else None}
        out.update(_pa.summary())
        return jsonify(out)

    if part == 'backfill':
        # POST a JSON list of fights to merge into the cache, e.g. to restore a
        # card a source dropped. Past fights by default; &upcoming=1 also
        # restores future fights (and records them as that source's last-good
        # set so they survive while the source is down).
        if request.method != 'POST':
            return jsonify({'error': 'POST a JSON list of fights'}), 405
        allow_upcoming = request.args.get('upcoming') == '1'
        incoming = request.get_json(silent=True) or []
        today_iso, cutoff = date.today().isoformat(), fight_store._retention_cutoff_iso()
        current = fight_store.load_cache(max_age_hours=24 * 365) or []
        seen = {(tuple(sorted([f['fighter1'].lower(), f['fighter2'].lower()])), f.get('date')) for f in current}
        added = []
        for f in incoming:
            if not isinstance(f, dict) or not all(f.get(k) for k in ('fighter1', 'fighter2', 'date', 'sport')):
                continue
            if f['date'] < cutoff or (f['date'] > today_iso and not allow_upcoming):
                continue
            k = (tuple(sorted([f['fighter1'].lower(), f['fighter2'].lower()])), f['date'])
            if k in seen:
                continue
            seen.add(k)
            current.append({key: f.get(key) for key in ('fighter1', 'fighter2', 'date', 'time', 'venue', 'location', 'sport',
                                                        'event_name', 'weight_class', 'card_type', 'rounds', 'is_main_event',
                                                        'streaming', 'time_estimated') if key in f})
            added.append(f"{f['fighter1']} vs {f['fighter2']} ({f['date']})")
        if added:
            current.sort(key=lambda x: x.get('date') or '9999-12-31')
            fight_store.save_cache(current, keep_timestamp=True)
            if allow_upcoming:
                for sport in ('UFC', 'Boxing'):
                    future = [f for f in incoming if isinstance(f, dict) and f.get('sport') == sport and (f.get('date') or '') > today_iso]
                    if future:
                        fight_store.save_last_good(sport, future, merge=True)
            threading.Thread(target=profile_store.refresh_profiles, args=(current,), daemon=True).start()
        if added:
            sports = {f.get('sport') for f in incoming if isinstance(f, dict)}
            _runs.write_run(sports.pop() if len(sports) == 1 else 'mixed', 'manual', 'backfill',
                            counts={'fights': len(added)}, note='debug API backfill')
        return jsonify({'added': added, 'total_now': len(current)})

    if part == 'page_probe':
        # Structure of a candidate schedule page (fixed list of hosts) to design a fallback parser.
        pages = {
            'espn_boxing': 'https://www.espn.com/boxing/schedule',
            'sky_boxing': 'https://www.skysports.com/boxing-schedule',
            'boxing_schedule_com': 'https://boxing-schedule.com/',
            'dazn_schedule': 'https://www.dazn.com/en-US/news/boxing/boxing-schedule',
        }
        which = request.args.get('which', '')
        if which not in pages:
            return jsonify({'error': f'which must be one of {sorted(pages)}'}), 400
        from bs4 import BeautifulSoup
        from collections import Counter
        try:
            r = requests.get(pages[which], headers={'User-Agent': _ESPN_UA if False else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}, timeout=25)
            soup = BeautifulSoup(r.text, 'html.parser')
            for t in soup(['script', 'style', 'noscript', 'svg']):
                t.decompose()
            classes = Counter(c for el in soup.find_all(True) for c in (el.get('class') or []))
            text = soup.get_text('\n', strip=True)
            vs_lines = [l for l in text.split('\n') if re.search(r'\bvs\.?\b', l, re.I)][:15]
            body = str(soup.body)[:12000] if soup.body else r.text[:12000]
            return jsonify({'url': pages[which], 'status': r.status_code, 'length': len(r.text),
                            'top_classes': classes.most_common(40), 'vs_lines': vs_lines,
                            'text_head': text[:2500], 'body_head': body})
        except Exception as e:
            return jsonify({'url': pages[which], 'error': str(e)[:300]})

    if part == 'alert_test':
        import alerts as _alerts
        return jsonify({'enabled': _alerts.enabled(), 'sent': _alerts.send('[fightschedule.live] test alert', 'Alerting works.')})

    if part == 'scrape_log':
        path = data_path('data_sources_comparison.txt')
        if not os.path.exists(path):
            return jsonify({'error': 'no scrape log yet'}), 404
        with open(path, encoding='utf-8', errors='replace') as f:
            body = f.read()
        resp = make_response(body[-20000:])
        resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return resp

    if part:
        filename = _DEBUG_PARTS.get(part)
        if not filename:
            return jsonify({'error': f'unknown part, valid: {sorted(_DEBUG_PARTS)}'}), 400
        path = data_path(filename)
        if not os.path.exists(path):
            return jsonify({'error': f'{filename} does not exist'}), 404
        with open(path) as f:
            return jsonify(json.load(f))

    # Default: summary overview
    summary = {'files': {}}
    for name, filename in _DEBUG_PARTS.items():
        path = data_path(filename)
        if os.path.exists(path):
            stat = os.stat(path)
            summary['files'][name] = {
                'size_bytes': stat.st_size,
                'modified_utc': datetime.utcfromtimestamp(stat.st_mtime).isoformat() + 'Z',
            }
        else:
            summary['files'][name] = None

    try:
        with open(fight_store.CACHE_FILE) as f:
            cache = json.load(f)
        fights = cache.get('fights', [])
        by_sport = {}
        pairs = {}
        for fight in fights:
            by_sport[fight.get('sport', '?')] = by_sport.get(fight.get('sport', '?'), 0) + 1
            key = ' vs '.join(sorted([fight.get('fighter1', '').lower(), fight.get('fighter2', '').lower()]))
            pairs[key] = pairs.get(key, 0) + 1
        dupes = {k: v for k, v in pairs.items() if v > 1}
        with_images = sum(1 for f_ in fights if f_.get('fighter1_image') or f_.get('fighter2_image'))
        summary['cache'] = {
            'timestamp': cache.get('timestamp'),
            'total_fights': len(fights),
            'by_sport': by_sport,
            'duplicate_matchups': dupes,
            'fights_with_any_image': with_images,
            'sample_fight': fights[0] if fights else None,
        }
    except Exception as e:
        summary['cache'] = {'error': str(e)}

    summary['persisted_fighter_images'] = []
    fighters_dir = data_path('fighters')
    if os.path.isdir(fighters_dir):
        summary['persisted_fighter_images'] = sorted(os.listdir(fighters_dir))

    return jsonify(summary)


_csrf.exempt(debug_state)
