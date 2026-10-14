"""Real-browser checks for fightschedule.live (the redesign of 2026-10-14). Run them locally before any change to
templates, CSS or static/js/site.js (CLAUDE.md: "Browser checks run locally before anything that changes templates
or JS").

They test behaviour, not looks, and read what a visitor sees (MISTAKES.md 2026-09-30: never the flag the code set):
  1. every page at phone, tablet and desktop widths: no script errors, no sideways scroll, one <h1>, no link inside
     a link, no photo left invisible, the 404 page answers 404, no small photo short of its half's width, no
     countdown after the start and none on a card that is over
  2. time zones, New York (12-hour clock) against Tallinn (24-hour): every time, date, day heading, day count, group
     ("This week" / "Next week" / "Later"), night hint ("Sat–Sun night") and clock-change row is checked against the
     visitor's own zone (MISTAKES.md 2026-09-29: two non-UTC zones, the full visible date + time), including the
     case the rules exist for: a fight at 02:00 on a Sunday in Tallinn is Saturday evening in New York
  3. what a click or tap does, on a phone (touch) and a desktop: the poster cards' hit areas (elementFromPoint at the
     photo, the names and the time: MISTAKES.md 2026-10-14), undercards open and close and their label changes,
     search opens, finds and closes with Escape, "Featured above" jumps to its card, /ufc#results lands on the
     results, the folded "no result on record" line opens
  4. usage counts: each tap sends the right name (and detail) to /api/t, one the server keeps (usage.valid_tap),
     and the "seen" beacon goes once after 5 visible seconds
  5. consent (the bar on a first visit; Decline hides it and Google Analytics never loads), reduced motion (nothing
     keeps moving), and without JavaScript (times and the time-zone label read UTC; links work)

Usage (start a server on a copy of live data first; CLAUDE.md "Test with a copy of live data"):
  DATA_DIR=<copy> python app.py                       # or any local server
  python checks/browser_checks.py --base http://127.0.0.1:5000 --clock 2026-10-13T21:00:00Z
      [--empty http://127.0.0.1:5001]                  a server whose boxing schedule is empty
      [--path /boxing-event/...]                       another page for section 1 (repeatable)
      [--alt http://127.0.0.1:5002@2026-10-17T21:30:00Z]  a server frozen at another moment (repeatable): the
                                                       time-zone checks again (e.g. a fight under way after the
                                                       visitor's midnight, or a night fight a week ahead)
--clock is the browser's clock; give the server's clock when the server's is frozen. Exit code 1 if anything fails.
Chromium: $CHROMIUM or /opt/pw-browsers/chromium. Only the local servers are reached; every other request is
blocked.
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import usage  # noqa: E402  (the server's own rule for which taps it keeps)

ap = argparse.ArgumentParser()
ap.add_argument('--base', default='http://127.0.0.1:5000')
ap.add_argument('--clock', default=None, help="the browser's clock, e.g. 2026-10-13T21:00:00Z (default: now)")
ap.add_argument('--empty', default=None, help='a server whose boxing schedule is empty')
ap.add_argument('--alt', action='append', default=[], metavar='URL@CLOCK',
                help='a server frozen at another moment, and that moment (repeatable): the time-zone checks again')
ap.add_argument('--only', default='pages,tz,clicks,misc', help='sections to run (default: all): pages,tz,clicks,misc')
ap.add_argument('--path', action='append', default=[], help='another page for section 1 (repeatable), e.g. a fight '
                'page whose card ended a moment ago (with --clock at that moment) or a poster with a small photo')
args = ap.parse_args()
ONLY = set(args.only.split(','))
CHROMIUM = os.environ.get('CHROMIUM', '/opt/pw-browsers/chromium')

PHONE = dict(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
             user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like '
                        'Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
TABLET = dict(viewport={'width': 820, 'height': 1180}, has_touch=True)
DESKTOP = dict(viewport={'width': 1440, 'height': 900})
# (zone, locale, 12-hour clock): the visitor pairs every time check runs for
ZONES = (('Europe/Tallinn', 'en-GB', False), ('America/New_York', 'en-US', True))
WD = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December')
fails = []
notes = []


def fail(msg):
    fails.append(msg)
    print('FAIL', msg)


def ok(msg):
    notes.append(msg)
    print('  ok', msg)


def hosts():
    out = [args.base] + [u for u in [args.empty] + [a.split('@')[0] for a in args.alt] if u]
    return [re.match(r'https?://[^/]+', u).group(0) for u in out]


def local_only(route):
    u = route.request.url
    if any(u.startswith(h) for h in hosts()):
        return route.continue_()
    return route.abort()


def parse_clock(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else datetime.now(timezone.utc)


def new_ctx(browser, size, tz='Europe/Tallinn', locale='en-GB', consent='denied', clock=None, **extra):
    ctx = browser.new_context(locale=locale, timezone_id=tz, **size, **extra)
    if consent:
        ctx.add_init_script(f"try{{localStorage.setItem('fs-consent','{consent}')}}catch(e){{}}")
    ctx.route('**/*', local_only)
    if clock or args.clock:
        ctx.clock.install(time=clock or args.clock)     # the clock starts there and runs
    return ctx


def open_page(ctx, url):
    pg = ctx.new_page()
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    resp = pg.goto(url, wait_until='networkidle')
    pg.wait_for_timeout(300)
    return pg, errors, resp


def beacons_of(pg):
    got = []

    def on_req(r):
        if r.url.endswith('/api/t') and r.method == 'POST':
            try:
                got.append(json.loads(r.post_data or '{}'))
            except ValueError:
                got.append({'name': '?', 'raw': r.post_data})
    pg.on('request', on_req)
    return got


# ---------------------------------------------------------------- the rules (design.py's, in the visitor's zone)
def utc_start(d, t):
    if not d or not t or not re.match(r'^\d{1,2}:\d{2}', t):
        return None
    h, m = t.split(':')[:2]
    y, mo, da = (int(x) for x in d[:10].split('-'))
    return datetime(y, mo, da, int(h), int(m[:2]), tzinfo=timezone.utc)


def hm_text(dt, h12):
    if not h12:
        return f'{dt.hour:02d}:{dt.minute:02d}'
    return f'{dt.hour % 12 or 12}:{dt.minute:02d}' + ('PM' if dt.hour >= 12 else 'AM')


def day_short(d):
    return f'{WD[d.weekday()][:3]} {d.day} {MONTHS[d.month - 1][:3]}'


def night_hint(dt):
    return f'{WD[(dt.weekday() - 1) % 7][:3]}–{WD[dt.weekday()][:3]} night' if dt and dt.hour < 6 else ''


def rel_day(d, today):
    n = (d - today).days
    return {0: 'Today', 1: 'Tomorrow', -1: 'Yesterday'}.get(n, f'in {n} days' if n > 1 else f'{-n} days ago')


def squash(s):
    return re.sub(r'[\s  ]+', '', s or '')


def transition_wall(a, b, z):
    """The wall time (on the old offset) at which z's offset changes between UTC instants a < b."""
    o0 = a.astimezone(z).utcoffset()
    while b - a > timedelta(minutes=1):
        mid = a + (b - a) / 2
        if mid.astimezone(z).utcoffset() == o0:
            a = mid
        else:
            b = mid
    at = b.replace(second=0, microsecond=0)
    return at.astimezone(timezone(o0))


