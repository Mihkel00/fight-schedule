# FightSchedule SEO Scaffold

SEO files scaffolded from Tokven's setup, adapted for fightschedule.live.

## Files

| File | Purpose | Where to put it |
|------|---------|-----------------|
| `index.html` | Full meta tags, OG, Twitter Card, JSON-LD, noscript fallback | Replace/merge into your `index.html` |
| `seo-utils.js` | JS utilities for dynamic meta/canonical/JSON-LD per route | `src/utils/seo-utils.js` |
| `robots.txt` | Crawler rules with AI bot allow list | `public/robots.txt` |
| `sitemap.xml` | Static sitemap template | `public/sitemap.xml` |
| `generate-sitemap.js` | Script to generate sitemap from DB | `scripts/generate-sitemap.js` |
| `llms.txt` | AI-friendly site description | `public/llms.txt` |
| `og-edge-function.jsx` | Dynamic OG image per event | `api/og/[slug].jsx` |
| `vercel.json` | Caching + SPA rewrites | Root `vercel.json` |

## Key differences from Tokven

1. **SportsEvent schema** instead of SoftwareApplication — Google supports event rich results
2. **Dynamic sitemap generation** — fight events change frequently, so generate from DB
3. **Higher changefreq** — `daily` for schedule pages since fights update often
4. **Competitor schema** — uses `Person` type for individual fighters (not `SportsTeam`)
5. **BreadcrumbList** support — better for deep pages like `/ufc-event/ufc-315-...`
6. **Event status** — supports `EventScheduled`, `EventPostponed`, `EventCancelled`

## Integration checklist

- [ ] Merge index.html meta tags into your existing index.html
- [ ] Add seo-utils.js to your src/utils/
- [ ] Call `setEventMeta()` on every event page mount
- [ ] Call `setHomeMeta()` on schedule list page mount
- [ ] Call `setEventListSchema()` with visible events on list page
- [ ] Drop robots.txt and llms.txt into public/
- [ ] Set up generate-sitemap.js as a daily cron or build step
- [ ] Deploy og-edge-function.jsx as api/og/[slug].jsx
- [ ] Add vercel.json rewrites for clean URLs
- [ ] Create a 1200x630 og-image.png for the homepage
- [ ] Add Google Search Console verification meta tag
- [ ] Submit sitemap in Google Search Console
