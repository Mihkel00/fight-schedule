# Mistakes log

Read this at the start of every session (CLAUDE.md requires it). Each entry
has a root cause, not just what went wrong. Add an entry whenever the owner
points out a mistake or one is discovered — before fixing it.

---

## 2026-09-30 — Committed after a test that never ran (exit code hidden by a pipe)

**What happened:** I ran `python smoke.py | tail -3 && git commit …`. The
test crashed on import, but `tail` exited 0, so the commit and push went
ahead. (The change was a Markdown file and the test passes on rerun, but the
gate did not work.)

**Root cause:** The `&&` rule was followed in form only: the command before
`&&` was a pipeline, whose status is the last command's (`tail`), not the
test's.

**Rule:** Never pipe a gating test. Write its output to a file, then gate on
the test's own exit code: `python test.py > out 2>&1 && git commit …`, and
read `out` afterwards.

## 2026-09-30 — Portfolio help was engineering-heavy for a product designer

**What happened:** Asked to help a product designer's case study, I drafted a
stack description, an outage post-mortem and technical trade-offs. The owner:
"most of this is very technical and not much UX in there."

**Root cause:** I wrote from what I know best — the code and incidents I worked
on — instead of from the audience: design hiring managers looking for user
problems, decisions, iterations and outcomes.

**Rule:** Before drafting anything for an audience, name the audience and what
they judge; translate technical work into what the user experiences and why it
was decided, and keep implementation detail to a supporting line at most.

## 2026-09-29 — Event pages and landing day headings show the UTC date next to a local time

**What happened:** A New York visitor sees "Sun, Oct 04 • 8:00 PM" for UFC 332:
the time is converted to local, the date is not, so the day is wrong. The
/ufc and /boxing day headings (my Ring-style redesign) group cards by UTC date
too. The homepage converts both correctly.

**Root cause:** I verified time conversion by checking the time text only, and
never loaded a page in a non-UTC timezone until today. The date sits in a
separate element that the event-page script never touches, and I copied UTC
day-grouping into the landing pages without asking which day a US visitor
would expect.

**Rule:** Anything shown with a time is checked in a real browser in at least
two non-UTC timezones (US and Europe), reading the full visible date + time,
not just the element I changed.

## 2026-09-29 — Read "geo" as geographic when the owner meant GEO (LLM findability)

**What happened:** Asked "What about geo", I wrote a full answer about
per-click country tracking. The owner meant generative engine optimisation —
being found and cited by ChatGPT, Claude, Perplexity and AI search.

**Root cause:** I resolved an ambiguous term from the most recent topic
(country routing in affiliate links) instead of the owner's larger goal
(traffic and SEO), and didn't ask one clarifying question.

**Rule:** When a short question uses a term with more than one plausible
meaning in context (GEO, CTR, CAC...), ask which one, or answer the
likelier one in a sentence and confirm, before writing a long answer.

## 2026-09-29 — UFC section went empty: source failure + missing cache defeated both safety nets

**What happened:** At 22:05 a scrape ran with no previous cache available and
ESPN refusing our server. The per-sport fallback carried forward nothing, the
new results archive seeded from nothing, and /ufc showed no fights at all.
Past results were restored from a copy I had; upcoming UFC could not be.
I had also told the owner the next scrape would be ~03:15 — it ran at 22:05.

**Root cause:** Both safety nets drew their data from the cache file, which
admin "Clear Cache" deletes and which a restart-time scrape overwrites. I
tested "cache deleted" and "source failing" separately, never together, and
the archive only protects *past* fights by design. The scrape-time estimate
was a guess from a timestamp I had not verified.

**Rule:** Test failure *combinations* (source down + state lost), not only
single failures. Each source's last known-good data lives in its own file that
no admin action deletes. Don't give the owner a time or number I haven't
checked; say it's an estimate or check it first.

## 2026-09-29 — Results archive has a first-run gap that "Clear Cache" can fall into

**What happened:** The new results archive is only created on the first
*scrape* after deploy. The last backfill reset the cache's timestamp, so that
scrape is hours away, and pressing admin "Clear Cache" before then would
delete the only copy of past results (UFC 331, Sept boxing cards).

**Root cause:** I tested every scrape path (deleted cache, corrupt cache,
concurrent workers) but did not list every code path that writes or deletes
the cache — the admin Clear Cache route and the backfill endpoint both
bypass the scrape, and the backfill's `save_cache` marks the cache fresh.

**Rule:** When changing how a piece of state is protected, enumerate every
code path that writes or deletes it (grep for the file/function), not just the
main one, and check the state on the first run after deploy.

## 2026-09-29 — Recommended and built image sources without checking the rights to use them

**What happened:** I proposed and built UFC.com and ESPN headshots as image
sources, and pulled Wikimedia photos, without saying that UFC.com/ESPN photos
are copyrighted with no licence for re-use, or that Wikimedia photos require
author/licence attribution (and share-alike for our crops). The site shows none.

