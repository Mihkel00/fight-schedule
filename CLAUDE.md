# fightschedule.live — working notes for Claude

**First, read `MISTAKES.md` in full.** It is the log of things that went wrong
in this project and why. Every session starts by reading it, and its rules
apply to all work here.

When the owner points out a mistake, or one is discovered, add an entry to
`MISTAKES.md` *before* fixing it, with:
- what happened (one or two sentences),
- the root cause — the reasoning or process failure, not the symptom,
- the rule that prevents it next time.

## Scope

- Build what was asked. Ideas for anything the owner did not request — and in
  particular anything a visitor would *see* differently — are proposed
  separately and built only after an explicit yes to that specific item.
  Never bundle a design change into a list of other items.
- When a request names a UI element ambiguously, name the concrete component
  before changing it.

## Project facts

- Flask app on Railway; persistent volume at `DATA_DIR` (`/data`).
- Data sources: ESPN (UFC schedule), boxingschedule.co (boxing schedule —
  has redesigned twice; parsers for all three layouts are kept), Wikipedia
  (fighter profiles, results, images), Wikidata and UFC.com (images).
- Tailwind CSS is built locally and committed (`static/css/styles.css`); the
  deploy does not rebuild it. Rebuild with
  `npx tailwindcss -i static/css/input.css -o static/css/styles.css --minify`
  after any template change that introduces new classes.
- The debug API (`/api/debug/state?token=…`) is the way to see production
  state; the sandbox cannot reach external hosts other than the site itself.
  Source health: `/health` (public, 200/503) and `part=health`, `part=run_log`,
  `part=snapshots`, `part=snapshot&source=Boxing|UFC` (the raw page a source
  sent). Every scrape saves its raw pages under `DATA_DIR/snapshots/` and a run
  record under `DATA_DIR/runs/` (see `runs.py`). A production page that
  parses wrongly is fetched with `part=snapshot` and becomes a test fixture
  before the parser is changed.
- Test with a copy of live data (`part=cache`, `part=profiles`, …) in a
  scratch `DATA_DIR`; never commit files under `data/`.
- Tests: `pytest -q` (tests/, fixtures in tests/fixtures/) must pass before any
  commit — `pytest -q > out 2>&1 && git commit …`, never through a pipe. GitHub
  Actions runs the same suite on every push. When a production page parses
  wrongly, fetch it with `part=snapshot`, save it under tests/fixtures/ with the
  correct expected output, and only then change the parser. Browser checks
  (Playwright, scratchpad `site_browser.py`, `tz_browser.py`) run locally before
  anything that changes templates or JS.
- Tests run with the clock frozen to the fixtures' day (`FIXTURE_NOW` in
  `tests/conftest.py`); a new fixture set brings its own date.
- Commits: gate commit/push on tests passing; never chain them past a test
  without `&&`.

## Parked (agreed to revisit — do not build without the owner's go-ahead)

- **Image rights** (from the 2026-09-29 review): UFC.com/ESPN headshots are
  copyrighted; Wikimedia photos need author/licence credit and share-alike for
  crops. Do not press "Apply new rules" on the image dry run (13 of 18 new
  images are UFC.com) until this is decided.
- **Rotate `DEBUG_API_TOKEN`**: it has appeared in chat and in URLs, and the
  debug API can now write (backfill).
- **Second boxing schedule source**: boxing-schedule.com probed as parseable
  (`events__single` grid); ESPN (bot challenge) and Sky (404) are not usable.
- **Outage alerts** are built but off until `RESEND_API_KEY` and
  `ALERT_EMAIL` are set on Railway.
- **Boxing URLs keep quote characters from nicknames** (e.g.
  `/boxing-event/isaac-“pitbull”-cruz-…`). Fixing `_to_slug` changes URLs, so
  it needs 301 redirects from the old ones.
