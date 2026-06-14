# An Endangered Globe

An interactive 3D globe in dark mode mapping animal species threatened with extinction. Inspired by [Topi Tjukanov's Notable People](https://tjukanovt.github.io/notable-people), the map displays no city names or political borders — the world's geography is redrawn entirely by the names of animals.

## Concept

Two core mechanics drive the experience:

**Popularity-based prioritization.** The more Wikipedia pageviews an animal has (e.g. Giant Panda, Tiger), the larger its name appears at low zoom. As you zoom in, space opens up and less-known species emerge — a fluid "popcorn" effect identical to the one that made Notable People go viral.

**Neon cloud & filters.** Beneath each name, a small glowing dot pulses in a neon color tied to its IUCN threat level. One click on a filter button isolates a threat category across the entire globe.

---

## Data Architecture

The project combines two data providers accessed through three distinct technical channels in Python:

```
[ IUCN Data ]              [ Wikidata ]              [ Wikipedia API ]
 (.SHP files)            (SPARQL query)             (REST Pageviews)
      │                        │                           │
 1. Geometries &         2. ID → Article          3. Traffic volume
    threat status           title mapping            over 12 months
    (CR, EN, VU)
```

### Channel 1 — IUCN (local Shapefiles)
What we take: geographic boundaries of species habitats and official threat status.
- **CR** — Critically Endangered
- **EN** — Endangered
- **VU** — Vulnerable

### Channel 2 — Wikidata (SPARQL API)
What we take: the translation dictionary. We query Wikidata with an IUCN species ID and get back the exact Wikipedia article title.

### Channel 3 — Wikipedia Pageviews (public REST API)
What we take: the cultural popularity score. Given the article title from step 2, the API returns the total view count over the past 12 months.

---

## Python Pipeline

All heavy processing runs locally and produces a single lightweight GeoJSON file (~2 MB). Nothing heavy is left for the browser.

### Step 1 — IUCN filtering & centroid computation

- Filter the IUCN dataset to keep only the animal kingdom and statuses CR, EN, VU.
- For each species, compute the **centroid** of its habitat polygon using `GeoPandas` / `Shapely` (a single lat/lon point is required to render text on a globe).

### Step 2 — Popularity harvesting

For each valid species:
1. Query Wikidata (SPARQL) to retrieve the Wikipedia article title.
2. Query the Wikimedia Pageviews REST API to get the 12-month view count.
3. Store this count as the species' popularity score.

Be polite to the Wikipedia API: set a proper `User-Agent` header (include your email) and add `time.sleep(0.1)` between requests.

### Step 3 — Clean GeoJSON export

The script produces `animals.geojson`, a list of GeoJSON Point features:

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [longitude, latitude] },
  "properties": {
    "label": "Siberian Tiger",
    "category_iucn": "EN",
    "popularity": 15400
  }
}
```

Expected output: **4,000–8,000 points**, roughly **2 MB**.

---

## Web Interface

### Stack (100% free, open-source, no recurring subscriptions)

| Role | Tool |
|---|---|
| 3D Globe engine | [MapLibre GL JS](https://maplibre.org/) — WebGL, native globe projection |
| Base map | CartoDB Dark Matter — dark, label-free tiles |
| Hosting | GitHub Pages (static, no server needed) |

### Rendering mechanics

**No clustering.** Bubble clustering destroys the intended effect. Instead, use MapLibre's native symbol de-overlap:

```js
'text-allow-overlap': false,
'symbol-sort-key': ['get', 'popularity']
```

The GPU automatically hides less-known species when a more popular one occupies the same geodesic area, producing a smooth fade as you zoom.

**Neon dots.** Below each text label, render a `circle` layer with `'circle-blur': 0.2`. Colors by IUCN category:
- CR → Electric Red (`#FF0040`)
- EN → Neon Orange (`#FF6B00`)
- VU → Fluoro Yellow (`#FFD700`)

At low zoom, the Earth appears covered in a glowing swarm of colored fireflies before individual names become legible.

**Glassmorphism UI.** Filter buttons (All / CR / EN / VU) float over the map with:

```css
background: rgba(0, 0, 0, 0.4);
backdrop-filter: blur(10px);
border: 1px solid rgba(255, 255, 255, 0.1);
```

---

## Known Challenges

**IUCN account creation.** This is the only mandatory account to create. The validation takes 24–48 hours — do it first. You need their API token for automated queries and shapefile downloads.

**Wikipedia API rate limits.** Wikimedia blocks scripts that query too fast without identifying themselves. Always set a proper `User-Agent` string (include your email address) and add a small delay between requests.

**Ocean emptiness.** Terrestrial species will cluster beautifully on biodiversity hotspots (Madagascar, Indonesia, Amazonia) while marine species (whales, sharks) may appear as isolated dots in the middle of oceans. The neon dot layer helps fill these vast blue spaces visually.

---

## Immediate Action Plan

1. **Create your IUCN account** at [iucnredlist.org](https://www.iucnredlist.org/) to get access to species geographic data (allow 24–48h for validation).
2. **Bootstrap the Python pipeline** locally with a small sample: 10 well-known mammals to validate the full flow end-to-end.
3. **Wire up the Wikidata → Pageviews bridge** in Python to confirm you can generate a popularity score for those 10 animals.
4. **Build a test HTML page** with MapLibre + CartoDB and light up your first 10 points on the dark globe.
5. **Scale the pipeline** to the full IUCN animal dataset, export `animals.geojson`, and deploy to GitHub Pages.

---

## Reference

- [Notable People by Topi Tjukanov](https://tjukanovt.github.io/notable-people) — visual and UX inspiration
- [MapLibre GL JS docs](https://maplibre.org/maplibre-gl-js/docs/)
- [IUCN Red List API](https://api.iucnredlist.org/)
- [Wikidata SPARQL endpoint](https://query.wikidata.org/)
- [Wikimedia Pageviews API](https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews)
