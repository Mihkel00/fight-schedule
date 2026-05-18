#!/bin/bash
# ============================================================================
# FightSchedule - GitHub Projects Kanban Board Setup
# ============================================================================
#
# Creates a GitHub Projects (v2) kanban board from ROADMAP.md items.
#
# Prerequisites:
#   1. gh CLI installed: https://cli.github.com
#   2. Authenticated: gh auth login
#   3. Project scope: gh auth refresh -s project
#
# Usage:
#   chmod +x scripts/setup-kanban.sh
#   ./scripts/setup-kanban.sh
#
# ============================================================================

set -euo pipefail

OWNER="Mihkel00"
REPO="fight-schedule"
PROJECT_TITLE="FightSchedule Roadmap"

echo "=== FightSchedule Kanban Board Setup ==="
echo ""

# --- Check prerequisites ---
if ! command -v gh &> /dev/null; then
  echo "Error: gh CLI not found. Install from https://cli.github.com"
  exit 1
fi

if ! gh auth status &> /dev/null; then
  echo "Error: Not authenticated. Run: gh auth login"
  exit 1
fi

echo "Authenticated as: $(gh api user --jq '.login')"
echo ""

# --- Ensure project scope ---
echo "Ensuring 'project' scope is available..."
gh auth refresh -s project 2>/dev/null || true

# --- Create GitHub Project ---
echo "Creating project: $PROJECT_TITLE ..."
PROJECT_NUMBER=$(gh project create --owner "$OWNER" --title "$PROJECT_TITLE" --format json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('number',''))" 2>/dev/null || echo "")