**Root cause:** I judged sources only on technical merit (accuracy, stability,
"publicly reachable") and treated reachable as usable. The owner had already
said the goal is to earn from the site, which makes rights matter more, and I
still never asked the question.

**Rule:** Every proposal for a new external source (data, images, text) states
its licence / terms-of-use status and what compliance requires, before it is
built. "Public" is not a licence.

## 2026-09-29 — Built a visual change (initials avatars) the owner did not ask for

**What happened:** Replaced the placeholder silhouette on every card and event
page with coloured initials circles. The owner had not asked for it and did
not want it.

**Root cause:** Scope creep dressed up as a suggestion. In a message about
image *sources*, I appended "one non-source suggestion" and then bundled it
into "want me to go ahead with those three?". A yes to a list is not a
decision about a design change nobody has seen. I treated the enthusiasm of
the moment as approval and skipped showing the result before shipping.

**Rule:** Anything a visitor will *see* differently — layout, colours,
components — is proposed on its own, with a description or mock-up, and built
only after an explicit yes to that item. Never bundle a design change into a
list of infrastructure items. When in doubt, build the thing that was asked
for and mention the idea separately.

## 2026-09-29 — Avatar data URIs contained a raw `#`

**What happened:** Server-rendered SVG avatars showed as broken images.

**Root cause:** I kept `#` in the URL-safe set when percent-encoding the data
URI; browsers read `#` as a fragment separator and drop everything after it.
My test checked the SVG decoded correctly, not that it rendered — the same
class of error as testing the wrong layer.

**Rule:** For anything the browser must parse (URLs, data URIs, HTML
nesting), test the artefact as the browser sees it, not the intermediate.

## 2026-09-29 — Redesigned the wrong cards (homepage carousels instead of Featured)

**What happened:** "Make our landing page main event cards like that" meant the
homepage's Featured This Week cards. I changed the UFC/Boxing carousels and
the search results, which were fine, and had to revert.

**Root cause:** I resolved an ambiguous phrase by picking the interpretation
that let me reuse the most code, instead of asking one clarifying question or
looking at which component is literally labelled "main event".

**Rule:** When a request names a UI element ambiguously, name the concrete
component I intend to change and confirm before touching it.

## 2026-09-29 — Admin page reloaded itself every few seconds and lost scroll position

**What happened:** The Review Images page used a whole-page meta refresh for
job progress and full-page form posts for every action.

**Root cause:** I built the admin page with the cheapest mechanism that
worked in a test client, without thinking about a person using it for twenty
minutes at a time. Progress polling and in-place actions were the obvious
requirement for a review tool with 250 items; I only added them after the
complaint.

**Rule:** Admin tools are used for long sessions. Before shipping one, walk
through the workflow as the person doing it: does anything reload, jump, or
require repeating an action many times?

## 2026-09-29 — Stream link inside a card link broke the card layout

**What happened:** Cards on the homepage and landing pages rendered sideways
and broken after I put a "Watch on" link inside them.

**Root cause:** The card is itself an `<a>`; nesting another `<a>` inside it
is invalid HTML and the browser splits the element apart. My tests checked
that the link text appeared in the HTML, not that the HTML was valid.

**Rule:** No interactive element inside a card that is a link. Validate
nesting when adding anything clickable to an existing component.

## 2026-09-29 — Pushed a commit whose test had just failed

**What happened:** The boxing `rsd-event` parser produced a garbage duplicate
bout; the assertion failed, but the commit and push in the same shell command
ran anyway because they were not chained to the test's exit status.

**Root cause:** Convenience batching of test + commit + push in one command
without `&&` between the test and the commit. The test's failure scrolled
past.

**Rule:** Never put a commit in the same command as a test unless the commit
is gated on the test's exit status. Read test output before pushing.

## 2026-09 — Fights finishing on the day were lost from the results archive

**What happened:** UFC 331 and UFC Vegas 121 disappeared instead of staying
as results; the "UFC results" feature therefore never showed anything.

**Root cause:** Carry-forward kept fights dated strictly *before* today,
assuming sources list a card until the day is over. ESPN drops a card the
moment it ends, often hours before UTC midnight. I verified the code path
locally with a scenario that did not include "dropped on the same day".

**Rule:** When relying on an external source's behaviour (what it lists and
for how long), test the edge at the boundary — the event's own day — not just
before and after.

## 2026-08/09 — Boxing source outage went unnoticed for five weeks

**What happened:** The boxing scraper silently returned zero for weeks; with
all-or-nothing validation the whole site went blank.

**Root cause:** No alerting, silent `return []` on parse failure, and
validation that discarded good data when one source failed. Each was a
reasonable shortcut on its own; together they turned a parser break into a
site outage nobody was told about.

**Rule:** A scraper that finds nothing logs *why*; validation is per source;
and failures that persist page the owner.
