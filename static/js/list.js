/* Shared page behaviour for the homepage, results, sport pages and fight pages:
   local times, regrouping by the visitor's local day, relative day labels,
   undercard open/close and the All / UFC / Boxing chips. The server renders UTC
   times and UTC day groups, so pages still read correctly without JavaScript. */
(function () {
    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

    function startOf(date, utc) {
        if (!date || !utc || !/^\d{1,2}:\d{2}/.test(utc)) return null;
        var p = utc.split(':');
        var d = new Date(date + 'T' + p[0].padStart(2, '0') + ':' + p[1].slice(0, 2) + ':00Z');
        return isNaN(d) ? null : d;
    }
    function dayKey(d) { return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate(); }
    function daysFromToday(d) {
        var t = new Date(); t.setHours(0, 0, 0, 0);
        return Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - t) / 86400000);
    }
    function aheadLabel(n) {
        if (n === 0) return 'today';
        if (n === 1) return 'tomorrow';
        return n > 1 && n < 7 ? 'in ' + n + ' days' : '';
    }
    function agoLabel(n) {
        if (n === 0) return 'today';
        if (n === -1) return 'yesterday';
        return n < -1 ? (-n) + ' days ago' : '';
    }
    function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
    function clock(d) {
        var h = d.getHours();
        return { hm: (h % 12 || 12) + ':' + String(d.getMinutes()).padStart(2, '0'), ap: h >= 12 ? 'PM' : 'AM' };
    }
    function shortDate(d) { return WEEKDAYS[d.getDay()].slice(0, 3) + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()]; }
    // Local calendar day an element starts on (date-only items keep their date).
    function localDayOf(el) {
        var t = el && el.querySelector('time[data-date]');
        if (!t) return null;
        var d = startOf(t.getAttribute('data-date'), t.getAttribute('data-utc-time'));
        if (d) return new Date(d.getFullYear(), d.getMonth(), d.getDate());
        var p = t.getAttribute('data-date').split('-');
        return new Date(+p[0], +p[1] - 1, +p[2]);
    }
    window.FS = { startOf: startOf, clock: clock, shortDate: shortDate, MONTHS: MONTHS };

    // 1. Times in the visitor's zone
    document.querySelectorAll('time.fight-time, time[data-format="date"]').forEach(function (el) {
        var fmt = el.getAttribute('data-format') || 'plain';
        var d = startOf(el.getAttribute('data-date'), el.getAttribute('data-utc-time'));
        var est = el.getAttribute('data-estimated') === 'true' ? '~' : '';
        if (!d) {
            var p = (el.getAttribute('data-date') || '').split('-');
            if (fmt === 'long' && p.length === 3) el.textContent = shortDate(new Date(+p[0], +p[1] - 1, +p[2])) + ' · Time TBA';
            if (fmt === 'date' && p.length === 3) el.textContent = shortDate(new Date(+p[0], +p[1] - 1, +p[2]));
            return;
        }
        var c = clock(d);
        if (fmt === 'big') {
            el.textContent = est + c.hm;
            var ap = document.createElement('span'); ap.className = 'ap'; ap.textContent = c.ap;
            el.appendChild(ap);
        } else if (fmt === 'long') {
            el.textContent = shortDate(d) + ' · ' + est + c.hm + ' ' + c.ap;
        } else {
            el.textContent = est + c.hm + ' ' + c.ap;
        }
        if (est) el.title = 'Estimated start time based on the venue region';
    });

    // 2. Time-zone line
    var tzEl = document.getElementById('timezone-display');
    if (tzEl) {
        try {
            var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            var abbr = new Date().toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ')[2];
            var prefix = tzEl.getAttribute('data-prefix') || (tzEl.textContent.charAt(0) === 'T' ? 'Times in ' : 'times in ');
            tzEl.textContent = prefix + tz.split('/').pop().replace(/_/g, ' ') + (abbr ? ' (' + abbr + ')' : '');
        } catch (e) {}
    }

    // 3. Regroup each list by the visitor's local day
    document.querySelectorAll('.days').forEach(function (box) {
        try {
            var past = box.getAttribute('data-order') === 'desc';
            var cards = Array.prototype.slice.call(box.querySelectorAll('article.ev'));
            if (!cards.length) return;
            var items = cards.map(function (c, i) { var d = localDayOf(c); return { c: c, i: i, d: d, k: d ? dayKey(d) : 0 }; });
            if (!items.every(function (x) { return x.d; })) return;
            items.sort(function (a, b) { return (past ? b.k - a.k : a.k - b.k) || (a.i - b.i); });
            var sections = [], sec = null, last = null;
            items.forEach(function (it) {
                if (it.k !== last) {
                    sec = document.createElement('section'); sec.className = 'day';
                    var h = document.createElement('h3'); h.className = 'day-h';
                    var n = document.createElement('span'); n.className = 'dname'; n.textContent = WEEKDAYS[it.d.getDay()];
                    var dt = document.createElement('span'); dt.className = 'ddate'; dt.textContent = it.d.getDate() + ' ' + MONTHS[it.d.getMonth()];
                    h.appendChild(n); h.appendChild(document.createTextNode(' ')); h.appendChild(dt);
                    var off = daysFromToday(it.d), r = past ? agoLabel(off) : aheadLabel(off);
                    if (r) {
                        var chip = document.createElement('span'); chip.className = past ? 'ago' : 'rel'; chip.textContent = r;
                        h.appendChild(document.createTextNode(' ')); h.appendChild(chip);
                    }
                    sec.appendChild(h); sections.push(sec); last = it.k;
                }
                sec.appendChild(it.c);
            });
            box.replaceChildren.apply(box, sections);
        } catch (e) { /* keep the server's grouping */ }
    });

    // 4. Relative chips on big cards and fight-page heroes
    document.querySelectorAll('[data-rel-chip]').forEach(function (host) {
        var chip = host.querySelector('.rel'), d = localDayOf(host);
        if (!chip || !d) return;
        chip.textContent = cap(aheadLabel(daysFromToday(d)) || (d.getDate() + ' ' + MONTHS[d.getMonth()]));
    });

    // 5. Undercard open/close
    document.querySelectorAll('.ev .more').forEach(function (btn) {
        var closed = btn.textContent;
        btn.addEventListener('click', function () {
            var list = document.getElementById(btn.getAttribute('aria-controls'));
            var open = btn.getAttribute('aria-expanded') !== 'true';
            list.hidden = !open;
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            btn.textContent = open ? btn.getAttribute('data-open-label') : closed;
        });
    });

    // 6. All / UFC / Boxing chips
    var chips = document.querySelectorAll('.chipf[data-filter]');
    function applyFilter(sport) {
        chips.forEach(function (c) { c.setAttribute('aria-pressed', c.getAttribute('data-filter') === sport ? 'true' : 'false'); });
        var match = function (el) { return sport === 'All' || el.getAttribute('data-sport') === sport; };
        document.querySelectorAll('.days article.ev').forEach(function (c) { c.hidden = !match(c); });
        document.querySelectorAll('.days section.day').forEach(function (s) {
            s.hidden = !s.querySelector('article.ev:not([hidden])');
        });
        var empty = document.getElementById('filterEmpty');
        if (empty) empty.hidden = !!document.querySelector('.days article.ev:not([hidden])') || !document.querySelector('.days article.ev');
        var first = true, anyBig = false;
        document.querySelectorAll('.rc').forEach(function (c) {
            var ok = match(c);
            c.hidden = !ok;
            c.classList.toggle('lead', ok && first);
            if (ok) { first = false; anyBig = true; }
        });
        var bigSec = document.querySelector('.big-section');
        if (bigSec) bigSec.hidden = !anyBig;
    }
    chips.forEach(function (c) {
        c.addEventListener('click', function () { applyFilter(c.getAttribute('data-filter')); });
    });
})();
