# 🚀 NEW FEATURES IMPLEMENTATION GUIDE

## ✅ FEATURES ADDED

1. **Real-time Search** - Search fighters, events, venues as you type
2. **Filter Persistence** - Remembers your last filter (All/UFC/Boxing)
3. **Manual Time Overrides** - Fix inaccurate boxing times manually

---

## 📋 INSTALLATION STEPS

### 1. Replace index.html

Replace your current `/templates/index.html` with the new version:

```bash
# Backup your current file
cp templates/index.html templates/index.html.backup

# Copy the new file
cp index.html templates/index.html
```

**What's new in index.html:**
- ✅ Search input with 300ms debounce (real-time search)
- ✅ Filter persistence using localStorage
- ✅ Results count display
- ✅ Combined search + filter logic
- ✅ Cleaner UI with better mobile responsiveness

---

### 2. Update app.py with Time Overrides

Add these functions to your `app.py`:

**Step 1:** Add the helper functions after your existing cache functions:

```python
def load_time_overrides():
    """Load manual time overrides from time_overrides.json"""
    try:
        with open('time_overrides.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Error loading time overrides: {e}")
        return {}

def get_fight_key(fight):
    """Generate unique key for a fight (used for time overrides)"""
    return f"{fight['fighter1']} vs {fight['fighter2']}|{fight['date']}"

def apply_time_overrides(fights):
    """Apply manual time overrides to fights"""
    overrides = load_time_overrides()
    
    if not overrides:
        return fights
    
    applied_count = 0
    for fight in fights:
        fight_key = get_fight_key(fight)
        if fight_key in overrides:
            old_time = fight.get('time', 'TBA')
            fight['time'] = overrides[fight_key]
            print(f"Time override applied: {fight['fighter1']} vs {fight['fighter2']}: {old_time} → {fight['time']}")
            applied_count += 1
    
    if applied_count > 0:
        print(f"\n✓ Applied {applied_count} manual time override(s)\n")
    
    return fights
```

**Step 2:** Update your `load_cache()` function:

Find this section in your current `load_cache()`:
```python
if datetime.now() - cache_time < CACHE_DURATION:
    print(f"Using cached data from {cache_time}")
    return cache_data['fights']  # OLD LINE
```

Replace with:
```python
if datetime.now() - cache_time < CACHE_DURATION:
    print(f"Using cached data from {cache_time}")
    
    # Apply time overrides to cached data
    fights = cache_data['fights']
    fights = apply_time_overrides(fights)
    
    return fights
```

**Step 3:** Update your `fetch_fights()` function:

Find the end of `fetch_fights()` (right before `return fights`), and add:

```python
    # Apply manual time overrides
    fights = apply_time_overrides(fights)
    
    # Save to cache
    if fights:
        save_cache(fights)
    
    return fights
```

---

### 3. Add the Time Override Tool

Copy `set_fight_time.py` to your project root:

```bash
cp set_fight_time.py /path/to/your/project/
```

---

## 🎯 HOW TO USE

### Real-time Search

1. Type in the search box
2. Results filter automatically after 300ms
3. Search works on:
   - Fighter names
   - Event names
   - Venues

**Example:**
```
Search: "canizales" → Shows only Carlos Canizales fights
Search: "t-mobile" → Shows all fights at T-Mobile Arena
```

---

### Filter Persistence

1. Click "UFC" or "Boxing" filter
2. Refresh page → Filter stays active
3. Works across browser sessions

**How it works:**
- Uses `localStorage` to remember filter
- Reapplies on page load
- Clears if you select "All"

---

### Manual Time Overrides

**Interactive Mode (Recommended):**

```bash
python set_fight_time.py
```

Follow the prompts:
1. See list of fights needing times
2. Select fight number
3. Enter correct time in HH:MM format (UK timezone)
4. Time saves to `time_overrides.json`
5. Run app → See updated time

**Example Session:**
```
Found 12 fights needing accurate times:

1. Carlos Canizales vs Thammanoon Niyomtrong
   Date: 2025-12-04
   Venue: Nong Nooch Tropical Garden, Pattaya, Thailand
   Current time: TBA

Select fight number (or 'q' to quit): 1
Enter correct time (HH:MM format, UK timezone): 14:00

✓ Time saved: Carlos Canizales vs Thammanoon Niyomtrong → 14:00 UK
```

**Bulk Add Mode:**

For adding many times at once:

```bash
python set_fight_time.py
# Select option 2

# Then paste lines in this format:
Carlos Canizales vs Thammanoon Niyomtrong|2025-12-04|14:00
Naoya Inoue vs David Picasso|2025-12-27|13:00
```

