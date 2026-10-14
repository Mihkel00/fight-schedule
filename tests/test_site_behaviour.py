"""The page script (static/js/site.js) and the server agree: every page of the redesign loads it, every tap it sends
is one /api/t keeps, the markup has the hooks it reads, and the poster card's card-wide link keeps its hit area while
pressed. What the script does in a browser (local times, regrouping, night hints, clicks) is checked in a real
browser by checks/browser_checks.py, which pytest cannot run; it is at least compiled here."""
import os
import py_compile
import re

import usage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(os.path.join(ROOT, 'static', 'js', 'site.js'), encoding='utf-8').read()
CSS = open(os.path.join(ROOT, 'static', 'css', 'site.css'), encoding='utf-8').read()


def _page(client, path):
    r = client.get(path)
    return r.status_code, r.get_data(as_text=True)


def test_every_tap_the_script_sends_is_one_the_server_keeps():
    names = set()
    for call in re.findall(r"\btap\(([^;]*)\);", JS):           # tap('card', sport); tap(open ? 'a' : 'b');
        first = re.split(r",(?![^(]*\))", call)[0]
        names |= set(re.findall(r"'([a-z_]+)'", first))
    assert {'seen', 'card', 'big_card', 'watch', 'undercard_open', 'undercard_close', 'search_open', 'search', 'nav',
            'crumb', 'foot_link', 'calendar_add', 'calendar_feed'} <= names
    assert names <= usage.TAP_NAMES, names - usage.TAP_NAMES
    # details are cleaned to what the server accepts ("Privacy & cookies" would otherwise drop the whole tap)
    assert "replace(/&/g, 'and')" in JS and usage.valid_tap('foot_link', 'Privacy and cookies')
    assert not usage.valid_tap('foot_link', 'Privacy & cookies')


def test_every_redesigned_page_loads_the_one_script(client):
    paths = ['/', '/ufc', '/boxing', '/results', '/privacy', '/no-such-fight-page']
    _, home = _page(client, '/')
    paths += sorted(set(re.findall(r'href="(/(?:event|boxing-event)/[^"#?]+)"', home)))[:2]
    for path in paths:
        status, h = _page(client, path)
        assert status in (200, 404), path
        assert h.count('<script src="/static/js/site.js" defer></script>') == 1, path
        assert 'list.js' not in h, path
    assert not os.path.exists(os.path.join(ROOT, 'static', 'js', 'list.js')), \
        'retired: a browser holding a cached list.js would run it against the new markup'


def test_markup_has_the_hooks_the_script_reads(client):
    _, h = _page(client, '/')
    for hook in ('id="timezone-display"', 'class="tz-display"', 'class="tt sched"', 'data-count', 'data-grp="week"',
                 '<section class="day" data-day="', '<h4 class="day-h">', 'data-utc-time="', 'data-format="big"',
                 'data-countdown="', 'data-rel ', 'class="ld-note"', '<details class="ucd"', 'data-open-label="Hide fights"',
                 'id="searchToggle"', 'id="searchBar"', 'id="searchInput"', 'id="searchResults"', 'id="search-data"',
                 'class="ptr-go" href="#lead', 'class="ev-main"', 'rc-link'):
        assert hook in h, hook
    # without JavaScript every time reads UTC
    assert re.search(r'data-format="big">~?\d{2}:\d{2} UTC</time>', h)


def test_the_poster_link_keeps_its_hit_area_while_pressed():
    """.btn:active scales the button; a transform makes the Fight card button the containing block of its ::after,
    so between press and release the card-wide hit area shrank to the button and a click on the photo went nowhere
    (found by checks/browser_checks.py, 2026-10-14). The card link must never take a transform or a filter."""
    rule = re.search(r'\.hero \.fc, \.hero \.fc:active \{([^}]*)\}', CSS)
    assert rule and 'transform: none' in rule.group(1) and 'backdrop-filter: none' in rule.group(1)
    checked = 0
    for m in re.finditer(r'([^{}]*\.fc\b[^{}]*)\{([^}]*)\}', CSS):
        if '.hero' not in m.group(1):
            continue
        for prop, val in re.findall(r'(?<![\w-])(-webkit-backdrop-filter|backdrop-filter|filter|transform|will-change|'
                                    r'contain)\s*:\s*([^;]+)', m.group(2)):
            checked += 1
            assert val.strip() in ('none', 'auto'), f'{m.group(1).strip()} sets {prop}: {val}'
    assert checked >= 3


def test_browser_checks_compile():
    py_compile.compile(os.path.join(ROOT, 'checks', 'browser_checks.py'), doraise=True)
