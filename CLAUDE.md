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
- Test with a copy of live data (`part=cache`, `part=profiles`, …) in a
  scratch `DATA_DIR`; never commit files under `data/`.
- Commits: gate commit/push on tests passing; never chain them past a test
  without `&&`.