**View Current Overrides:**

```bash
python set_fight_time.py
# Select option 3
```

---

## 📁 NEW FILES CREATED

1. `index.html` (updated) - Frontend with search + persistence
2. `set_fight_time.py` - Time override CLI tool
3. `time_overrides.json` - Stores manual times (auto-created)

---

## 🔄 WORKFLOW

### Daily Use:

1. **Check schedule:** Visit your app
2. **Search fighter:** Type name in search box
3. **Filter sport:** Click UFC or Boxing (persists)
4. **Times wrong?** Run `python set_fight_time.py`

### When Adding Times:

1. Find accurate time from Box.Live, Tapology, or official sources
2. Run `set_fight_time.py`
3. Select fight → Enter time
4. Refresh app → See updated time
5. Time persists across cache refreshes

---

## 🐛 TROUBLESHOOTING

### Search Not Working

**Symptom:** Typing in search box does nothing

**Fix:** Make sure you replaced `index.html` in `/templates/` folder

**Test:**
```html
<!-- Open index.html and search for this line: -->
<input id="search-input" type="text"
```
If you don't see `id="search-input"`, you haven't updated the file.

---

### Filter Not Persisting

**Symptom:** Filter resets to "All" on page refresh

**Fix:** Check browser localStorage is enabled

**Test in browser console:**
```javascript
localStorage.setItem('test', 'works')
localStorage.getItem('test') // Should return 'works'
```

---

### Time Overrides Not Applying

**Symptom:** Set time but still shows TBA

**Fix:** Check these things:

1. **Does `time_overrides.json` exist?**
   ```bash
   cat time_overrides.json
   ```

2. **Is fight key correct?**
   ```bash
   # Should look like:
   # "Carlos Canizales vs Thammanoon Niyomtrong|2025-12-04": "14:00"
   ```

3. **Did you update app.py?**
   Search for `apply_time_overrides` in app.py
   ```bash
   grep "apply_time_overrides" app.py
   ```
   Should show 3-4 matches

4. **Clear cache and restart:**
   ```bash
   rm fights_cache.json
   python app.py
   ```

---

## 📊 TESTING CHECKLIST

After installation, test each feature:

- [ ] Search works (type fighter name)
- [ ] Search + filter works together
- [ ] Filter persists after refresh
- [ ] Can add manual time
- [ ] Manual time appears in app
- [ ] Results count shows correctly
- [ ] Mobile responsive (test on phone)

---

## 🎨 UI CHANGES

### Before:
- Search box existed but did nothing
- Filter reset on every page load
- No results count

### After:
- Real-time search with 300ms debounce
- Filter remembered via localStorage
- Results count shows filtered total
- Search + filter work together seamlessly

---

## 💡 PRO TIPS

### Finding Accurate Fight Times:

1. **Box.Live** - Most accurate for boxing
   - Visit individual fight pages
   - Look for "Estimated Ringwalk" time
   - Convert to UK timezone

2. **Tapology** - Good for UFC times
   - Usually shows local venue time
   - Convert to UK

3. **Official Sources**
   - UFC.com for UFC events
   - Promoter websites (Top Rank, Matchroom, etc.)

### Time Zones:

- Tool expects **UK time** (GMT/BST)
- If source shows PT (Pacific): Add 8 hours
- If source shows ET (Eastern): Add 5 hours
- If source shows JST (Japan): Subtract 9 hours

**Example:**
```
Box.Live shows: 10:00 PM ET (US East Coast)
UK time: 10:00 PM + 5 hours = 3:00 AM next day
Enter: 03:00
```

---

## 🚀 NEXT STEPS

After installing these features, you can focus on:

1. **Google Analytics** - Track which fights users search for
2. **Calendar Export** - .ics file for Google Calendar
3. **Image Hosting** - Download images to Railway (stop hotlinking)
4. **Production Hardening** - Error monitoring, health checks

---

## 📝 SUMMARY

**What You Got:**
- ✅ Real-time fighter search (300ms debounce)
- ✅ Persistent filters using localStorage
- ✅ Manual time override system
- ✅ Interactive CLI tool for setting times
- ✅ Bulk time import mode
- ✅ Better UX with results count

**Effort Required:**
- Replace 1 file (index.html)
- Update 2 functions in app.py
- Add 3 new functions to app.py
- Copy 1 new script (set_fight_time.py)

**Total Time:** 15-20 minutes

---

**Questions? Issues?**
Open the files and read the inline comments - everything is documented!

