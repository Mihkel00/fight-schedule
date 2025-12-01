# ✅ DEPLOYMENT CHECKLIST

## Pre-Deployment (Local Testing)

### Step 1: Update Files
- [ ] Backup current `templates/index.html`
  ```bash
  cp templates/index.html templates/index.html.backup
  ```

- [ ] Replace `templates/index.html` with new version
  ```bash
  cp /path/to/new/index.html templates/index.html
  ```

- [ ] Copy `set_fight_time.py` to project root
  ```bash
  cp /path/to/set_fight_time.py .
  ```

### Step 2: Update app.py

- [ ] Add `load_time_overrides()` function (after line ~605)
- [ ] Add `get_fight_key()` function 
- [ ] Add `apply_time_overrides()` function
- [ ] Update `load_cache()` to apply overrides
- [ ] Update `fetch_fights()` to apply overrides before saving

### Step 3: Test Locally

- [ ] Clear cache: `rm fights_cache.json`
- [ ] Start app: `python app.py`
- [ ] Open browser: `http://localhost:5000`

**Test Search:**
- [ ] Type "volkanovski" → Should filter to Volkanovski fights
- [ ] Type "t-mobile" → Should show T-Mobile Arena fights
- [ ] Clear search → Should show all fights

**Test Filters:**
- [ ] Click "UFC" → Should show only UFC
- [ ] Click "Boxing" → Should show only Boxing
- [ ] Click "All" → Should show everything
- [ ] Refresh page → Filter should stay active

**Test Time Overrides:**
- [ ] Run: `python set_fight_time.py`
- [ ] Select option 1 (Interactive mode)
- [ ] Pick a fight
- [ ] Enter time (e.g., "21:00")
- [ ] Check `time_overrides.json` was created
- [ ] Restart app
- [ ] Verify time shows in UI

---

## Deployment to Railway

### Step 1: Commit Changes
- [ ] `git status` (verify changes)
- [ ] `git add templates/index.html`
- [ ] `git add set_fight_time.py`
- [ ] `git add app.py`
- [ ] `git commit -m "Add search, filter persistence, and time overrides"`

### Step 2: Push to GitHub
- [ ] `git push origin main`
- [ ] Verify push succeeded

### Step 3: Railway Auto-Deploy
- [ ] Check Railway dashboard
- [ ] Wait for build to complete (~2-3 min)
- [ ] Check deployment logs for errors

### Step 4: Test on Production
- [ ] Visit: `fight-schedule-production.up.railway.app`

**Test Search:**
- [ ] Search works on live site
- [ ] Debouncing works (no lag)

**Test Filters:**
- [ ] Filter persistence works
- [ ] Refresh maintains filter

**Test Time Overrides:**
- [ ] Times show correctly
- [ ] Overrides persist

---

## Post-Deployment

### Immediate Tasks
- [ ] Clear Railway cache if needed:
  ```
  # Via Railway CLI or dashboard
  rm fights_cache.json
  ```

- [ ] Set accurate times for 2-3 major upcoming fights:
  ```bash
  python set_fight_time.py
  # Add UFC 323, UFC 324, major boxing matches
  ```

- [ ] Add missing fighter images (top 10 priority):
  ```bash
  python missing_fighters.py
  # Review report
  # Add images for most frequent fighters
  ```

### Within 24 Hours
- [ ] Test on mobile devices
- [ ] Test on different browsers (Chrome, Firefox, Safari)
- [ ] Monitor Railway logs for errors
- [ ] Check Sentry/error tracking (if enabled)

### Within 1 Week
- [ ] Add 5-10 more missing fighter images
- [ ] Set accurate times for all major fights this month
- [ ] Consider enabling Google Analytics
- [ ] Review user feedback (if any)

---

## Rollback Plan (If Something Breaks)

### Quick Rollback
- [ ] `git revert HEAD`
- [ ] `git push origin main`
- [ ] Railway auto-deploys previous version

### Manual Rollback
- [ ] Restore backup: `cp templates/index.html.backup templates/index.html`
- [ ] Remove time override code from app.py
- [ ] Commit and push

---

## Success Criteria

App is successfully deployed when:
- [x] Search filters fighters in real-time
- [x] Filter choice persists across refreshes
- [x] Manual time overrides appear in UI
- [x] No console errors
- [x] Mobile responsive
- [x] Page loads in <2 seconds

---

## Monitoring

### Daily (First Week)
- [ ] Check Railway logs for errors
- [ ] Verify cache refresh working (every 6 hours)
- [ ] Test search on live site

### Weekly (Ongoing)
- [ ] Update fight times as needed
- [ ] Add new fighter images
- [ ] Clear old fights from cache

---

## Notes

**Common Issues:**

| Issue | Fix |
|-------|-----|
| Search not working | Verify index.html updated |
| Filter resets | Check localStorage enabled |
| Times not showing | Clear Railway cache |
| Images missing | Run `python missing_fighters.py` |

**Support Resources:**
- INTEGRATION_GUIDE.md - Full setup instructions
- QUICK_REFERENCE.md - Feature usage
- DELIVERY_SUMMARY.md - What was built

---

## Sign-Off

Deployment completed by: _______________

Date: _______________

All features tested: ☐ Yes  ☐ No

Issues found: _______________________________________________

---

**Version:** 1.1 (Search + Overrides)
**Last Updated:** 2025-11-29
