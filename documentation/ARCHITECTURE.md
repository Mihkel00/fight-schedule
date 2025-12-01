# 🏗️ SYSTEM ARCHITECTURE

## 📊 HOW IT ALL WORKS TOGETHER

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER'S BROWSER                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                      index.html                           │ │
│  │                                                           │ │
│  │  [Search Box] ──┐                                        │ │
│  │                 │                                        │ │
│  │  [All][UFC][Boxing] ── localStorage (Filter State)      │ │
│  │                 │                                        │ │
│  │                 ▼                                        │ │
│  │         JavaScript filters                              │ │
│  │         allFights array                                 │ │
│  │                 │                                        │ │
│  │                 ▼                                        │ │
│  │    [8 Fight Cards] + [List of Rest]                     │ │
│  └───────────────────────────────────────────────────────────┘ │
│                         │                                       │
│                         │ HTTP Request                          │
│                         ▼                                       │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │
┌─────────────────────────────────────────────────────────────────┐
│                      FLASK SERVER (app.py)                      │
│                                                                 │
│  @app.route('/')                                               │
│      │                                                         │
│      ▼                                                         │
│  fetch_fights()                                               │
│      │                                                         │
│      ├─→ Check cache (load_cache) ──┐                        │
│      │   - Is cache fresh (<6hrs)?  │                        │
│      │                               │                        │
│      │   YES ─→ apply_time_overrides()                       │
│      │          │                                             │
│      │          ▼                                             │
│      │   Return cached fights                                │
│      │                                                        │
│      │   NO ─→ Scrape fresh data                            │
│      │         │                                             │
│      ▼         ▼                                             │
│   Scraping Pipeline:                                         │
│      │                                                        │
│      ├─→ scrape_mma_fighting() ─→ UFC fights                │
│      │   (mmafighting.com)                                   │
│      │                                                        │
│      ├─→ scrape_bbc_boxing() ─→ Boxing fights               │
│      │   (bbc.com/sport/boxing)                              │
│      │                                                        │
│      ├─→ fetch_boxing_events() ─→ Boxing images             │
│      │   (TheSportsDB API)                                   │
│      │                                                        │
│      ▼                                                        │
│   Merge + Process:                                           │
│      │                                                        │
│      ├─→ Load fighter images                                │
│      │   (fighters.json, fighters_ufc.json)                 │
│      │                                                        │
│      ├─→ Filter past fights                                 │
│      │                                                        │
│      ├─→ apply_time_overrides() ◄──┐                        │
│      │   - Load time_overrides.json │                        │
│      │   - Match by fight key       │                        │
│      │   - Override times           │                        │
│      │                               │                        │
│      ├─→ save_cache()               │                        │
│      │   (fights_cache.json)         │                        │
│      │                               │                        │
│      ▼                               │                        │
│   Return JSON to template            │                        │
└──────────────────────────────────────┼────────────────────────┘
                                       │
                                       │
┌──────────────────────────────────────┼────────────────────────┐
│              CLI TOOL (set_fight_time.py)                     │
│                                      │                        │
│  Interactive Mode:                   │                        │
│   1. Load fights_cache.json          │                        │
│   2. Show fights needing times       │                        │
│   3. User selects fight              │                        │
│   4. User enters time (HH:MM)        │                        │
│   5. Save to time_overrides.json ────┘                        │
│                                                                │
│  time_overrides.json format:                                  │
│  {                                                             │
│    "Fighter1 vs Fighter2|YYYY-MM-DD": "HH:MM"                 │
│  }                                                             │
└────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────┐
│                        DATA FILES                               │
│                                                                 │
│  fights_cache.json ◄───────┐                                   │
│  ├─ timestamp              │ Refreshed every 6 hours           │
│  └─ fights array           │                                   │
│                            │                                   │
│  time_overrides.json ◄─────┼─ Manual times (persistent)       │
│  ├─ "Fight1|Date": "Time"  │                                   │
│  └─ "Fight2|Date": "Time"  │                                   │
│                            │                                   │
│  fighters_ufc.json ◄───────┼─ UFC fighter images (886)        │
│                            │                                   │
│  fighters.json ◄───────────┘  Boxing fighter images (manual)  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔄 DATA FLOW

### 1. Initial Page Load
```
User → Browser → GET / → Flask app.py
                          ↓
                    fetch_fights()
                          ↓
                    Check cache
                          ↓
                    Apply overrides
                          ↓
                    JSON to template
                          ↓
                    Render index.html
                          ↓
                    JavaScript loads
                          ↓
                    Render 8 cards + list
```

### 2. User Searches "volkanovski"
```
User types → JavaScript debounce (300ms)
                      ↓
                Filter allFights array
                      ↓
                Keep only matching
                      ↓
                Re-render cards/list
```

### 3. User Clicks "UFC" Filter
```
User clicks → Update button styles
                      ↓
                Set currentFilter = "UFC"
                      ↓
                localStorage.setItem()
                      ↓
                Filter allFights
                      ↓
                Re-render cards/list
```

