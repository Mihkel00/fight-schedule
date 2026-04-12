# Roadmap

UX improvement ideas for fightschedule.live, prioritized by user impact and implementation effort.

---

## High Priority

### ICS Calendar Feed
Subscribe to a live-updating calendar of all upcoming fights directly in Google Calendar, Apple Calendar, or Outlook. A single `/calendar.ics` endpoint that returns all events in iCalendar format, plus per-sport feeds (`/calendar/ufc.ics`, `/calendar/boxing.ics`).

- **Reference:** [clarencechaan/ufc-cal](https://github.com/clarencechaan/ufc-cal) - automated UFC calendar feed using GitHub Actions
- **Python library:** [ics-py/ics-py](https://github.com/ics-py/ics-py) - Pythonic iCalendar (RFC 5545) library
- **Complexity:** Low - data already exists, just needs ICS serialization

### "Add to Calendar" Buttons
Per-event buttons on detail pages to add a single fight/event to the user's calendar. Google Calendar deep link + downloadable `.ics` file.

- **Reference:** [JS library: add-to-calendar-button](https://github.com/add2cal/add-to-calendar-button) - widely used web component
- **Complexity:** Low - generates links from existing date/time/venue data

### PWA Support
Make the site installable on mobile home screens with offline access to cached fight schedules. Requires a web app manifest and service worker for caching.

- **Benefits:** App-like experience, offline schedule access, faster repeat loads
- **Complexity:** Medium - need service worker with cache-first strategy for schedule data

---

## Medium Priority

### Push Notifications / Fight Reminders
Browser push notifications before fights start (e.g. 30 min, 1 hour). Users opt in and select which events to be reminded about.

- **Reference:** [FightAlarm](https://fightalarm.com/) - sends notifications 10 min before selected fights
- **Approach:** Web Push API (no app store needed), or integrate with service worker from PWA
- **Complexity:** Medium-High - needs notification permission flow, server-side push, scheduling

### Fighter Favorites
Let users "follow" fighters and see a personalized feed of their upcoming fights. No account needed - store preferences in localStorage.

- **UX pattern:** Star/heart toggle on fighter names, dedicated "My Fighters" filtered view
- **Complexity:** Medium - client-side filtering + localStorage persistence

### Filtering & Sorting
Add filters on the homepage: by sport (UFC/Boxing), weight class, date range, promotion. Currently only search exists.

- **Complexity:** Low-Medium - client-side JS filtering on existing data

### Social Sharing
Share buttons on event detail pages (Twitter/X, Facebook, WhatsApp, copy link). Use existing OG meta tags for rich link previews.

- **Complexity:** Low - share intent URLs + copy-to-clipboard

### Fight Results
After events conclude, show results (winner, method, round). Mark completed events differently from upcoming ones.

- **Data sources:**
  - [ESPN MMA API](https://github.com/pseudo-r/Public-ESPN-API) (free, no auth) - `site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard`
  - [UFC-DataLab](https://github.com/komaksym/UFC-DataLab) - comprehensive historical UFC dataset
- **Complexity:** Medium - needs post-event scraping/API polling + UI for results display

---

## Low Priority / Future

### Public REST API
Expose fight schedule data as a JSON API for third-party apps, bots, and widgets.

- **Endpoints:** `/api/fights`, `/api/events/<id>`, `/api/fighters/<name>`
- **Reference:** [ginorey/itstimeAPI](https://github.com/ginorey/itstimeAPI) - open-source UFC API
- **Complexity:** Medium - needs rate limiting, docs, versioning

### Calendar Grid View
Monthly/weekly calendar grid alongside the current list/card views. Visual overview of fight density across dates.

- **Complexity:** Medium - frontend calendar component + responsive layout

### Historical Fight Data & Fighter Records
Display fighter win/loss records, fight history, and stats. Enriches event pages with context.

- **Data sources:**
  - [UFC-DataLab](https://github.com/komaksym/UFC-DataLab) - every UFC fight + fighter stats + scorecards
  - [scrape_ufc_stats](https://github.com/Greco1899/scrape_ufc_stats) - daily automated stats scraper
  - [Sherdog API (unofficial)](https://github.com/valish/sherdog-api) - fighter profile data
- **Complexity:** High - needs data pipeline, storage, and fighter profile pages

### Betting Odds Integration
Show opening/current odds alongside fight cards for additional context.

- **Complexity:** High - needs odds data source, frequent updates, legal considerations

### Multi-Language Support
Internationalize the site for non-English audiences.

- **Complexity:** High - needs i18n framework, translation management

---

## Reference Projects

| Project | Description | Link |
|---------|-------------|------|
| ufc-cal | Automated UFC calendar ICS feed | [GitHub](https://github.com/clarencechaan/ufc-cal) |
| ics-py | Python iCalendar library | [GitHub](https://github.com/ics-py/ics-py) |
| UFC-DataLab | Complete UFC fight/fighter dataset | [GitHub](https://github.com/komaksym/UFC-DataLab) |
| scrape_ufc_stats | Daily automated UFC stats scraper | [GitHub](https://github.com/Greco1899/scrape_ufc_stats) |
| Public-ESPN-API | Free ESPN API documentation | [GitHub](https://github.com/pseudo-r/Public-ESPN-API) |
| itstimeAPI | Open-source UFC API | [GitHub](https://github.com/ginorey/itstimeAPI) |
| BoxRec wrapper | Python BoxRec data access | [GitHub](https://github.com/FlorisHoogenboom/BoxRec) |
| add-to-calendar-button | Calendar button web component | [GitHub](https://github.com/add2cal/add-to-calendar-button) |

## Competitor Reference

- **[Tapology](https://tapology.com/)** - largest MMA database, fighter profiles, Pick 'Em games
- **[Sherdog](https://sherdog.com/)** - MMA news, fighter profiles, fight finder
- **[FightAlarm](https://fightalarm.com/)** - fight notifications app (10 min before start)
- **[Fights.Guide](https://fights.guide/)** - clean editorial combat sports calendar by city/date