TABLE_JS = r"""() => {
  const sec = document.querySelector('.tt.sched'); if (!sec) return null;
  const vis = x => !!x && x.getClientRects().length > 0;
  const out = {count: (sec.querySelector('[data-count]') || {}).textContent || '', groups: [], flat: []};
  sec.querySelectorAll('.grp').forEach(g => {
    const grp = {id: g.dataset.grp, name: (g.querySelector('.grp-h .gn') || {}).textContent, none: !!g.querySelector('.grp-none'), n: 0};
    out.groups.push(grp);
    g.querySelectorAll('.days > *').forEach(b => {
      if (b.matches('p.clockchg')) { out.flat.push({kind: 'cc', grp: grp.id, text: b.textContent, h: b.querySelector('.cc-h').textContent, from: +b.dataset.offsetFrom, to: +b.dataset.offsetTo}); return; }
      const dh = b.querySelector('.day-h');
      b.querySelectorAll(':scope > *').forEach(x => {
        if (x.matches('p.clockchg')) out.flat.push({kind: 'cc', grp: grp.id, text: x.textContent, h: x.querySelector('.cc-h').textContent, from: +x.dataset.offsetFrom, to: +x.dataset.offsetTo});
        else if (x.matches('article.ev')) {
          grp.n++;
          const t = x.querySelector('.t time');
          const go = x.querySelector('a.ptr-go'), hero = go && document.getElementById(go.getAttribute('href').slice(1));
          out.flat.push({kind: x.classList.contains('ptr') ? 'ptr' : 'ev', grp: grp.id, key: x.dataset.key, day: b.dataset.day,
            dfull: dh.querySelector('.dfull').textContent, drel: dh.querySelector('.drel').textContent,
            date: t.dataset.date, utc: t.dataset.utcTime || null, est: t.dataset.estimated === 'true', text: t.textContent,
            live: x.classList.contains('is-live') || !!(hero && hero.classList.contains('is-live')),
            night: (x.querySelector('.nt.night') || {}).textContent || '', visible: vis(x)});
        }
      });
    });
  });
  return out;
}"""

TIMES_JS = r"""() => [...document.querySelectorAll('time.fight-time, time.fdate')].map(t => ({
  cls: t.className, fmt: t.dataset.format, date: t.dataset.date, utc: t.dataset.utcTime || null,
  est: t.dataset.estimated === 'true', text: t.textContent, hero: !!t.closest('.hero'), live: !!t.closest('.ev.is-live')}))"""

HEROES_JS = r"""() => [...document.querySelectorAll('.hero, .when')].map(h => {
  const r = h.querySelector('[data-rel]'), t = h.querySelector('.ld-time time'), n = h.querySelector('.ld-note');
  return {id: h.id || h.className, live: h.classList.contains('is-live') || !!h.querySelector('.ld-time .live'),
    rel: r ? r.textContent : null, date: r ? r.dataset.date : null, utc: r ? (r.dataset.utcTime || null) : null,
    tutc: t ? (t.dataset.utcTime || null) : null, tdate: t ? t.dataset.date : null,
    night: n ? ((n.querySelector('.nt.night') || {}).textContent || '') : '', notehidden: n ? n.hidden : null};
})"""


def check_times(pg, z, h12, today, tag):
    bad = 0
    for t in pg.evaluate(TIMES_JS):
        s = utc_start(t['date'], t['utc'])
        if t['fmt'] == 'date':
            d = s.astimezone(z).date() if s else date.fromisoformat(t['date'][:10])
            want = day_short(d)
        elif not s:
            want = 'TimeTBA'
        else:
            want = ('~' if t['est'] else '') + hm_text(s.astimezone(z), h12)
        if squash(t['text']) != squash(want):
            bad += 1
            if bad <= 3:
                fail(f'{tag}: <time {t["fmt"]}> for {t["date"]} {t["utc"]} UTC shows {t["text"]!r}, expected {want!r}')
    return bad


