"""
Cookie-free counting: page views, taps, watch-link redirects (/go/).

Moved out of app.py unchanged (2026-10); app.py imports every module so
the routes register on the one Flask app.
"""
import affiliates as _aff
import json
import os
import re
import threading
import usage as _usage
from admin_setup_simple import csrf as _csrf
from datetime import datetime, timedelta
from flask import abort, make_response, redirect, request
from core import app, data_path, logger


CLICKS_FILE = data_path('clicks.jsonl')


_clicks_lock = threading.Lock()


_BOT_UA = re.compile(r'bot|crawl|spider|slurp|preview|fetch|scrap|headless|python|curl|wget|httpclient|'
                     r'axios|node-fetch|go-http|java/|okhttp|facebookexternalhit|embedly|whatsapp|telegram|'
                     r'discord|slack|skype|monitor|uptime|lighthouse|pagespeed|google-read-aloud|mediapartners|'
                     r'gptbot|claude|anthropic|perplexity|bytespider|ccbot|cohere|amazonbot|youbot|meta-external',
                     re.IGNORECASE)


def _is_bot(ua):
    """Best-effort: empty user agents and known crawler / tool signatures."""
    return (not ua) or bool(_BOT_UA.search(ua))


def _from_this_site(req):
    """Did this request come from a page on fightschedule.live (or a local dev
    server)? Scripts hitting endpoints directly send no Referer/Origin."""
    src = req.headers.get('Origin') or req.headers.get('Referer') or ''
    host = req.host.split(':')[0]
    return bool(re.match(r'https?://(www\.)?' + re.escape(host) + r'(:\d+)?(/|$)', src))


@app.after_request
def _count_page_view(resp):
    """One usage record per HTML page served to a browser. Cookie-free; no IP."""
    try:
        if (request.method == 'GET' and resp.status_code == 200
                and resp.mimetype == 'text/html'
                and not request.path.startswith(('/admin', '/api', '/static', '/go/', '/health'))):
            ua = request.headers.get('User-Agent') or ''
            _usage.record('view', _usage.page_type(request.path), bot=_is_bot(ua),
                          lang=(request.headers.get('Accept-Language') or '').strip())
    except Exception:
        pass
    return resp


@app.route('/api/t', methods=['POST'])
def usage_beacon():
    """Tap counter. Body: {"name": "card", "page": "/ufc", "detail": "UFC"}.
    Always 204; invalid or oversized bodies are dropped silently."""
    try:
        if request.content_length and request.content_length > 600:
            return '', 204
        data = request.get_json(force=True, silent=True) or {}
        name, detail = data.get('name'), data.get('detail')
        if not _usage.valid_tap(name, detail):
            return '', 204
        ua = request.headers.get('User-Agent') or ''
        seen = name == _usage.SEEN
        _usage.record('seen' if seen else 'tap', _usage.page_type(str(data.get('page') or request.headers.get('Referer') or '')),
                      name=None if seen else name, detail=None if seen else (detail or None), bot=_is_bot(ua),
                      lang=(request.headers.get('Accept-Language') or '').strip(),
                      referer_ok=_from_this_site(request))
    except Exception:
        pass
    resp = make_response('', 204)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


_csrf.exempt(usage_beacon)


@app.route('/go/<provider>')
def go_provider(provider):
    """Redirect to a streaming provider and log the click (server-side, ad-blocker proof)."""
    url = _aff.affiliate_url(provider, request.args.get('event', '')[:120])
    if not url:
        abort(404)
    try:
        ua = (request.headers.get('User-Agent') or '')[:200]
        lang = (request.headers.get('Accept-Language') or '').split(',')[0].split(';')[0].strip()[:12] or None
        record = {
            'ts': datetime.utcnow().isoformat() + 'Z',
            'bot': _is_bot(ua),
            'ua': ua,
            'lang': lang,
            'provider': provider,
            'event': request.args.get('event', '')[:120],
            'sport': request.args.get('sport', '')[:10],
            'placement': request.args.get('p', '')[:20],
            'referer': (request.headers.get('Referer') or '')[:200],
            'affiliate': _aff.is_affiliate_configured(provider),
        }
        with _clicks_lock:
            with open(CLICKS_FILE, 'a') as f:
                f.write(json.dumps(record) + '\n')
    except Exception as e:
        logger.warning(f"click log failed: {e}")
    resp = redirect(url, code=302)
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return resp


