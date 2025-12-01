# Logging System

Your app now has a **professional logging system** that writes to **both terminal and file**.

## 📍 Log Locations

### Terminal/Console
Real-time logs appear when you run the app:
```bash
python app.py
```

### Log File
All logs are saved to: **`logs/app.log`**
- Auto-creates `logs/` directory if it doesn't exist
- Rotates when file reaches 10MB (keeps 3 backup files)
- Files: `app.log`, `app.log.1`, `app.log.2`, `app.log.3`

## 📊 Log Levels

**What you see in TERMINAL:**
- INFO: Normal operations (page visits, cache operations)
- WARNING: Unusual but not critical (fallback events)
- ERROR: Problems that need attention

**What's saved in FILE:**
- DEBUG: Detailed technical info (slug parsing, event matching)
- INFO: Everything from terminal
- WARNING/ERROR: All problems

## 🔍 Example Log Output

**Terminal (when you start the app):**
```
[2025-12-01 16:30:00] INFO: ======================================================================
[2025-12-01 16:30:00] INFO: FIGHT SCHEDULE APP STARTING
[2025-12-01 16:30:00] INFO: ======================================================================
[2025-12-01 16:30:00] INFO: Starting Flask server on port 5000
[2025-12-01 16:30:00] INFO: Debug mode: False
[2025-12-01 16:30:00] INFO: Cache duration: 6 hours
```

**When someone visits the homepage:**
```
[2025-12-01 16:31:15] INFO: → Home page accessed
[2025-12-01 16:31:15] INFO: ✓ Using cached data from 2025-12-01 16:30:00 (age: 1 minutes)
[2025-12-01 16:31:15] INFO:   Loaded 24 fights from cache
[2025-12-01 16:31:15] INFO:   Rendering 24 fights
```

**When someone clicks on an event:**
```
[2025-12-01 16:32:30] INFO: → Event detail accessed: ufc-323-dvalishvili-vs-yan-2-2025-01-25
[2025-12-01 16:32:30] INFO:   ✓ Matched event: UFC 323: Dvalishvili vs Yan 2 (12 fights)
```

**When cache expires:**
```
[2025-12-01 22:31:00] INFO: ✗ Cache expired (age: 6 hours), fetching new data...
[2025-12-01 22:31:45] INFO: ✓ Cache saved: 28 fights at 2025-12-01 22:31:45
```

## 🛠️ How to Use

### View Live Logs
Just run the app and watch the terminal:
```bash
python app.py
```

### Review Past Logs
Check what happened earlier:
```bash
cat logs/app.log
```

### Search Logs
Find specific events:
```bash
grep "Event detail" logs/app.log
grep "ERROR" logs/app.log
grep "Cache" logs/app.log
```

### Clear Logs
Start fresh:
```bash
rm logs/app.log*
```

## 🎯 What Gets Logged

✅ **App startup** - Port, settings, cache duration
✅ **Cache operations** - Load, save, expiry
✅ **Page visits** - Home, event detail pages
✅ **Event matching** - Which event matched a slug
✅ **Fight counts** - How many fights loaded/rendered
✅ **Errors** - Any problems that occur

## 📝 Log Symbols

- `→` Route accessed
- `✓` Success
- `✗` Failure/expired
- `!` Warning/fallback

## 🚀 On Railway

When deployed, you can:
1. View logs in Railway dashboard
2. Download `logs/app.log` via Railway CLI
3. All logs are timestamped for debugging issues

## 💡 Tips

**Development:**
- Keep terminal open to see real-time activity
- Check log file for detailed debugging info

**Production:**
- Monitor log file for errors
- Log rotation prevents disk space issues
- Timestamps help track down when issues occurred

That's it! Your app now tells you exactly what it's doing. 🎉
