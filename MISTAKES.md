# Mistakes log

Read this at the start of every session (CLAUDE.md requires it). Each entry
has a root cause, not just what went wrong. Add an entry whenever the owner
points out a mistake or one is discovered — before fixing it.

---

## 2026-10-06 — The preview check let a wrong number through on day one

**What happened:** The first live grounded previews included "Four-inch reach
advantage at 81 inches versus 73" (it is 8) and "8 title defenses" (our data
says 8 title *wins*). The check passed both.

**Root cause:** I tested the check against the two errors I already knew
about, and whitelisted 0–5 as "probably rounds", so any small number, or one
the model calculated itself, went unchecked. A check written only from known
failures misses the next kind.

**Rule:** Before calling a checker done, read a batch of real outputs
(10 or more) by hand against the data, and add a test case for every
miss. Numbers the model may compute (differences) are recomputed by the
checker, never whitelisted by size.

## 2026-10-06 — Said 14 titles would be cut off; measured, it was 2

**What happened:** Asked whether the new page titles were too long, I said
14 of 48 would be truncated in Google and proposed shortening them. That
came from a "55–60 characters" rule of thumb applied to character counts.
When the owner asked whether I had checked our case, measuring each title's
pixel width at Google's display size (Arial 20px, ~600px) showed 46 of 48 fit.

**Root cause:** I answered with a generic SEO rule and presented it as a
finding about our pages, without measuring what the rule is a proxy for.

**Rule:** Claims about our pages are measured on our pages first. When a
rule of thumb stands in for a real limit (characters for pixels), measure
the real limit, or label the answer as a rule of thumb.

## 2026-10-06 — Deploy failed; I named the wrong cause before reading the log

**What happened:** The Railway deploy for PR #77 failed and the old version
kept running. I told the owner "merge to deploy" without checking the deploy
result. Then, without the build log, I presented the AI preview step in the
start command as the likely cause and opened PR #78 for it. The real log
said `railpack prepare exited with an error`: Railway had switched the
service from Nixpacks to Railpack overnight, and the repo still carried the
legacy `nixpacks.toml`. The preview step was a real but separate risk
(`generate_previews.py && gunicorn` stops the server if the script exits 1).

**Root cause:** I treated "merged" as "deployed", and diagnosed from the
code I knew instead of from the failing system's own output. The build had
not even reached our code.

**Rule:** After a merge, confirm the deploy (GitHub deployment status or a
change visible on the live site) before calling it live. When a deploy
fails, get the build/deploy log first and name the failing stage before
proposing a cause; say "unknown until we see the log" rather than guess.
Optional pre-start steps must never be able to stop the server.

## 2026-10-05 — Tests started failing on their own when the calendar moved on

**What happened:** A page test looked for UFC 332 on the homepage. Once
4 October passed, the event moved to Results and the test failed on unchanged
code. CI would have gone red on the next push for no real reason.

**Root cause:** The tests read the real clock while the fixtures are a frozen
snapshot of 2 October. I wrote assertions about "upcoming" and "past" without
pinning "today", so the suite had a built-in expiry date.

**Rule:** Tests run on the fixtures' own day: the clock is frozen in
`tests/conftest.py` to the date the fixtures were captured. A new fixture set
comes with its own frozen date.

## 2026-10-01 — UFC cards showed the opening bout as the main event

**What happened:** After ESPN came back, UFC 332 appeared everywhere as
"McGee vs Nolan" (the first bout) instead of Silva vs Wang, with the 20:00 UTC
opener as its start time and a fight page dated a day early.

**Root cause:** The code took "first non-prelim bout in the list" as the main
event. That only held because the restored data happened to list the main
event first; ESPN lists bouts earliest first and labels every bout "Main
Card". I relied on list order instead of data that identifies the main event.

**Rule:** Identify the main event from the data itself (the bout named in the
event title, else the latest start), never from list position, and derive
main card vs prelims from start times when the source's labels don't
distinguish them. Re-check live pages after a data source recovers.

## 2026-10-01 — Overstated real watch-link clicks (said ~35–62, it was ~2)

**What happened:** I told the owner about 62 clicks "look like real people"
and used ~35 as the basis for an earnings estimate. The live breakdown showed
61 of those 63 had no referrer, i.e. they never came from a page on the site;
only 2 did.

**Root cause:** I filtered by the signals I had (bot user agent, browser
language) and presented the remainder as people without checking the one
signal a real click from our page always carries: the referring page. I
treated "not caught by my filters" as "real".

**Rule:** Count a click as real only when it carries positive evidence of a
visit (referrer from our own site, plus a normal browser). When a number is
the basis for money advice, state how it was derived and its weakest
assumption.

## 2026-09-30 — Boxing cards shown twice (Whittaker–Wallace, Messaudi–Alhambra)

**What happened:** The live site listed several 3 Oct boxing cards twice, each
claiming "+17 fights". The cache held 19 fights twice over.

**Root cause:** boxingschedule.co started listing that weekend's cards in two
blocks on the same page. The UFC scraper removes duplicate matchups; the boxing
scraper and the merge step never did — the code trusted a source to list each
event once. The earlier cards hid it because nothing grouped them per event.

**Rule:** Every source's output is deduplicated by matchup and date before
use, and the merged list is deduplicated again. Never assume a scraped page
lists each item once.

## 2026-09-30 — Homepage filter left the other sport's cards on screen

**What happened:** Tapping UFC hid the boxing day headings but left 10 boxing
cards visible (Boxing left 4 UFC cards). The cards had the `hidden` attribute,
but `.ev { display: grid }` overrode it.

**Root cause:** My browser test asserted `element.hidden`, the flag I had set
myself, instead of what the visitor sees. A test that reads back its own input
cannot fail.

**Rule:** Interaction tests assert visible state (`offsetParent`,
`getComputedStyle`, a screenshot), never the flag the code just set. Any
element that gets its own `display` must also be covered by
`[hidden] { display: none !important }`.

## 2026-09-30 — Selected header pill turned white-on-white after a tap

**What happened:** After tapping UFC or Boxing, the chosen pill became a white
blob with invisible text.

**Root cause:** The JavaScript swapped colour classes but left the
`hover:text-white` class; on phones hover sticks after a tap. I checked that the
filter ran, and took screenshots only *before* clicking, so I never saw the
control after the interaction.

**Rule:** Style interactive state from the element's state (`aria-pressed`,
`aria-current`) in CSS, not by toggling colour classes. Screenshot every
control *after* interacting with it, in a touch emulation as well as desktop.

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
