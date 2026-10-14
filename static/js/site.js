/* fightschedule.live — behaviour for the redesign (templates/_base.html, templates/_ui.html). Vanilla, no
   dependencies. The server renders every time in UTC ("18:00 UTC") and groups the schedule by UTC day, so a page
   reads correctly without JavaScript; this script shows it in the visitor's zone:

     0. usage counts (cookie-free, /privacy#usage): the "seen" beacon and taps to /api/t (same names as list.js)
     1. times and dates in the visitor's zone (24-hour, or 12-hour where the visitor's locale uses it)
     2. the time-zone label (#timezone-display, .tz-display)
     3. the schedule table regrouped by the visitor's local day: This week / Next week / Later, day headings and
        counts, night hints ("Fri–Sat night"), clock-change rows (the same rules as design.py's schedule())
     4. day counts and the hours countdown on the poster cards
     5. results: one name size per row of box scores
     6. undercard labels, the search drawer
   Every step is wrapped: if one fails, the server's UTC rendering stays. */
(function () {
    'use strict';
    var doc = document;
    var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
        'November', 'December'];
    var WD = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    var DAY = 864e5;

    function safe(fn) { try { fn(); } catch (e) { /* keep the server's rendering */ } }

    /* ---------- 0. usage counts ---------- */
    function tap(name, detail) {
        try {
            var body = JSON.stringify({ name: name, detail: detail || null, page: location.pathname });
            if (navigator.sendBeacon) navigator.sendBeacon('/api/t', new Blob([body], { type: 'application/json' }));
            else fetch('/api/t', { method: 'POST', body: body, headers: { 'Content-Type': 'application/json' }, keepalive: true });
        } catch (e) {}
    }
    window.FS_tap = tap;

    // A page counts as "seen" once it has been on screen for 5 seconds in total (the people count).
    (function () {
        var need = 5000, shown = 0, since = null, timer = null, sent = false;
        function start() {
            if (sent || since !== null) return;
            since = Date.now();
            timer = setTimeout(function () {
                shown += Date.now() - since; since = null;
                if (shown >= need) { sent = true; tap('seen'); } else start();
            }, need - shown);
        }
        function stop() {
            if (since === null) return;
            clearTimeout(timer); shown += Date.now() - since; since = null;
        }
        doc.addEventListener('visibilitychange', function () {
            if (doc.visibilityState === 'visible') start(); else stop();
        });
        if (doc.visibilityState === 'visible') start();
    })();

    function goProvider(el) {
        var h = el.getAttribute('href') || '';
        return h.indexOf('/go/') !== -1 ? h.split('/go/')[1].split('?')[0] : null;
    }
    doc.addEventListener('click', function (ev) {
        var el = ev.target.closest('a, button, summary');
        if (!el) return;
        var c = el.classList, art = el.closest('article');
        var sport = art && art.getAttribute('data-sport');
        if (c.contains('ev-main') || c.contains('bx-main') || c.contains('pl-n')) tap('card', sport);
        else if (c.contains('rc-link')) tap('big_card', sport);
        else if (c.contains('more')) {
            var d = el.closest('details');
            tap(d && d.open ? 'undercard_close' : 'undercard_open');
        }
        else if (c.contains('wrow') || c.contains('watch') || c.contains('rc-watch')) tap('watch', goProvider(el));
        else if (el.closest('.cal-links')) tap((el.getAttribute('href') || '').indexOf('.ics') !== -1 ? 'calendar_feed' : 'calendar_add');
        else if (c.contains('nav-pill')) tap('nav', el.textContent.trim());
        else if (el.id === 'searchToggle') tap('search_open');
        else if (el.hasAttribute('data-tab')) tap('tab', el.getAttribute('data-tab'));
        else if (el.closest('.crumbs')) tap('crumb');
        else if (el.closest('.page-foot')) tap('foot_link', el.textContent.trim());
        // the affiliate click event for Google Analytics (only loaded after consent), as _watch.html sends it
        var p = goProvider(el);
        if (p && window.gtag) {
            var q = new URLSearchParams((el.getAttribute('href') || '').split('?')[1] || '');
            window.gtag('event', 'affiliate_click', { provider: p, event_slug: q.get('event'), placement: q.get('p') });
        }
    }, true);

    /* ---------- time helpers ---------- */
    function startOf(date, utc) {
        if (!date || !utc || !/^\d{1,2}:\d{2}/.test(utc)) return null;
        var p = utc.split(':');
        var d = new Date(date + 'T' + p[0].padStart(2, '0') + ':' + p[1].slice(0, 2) + ':00Z');
        return isNaN(d) ? null : d;
    }
    function elStart(el) { return el ? startOf(el.getAttribute('data-date'), el.getAttribute('data-utc-time')) : null; }
    function dateOnly(iso) { var p = (iso || '').split('-'); return p.length === 3 ? new Date(+p[0], +p[1] - 1, +p[2]) : null; }
    function midnight(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
    function localDayOf(el) {
        // the local calendar day an element starts on (date-only items keep their date)
        var s = elStart(el);
        return s ? midnight(s) : dateOnly(el && el.getAttribute('data-date'));
    }
    function dayDiff(a, b) { return Math.round((midnight(a) - midnight(b)) / DAY); }
    function iso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
    function shortDay(d) { return WD[d.getDay()].slice(0, 3) + ' ' + d.getDate() + ' ' + MON[d.getMonth()]; }
    function relText(n) {
        if (n === 0) return 'Today';
        if (n === 1) return 'Tomorrow';
        if (n > 1) return 'in ' + n + ' days';
        if (n === -1) return 'Yesterday';
        return (-n) + ' days ago';
    }
    function nightText(d) {
        // 00:00-05:59 is the night between two days (design.night_hint)
        if (!d || d.getHours() >= 6) return '';
        return WD[(d.getDay() + 6) % 7].slice(0, 3) + '–' + WD[d.getDay()].slice(0, 3) + ' night';
    }
    var H12 = false;
    try { H12 = !!new Intl.DateTimeFormat(undefined, { hour: 'numeric' }).resolvedOptions().hour12; } catch (e) {}
    function clockParts(d) {
        var h = d.getHours(), m = String(d.getMinutes()).padStart(2, '0');
        if (!H12) return { hm: String(h).padStart(2, '0') + ':' + m, ap: '' };
        return { hm: (h % 12 || 12) + ':' + m, ap: h >= 12 ? 'PM' : 'AM' };
    }
    function offsetMin(d) { return -d.getTimezoneOffset(); }
    function gmt(min) {
        var a = Math.abs(min), h = Math.floor(a / 60), m = a % 60;
        return 'GMT' + (min >= 0 ? '+' : '−') + h + (m ? ':' + String(m).padStart(2, '0') : '');
    }
    function el(tag, cls, text) {
        var x = doc.createElement(tag);
        if (cls) x.className = cls;
        if (text != null) x.textContent = text;
        return x;
    }

    /* ---------- 1. times and dates ---------- */
    function renderTime(t) {
        var fmt = t.getAttribute('data-format') || 'short';
        if (fmt === 'date') {
            var day = localDayOf(t);
            if (day) t.textContent = shortDay(day);
            return;
        }
        var d = elStart(t);
        if (!d) return;                                   // "Time TBA" stays
        var est = t.getAttribute('data-estimated') === 'true';
        var c = clockParts(d);
        t.textContent = '';
        if (est) {
            if (fmt === 'big' || fmt === 'long') { var ti = el('span', 'tilde', '~'); ti.setAttribute('aria-hidden', 'true'); t.appendChild(ti); }
            else t.appendChild(doc.createTextNode('~'));
            t.title = 'Estimated start time';
        }
        t.appendChild(doc.createTextNode(c.hm));
        if (c.ap) t.appendChild(el('span', 'ap', c.ap));
    }
    safe(function () { doc.querySelectorAll('time.fight-time, time[data-format="date"]').forEach(renderTime); });

    /* ---------- 2. the time-zone label ---------- */
    var tzText = 'your time zone';
    safe(function () {
        var tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
        var city = tz.split('/').pop().replace(/_/g, ' ');
        tzText = (city && city !== 'UTC' ? city + ' (' + gmt(offsetMin(new Date())) + ')' : 'UTC');
        var main = doc.getElementById('timezone-display');
        if (main) main.textContent = tzText;
        doc.querySelectorAll('.tz-display').forEach(function (x) { x.textContent = tzText; });
    });

    /* ---------- notes under a time: the night hint is local ---------- */
    function setNight(host, sepHtml, start) {
        // host: a row's .t (its notes in .sub) or a poster's .ld-note
        var poster = host.classList.contains('ld-note');
        var box = poster ? host : host.querySelector('.sub');
        var text = nightText(start);
        var cur = box && box.querySelector('.nt.night');
        if (cur && text) { cur.textContent = text; return; }
        if (cur && !text) {
            var prev = cur.previousElementSibling, next = cur.nextElementSibling;
            if (prev && prev.classList.contains('ns')) prev.remove(); else if (next && next.classList.contains('ns')) next.remove();
            cur.remove();
            if (box && !box.querySelector('.nt')) { if (poster) box.hidden = true; else box.remove(); }
            return;
        }
        if (!text) return;
        if (!box) { box = el('span', 'sub'); host.appendChild(box); }
        if (poster) box.hidden = false;
        var n = el('span', 'nt night', text);
        var est = box.querySelector('.nt.est');
        var sep = function () { var s = el('span', 'ns'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = sepHtml; return s; };
        if (est) { est.after(sep(), n); }
        else if (box.querySelector('.nt')) { box.prepend(n, sep()); }
        else box.appendChild(n);
    }

    /* ---------- 3. the schedule, regrouped by the visitor's local day ---------- */
    var GROUPS = [['week', 'This week', 0, 7, '', 'w', 'this week'], ['next', 'Next week', 7, 14, '', 'n', 'next week'],
        ['later', 'Later', 14, null, '', 'l', 'later'], ['ahead', 'Further ahead', null, null, 'headline events only', 'a', 'further ahead']];

    function transition(a, b) {
        // the instant between a and b (Dates) at which the local offset changes, to the minute
        var t0 = a.getTime(), t1 = b.getTime(), o0 = offsetMin(a);
        while (t1 - t0 > 60000) {
            var mid = t0 + Math.floor((t1 - t0) / 2);
            if (offsetMin(new Date(mid)) === o0) t0 = mid; else t1 = mid;
        }
        return new Date(Math.floor(t1 / 60000) * 60000);
    }
    function clockRow(prevStart, start, outside) {
        var oa = offsetMin(prevStart), ob = offsetMin(start);
        if (oa === ob || start <= prevStart) return null;
        var at = transition(prevStart, start);
        var old = new Date(at.getTime() + oa * 60000);     // its wall time on the old offset, read as UTC fields
        var d = Math.abs(ob - oa);
        var by = d === 60 ? 'an hour' : (d % 60 === 0 ? (d / 60) + ' hours' : d + ' minutes');
        var p = el('p', 'clockchg' + (outside ? ' out' : ''));
        p.setAttribute('role', 'note');
        p.setAttribute('data-offset-from', oa); p.setAttribute('data-offset-to', ob);
        p.appendChild(el('span', 'cc-d', WD[old.getUTCDay()].slice(0, 3) + ' ' + old.getUTCDate() + ' ' + MON[old.getUTCMonth()]));
        p.appendChild(el('span', 'cc-h', String(old.getUTCHours()).padStart(2, '0') + ':' + String(old.getUTCMinutes()).padStart(2, '0')));
        var x = el('span', 'cc-x');
        x.appendChild(el('b', 'cc-t', 'Clocks go ' + (ob < oa ? 'back' : 'forward') + ' ' + by));
        x.appendChild(doc.createTextNode(' ·\u00a0times from here on are ' + gmt(ob)));
        p.appendChild(x);
        return { node: p, day: midnight(at) };
    }
    function dayHead(d, today) {
        var h = el('h4', 'day-h');
        var full = el('span', 'dfull', WD[d.getDay()] + ' ');
        full.appendChild(el('span', null, d.getDate() + ' ' + MONTHS[d.getMonth()]));
        var sh = el('span', 'dshort', shortDay(d)); sh.setAttribute('aria-hidden', 'true');
        var n = dayDiff(d, today);
        h.append(full, sh, el('span', 'drel' + (n >= 0 && n <= 1 ? ' soon' : ''), relText(n)));
        return h;
    }
    function regroup(sec) {
        var today = midnight(new Date());
        var rows = [].slice.call(sec.querySelectorAll('article.ev'));
        if (!rows.length) return;
        var items = rows.map(function (a, i) {
            var t = a.querySelector('.t time');
            var s = elStart(t), day = localDayOf(t);
            var nd = s && s.getHours() < 6 ? new Date(day.getTime() - DAY) : day;
            return { a: a, i: i, s: s, day: day, nday: nd, beyond: !!a.closest('[data-grp="ahead"]') };
        });
        if (!items.every(function (x) { return x.day; })) return;
        items = items.filter(function (x) { return dayDiff(x.day, today) >= 0; }).concat([]);
        items.sort(function (a, b) {
            return (a.day - b.day) || ((a.s ? 0 : 1) - (b.s ? 0 : 1)) || ((a.s && b.s) ? a.s - b.s : 0) || (a.i - b.i);
        });
        var keepEmpty = {}, oldGroups = [].slice.call(sec.querySelectorAll('.grp'));
        oldGroups.forEach(function (g) { keepEmpty[g.getAttribute('data-grp')] = true; });
        function off(x) { return Math.max(0, dayDiff(x.nday, today)); }
        var plan = [];
        GROUPS.forEach(function (G) {
            var its = items.filter(function (x) {
                if (G[0] === 'ahead') return x.beyond;
                return !x.beyond && off(x) >= G[2] && (G[3] === null || off(x) < G[3]);
            });
            if (!its.length && (G[0] === 'later' || G[0] === 'ahead')) return;
            if (!its.length && !keepEmpty[G[0]]) return;
            plan.push({ G: G, items: its, blocks: [] });
        });
        function groupOf(d) {
            var k = dayDiff(d, today);
            for (var i = 0; i < plan.length; i++) {
                var G = plan[i].G;
                if (G[0] !== 'ahead' && k >= G[2] && (G[3] === null || k < G[3])) return plan[i];
            }
            return null;
        }
        var prev = null;
        plan.forEach(function (g) {
            var by = {}, keys = [];
            g.items.forEach(function (x) { var k = x.day.getTime(); if (!by[k]) { by[k] = []; keys.push(k); } by[k].push(x); });
            keys.sort(function (a, b) { return a - b; });
            keys.forEach(function (k) {
                var list = by[k], first = null;
                for (var j = 0; j < list.length; j++) if (list[j].s) { first = list[j]; break; }
                if (prev && first) {
                    var chg = clockRow(prev.s, first.s, true);
                    if (chg) { var home = groupOf(chg.day); ((home && home !== g) ? home : g).blocks.push(chg.node); }
                    prev = first;
                }
                var secEl = el('section', 'day');
                secEl.setAttribute('data-day', iso(list[0].day));
                secEl.appendChild(dayHead(list[0].day, today));
                list.forEach(function (x) {
                    if (prev && x.s && x !== first) { var c = clockRow(prev.s, x.s, false); if (c) secEl.appendChild(c.node); }
                    secEl.appendChild(x.a);
                    if (x.s) prev = x;
                });
                g.blocks.push(secEl);
            });
        });
        var frag = doc.createDocumentFragment(), sid = sec.id || 'sched';
        plan.forEach(function (g) {
            var G = g.G, box = el('div', 'grp');
            box.setAttribute('data-grp', G[0]); box.id = sid + '-' + G[0];
            var h = el('h3', 'grp-h');
            h.appendChild(el('span', 'gn', G[1]));
            if (G[4]) h.appendChild(el('span', 'gs', G[4]));
            var days = el('div', 'days');
            days.setAttribute('data-order', 'asc'); days.setAttribute('data-prefix', G[5]);
            g.blocks.forEach(function (b) { days.appendChild(b); });
            box.append(h, days);
            if (!g.items.length) box.appendChild(el('p', 'grp-none', 'No fights listed ' + G[6]));
            frag.appendChild(box);
        });
        oldGroups.forEach(function (g) { g.remove(); });
        sec.appendChild(frag);
        var count = sec.querySelector('[data-count]');
        if (count) { var n = items.length; count.textContent = n + ' event' + (n === 1 ? '' : 's'); }
        // the night hint under each time
        items.forEach(function (x) {
            if (x.a.classList.contains('ptr') || x.a.classList.contains('is-live')) return;
            setNight(x.a.querySelector('.t'), '&#8239;·&#160;', x.s);
        });
    }
    safe(function () { doc.querySelectorAll('.tt.sched').forEach(function (s) { safe(function () { regroup(s); }); }); });

    /* ---------- 4. poster cards: day count, countdown, night hint ---------- */
    function cdText(target) {
        var mins = Math.floor((target - Date.now()) / 60000);
        if (mins <= 0) return 'starting now';
        if (mins >= 1440) return '';
        var h = Math.floor(mins / 60), m = mins % 60;
        return h ? 'in ' + h + ' h ' + m + ' min' : 'in ' + m + ' min';
    }
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
    function renderCounts(animate) {
        var today = midnight(new Date());
        doc.querySelectorAll('[data-rel]').forEach(function (r) {
            var d = localDayOf(r);
            if (d) { var t = relText(dayDiff(d, today)); if (r.textContent !== t) r.textContent = t; }
        });
        doc.querySelectorAll('[data-countdown]').forEach(function (c) {
            var t = cdText(Date.parse(c.getAttribute('data-countdown')));
            if (c.textContent !== t) {
                c.textContent = t;
                if (animate && !(reduce && reduce.matches)) { c.classList.remove('tick'); void c.offsetWidth; c.classList.add('tick'); }
            }
        });
    }
    safe(function () {
        renderCounts(false);
        doc.querySelectorAll('.hero .ld-note').forEach(function (n) {
            var hero = n.closest('.hero');
            if (hero.classList.contains('is-live')) return;
            safe(function () { setNight(n, ' ·&#160;', elStart(hero.querySelector('.ld-time time'))); });
        });
        if (doc.querySelector('[data-countdown], [data-rel]')) {
            (function tick() { setTimeout(function () { safe(function () { renderCounts(true); }); tick(); }, 60000 - (Date.now() % 60000) + 40); })();
        }
    });

    /* ---------- 5. results: one name size per row of box scores (the smallest fit, 18-26px) ---------- */
    function vis(x) { return x.getClientRects().length > 0; }
    function emOf(c) { return parseFloat(c.style.getPropertyValue('--em-s')) || parseFloat(getComputedStyle(c).getPropertyValue('--em-s')); }
    function fitAll() {
        doc.querySelectorAll('.bxs').forEach(function (r) {
            if (innerWidth < 1024) { r.style.removeProperty('--nm'); return; }
            var m = 26;
            [].slice.call(r.querySelectorAll('.bx')).filter(vis).forEach(function (c) {
                var main = c.querySelector('.bx-main'), e = emOf(c);
                if (main && e) m = Math.min(m, (main.clientWidth - 34 - 50) / e / 1.03);
            });
            r.style.setProperty('--nm', Math.max(18, m).toFixed(2) + 'px');
        });
    }
    safe(function () {
        if (!doc.querySelector('.bxs')) return;
        var queued = false;
        var queue = function () { if (queued) return; queued = true; requestAnimationFrame(function () { queued = false; safe(fitAll); }); };
        fitAll();
        if (window.ResizeObserver) new ResizeObserver(queue).observe(doc.body); else window.addEventListener('resize', queue);
    });

    /* ---------- 6. undercard labels; the search drawer ---------- */
    safe(function () {
        doc.querySelectorAll('details.ucd').forEach(function (d) {
            d.addEventListener('toggle', function () {
                var s = d.querySelector(':scope > summary'), l = s && s.querySelector('.lbl');
                if (l) l.textContent = d.open ? s.getAttribute('data-open-label') : s.getAttribute('data-closed-label');
            });
        });
    });

    safe(function () {
        var toggle = doc.getElementById('searchToggle'), bar = doc.getElementById('searchBar');
        var input = doc.getElementById('searchInput'), out = doc.getElementById('searchResults');
        if (!toggle || !bar || toggle.tagName !== 'BUTTON') return;
        var data = [];
        try { data = JSON.parse((doc.getElementById('search-data') || {}).textContent || '[]'); } catch (e) {}
        function open() { bar.hidden = false; toggle.setAttribute('aria-expanded', 'true'); if (input) input.focus(); }
        function close(back) {
            bar.hidden = true; toggle.setAttribute('aria-expanded', 'false');
            if (input) { input.value = ''; render(''); }
            if (back) toggle.focus();
        }
        toggle.addEventListener('click', function () { if (bar.hidden) open(); else close(false); });
        doc.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !bar.hidden) close(true); });
        if (location.hash === '#search') open();
        function when(f) {
            var d = startOf(f.date, f.time);
            if (!d) { var p = dateOnly(f.date); return (p ? shortDay(p) : f.date) + ' · Time TBA'; }
            var c = clockParts(d);
            return shortDay(d) + ' · ' + (f.time_estimated ? '~' : '') + c.hm + (c.ap ? ' ' + c.ap : '');
        }
        function render(q) {
            q = (q || '').toLowerCase().trim();
            out.replaceChildren();
            if (!q) return;
            var hits = data.filter(function (f) {
                return [f.fighter1, f.fighter2, f.event_name, f.venue].some(function (v) { return v && v.toLowerCase().indexOf(q) !== -1; });
            });
            out.appendChild(el('p', 'sr-h', hits.length ? hits.length + ' fight' + (hits.length === 1 ? '' : 's') + ' found' : 'No fights found for “' + q + '”'));
            if (!hits.length) return;
            var list = el('div', 'sr-list');
            hits.slice(0, 50).forEach(function (f) {
                var a = el('a'); a.href = f.path;
                var n = el('span', 'sr-n', f.fighter1 + ' vs ' + f.fighter2);
                if (f.event_name || f.venue) n.appendChild(el('small', null, f.event_name || f.venue));
                a.append(n, el('span', 'sr-t', when(f)));
                list.appendChild(a);
            });
            out.appendChild(list);
        }
        var searched = false;
        if (input) input.addEventListener('input', function () {
            if (!searched && input.value.trim()) { searched = true; tap('search'); }
            if (!input.value.trim()) searched = false;
            render(input.value);
        });
    });
})();