if [ -z "$PROJECT_NUMBER" ]; then
  echo "Project may already exist. Checking..."
  PROJECT_NUMBER=$(gh project list --owner "$OWNER" --format json | python3 -c "
import sys, json
projects = json.load(sys.stdin).get('projects', [])
for p in projects:
    if p.get('title') == '$PROJECT_TITLE':
        print(p['number'])
        break
" 2>/dev/null || echo "")
fi

if [ -z "$PROJECT_NUMBER" ]; then
  echo "Error: Could not create or find project. You may need to create it manually at:"
  echo "  https://github.com/orgs/$OWNER/projects/new or https://github.com/users/$OWNER/projects/new"
  exit 1
fi

echo "Project #$PROJECT_NUMBER created/found."
echo ""

# --- Create labels ---
echo "Creating labels..."
create_label() {
  local name="$1" color="$2" desc="$3"
  gh label create "$name" --color "$color" --description "$desc" --repo "$OWNER/$REPO" 2>/dev/null || echo "  Label '$name' already exists"
}

create_label "priority: high"   "e11d48" "High priority item"
create_label "priority: medium" "f59e0b" "Medium priority item"
create_label "priority: low"    "6b7280" "Low priority / future item"
create_label "feature"          "0ea5e9" "New feature"
create_label "enhancement"      "a855f7" "Enhancement to existing feature"
create_label "infrastructure"   "64748b" "Infrastructure / tooling"
echo ""

# --- Create issues ---
echo "Creating issues from ROADMAP.md..."

create_issue() {
  local title="$1" body="$2" labels="$3"
  local url
  url=$(gh issue create \
    --repo "$OWNER/$REPO" \
    --title "$title" \
    --body "$body" \
    --label "$labels" \
    2>&1) || { echo "  Failed to create: $title"; return 1; }
  echo "  Created: $title -> $url"
  echo "$url"
}

add_to_project() {
  local issue_url="$1"
  gh project item-add "$PROJECT_NUMBER" --owner "$OWNER" --url "$issue_url" 2>/dev/null || echo "  Failed to add to project: $issue_url"
}

# ---- HIGH PRIORITY ----
echo ""
echo "-- High Priority --"

URL=$(create_issue \
  "ICS Calendar Feed" \
  "Subscribe to a live-updating calendar of all upcoming fights directly in Google Calendar, Apple Calendar, or Outlook.

## Requirements
- Single \`/calendar.ics\` endpoint returning all events in iCalendar format
- Per-sport feeds: \`/calendar/ufc.ics\`, \`/calendar/boxing.ics\`
- Auto-updating as new events are added

## References
- [clarencechaan/ufc-cal](https://github.com/clarencechaan/ufc-cal) - automated UFC calendar feed using GitHub Actions
- [ics-py/ics-py](https://github.com/ics-py/ics-py) - Pythonic iCalendar (RFC 5545) library

## Complexity
Low - data already exists, just needs ICS serialization" \
  "priority: high,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Add to Calendar buttons on event pages" \
  "Per-event buttons on detail pages to add a single fight/event to the user's calendar.

## Requirements
- Google Calendar deep link
- Downloadable \`.ics\` file per event
- Works on both UFC and boxing detail pages

## References
- [add-to-calendar-button](https://github.com/add2cal/add-to-calendar-button) - widely used web component

## Complexity
Low - generates links from existing date/time/venue data" \
  "priority: high,feature")
add_to_project "$URL"

URL=$(create_issue \
  "PWA Support (installable + offline)" \
  "Make the site installable on mobile home screens with offline access to cached fight schedules.

## Requirements
- Web app manifest (\`manifest.json\`)
- Service worker with cache-first strategy for schedule data
- Offline fallback page

## Benefits
- App-like experience on mobile
- Offline schedule access
- Faster repeat loads

## Complexity
Medium - need service worker with proper caching strategy" \
  "priority: high,feature")
add_to_project "$URL"

# ---- MEDIUM PRIORITY ----
echo ""
echo "-- Medium Priority --"

URL=$(create_issue \
  "Push notifications / fight reminders" \
  "Browser push notifications before fights start (e.g. 30 min, 1 hour). Users opt in and select which events to be reminded about.

## Requirements
- Web Push API (no app store needed)
- Notification permission flow
- Server-side push scheduling
- User-selectable reminder times

## References
- [FightAlarm](https://fightalarm.com/) - sends notifications 10 min before selected fights

## Complexity
Medium-High - needs notification permission flow, server-side push, scheduling" \
  "priority: medium,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Fighter favorites (follow fighters)" \
  "Let users \"follow\" fighters and see a personalized feed of their upcoming fights. No account needed - store preferences in localStorage.

## Requirements
- Star/heart toggle on fighter names
- Dedicated \"My Fighters\" filtered view
- localStorage persistence (no account needed)

## Complexity
Medium - client-side filtering + localStorage persistence" \
  "priority: medium,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Filtering and sorting on homepage" \
  "Add filters on the homepage: by sport (UFC/Boxing), weight class, date range, promotion. Currently only search exists.

## Requirements
- Sport filter (UFC / Boxing / All)
- Weight class filter
- Date range filter
- Client-side JS filtering on existing data

## Complexity
Low-Medium - client-side JS filtering on existing data" \
  "priority: medium,enhancement")
add_to_project "$URL"

URL=$(create_issue \
  "Social sharing buttons on event pages" \
  "Share buttons on event detail pages (Twitter/X, Facebook, WhatsApp, copy link). Use existing OG meta tags for rich link previews.

## Requirements
- Twitter/X share intent
- Facebook share
- WhatsApp share
- Copy link to clipboard
- Use existing OG meta tags

## Complexity
Low - share intent URLs + copy-to-clipboard" \
  "priority: medium,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Fight results after events conclude" \
  "After events conclude, show results (winner, method, round). Mark completed events differently from upcoming ones.

## Data sources
- [ESPN MMA API](https://github.com/pseudo-r/Public-ESPN-API) (free, no auth)
- [UFC-DataLab](https://github.com/komaksym/UFC-DataLab) - comprehensive historical dataset

## Requirements
- Post-event scraping/API polling
- Winner, method, round display
- Visual distinction between past and upcoming events

## Complexity
Medium - needs post-event data pipeline + results UI" \
  "priority: medium,feature")
add_to_project "$URL"

# ---- LOW PRIORITY ----
echo ""
echo "-- Low Priority --"

URL=$(create_issue \
  "Public REST API" \
  "Expose fight schedule data as a JSON API for third-party apps, bots, and widgets.

## Endpoints
- \`/api/fights\` - list all upcoming fights
- \`/api/events/<id>\` - single event details
- \`/api/fighters/<name>\` - fighter info

## References
- [ginorey/itstimeAPI](https://github.com/ginorey/itstimeAPI) - open-source UFC API

## Complexity
Medium - needs rate limiting, docs, versioning" \
  "priority: low,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Calendar grid view" \
  "Monthly/weekly calendar grid alongside the current list/card views. Visual overview of fight density across dates.

## Requirements
- Monthly and weekly views
- Responsive layout
- Toggle between list and calendar views

## Complexity
Medium - frontend calendar component + responsive layout" \
  "priority: low,enhancement")
add_to_project "$URL"

URL=$(create_issue \
  "Historical fight data and fighter records" \
  "Display fighter win/loss records, fight history, and stats. Enriches event pages with context.

## Data sources
- [UFC-DataLab](https://github.com/komaksym/UFC-DataLab) - every UFC fight + fighter stats + scorecards
- [scrape_ufc_stats](https://github.com/Greco1899/scrape_ufc_stats) - daily automated stats scraper
- [Sherdog API (unofficial)](https://github.com/valish/sherdog-api) - fighter profile data

## Complexity
High - needs data pipeline, storage, and fighter profile pages" \
  "priority: low,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Betting odds integration" \
  "Show opening/current odds alongside fight cards for additional context.

## Considerations
- Needs reliable odds data source
- Frequent update requirements
- Legal considerations by jurisdiction

## Complexity
High - needs odds data source, frequent updates, legal review" \
  "priority: low,feature")
add_to_project "$URL"

URL=$(create_issue \
  "Multi-language support (i18n)" \
  "Internationalize the site for non-English audiences.

## Requirements
- i18n framework integration
- Translation management
- Language selector in UI
- RTL support consideration

## Complexity
High - needs i18n framework, translation management" \
  "priority: low,feature")
add_to_project "$URL"

echo ""
echo "=== Done! ==="
echo ""
echo "View your kanban board at:"
echo "  https://github.com/users/$OWNER/projects/$PROJECT_NUMBER"
echo ""
echo "To switch to Board (kanban) view:"
echo "  1. Open the project URL above"
echo "  2. Click the view dropdown (top-left, near the project title)"
echo "  3. Select 'Board' layout"
echo "  4. Set 'Column field' to 'Status'"
echo ""
echo "Default status columns: Todo, In Progress, Done"
echo "You can add custom columns like 'Backlog' in the project settings."
