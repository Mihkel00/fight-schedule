# ⚡ QUICK REFERENCE CARD

## 🔍 SEARCH

**How to use:**
- Type in search box → Results filter automatically
- Works on: Fighter names, events, venues
- Combines with sport filters (UFC/Boxing)

**Examples:**
```
"volkanovski"     → Shows Volkanovski fights
"t-mobile arena"  → Shows all T-Mobile Arena fights
"ufc 324"         → Shows UFC 324 fights
```

---

## 🎯 FILTERS

**Sport Filters:**
- All / UFC / Boxing
- Click to activate
- **Persists across refreshes**

**How it works:**
- Saved to browser localStorage
- Reapplies automatically on page load
- Cleared when you click "All"

---

## ⏰ MANUAL TIME OVERRIDES

### Quick Start:
```bash
python set_fight_time.py
```

### Format:
```
Fighter1 vs Fighter2|YYYY-MM-DD|HH:MM
```

### Example:
```
Carlos Canizales vs Thammanoon Niyomtrong|2025-12-04|14:00
```

### Commands:
| Action | Command |
|--------|---------|
| Set times interactively | `python set_fight_time.py` → option 1 |
| Bulk add times | `python set_fight_time.py` → option 2 |
| View current overrides | `python set_fight_time.py` → option 3 |

---

## 📁 FILES

| File | Purpose |
|------|---------|
| `index.html` | Frontend (search + filters) |
| `set_fight_time.py` | CLI tool for setting times |
| `time_overrides.json` | Stores manual times (auto-created) |
| `app.py` | Backend (needs 3 functions added) |

---

## 🔄 COMMON WORKFLOWS

### Fixing a Fight Time:
```bash
1. python set_fight_time.py
2. Select fight number
3. Enter time (HH:MM UK timezone)
4. Refresh app → See updated time
```

### Clearing Cache:
```bash
rm fights_cache.json
python app.py
```

### Testing Search:
```
1. Open app
2. Type "volkanovski" in search
3. Should show only matching fights
```

---

## 🐛 TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| Search doesn't work | Replace `templates/index.html` with new version |
| Filter resets | Check localStorage enabled in browser |
| Time override not showing | `rm fights_cache.json` + restart app |
| Wrong timezone | Tool expects UK time (add/subtract from source) |

---

## ⏰ TIMEZONE CONVERSIONS

| Source | Conversion to UK |
|--------|------------------|
| ET (US East) | Add 5 hours |
| PT (US West) | Add 8 hours |
| JST (Japan) | Subtract 9 hours |
| CET (Europe) | Subtract 1 hour |

**Example:**
```
Source: 10:00 PM ET
UK: 10:00 PM + 5 = 3:00 AM (next day)
Enter: 03:00
```

---

## 📊 FEATURE STATUS

| Feature | Status |
|---------|--------|
| Search | ✅ Complete |
| Filter Persistence | ✅ Complete |
| Time Overrides | ✅ Complete |
| Results Count | ✅ Complete |
| Mobile Responsive | ✅ Complete |

---

## 🎯 WHAT'S NEXT?

**Immediate (MVP1):**
- [ ] Add missing fighter images (use `missing_fighters.py`)
- [ ] Set accurate times for major boxing fights
- [ ] Test on mobile devices

**Soon (MVP2):**
- [ ] Google Analytics integration
- [ ] Calendar export (.ics files)
- [ ] Image hosting on Railway

**Future (MVP3):**
- [ ] Odds integration
- [ ] Streaming links
- [ ] User accounts

---

**Last Updated:** 2025-11-29
**Version:** 1.1 (Search + Overrides)
