/**
 * SEO utility functions for FightSchedule
 *
 * Follows the same pattern as Tokven's analytics.js —
 * lightweight DOM manipulation, no react-helmet dependency.
 *
 * Usage:
 *   import { setMeta, setCanonical, setJsonLd, setSportsEventSchema } from "./seo-utils";
 */

// ── Generic helpers ──────────────────────────────────────────────

/** Create or update a <meta> tag */
export function setMeta(name, content) {
  const isProperty = name.startsWith("og:") || name.startsWith("twitter:");
  const attr = isProperty ? "property" : "name";
  let el = document.querySelector(`meta[${attr}="${name}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, name);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

/** Create or update <link rel="canonical"> */
export function setCanonical(href) {
  let el = document.querySelector('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", "canonical");
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

/** Create or update a <script type="application/ld+json"> by id */
export function setJsonLd(id, data) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("script");
    el.id = id;
    el.type = "application/ld+json";
    document.head.appendChild(el);
  }
  el.textContent = JSON.stringify(data);
}

/** Remove a JSON-LD block by id (useful on unmount) */
export function removeJsonLd(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

/** Set document.title */
export function setTitle(title) {
  document.title = title;
}

// ── Page-level SEO presets ───────────────────────────────────────

/** Set all meta for the homepage / schedule list */
export function setHomeMeta() {
  const title = "UFC & Boxing Schedule 2026 | Live Fight Calendar & Event Times";
  const desc = "Complete UFC and boxing fight schedule with automatic timezone conversion. Live updates on fight dates, times, venues, and AI-powered previews for all major events.";
  const url = "https://fightschedule.live/";
  const img = "https://fightschedule.live/og-image.png";

  setTitle(title);
  setMeta("description", desc);
  setMeta("og:title", title);
  setMeta("og:description", desc);
  setMeta("og:url", url);
  setMeta("og:image", img);
  setMeta("twitter:title", title);
  setMeta("twitter:description", desc);
  setMeta("twitter:image", img);
  setCanonical(url);
}

/**
 * Set all meta + structured data for a single fight event page.
 *
 * @param {Object} event
 * @param {string} event.name           - e.g. "UFC 315: Jones vs Aspinall"
 * @param {string} event.slug           - e.g. "ufc-315-jones-vs-aspinall-2026-04-18"
 * @param {string} event.description    - Short text about the event
 * @param {string} event.startDate      - ISO 8601 with timezone
 * @param {string} [event.endDate]      - ISO 8601 with timezone
 * @param {string} event.sport          - "Mixed Martial Arts" | "Boxing"
 * @param {string} [event.status]       - "EventScheduled" | "EventPostponed" | "EventCancelled"
 * @param {Object} [event.venue]        - { name, streetAddress, city, region, postalCode, country }
 * @param {Array}  event.competitors    - [{ name: "Jon Jones" }, { name: "Tom Aspinall" }]
 * @param {Object} [event.organizer]    - { name: "UFC", url: "https://ufc.com" }
 * @param {string} [event.image]        - OG image URL
 * @param {string} [event.ticketUrl]    - Where to buy tickets
 */
export function setEventMeta(event) {
  const url = `https://fightschedule.live/${event.sport === "Boxing" ? "boxing-event" : "ufc-event"}/${event.slug}`;
  const title = `${event.name} — Fight Schedule & Card | FightSchedule`;
  const img = event.image || `https://fightschedule.live/og/${event.slug}.png`;

  // Standard meta
  setTitle(title);
  setMeta("description", event.description);
  setMeta("og:title", title);
  setMeta("og:description", event.description);
  setMeta("og:url", url);
  setMeta("og:image", img);
  setMeta("og:type", "website");
  setMeta("twitter:title", title);
  setMeta("twitter:description", event.description);
  setMeta("twitter:image", img);
  setCanonical(url);

  // SportsEvent JSON-LD
  const schema = {
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    name: event.name,
    description: event.description,
    startDate: event.startDate,
    eventStatus: `https://schema.org/${event.status || "EventScheduled"}`,
    eventAttendanceMode: "https://schema.org/MixedEventAttendanceMode",
    sport: event.sport,
    competitor: event.competitors.map((c) => ({
      "@type": "Person",
      name: c.name,
    })),
    image: img,
    url,
  };

  if (event.endDate) schema.endDate = event.endDate;

  if (event.venue) {
    schema.location = {
      "@type": "Place",
      name: event.venue.name,
      address: {
        "@type": "PostalAddress",
        streetAddress: event.venue.streetAddress,
        addressLocality: event.venue.city,
        addressRegion: event.venue.region,
        postalCode: event.venue.postalCode,
        addressCountry: event.venue.country || "US",
      },
    };
  }

  if (event.organizer) {
    schema.organizer = {
      "@type": "Organization",
      name: event.organizer.name,
      url: event.organizer.url,
    };
  }

  if (event.ticketUrl) {
    schema.offers = {
      "@type": "Offer",
      url: event.ticketUrl,
      availability: "https://schema.org/InStock",
    };
  }

  setJsonLd("event-jsonld", schema);
}

/**
 * Set ItemList schema for the schedule listing page.
 * Google can use this for carousel/list rich results.
 *
 * @param {Array} events - Array of { name, slug, sport }
 */
export function setEventListSchema(events) {
  const schema = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    itemListElement: events.map((e, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: e.name,
      url: `https://fightschedule.live/${e.sport === "Boxing" ? "boxing-event" : "ufc-event"}/${e.slug}`,
    })),
  };
  setJsonLd("event-list-jsonld", schema);
}

/**
 * Set BreadcrumbList schema.
 *
 * @param {Array} crumbs - [{ name: "Home", url: "/" }, { name: "UFC Events", url: "/ufc" }, ...]
 */
export function setBreadcrumbs(crumbs) {
  const schema = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: c.name,
      item: c.url.startsWith("http") ? c.url : `https://fightschedule.live${c.url}`,
    })),
  };
  setJsonLd("breadcrumb-jsonld", schema);
}
