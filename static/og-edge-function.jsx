/**
 * Dynamic OG image generation for fight events.
 *
 * Deploy as: api/og/[slug].jsx (Vercel Edge Function)
 *
 * Generates a 1200x630 branded image per event showing:
 * - Fighter names
 * - Event name (e.g. "UFC 315")
 * - Date & venue
 * - Sport type badge
 *
 * Requires: @vercel/og package
 */

import { ImageResponse } from "@vercel/og";

export const config = { runtime: "edge" };

export default async function handler(req) {
  const { searchParams } = new URL(req.url);
  const slug = searchParams.get("slug");

  if (!slug) {
    return new Response("Missing slug", { status: 400 });
  }

  // Fetch event data from your DB — adapt to your setup
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

  let event = null;
  if (supabaseUrl && supabaseKey) {
    const res = await fetch(
      `${supabaseUrl}/rest/v1/events?slug=eq.${slug}&select=name,sport,start_date,venue_name,venue_city,competitors&limit=1`,
      { headers: { apikey: supabaseKey, Authorization: `Bearer ${supabaseKey}` } }
    );
    const rows = await res.json();
    event = rows?.[0];
  }

  // Fallback if no event found
  const title = event?.name || slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const sport = event?.sport || (slug.includes("ufc") ? "UFC" : "Boxing");
  const venue = event ? `${event.venue_name}, ${event.venue_city}` : "";
  const date = event?.start_date
    ? new Date(event.start_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : "";
  const competitors = event?.competitors || [];

  const sportColor = sport === "UFC" || sport === "MMA" ? "#e11d48" : "#2563eb";

  return new ImageResponse(
    (
      <div
        style={{
          width: 1200,
          height: 630,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          background: "linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%)",
          fontFamily: "system-ui, sans-serif",
          color: "#fff",
          padding: 60,
        }}
      >
        {/* Sport badge */}
        <div
          style={{
            display: "flex",
            background: sportColor,
            color: "#fff",
            padding: "6px 20px",
            borderRadius: 20,
            fontSize: 18,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            marginBottom: 24,
          }}
        >
          {sport}
        </div>

        {/* Event title */}
        <div
          style={{
            fontSize: title.length > 40 ? 48 : 64,
            fontWeight: 800,
            textAlign: "center",
            lineHeight: 1.1,
            marginBottom: 20,
            maxWidth: 1000,
          }}
        >
          {title}
        </div>

        {/* Competitors */}
        {competitors.length >= 2 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 24,
              fontSize: 28,
              fontWeight: 500,
              color: "rgba(255,255,255,0.8)",
              marginBottom: 16,
            }}
          >
            <span>{competitors[0].name}</span>
            <span style={{ color: sportColor, fontWeight: 700 }}>VS</span>
            <span>{competitors[1].name}</span>
          </div>
        )}

        {/* Date & Venue */}
        {(date || venue) && (
          <div
            style={{
              fontSize: 20,
              color: "rgba(255,255,255,0.5)",
              textAlign: "center",
            }}
          >
            {[date, venue].filter(Boolean).join(" • ")}
          </div>
        )}

        {/* Branding */}
        <div
          style={{
            position: "absolute",
            bottom: 30,
            right: 40,
            fontSize: 16,
            color: "rgba(255,255,255,0.3)",
            fontWeight: 600,
          }}
        >
          fightschedule.live
        </div>
      </div>
    ),
    { width: 1200, height: 630 }
  );
}