def check_heroes(pg, z, today, tag):
    for h in pg.evaluate(HEROES_JS):
        if h['rel'] is not None:
            s = utc_start(h['date'], h['utc'])
            d = s.astimezone(z).date() if s else date.fromisoformat(h['date'][:10])
            if h['rel'] != rel_day(d, today):
                fail(f'{tag}: {h["id"]} day count {h["rel"]!r}, expected {rel_day(d, today)!r}')
        s = utc_start(h['tdate'], h['tutc'])
        if s and not h['live'] and h['notehidden'] is not None:
            want = night_hint(s.astimezone(z))
            if h['night'] != want:
                fail(f'{tag}: {h["id"]} night hint {h["night"]!r}, expected {want!r}')


def check_table(pg, z, h12, today, tag, only_week=False):
    tab = pg.evaluate(TABLE_JS)
    if tab is None:
        return None
    rows = [x for x in tab['flat'] if x['kind'] != 'cc']
    n = len(rows)
    if tab['count'].strip() != f'{n} event{"" if n == 1 else "s"}':
        fail(f'{tag}: count says {tab["count"]!r} for {n} rows')
    gids = [g['id'] for g in tab['groups']]
    names = {'week': 'This week', 'next': 'Next week', 'later': 'Later', 'ahead': 'Further ahead'}
    for g in tab['groups']:
        if g['name'] != names.get(g['id']):
            fail(f'{tag}: group {g["id"]} headed {g["name"]!r}')
        if g['none'] != (g['n'] == 0):
            fail(f'{tag}: group {g["id"]} has {g["n"]} rows but "No fights listed" is {"shown" if g["none"] else "missing"}')
        if g['n'] == 0 and g['id'] in ('later', 'ahead'):
            fail(f'{tag}: empty {g["id"]} group shown')
    if gids != sorted(gids, key=['week', 'next', 'later', 'ahead'].index):
        fail(f'{tag}: groups out of order {gids}')
    if not only_week and ('week' not in gids or 'next' not in gids):
        fail(f'{tag}: This week / Next week missing ({gids})')
    prev_key = None
    for r in rows:
        s = utc_start(r['date'], r['utc'])
        loc = s.astimezone(z) if s else None
        lday = loc.date() if loc else date.fromisoformat(r['date'][:10])
        what = f'{tag}: {r["key"][:44]}'
        if r['day'] != lday.isoformat():
            fail(f'{what} listed under {r["day"]}, its local day is {lday}')
        want_full = f'{WD[lday.weekday()]} {lday.day} {MONTHS[lday.month - 1]}'
        if squash(r['dfull']) != squash(want_full) or r['drel'] != rel_day(lday, today):
            fail(f'{what}: day heading {r["dfull"]!r} / {r["drel"]!r}, expected {want_full!r} / {rel_day(lday, today)!r}')
        if (lday - today).days < 0 and not r['live']:
            fail(f'{what}: a fight of {lday} still listed on {today}')
        if r['grp'] != 'ahead':
            nday = lday - timedelta(days=1) if (loc and loc.hour < 6) else lday
            off = max(0, (nday - today).days)
            want_g = 'week' if off < 7 else 'next' if off < 14 else 'later'
            if r['grp'] != want_g:
                fail(f'{what} under {r["grp"]}, expected {want_g} (evening of {nday}, today {today})')
            cal = max(0, (lday - today).days)
            if want_g != ('week' if cal < 7 else 'next' if cal < 14 else 'later'):
                ok(f'{what}: {loc:%a %H:%M} counts as the evening before, so it is under {want_g}')
        want_t = ('~' if r['est'] else '') + hm_text(loc, h12) if loc else 'TimeTBA'
        if squash(r['text']) != squash(want_t):
            fail(f'{what}: time {r["text"]!r}, expected {want_t!r}')
        if r['kind'] == 'ev' and not r['live']:
            want_n = night_hint(loc) if loc else ''
            if r['night'] != want_n:
                fail(f'{what}: night hint {r["night"]!r}, expected {want_n!r}')
        if r['kind'] == 'ptr' and r['night']:
            fail(f'{what}: a pointer row with a night hint')
        k = (lday, s is None, s.timestamp() if s else 0)
        if r['grp'] != 'ahead' and prev_key and k < prev_key:
            fail(f'{what}: out of order')
        if r['grp'] != 'ahead':
            prev_key = k
    # clock-change rows: exactly between two timed rows whose offsets differ, worded in the visitor's clock
    timed = [(i, x) for i, x in enumerate(tab['flat']) if x['kind'] != 'cc' and x['utc']]
    seen_cc = 0
    for (i, a), (j, b) in zip(timed, timed[1:]):
        sa, sb = utc_start(a['date'], a['utc']), utc_start(b['date'], b['utc'])
        between = [x for x in tab['flat'][i + 1:j] if x['kind'] == 'cc']
        oa, ob = sa.astimezone(z).utcoffset(), sb.astimezone(z).utcoffset()
        if oa == ob or sb <= sa:
            if between:
                fail(f'{tag}: a clock-change row between {a["key"][:30]} and {b["key"][:30]} where the clock does not change')
            continue
        if len(between) != 1:
            fail(f'{tag}: {len(between)} clock-change rows between {a["key"][:30]} and {b["key"][:30]} (offset {oa} -> {ob})')
            continue
        cc = between[0]
        seen_cc += 1
        wall = transition_wall(sa, sb, z)
        word = 'back' if ob < oa else 'forward'
        if f'Clocks go {word}' not in cc['text'] or squash(cc['h']) != squash(hm_text(wall, h12)):
            fail(f'{tag}: clock-change row {cc["text"]!r}, expected "Clocks go {word}" at {hm_text(wall, h12)}')
        else:
            ok(f'{tag}: clock-change row "{squash(cc["h"])} Clocks go {word}" between {a["key"][:24]} and {b["key"][:24]}')
    if len([x for x in tab['flat'] if x['kind'] == 'cc']) != seen_cc:
        fail(f'{tag}: clock-change rows where none belong')
    return tab


