# Mistakes log

Read this at the start of every session (CLAUDE.md requires it). Each entry
has a root cause, not just what went wrong. Add an entry whenever the owner
points out a mistake or one is discovered — before fixing it.

---

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
