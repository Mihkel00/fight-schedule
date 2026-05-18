/**
 * generate-sitemap.js
 *
 * Run daily via cron or at build time to generate sitemap.xml
 * from your event database.
 *
 * Usage:
 *   node generate-sitemap.js > public/sitemap.xml
 *
 * Requires: SUPABASE_URL and SUPABASE_SERVICE_KEY env vars
 * (or adapt to whatever DB you use).
 */

const SITE = "https://fightschedule.live";

// ── Adapt this to your data source ──────────────────────────────
async function fetchEvents() {
  // Example using Supabase — replace with your actual query
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;

  if (!url || !key) {
    console.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY");
    process.exit(1);
  }

  const res = await fetch(
    `${url}/rest/v1/events?select=slug,sport,updated_at&order=start_date.asc`,
    { headers: { apikey: key, Authorization: `Bearer ${key}` } }
  );
  return res.json();
}

// ── Static pages ────────────────────────────────────────────────
const today = new Date().toISOString().split("T")[0];

const staticPages = [
  { loc: "/",       changefreq: "daily",   priority: "1.0" },
  { loc: "/ufc",    changefreq: "daily",   priority: "0.9" },
  { loc: "/boxing", changefreq: "daily",   priority: "0.9" },
];

function escapeXml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function urlEntry({ loc, lastmod, changefreq, priority }) {
  return `  <url>
    <loc>${escapeXml(SITE + loc)}</loc>
    <lastmod>${lastmod || today}</lastmod>
    <changefreq>${changefreq}</changefreq>
    <priority>${priority}</priority>
  </url>`;
}

async function main() {
  const events = await fetchEvents();

  const eventEntries = events.map((e) => {
    const prefix = e.sport === "boxing" ? "boxing-event" : "ufc-event";
    return urlEntry({
      loc: `/${prefix}/${e.slug}`,
      lastmod: e.updated_at?.split("T")[0] || today,
      changefreq: "weekly",
      priority: "0.8",
    });
  });

  const staticEntries = staticPages.map((p) =>
    urlEntry({ ...p, lastmod: today })
  );

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${staticEntries.join("\n")}

  <!-- Event pages (${eventEntries.length} events) -->
${eventEntries.join("\n")}
</urlset>`;

  console.log(xml);
}

main();