### 4. Setting Manual Time
```
User → python set_fight_time.py
              ↓
        Load fights_cache.json
              ↓
        Show fights list
              ↓
        User selects fight
              ↓
        User enters time
              ↓
        Save to time_overrides.json
              ↓
        Next app load → time appears!
```

---

## 🗂️ FILE RELATIONSHIPS

```
project/
│
├── app.py ◄────────────────┐
│   │                       │ Imports data from
│   ├─ Loads: fighters_ufc.json
│   ├─ Loads: fighters.json
│   ├─ Loads: fights_cache.json
│   ├─ Loads: time_overrides.json
│   └─ Saves: fights_cache.json
│
├── templates/
│   └── index.html
│       └─ Receives: fights JSON from app.py
│
├── set_fight_time.py
│   ├─ Loads: fights_cache.json
│   └─ Saves: time_overrides.json
│
├── fighters_ufc.json ◄── Generated by scrape_ufc_fighters.py
├── fighters.json ◄──────── Updated by add_fighter_image.py
├── fights_cache.json ◄──── Auto-generated, 6hr refresh
└── time_overrides.json ◄─ Created by set_fight_time.py
```

---

## ⚙️ FEATURE INTERACTIONS

### Search + Filter
```
User types "volkanovski" + clicks "UFC"
        ↓
JavaScript combines both filters:
        ↓
allFights
  .filter(sport === "UFC")      // Filter first
  .filter(name includes "volk")  // Then search
        ↓
Render filtered results
```

### Time Overrides + Cache
```
Cache loads → fights have "TBA" times
        ↓
apply_time_overrides() runs
        ↓
Checks time_overrides.json
        ↓
Matches by "Fighter1 vs Fighter2|Date"
        ↓
Replaces "TBA" with manual time
        ↓
Returns updated fights to user
```

### Filter Persistence
```
User clicks "Boxing" → currentFilter = "BOXING"
        ↓
localStorage.setItem('fightScheduleFilter', 'BOXING')
        ↓
User refreshes page
        ↓
restoreSavedFilter() runs on load
        ↓
Reads localStorage.getItem('fightScheduleFilter')
        ↓
Returns "BOXING" → applies filter automatically
```

---

## 🔧 KEY FUNCTIONS

### Frontend (index.html)
```javascript
getFilteredFights()      // Combines search + sport filter
applyFiltersAndRender()  // Main render orchestrator
renderCard(fight)        // Creates card HTML
renderListItem(fight)    // Creates list HTML
restoreSavedFilter()     // Loads from localStorage
```

### Backend (app.py)
```python
fetch_fights()           // Main orchestrator
scrape_mma_fighting()    // UFC scraper
scrape_bbc_boxing()      // Boxing scraper
load_cache()             // Load + apply overrides
save_cache()             // Save to JSON
apply_time_overrides()   // Override fight times
get_fight_key()          // Generate unique key
```

### CLI Tool (set_fight_time.py)
```python
interactive_mode()       // User selects fights
bulk_add_mode()          // Paste multiple times
view_overrides()         // See current overrides
validate_time()          // Check HH:MM format
```

---

## 🎯 CACHE STRATEGY

```
┌─────────────────────────────────────────┐
│         Cache Lifecycle                 │
│                                         │
│  Page load                              │
│     ↓                                   │
│  Check cache age                        │
│     ↓                                   │
│  < 6 hours?                             │
│     ├─ YES → Use cache + apply overrides│
│     └─ NO  → Scrape fresh data          │
│                 ↓                       │
│           Apply overrides               │
│                 ↓                       │
│           Save new cache                │
│                                         │
│  Manual clear: rm fights_cache.json     │
└─────────────────────────────────────────┘
```

---

## 🔐 OVERRIDE PRIORITY

```
Time Sources (highest to lowest priority):

1. time_overrides.json  ◄── Manual (highest priority)
        ↓ (if not found)
2. Scraped time        ◄── MMA Fighting / BBC Sport
        ↓ (if not found)
3. "TBA"               ◄── No time available
```

---

## 📊 PERFORMANCE

```
Feature          | Response Time | Notes
─────────────────┼───────────────┼──────────────────────
Search debounce  | 300ms         | Prevents lag
Filter click     | ~10ms         | Instant
Cache load       | ~50ms         | Very fast
Fresh scrape     | 5-10 sec      | Multiple sites
Time override    | ~5ms          | JSON lookup
localStorage     | ~1ms          | Browser native
```

---

## 🎨 UI STATE MANAGEMENT

```
State Variables:
├── allFights          (loaded once from server)
├── currentFilter      (ALL | UFC | BOXING)
├── currentSearchTerm  (user input)
└── localStorage       (persistent filter)

State Flow:
User action → Update state → Re-render UI
```

---

This architecture ensures:
- ✅ Fast user experience (client-side filtering)
- ✅ Accurate data (time overrides)
- ✅ Persistent preferences (localStorage)
- ✅ Efficient caching (6hr refresh)
- ✅ Easy maintenance (clear separation)

---

**Last Updated:** November 29, 2025