def tz_suite(br, base, clock, label):
    """Section 2: every visible time on the schedule pages and a few fight pages, in both zones."""
    now = parse_clock(clock)
    ctx = new_ctx(br, DESKTOP, clock=clock)
    pg, _, _ = open_page(ctx, base + '/')
    fights = pg.eval_on_selector_all('.tt.sched a.ev-main, .hero a.rc-link', 'as => as.map(a => a.getAttribute("href"))')
    pg.goto(base + '/results', wait_until='networkidle')
    fights += pg.eval_on_selector_all('a.bx-main', 'as => as.map(a => a.getAttribute("href"))')[:2]
    ctx.close()
    fights = list(dict.fromkeys(fights))
    ufc = [f for f in fights if f.startswith('/event/')][:2]
    box = [f for f in fights if f.startswith('/boxing-event/')][:2]
    pages = ['/', '/ufc', '/boxing', '/results'] + ufc + box
    tables = {}
    for zname, loc, h12 in ZONES:
        z = ZoneInfo(zname)
        today = now.astimezone(z).date()
        ctx = new_ctx(br, DESKTOP, tz=zname, locale=loc, clock=clock)
        for path in pages:
            pg, errors, _ = open_page(ctx, base + path)
            tag = f'{label} {path} [{zname}]'
            if errors:
                fail(f'{tag}: script errors {errors[:2]}')
            lbl = pg.text_content('#timezone-display') or ''
            city = zname.split('/')[-1].replace('_', ' ')
            off = int(now.astimezone(z).utcoffset().total_seconds() // 60)
            want_lbl = f'{city} (GMT{"+" if off >= 0 else "−"}{abs(off) // 60}{":%02d" % (abs(off) % 60) if off % 60 else ""})'
            if lbl != want_lbl:
                fail(f'{tag}: time-zone label {lbl!r}, expected {want_lbl!r}')
            bad = [x for x in pg.eval_on_selector_all('.tz-display', 'xs => xs.map(x => x.textContent)') if x != want_lbl]
            if bad:
                fail(f'{tag}: "Times in" copies say {bad[:2]}')
            check_times(pg, z, h12, today, tag)
            check_heroes(pg, z, today, tag)
            tab = check_table(pg, z, h12, today, tag)
            if tab is not None:
                tables[(path, zname)] = tab
            pg.close()
        # the 404 page lists this week only
        pg, errors, resp = open_page(ctx, base + '/no-such-fight-page')
        check_table(pg, z, h12, today, f'{label} 404 [{zname}]', only_week=True)
        pg.close()
        ctx.close()
    # the case the rules exist for: a fight at 00:00-05:59 in Tallinn (ideally 02:00 on a Sunday) that is the
    # evening before in New York
    home_t, home_n = tables.get(('/', 'Europe/Tallinn')), tables.get(('/', 'America/New_York'))
    if home_t and home_n:
        tl, ny = ZoneInfo('Europe/Tallinn'), ZoneInfo('America/New_York')
        cands = []
        for r in home_t['flat']:
            s = utc_start(r.get('date'), r.get('utc'))
            # (not a fight under way: its row says LIVE, with no night hint)
            if r['kind'] == 'ev' and not r['live'] and s and s.astimezone(tl).hour < 6 and s.astimezone(ny).hour >= 17:
                lt = s.astimezone(tl)
                cands.append(((lt.weekday() != 6, abs(lt.hour - 2)), r, s))
        if not cands:
            notes.append(f'{label}: no fight at night in Tallinn and evening in New York to check')
            print(f'  -- {label}: no Tallinn-night / New-York-evening fight in the data')
        else:
            cands.sort(key=lambda c: c[0])
            _, r, s = cands[0]
            n = next((x for x in home_n['flat'] if x.get('key') == r['key']), None)
            lt, nt = s.astimezone(tl), s.astimezone(ny)
            want_t = (lt.date().isoformat(), night_hint(lt))
            want_n = (nt.date().isoformat(), '')
            got_t, got_n = (r['day'], r['night']), ((n['day'], n['night']) if n else None)
            if got_t != want_t or got_n != want_n or not n or not n['visible'] or not r['visible']:
                fail(f'{label}: {r["key"]}: Tallinn {got_t} (want {want_t}), New York {got_n} (want {want_n})')
            else:
                ok(f'{label}: {r["key"][:40]} at {lt:%a %d %b %H:%M} in Tallinn ("{r["night"]}", {r["grp"]}) is '
                   f'{nt:%a %d %b} {hm_text(nt, True)} in New York (no night hint, {n["grp"]}, under {n["day"]})')


# ---------------------------------------------------------------- clicks, taps and what they send
def no_nav(pg, on=True):
    pg.evaluate("on => { window.__noNav = on; if (!window.__noNavSet) { window.__noNavSet = 1;"
                " window.addEventListener('click', e => { if (window.__noNav) e.preventDefault(); }); } }", on)

TOUCH = {'on': False}
HITS = {'n': 0}

def press(locator, force=False):
    # a tap on a touch screen, a click on a desktop; force: whatever is on top at the element's centre takes it
    # (the poster's card-wide link lies over its photos)
    locator.scroll_into_view_if_needed()
    if TOUCH['on']:
        locator.tap(force=force)
    else:
        locator.click(force=force)

def hit_at(pg, got, sel, name, what):
    # a real press and release at the centre of the first visible `sel` (clamped into the viewport)
    loc = pg.locator(sel).locator('visible=true').first
    if not loc.count():
        return
    loc.scroll_into_view_if_needed()
    bb = loc.bounding_box()
    vw, vh = pg.viewport_size['width'], pg.viewport_size['height']
    x = min(max(bb['x'] + bb['width'] / 2, 2), vw - 2)
    y = min(max(bb['y'] + bb['height'] / 2, 2), vh - 2)
    n0 = len(got)
    no_nav(pg, True)
    pg.evaluate("() => { window.__hit = null; document.addEventListener('click', e => { window.__hit = e.target.closest('a') ? e.target.closest('a').className : e.target.tagName + '.' + e.target.className; }, {once: true, capture: true}); }")
    if TOUCH['on']:
        pg.touchscreen.tap(x, y)
    else:
        pg.mouse.click(x, y)
    pg.wait_for_timeout(250)
    no_nav(pg, False)
    new = [b for b in got[n0:] if b.get('name') == name]
    if not new:
        fail(f'{what}: the click reached {pg.evaluate("window.__hit")!r}, no {name} tap')
    elif new[0].get('detail') not in ('UFC', 'Boxing'):
        fail(f'{what}: {name} tap without its sport ({new[0]})')
    else:
        HITS['n'] += 1

def expect_tap(pg, got, locator, name, detail=None, what='', force=False):
    n0 = len(got)
    no_nav(pg, True)
    press(locator, force)
    pg.wait_for_timeout(250)
    no_nav(pg, False)
    new = got[n0:]
    hit = [b for b in new if b.get('name') == name and (detail is None or b.get('detail') == detail)]
    if not hit:
        fail(f'{what or name}: sent {[(b.get("name"), b.get("detail")) for b in new]}, expected {name} {detail or ""}')
        return None
    b = hit[0]
    if not usage.valid_tap(b.get('name'), b.get('detail')):
        fail(f'{what or name}: the server drops this tap ({b})')
    return b



with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=['--no-proxy-server'])
    B = args.base

    # ------------------------------------------------------------ 1. every page, three widths
    ctx = new_ctx(br, DESKTOP)
    pg, _, _ = open_page(ctx, B + '/')
    up = pg.eval_on_selector_all('.tt.sched a.ev-main', 'as => as.map(a => a.getAttribute("href"))')
    pg.goto(B + '/results', wait_until='networkidle')
    past = pg.eval_on_selector_all('a.bx-main', 'as => as.map(a => a.getAttribute("href"))')
    ctx.close()
    if not up:
        fail('the home page lists no fights (a.ev-main)')
    pick = [next((l for l in up if l.startswith(pre)), None) for pre in ('/event/', '/boxing-event/')]
    pick += [next((l for l in past if l.startswith(pre)), None) for pre in ('/event/', '/boxing-event/')]
    pages = ['/', '/ufc', '/boxing', '/results', '/privacy', '/no-such-fight-page'] + [x for x in pick if x] + args.path
    if 'pages' in ONLY:
        for size_name, size in (('phone', PHONE), ('tablet', TABLET), ('desktop', DESKTOP)):
            ctx = new_ctx(br, size)
            for path in pages:
                pg, errors, resp = open_page(ctx, B + path)
                tag = f'{path} [{size_name}]'
                if errors:
                    fail(f'{tag}: script errors {errors[:2]}')
                if path == '/no-such-fight-page' and resp.status != 404:
                    fail(f'{tag}: status {resp.status}, expected 404')
                elif path != '/no-such-fight-page' and resp.status != 200:
                    fail(f'{tag}: status {resp.status}')
                over = pg.evaluate('document.documentElement.scrollWidth - window.innerWidth')
                if over > 0:
                    fail(f'{tag}: scrolls sideways by {over}px')
                if pg.locator('h1').count() != 1:
                    fail(f'{tag}: {pg.locator("h1").count()} <h1> elements')
                if pg.locator('a a').count():
                    fail(f'{tag}: a link inside a link')
                # scroll through so lazy photos load, then: every photo that arrived is shown, none is left at opacity 0
                pg.evaluate('async () => { for (let y = 0; y < document.body.scrollHeight; y += 700) { scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); } scrollTo(0, 0); }')
                pg.wait_for_timeout(400)
                hidden = pg.evaluate("""[...document.querySelectorAll('.ph img, .face img, .won-ring img')]
                    .filter(i => i.complete && i.naturalWidth > 0 && (!i.classList.contains('ok') || getComputedStyle(i).opacity === '0'))
                    .map(i => i.getAttribute('src'))""")
                if hidden:
                    fail(f'{tag}: {len(hidden)} photos arrived but stay invisible {hidden[:2]}')
                if 'UTC' in ''.join(pg.eval_on_selector_all('time.fight-time', 'ts => ts.map(t => t.textContent)')):
                    fail(f'{tag}: a time still reads UTC after the script ran')
                # a file too short for its half covers the half's width (else its stretched rows framed it in a box)
                short = pg.evaluate("""[...document.querySelectorAll('.ph.sh:not(.vacant)')].map(ph => {
                    const h = ph.getBoundingClientRect(), i = ph.querySelector('img.pi');
                    if (!i || !h.width) return null;
                    const r = i.getBoundingClientRect();
                    return (r.left > h.left + 1 || r.right < h.right - 1) ? i.getAttribute('src') + ' ' + Math.round(r.left - h.left) + 'px/' + Math.round(h.right - r.right) + 'px' : null;
                }).filter(Boolean)""")
                if short:
                    fail(f'{tag}: a small photo stops short of its half (left/right gap) {short[:2]}')
                # the countdown: a freshly loaded page has none for a card that started (the server renders it only
                # before the start; give --clock the server's moment), and none on a card that is over
                stale = pg.evaluate("""[...document.querySelectorAll('[data-countdown]')].filter(c =>
                    Date.parse(c.dataset.countdown) < Date.now() - 15 * 60000).map(c => c.dataset.countdown + ' "' + c.textContent + '"')""")
                if stale:
                    fail(f'{tag}: a countdown for a card that started {stale[:2]}')
                if pg.locator('.fp.past [data-countdown], .fp.past .watch-panel').count():
                    fail(f'{tag}: a card that is over still shows its countdown or Where to watch')
                pg.close()
            ctx.close()
        print('1. pages: done')

    # ------------------------------------------------------------ 2. time zones
    if 'tz' in ONLY:
        tz_suite(br, B, args.clock, 'base')
        for n_alt, alt in enumerate(args.alt, 1):
            a_url, a_clock = alt.split('@', 1)
            tz_suite(br, a_url, a_clock, f'alt{n_alt}')
            # a fight under way stays listed after the visitor's midnight
            for zname, loc, h12 in ZONES:
                ctx = new_ctx(br, DESKTOP, tz=zname, locale=loc, clock=a_clock)
                raw = ctx.new_page()
                ctx.route('**/static/js/site.js', lambda r: r.abort())
                raw.goto(a_url + '/', wait_until='networkidle')
                server_live = raw.eval_on_selector_all('.tt.sched article.ev.is-live, .tt.sched article.ev.ptr',
                                                      'as => as.filter(a => a.classList.contains("is-live") || document.getElementById(a.querySelector("a.ptr-go").getAttribute("href").slice(1)).classList.contains("is-live")).map(a => a.dataset.key)')
                ctx.unroute('**/static/js/site.js')
                pg, _, _ = open_page(ctx, a_url + '/')
                shown = pg.eval_on_selector_all('.tt.sched article.ev', 'as => as.map(a => a.dataset.key)')
                gone = [k for k in server_live if k not in shown]
                if gone:
                    fail(f'alt{n_alt} [{zname}]: fights under way dropped from the table: {gone}')
                elif server_live:
                    ok(f'alt{n_alt} [{zname}]: {len(server_live)} fight(s) under way stay listed: {server_live}')
                ctx.close()
        print('2. time zones: done')

    # ------------------------------------------------------------ 3 + 4. clicks, taps and usage counts
    if 'clicks' in ONLY:
        for size_name, size in (('phone', PHONE), ('desktop', DESKTOP)):
            tag = f'[{size_name}]'
            TOUCH['on'] = size_name == 'phone'
            ctx = new_ctx(br, size)
            pg, errors, _ = open_page(ctx, B + '/')
            got = beacons_of(pg)
            # card-wide links, clicked (or tapped) for real at the photo, the names and the time: the press must land
            # on the link and its release too (a :active transform once moved the release off it), so the page counts
            # the tap and the browser would follow the link. elementFromPoint alone cannot see that (MISTAKES.md).
            for hid in pg.eval_on_selector_all('.hero', 'hs => hs.map(h => h.id)'):
                for sel in ('.stage .ph.l', '.stage .ph.r', '.lockup', '.ld-time'):
                    hit_at(pg, got, f'#{hid} {sel}', 'big_card', f'poster #{hid} {sel} {tag}')
            for sel in ('.t', '.ev-main', '.top', '.pair'):
                hit_at(pg, got, f'.tt.sched article.ev:not(.ptr):not(.is-live) {sel}', 'card', f'schedule row {sel} {tag}')
            hit_at(pg, got, '#results .bx .bx-r', 'card', f'box score {tag}')
            w = pg.locator('.tt.sched a.watch').first
            if w.count():
                prov = w.get_attribute('href').split('/go/')[1].split('?')[0]
                expect_tap(pg, got, w, 'watch', prov, what=f'row Watch {tag}')
            w = pg.locator('.hero a.rc-watch').first
            if w.count():
                prov = w.get_attribute('href').split('/go/')[1].split('?')[0]
                expect_tap(pg, got, w, 'watch', prov, what=f'poster Watch {tag}')
            # undercard: opens, shows its fights, the label changes; closes again
            s = pg.locator('.tt.sched details.ucd > summary.more').first
            if s.count():
                closed = s.get_attribute('data-closed-label')
                n0 = len(got)
                press(s); pg.wait_for_timeout(350)
                uc_vis = pg.evaluate("() => { const d = document.querySelector('.tt.sched details.ucd'), u = d.querySelector('.uc');"
                                     " const r = u.getBoundingClientRect(); return d.open && r.height > 20 && u.getClientRects().length > 0; }")
                lbl = s.locator('.lbl').text_content()
                if not uc_vis or lbl != s.get_attribute('data-open-label'):
                    fail(f'undercard {tag}: open={uc_vis}, label {lbl!r}')
                press(s); pg.wait_for_timeout(350)
                lbl = s.locator('.lbl').text_content()
                if pg.evaluate("document.querySelector('.tt.sched details.ucd').open") or lbl != closed:
                    fail(f'undercard {tag}: did not close (label {lbl!r})')
                names = [b.get('name') for b in got[n0:]]
                if names[:2] != ['undercard_open', 'undercard_close']:
                    fail(f'undercard {tag}: sent {names}, expected undercard_open then undercard_close')
            else:
                fail(f'no undercard on the home page {tag}')
            # search: opens and takes the focus, finds a fighter on the page, Escape closes and gives the focus back
            n0 = len(got)
            press(pg.locator('#searchToggle')); pg.wait_for_timeout(250)
            st = pg.evaluate("() => ({open: !document.getElementById('searchBar').hidden && document.getElementById('searchBar').getClientRects().length > 0,"
                             " exp: document.getElementById('searchToggle').getAttribute('aria-expanded'), focus: document.activeElement && document.activeElement.id})")
            if not st['open'] or st['exp'] != 'true' or st['focus'] != 'searchInput':
                fail(f'search {tag}: did not open with the focus in the box ({st})')
            data = json.loads(pg.text_content('#search-data') or '[]')
            name = next((f['fighter1'] for f in data if f.get('fighter1') and not re.search(r'[^\x00-\x7f]', f['fighter1'])), 'a')
            q = name.split()[-1][:5].lower()
            pg.locator('#searchInput').fill(q); pg.wait_for_timeout(250)
            hits = pg.eval_on_selector_all('#searchResults a', 'as => as.filter(a => a.getClientRects().length).map(a => a.getAttribute("href"))')
            want = [f for f in data if any(q in (f.get(k) or '').lower() for k in ('fighter1', 'fighter2', 'event_name', 'venue'))]
            if not hits or len(hits) != min(50, len(want)):
                fail(f'search {tag}: "{q}" shows {len(hits)} results, expected {min(50, len(want))}')
            if any(not re.match(r'^/(event|boxing-event)/', h) for h in hits):
                fail(f'search {tag}: a result is not a fight page {hits[:3]}')
            acc = next((f for f in data if re.search(r'[áéíóúčšžñ]', (f.get('fighter1') or '') + (f.get('fighter2') or ''))), None)
            if acc:
                word = next(w for w in (acc['fighter1'] + ' ' + acc['fighter2']).split() if re.search(r'[áéíóúčšžñ]', w))
                plain = word.lower().translate(str.maketrans('áéíóúčšžñ', 'aeioucszn'))
                pg.locator('#searchInput').fill(plain); pg.wait_for_timeout(200)
                if not pg.locator('#searchResults a').count():
                    fail(f'search {tag}: "{plain}" does not find {word}')
            pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
            st = pg.evaluate("() => ({open: document.getElementById('searchBar').getClientRects().length > 0, focus: document.activeElement && document.activeElement.id})")
            if st['open'] or st['focus'] != 'searchToggle':
                fail(f'search {tag}: Escape left it {st}')
            names = [b.get('name') for b in got[n0:]]
            if names.count('search_open') != 1 or names.count('search') != 1:
                fail(f'search {tag}: sent {names}, expected search_open and search once each')
            press(pg.locator('#searchToggle')); pg.wait_for_timeout(150)
            n0 = len(got)
            press(pg.locator('#searchToggle')); pg.wait_for_timeout(150)          # closing is not an "open"
            if any(b.get('name') == 'search_open' for b in got[n0:]):
                fail(f'search {tag}: closing the drawer counted as search_open')
            # "Featured above" jumps to its poster card
            go = pg.locator('.tt.sched a.ptr-go').first
            if go.count():
                hid = go.get_attribute('href')[1:]
                press(go); pg.wait_for_timeout(700)
                top = pg.evaluate("hid => document.getElementById(hid).getBoundingClientRect().top", hid)
                if not (-5 <= top <= pg.viewport_size['height'] * 0.5):
                    fail(f'"Featured above" {tag}: #{hid} is at {top:.0f}px after the click')
            # the header and the footer
            expect_tap(pg, got, pg.locator('.nav-pill', has_text='Results').first if size_name == 'desktop' else
                       pg.locator('.nav-pill').nth(1), 'nav', what=f'nav {tag}')
            expect_tap(pg, got, pg.locator('.page-foot a[href="/privacy"]').first, 'foot_link', 'Privacy and cookies',
                       what=f'footer link {tag}')
            expect_tap(pg, got, pg.locator('.page-foot a[href$="ufc.ics"]').first, 'calendar_feed', 'ufc', what=f'feed {tag}')
            bad = [b for b in got if not usage.valid_tap(b.get('name'), b.get('detail'))]
            if bad:
                fail(f'home {tag}: taps the server drops: {bad[:3]}')
            ctx.close()

            # the poster cards on the other pages (the sport pages' one or two, the 404 page's one)
            for path in ('/ufc', '/boxing', '/no-such-fight-page'):
                ctx2 = new_ctx(br, size)
                pg2, _, _ = open_page(ctx2, B + path)
                got2 = beacons_of(pg2)
                for hid in pg2.eval_on_selector_all('.hero', 'hs => hs.map(h => h.id)'):
                    for sel in ('.stage .ph.l', '.stage .ph.r', '.lockup', '.ld-time'):
                        hit_at(pg2, got2, f'#{hid} {sel}', 'big_card', f'{path} poster #{hid} {sel} {tag}')
                ctx2.close()

            # another page's Search goes to the home page's search, open
            ctx = new_ctx(br, size)
            pg, _, _ = open_page(ctx, B + '/ufc')
            got = beacons_of(pg)
            press(pg.locator('#searchToggle')); pg.wait_for_load_state('networkidle'); pg.wait_for_timeout(300)
            if not pg.url.endswith('/#search') or not pg.evaluate("document.getElementById('searchBar').getClientRects().length > 0"):
                fail(f'/ufc Search {tag}: ended at {pg.url} with the drawer shut')
            # /ufc#results lands on the results; the folded "no result on record" line opens
            pg.goto(B + '/ufc#results', wait_until='networkidle'); pg.wait_for_timeout(400)
            top, at_end = pg.evaluate("[document.getElementById('results').getBoundingClientRect().top,"
                                      " scrollY >= document.documentElement.scrollHeight - innerHeight - 2]")
            if not (-5 <= top <= 120 or (at_end and 0 <= top <= pg.viewport_size['height'] * 0.6)):
                fail(f'/ufc#results {tag}: the results start at {top:.0f}px')
            nr = pg.locator('details.nr > summary').first
            if nr.count():
                press(nr); pg.wait_for_timeout(300)
                if not pg.evaluate("[...document.querySelectorAll('details.nr .pl-row')].some(x => x.getClientRects().length && x.getBoundingClientRect().height > 10)"):
                    fail(f'/ufc {tag}: the "no result on record" line did not open')
            # a fight page: Watch, Add to calendar, the breadcrumb
            if pick[0]:
                pg.goto(B + pick[0], wait_until='networkidle')
                got = beacons_of(pg)
                w = pg.locator('a.wrow').first
                if w.count():
                    prov = w.get_attribute('href').split('/go/')[1].split('?')[0]
                    expect_tap(pg, got, w, 'watch', prov, what=f'fight page Watch {tag}')
                c = pg.locator('.cal-links a').first
                if c.count():
                    expect_tap(pg, got, c, 'calendar_add', what=f'Add to calendar {tag}')
                expect_tap(pg, got, pg.locator('.crumbs a').first, 'crumb', what=f'breadcrumb {tag}')
            # the 404 page counts as /404
            pg.goto(B + '/no-such-fight-page', wait_until='networkidle')
            got = beacons_of(pg)
            b = expect_tap(pg, got, pg.locator('.nav-pill').first, 'nav', what=f'404 nav {tag}')
            if b and b.get('page') != '/404':
                fail(f'404 {tag}: a tap reports page {b.get("page")!r}')
            ctx.close()

        # "seen": once, after 5 visible seconds
        ctx = new_ctx(br, PHONE)
        pg = ctx.new_page()
        got = beacons_of(pg)
        pg.goto(B + '/', wait_until='networkidle')
        pg.wait_for_timeout(3500)
        if any(b.get('name') == 'seen' for b in got):
            fail('"seen" sent before 5 seconds')
        pg.wait_for_timeout(3500)
        if [b.get('name') for b in got].count('seen') != 1:
            fail(f'"seen" sent {[b.get("name") for b in got].count("seen")} times in 7 s, expected once')
        ctx.close()
        print(f'3/4. clicks and usage counts: done ({HITS["n"]} real clicks reached their card link)')

    # ------------------------------------------------------------ 5. consent, reduced motion, no JavaScript
    if 'misc' in ONLY:
        ctx = new_ctx(br, PHONE, consent=None)
        pg, _, _ = open_page(ctx, B + '/')
        if not pg.locator('#fs-consent').is_visible():
            fail('consent bar not shown on a first visit')
        else:
            pg.locator('[data-consent="denied"]').first.click(); pg.wait_for_timeout(300)
            if pg.locator('#fs-consent').is_visible():
                fail('consent bar still shown after Decline')
            if pg.evaluate('!!window.gtag'):
                fail('Google Analytics loaded after Decline')
            # the footer's "Cookie settings" brings the bar back (Accept / Decline), focus on it, the page stays
            got = beacons_of(pg)
            pg.locator('.page-foot [data-consent-open]').click(); pg.wait_for_timeout(300)
            if not pg.locator('#fs-consent').is_visible() or pg.url.rstrip('/') != B.rstrip('/'):
                fail(f'footer Cookie settings: bar shown {pg.locator("#fs-consent").is_visible()}, now on {pg.url}')
            elif not pg.evaluate("!!document.activeElement.closest('#fs-consent')"):
                fail('footer Cookie settings: focus is not on the consent bar')
            else:
                ok('footer Cookie settings reopens the consent bar')
            if not any(b.get('name') == 'foot_link' and b.get('detail') == 'Cookie settings' for b in got):
                fail(f'footer Cookie settings: no foot_link tap ({got[-2:]})')
        ctx.close()

        ctx = new_ctx(br, PHONE, reduced_motion='reduce')
        for path in ['/'] + [x for x in pick[:1] if x]:
            pg, _, _ = open_page(ctx, B + path)
            pg.wait_for_timeout(600)
            running = pg.evaluate("document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.getTiming().duration > 50).length")
            if running:
                fail(f'{path}: {running} animations still running with reduced motion')
            pg.close()
        ctx.close()

        ctx = br.new_context(java_script_enabled=False, **DESKTOP)
        ctx.route('**/*', local_only)
        for path in ['/', '/ufc'] + [x for x in pick[:2] if x]:
            pg = ctx.new_page()
            pg.goto(B + path, wait_until='networkidle')
            times = pg.eval_on_selector_all('time.fight-time[data-utc-time]', 'ts => ts.map(t => t.textContent)')
            if not times or any(not t.endswith('UTC') for t in times):
                fail(f'no JavaScript {path}: times {times[:3]} do not read UTC')
            if (pg.text_content('#timezone-display') or '') != 'UTC':
                fail(f'no JavaScript {path}: the time-zone label is not UTC')
            if path in ('/', '/ufc') and not pg.locator('.tt.sched a.ev-main').count():
                fail(f'no JavaScript {path}: no fight links')
            pg.close()
        ctx.close()
        print('5. consent, reduced motion, no JavaScript: done')

    # ------------------------------------------------------------ the empty boxing schedule
    if 'misc' in ONLY and args.empty:
        for size_name, size in (('phone', PHONE), ('desktop', DESKTOP)):
            ctx = new_ctx(br, size)
            pg, errors, resp = open_page(ctx, args.empty + '/boxing')
            tag = f'empty /boxing [{size_name}]'
            if errors:
                fail(f'{tag}: script errors {errors[:2]}')
            if not pg.locator('section.mc.em').is_visible():
                fail(f'{tag}: no "No fights listed" message')
            if pg.locator('h1').count() != 1:
                fail(f'{tag}: {pg.locator("h1").count()} <h1>')
            if pg.evaluate('document.documentElement.scrollWidth - window.innerWidth') > 0:
                fail(f'{tag}: scrolls sideways')
            got = beacons_of(pg)
            feed = pg.locator('section.mc.em a[href$=".ics"]').first
            if feed.count():
                expect_tap(pg, got, feed, 'calendar_feed', 'boxing', what=tag + ' feed')
            ctx.close()
    br.close()

print()
print('browser checks:', 'all passed' if not fails else f'{len(fails)} failed')
sys.exit(1 if fails else 0)
