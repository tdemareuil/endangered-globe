# An Endangered Globe

An interactive 3D globe in dark mode mapping animal species threatened with extinction. Inspired by [Topi Tjukanov's Notable People](https://tjukanovt.github.io/notable-people), the map displays no city names or political borders — the world's geography is redrawn entirely by the names of animals.

## Concept

Two core mechanics drive the experience:

**Popularity-based prioritization.** The more Wikipedia pageviews an animal has (e.g. Giant Panda, Tiger), the larger its name appears at low zoom. As you zoom in, space opens up and less-known species emerge — a fluid "popcorn" effect identical to the one that made Notable People go viral.

**Neon cloud & filters.** Beneath each name, a small glowing dot pulses in a neon color tied to its IUCN threat level. One click on a filter button isolates a threat category across the entire globe.

---

## IUCN Categories Included

| Code | Category | Dot color |
|------|----------|-----------|
| EW | Extinct in the Wild | Violet `#CC77FF` |
| CR | Critically Endangered | Dark crimson `#8F102A` |
| EN | Endangered | Red `#E32636` |
| VU | Vulnerable | Neon orange `#FF944D` |
| NT | Near Threatened (incl. Conservation Dependent) | Fluoro yellow `#FFE64D` |

---

## Data Architecture

The project combines IUCN, Wikidata, and Wikimedia data through four technical channels in Python:

```
[ IUCN API v4 ]        [ IUCN Spatial Data ]       [ Wikidata ]        [ Wikipedia API ]
(REST assessments)          (.SHP files)          (SPARQL query)       (REST Pageviews)
       │                         │                      │                    │
 1. Species IDs,          2. Habitat geometry     3. ID → Article     4. Traffic volume
    threat status,           → label points          title mapping       over 12 months
    taxonomy
```

### Channel 1 — IUCN Red List API
What we take: latest global assessments, taxonomic class, species IDs, scientific names, common names, official threat status, population trend, number of mature individuals when available, estimated area of occupancy, estimated extent of occurrence, assessment date/year, citation URL, and whether IUCN has range/point spatial data for the assessment.

The notebook uses the currently recommended and documented API v4 flow: query minimal assessments by taxonomy, then fetch full assessment data only for the candidate assessments. Sample mode uses the same path but only fetches 20 mammals; full mode keeps the complete configured animal scope.

The API fetch is rank-aware but not rank-exclusive: it keeps the IUCN taxon rank in `taxon_rank`. When fetched infrarank rows exist for a parent species, the notebook removes the parent species and displays the infrarank rows instead. When a species mentions infrarank children but those children are not present in the fetched assessments, the species is kept and the notebook logs that case.

Default displayed animal groups:
- Mammals
- Birds
- Other (Reptiles, Amphibians)

Underlying IUCN classes queried:
- `Mammalia`
- `Aves`
- `Reptilia`
- `Amphibia`

The pipeline keeps the original class in `taxon_class` and derives the UI-facing `taxon_group` through `TAXON_GROUP_MAP`, so the display grouping can be changed later without re-querying or losing taxonomic granularity.

Excluded by default: fish, plants, fungi, corals, molluscs, most other invertebrates, and insects. Fish are temporarily excluded because the IUCN spatial source splits them across many shapefiles and subcategories that need a separate pass. Insects are not included in final mode by default because the API can filter `Insecta`, but not "large insects" specifically, so it would add a lot of low-signal API calls.

Included Red List categories:
- **EW** — Extinct in the Wild (surviving only in captivity or cultivation)
- **CR** — Critically Endangered
- **EN** — Endangered
- **VU** — Vulnerable
- **NT** — Near Threatened (includes Conservation Dependent / CD)

### Channel 2 — IUCN Spatial Data
What we take: geographic boundaries and source spatial geometries for species habitats. The API assessment detail tells us whether range polygons or points exist; the actual geometries are read from local IUCN shapefiles.

Local spatial downloads live in `data/shapefiles/` and are ignored by git. The mammal download is split into `MAMMALS_PART1.shp` and `MAMMALS_PART2.shp`; these are two chunks of the same polygon dataset and should be concatenated. Match spatial records to API rows with `id_no == taxonid`. Do not match on `assessment_id`.

The notebook launches `scripts/clean_spatial_data.py` after the IUCN API fetch. It writes the current target taxa to `data/processed/iucn_target_taxa.csv`, filters the heavy source files once, and outputs `data/processed/iucn_spatial_clean.geojson`. `data/processed/` is also ignored by git.

Official IUCN AOO/EOO fields are kept as raw assessment attributes: `estimated_area_of_occupancy` and `estimated_extent_of_occurrence`. Polygon-derived areas are exported separately as `computed_range_area_km2` and `computed_range_component_area_km2`; these are range geometry measurements, not substitutes for IUCN AOO.

Before centroid placement, `presence` is used as a strong priority per taxon, not as a hard filter. The representative geometry is chosen from the best available presence bucket: Extant, then Probably Extant, then Possibly Extant, then Possibly Extinct, then Presence Uncertain, then Extinct. This keeps useful historical range information for EW species when no current wild range is available.

`origin` is ignored: native, reintroduced, introduced, vagrant, origin uncertain, and assisted-colonisation records are not filtered differently.

`seasonal` is used as a secondary soft priority per taxon. After the best presence bucket is selected, the representative geometry is chosen from the best available seasonal bucket: Resident, then Breeding, then Non-breeding, then Passage, then Seasonality Uncertain.

Credit requirement: IUCN spatial data must be credited in any derived product. The notebook keeps species-level spatial citation fields when present and exports both `spatial_credit` and `iucn_dataset_citation`.

### Channel 3 — Wikidata (SPARQL API)
What we take: the translation dictionary and primary image. We query Wikidata with an IUCN species ID and get back the best available Wikipedia sitelink plus the `P18` image when available.

Wikipedia language priority is: English, German, French, Japanese, Russian, Spanish, Italian, Chinese, Polish, Portuguese, then the first remaining Wikipedia sitelink returned by Wikidata.

### Channel 4 — Wikipedia Pageviews (public REST API)
What we take: the cultural popularity score. Given the article title from Wikidata, the API returns the total view count over the past 12 months.

When Wikidata has no `P18` image, the notebook queries the selected Wikipedia article's page summary and uses its thumbnail as a fallback popup image.

Image attribution is currently stored only as `image_source` (`Wikidata P18` or `Wikipedia thumbnail`). Before a public release, add Commons/Wikipedia image metadata if per-image author/license attribution is required.

---

## Python Pipeline

All heavy processing runs locally and produces a single lightweight GeoJSON file (~2 MB). Nothing heavy is left for the browser.

### Step 1 — IUCN filtering & label-point computation

- Query the IUCN API for latest global assessments in the default animal classes.
- Keep only statuses EW, CR, EN, VU, NT, and CD (displayed as NT).
- Keep assessment date/year, citation URL, population trend, raw number of mature individuals, raw estimated area of occupancy, raw estimated extent of occurrence, and IUCN spatial availability flags.
- Run the spatial cleaning script from the notebook to keep only source records matching the current target `taxonid`s.
- Read the cleaned spatial file instead of reopening the raw shapefiles in the notebook.
- For each species, compute one or more **label points** from its habitat geometry:
  - one contiguous range polygon → one centroid-like point inside the polygon;
  - multiple disjoint range polygons → one point for each of the 10 largest components max;
  - no range polygon → one centroid from the observation points.
- Export the dissolved source geometry separately as `animals-spatial.geojson` for future polygon/point work.

### Step 2 — Popularity harvesting

For each valid species:
1. Query Wikidata (SPARQL) to retrieve the preferred Wikipedia sitelink and `P18` image.
2. Query the matching Wikimedia Pageviews project to get the 12-month view count.
3. Query the selected Wikipedia page summary only when a Wikidata image is missing, and use its thumbnail as fallback.
4. Store the final `image_url`, `image_source`, and popularity score.

Be polite to the Wikipedia API: set a proper `User-Agent` header (include your email) and add `time.sleep(0.1)` between requests.

### Step 3 — Clean GeoJSON export

The script produces `animals.geojson`, a lightweight list of GeoJSON Point features. A species can appear multiple times when its range has several large disjoint components:

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [longitude, latitude] },
  "properties": {
    "label": "Siberian Tiger",
    "category_iucn": "EN",
    "wiki_title": "Tiger",
    "wiki_language": "en",
    "wiki_project": "en.wikipedia.org",
    "wiki_url": "https://en.wikipedia.org/wiki/Tiger",
    "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Panthera_tigris_tigris.jpg",
    "image_source": "Wikidata P18",
    "population_trend": "Decreasing",
    "number_of_mature_individuals": "2654",
    "estimated_area_of_occupancy": "882408",
    "estimated_extent_of_occurrence": "939120",
    "computed_range_area_km2": 5410023.4,
    "computed_range_component_area_km2": 273812.6,
    "assessment_date": "2021-11-01T00:00:00.000+00:00",
    "year_published": "2022",
    "taxon_class": "Mammalia",
    "taxon_group": "Mammals",
    "taxon_rank": "species",
    "iucn_has_ranges": true,
    "iucn_has_points": false,
    "centroid_source": "range_polygon",
    "centroid_rank": 1,
    "centroid_count": 3,
    "range_component_count": 12,
    "spatial_presence_label": "Extant",
    "spatial_seasonal_label": "Resident",
    "spatial_credit": "IUCN 2025. The IUCN Red List of Threatened Species. Version 2025-2. https://www.iucnredlist.org. Downloaded on 14 June 2026.",
    "iucn_data_last_updated": "10 October 2025",
    "popularity": 15400
  }
}
```

It also produces `animals-spatial.geojson`, a heavier sidecar containing the dissolved source spatial geometry for each species.

For dataset-level credit, use:

```text
IUCN 2025. The IUCN Red List of Threatened Species. Version 2025-2. https://www.iucnredlist.org. Downloaded on 14 June 2026.
```

If you download a different spatial version or download date, update `IUCN_RED_LIST_VERSION`, `IUCN_RED_LIST_VERSION_YEAR`, `IUCN_DATA_LAST_UPDATED`, and `SPATIAL_DATA_DOWNLOAD_DATE` in the notebook before exporting.

Expected output: **5,000–10,000 points**, roughly **2–3 MB**.

---

## Web Interface

### Stack (100% free, open-source, no recurring subscriptions)

| Role | Tool |
|---|---|
| 3D Globe engine | [MapLibre GL JS v5](https://maplibre.org/) — WebGL, native globe projection |
| Base map | CartoDB Dark Matter (no labels) — dark, label-free tiles |
| Starfield | [maplibre-gl-starfield](https://github.com/markmclaren/maplibre-gl-starfield) — custom celestial-vault motion |
| Hosting | GitHub Pages (static, no server needed) |

### Visual atmosphere

**Dark space background.** A custom starfield (600 stars) is rendered in a dedicated SVG layer behind the WebGL canvas. Instead of depth-based parallax, the stars move as a single curved celestial vault when the globe rotates, with a slight center-based rotation to avoid flat sliding.

**Styled globe.** CartoDB Dark Matter provides the label-free vector geometry, while the prototype overrides land, water, and boundary colors to create a saturated violet-blue globe inspired by Notable People.

**Thin label halos.** Species labels use a very light text halo so names stay legible without the heavy outlined look of the first prototype.

### Rendering mechanics

**No clustering.** Bubble clustering destroys the intended effect. Instead, use MapLibre's native symbol de-overlap:

```js
'text-allow-overlap': false,
'symbol-sort-key': ['*', -1, ['to-number', ['get', 'popularity'], 0]]
```

The negative sort key gives more popular species placement priority, so the GPU hides less-known species when a more popular one occupies the same geodesic area. This produces a smooth fade as you zoom.

**Neon dots.** Below each text label, render a `circle` layer with `'circle-blur': 0.4`. Colors by IUCN category (see table above).

At low zoom, the Earth appears covered in a glowing swarm of colored fireflies before individual names become legible.

**Glassmorphism UI.** Filter buttons (All / EW / CR / EN / VU / NT) float over the map with:

```css
background: rgba(10, 10, 15, 0.6);
backdrop-filter: blur(12px);
border: 1px solid rgba(255, 255, 255, 0.08);
```

---

## Known Challenges

**IUCN account creation.** This is the only mandatory account to create. The validation takes 24–48 hours — do it first. You need their API token for automated assessment queries and shapefile downloads.

**IUCN API rate limits.** The notebook uses a local cache and a 0.5s delay between IUCN API calls. Keep both enabled while iterating, especially in sample mode.

**Wikipedia API rate limits.** Wikimedia blocks scripts that query too fast without identifying themselves. Always set a proper `User-Agent` string (include your email address) and add a small delay between requests.

**Ocean emptiness.** Terrestrial species will cluster beautifully on biodiversity hotspots (Madagascar, Indonesia, Amazonia) while marine species (whales, sharks) may appear as isolated dots in the middle of oceans. The neon dot layer helps fill these vast blue spaces visually.

**NT scale.** Near Threatened adds a significantly larger population of species than CR/EN/VU. The "popcorn" de-overlap effect will be more aggressive at low zoom — this is intended behavior.

---

## Immediate Action Plan

1. **Create your IUCN account** at [iucnredlist.org](https://www.iucnredlist.org/) to get access to species geographic data (allow 24–48h for validation).
2. **Bootstrap the Python pipeline** locally in sample mode: query the IUCN API for 20 mammals using the same downstream steps as the full run.
3. **Wire up the Wikidata → Pageviews bridge** in Python to confirm you can generate a popularity score for those animals.
4. **Replace inline test data** in `index.html` with `fetch('animals.geojson')` once the pipeline produces the real file.
5. **Scale the pipeline** to the full IUCN animal dataset (EW + CR + EN + VU + NT/CD), export `animals.geojson`, and deploy to GitHub Pages.

---

## Reference

- [Notable People by Topi Tjukanov](https://tjukanovt.github.io/notable-people) — visual and UX inspiration
- [MapLibre GL JS docs](https://maplibre.org/maplibre-gl-js/docs/)
- [IUCN Red List API](https://api.iucnredlist.org/)
- [Wikidata SPARQL endpoint](https://query.wikidata.org/)
- [Wikimedia Pageviews API](https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews)
- [maplibre-gl-starfield plugin](https://github.com/markmclaren/maplibre-gl-starfield)