def click_stats(days=30):
    """Aggregate clicks.jsonl by provider / day for the debug API."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    by_provider, by_day, by_event, total = {}, {}, {}, 0
    kinds = {'human': 0, 'bot': 0, 'unknown (before user agents were logged)': 0}
    human_provider, human_lang, bot_agents = {}, {}, {}
    # 'Real' = not a known bot, the browser sent a language, AND the click came
    # from a page on this site (Referer). A visitor tapping a watch link always
    # sends both; scripts hitting /go/ directly usually send neither referer
    # nor language (61 of 63 'browser-like' clicks on 2026-10-01 had no referer).
    real = {'total': 0, 'by_day': {}, 'by_placement': {}, 'by_provider': {}, 'by_page': {}, 'by_sport': {}}

    def _bump(d, k):
        d[k] = d.get(k, 0) + 1

    def _page(ref):
        path = re.sub(r'^https?://[^/]+', '', ref or '').split('?')[0].split('#')[0]
        if path in ('', '/'):
            return 'homepage'
        for prefix, name in (('/results', 'results'), ('/ufc', 'ufc page'), ('/boxing-event/', 'boxing fight page'),
                             ('/boxing', 'boxing page'), ('/event/', 'ufc fight page')):
            if path.startswith(prefix):
                return name
        return 'other'
    if os.path.exists(CLICKS_FILE):
        with open(CLICKS_FILE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('ts', '') < cutoff:
                    continue
                total += 1
                if 'bot' not in r:
                    kinds['unknown (before user agents were logged)'] += 1
                elif r['bot']:
                    kinds['bot'] += 1
                    agent = (r.get('ua') or '(empty)')[:60]
                    bot_agents[agent] = bot_agents.get(agent, 0) + 1
                else:
                    kinds['human'] += 1
                    human_provider[r.get('provider')] = human_provider.get(r.get('provider'), 0) + 1
                    lg = r.get('lang') or '(none)'
                    human_lang[lg] = human_lang.get(lg, 0) + 1
                    if r.get('lang') and re.match(r'https?://(www\.)?fightschedule\.live/', r.get('referer') or ''):
                        real['total'] += 1
                        _bump(real['by_day'], r['ts'][:10])
                        _bump(real['by_placement'], r.get('placement') or '(not tagged)')
                        _bump(real['by_provider'], r.get('provider'))
                        _bump(real['by_page'], _page(r.get('referer')))
                        _bump(real['by_sport'], r.get('sport') or '-')
                by_provider[r.get('provider')] = by_provider.get(r.get('provider'), 0) + 1
                by_day[r['ts'][:10]] = by_day.get(r['ts'][:10], 0) + 1
                by_event[r.get('event') or '-'] = by_event.get(r.get('event') or '-', 0) + 1
    return {'days': days, 'total': total, 'by_kind': kinds, 'human_by_provider': human_provider,
            'human_languages': sorted(human_lang.items(), key=lambda kv: -kv[1])[:15],
            'bot_agents': sorted(bot_agents.items(), key=lambda kv: -kv[1])[:15],
            'by_provider': by_provider, 'by_day': dict(sorted(by_day.items())),
            'top_events': sorted(by_event.items(), key=lambda kv: -kv[1])[:20],
            'configured_affiliates': [k for k in _aff.PROVIDERS if _aff.is_affiliate_configured(k)],
            'real_clicks': {**real, 'by_day': dict(sorted(real['by_day'].items()))}}
