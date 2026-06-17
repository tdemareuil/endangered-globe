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

The notebook uses IUCN API v4 for assessment details, but it no longer starts from broad taxonomic classes. It first reads `id_no` taxon IDs from the local IUCN spatial packages selected by `RUN_MODE`, then fetches IUCN details only for those spatially relevant taxa. This avoids broad queries such as the whole marine + freshwater `Actinopterygii` universe when only the `FW_FISH` spatial package is in scope.

When the shapefile exposes a `category` attribute, the notebook uses it as a conservative prefilter before calling the API: only taxa whose spatial category can be displayed on the globe are fetched. This avoids spending API calls on obvious LC/DD/NE spatial taxa.

The IUCN API token is not stored in the notebook. Set it with the `IUCN_TOKEN` environment variable, or put it in the local ignored file `data/secrets/iucn_token.txt`.

Available run modes:
- `sample` — small run seeded from the local `MAMMALS` spatial package for fast iteration.
- `full_mammals` — taxa present in the local `MAMMALS` spatial package.
- `full_other` — taxa present in the local `REPTILES`, `AMPHIBIANS`, `FW_CRABS`, `FW_CRAYFISH`, `FW_SHRIMPS`, and `LOBSTERS` spatial packages.
- `full_fish` — taxa present in the local `FW_FISH` and `SHARKS_RAYS_CHIMAERAS` spatial packages.

The API fetch is rank-aware but not rank-exclusive: it keeps the IUCN taxon rank in `taxon_rank`. If a fetched/displayable parent species reports infrarank children that are absent from the shapefiles, the notebook can fetch those children; if they have an endangered category used by the globe, it displays the infrarank rows and lets them inherit the parent species geometry as a lookup source. When a species mentions infrarank children but no fetched/displayable child has an endangered category, the parent species is kept.

Ignored edge case for speed and simplicity: a non-threatened parent species whose missing infrarank child is threatened and absent from the shapefiles. The pipeline does not fetch LC/DD/NE parent taxa solely to discover this case.

Current displayed animal groups:
- Mammals
- Other (Reptiles, Amphib., Crust.)
- Fish (sharks, freshwater)

The HTML also has a Birds filter ready, but birds are handled later because their spatial source needs a separate pass.

Underlying IUCN classes currently expected in the selected spatial packages:
- `Mammalia`
- `Reptilia`
- `Amphibia`
- `Malacostraca`
- `Actinopterygii`
- `Chondrichthyes`
- `Myxini`
- `Petromyzonti`
- `Sarcopterygii`

The pipeline keeps the original IUCN class in `taxon_class` as raw API metadata, but derives the UI-facing `taxon_group` from `spatial_package`. This keeps the browser grouping aligned with the spatial download actually used: mammals come from `MAMMALS`, reptiles/amphibians/selected crustaceans from the Other packages, and fish only from the selected fish packages.

Excluded by default: plants, fungi, corals, molluscs, most other invertebrates beyond the selected crustacean packages, marine bony fish outside the current freshwater package, and insects. Insects are not included in final mode by default because the API can filter `Insecta`, but not "large insects" specifically, so it would add a lot of low-signal API calls.

Included Red List categories:
- **EW** — Extinct in the Wild (surviving only in captivity or cultivation)
- **CR** — Critically Endangered
- **EN** — Endangered
- **VU** — Vulnerable
- **NT** — Near Threatened (includes Conservation Dependent / CD)

### Channel 2 — IUCN Spatial Data
What we take: geographic boundaries and source spatial geometries for species habitats. The API assessment detail tells us whether range polygons or points exist; the actual geometries are read from local IUCN shapefiles.

Local spatial downloads live in `data/shapefiles/` and are ignored by git. The notebook first builds a spatial manifest from explicit package folders:

- `sample`, `full_mammals` → `data/shapefiles/MAMMALS/*.shp`
- `full_other` → `data/shapefiles/REPTILES/*.shp`, `AMPHIBIANS/*.shp`, `FW_CRABS/*.shp`, `FW_CRAYFISH/*.shp`, `FW_SHRIMPS/*.shp`, `LOBSTERS/*.shp`
- `full_fish` → `data/shapefiles/FW_FISH/*.shp`, `SHARKS_RAYS_CHIMAERAS/*.shp`

The cleaning script uses the target table's explicit `spatial_package` value when choosing folders. `taxon_class` is not used for spatial routing.

Spatial download coverage log for IUCN spatial-download categories. Keep this ledger in sync with the official [IUCN spatial data download page](https://www.iucnredlist.org/resources/spatial-data-download) whenever a new package is downloaded or wired into the pipeline.

| IUCN spatial category / local folder | Status | IUCN class metadata expected | UI group | Run mode | Notes |
|---|---|---|---|---|---|
| Mammals / `MAMMALS` | Covered | `Mammalia` | Mammals | `sample`, `full_mammals` | Split files such as `MAMMALS_PART*.shp` are concatenated by the cleaning script. |
| Birds / `BIRDS` | Downloaded, not covered yet | `Aves` | Birds | none | The HTML filter is ready, but birds need a separate pipeline pass because their spatial source/format needs more work. |
| Amphibians / `AMPHIBIANS` | Covered | `Amphibia` | Other (Reptiles, Amphib., Crust.) | `full_other` | Grouped with reptiles and selected crustaceans in the UI. |
| Reptiles / `REPTILES` | Covered | `Reptilia` | Other (Reptiles, Amphib., Crust.) | `full_other` | Grouped with amphibians and selected crustaceans in the UI. |
| Freshwater crabs / `FW_CRABS` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean package. |
| Freshwater crayfish / `FW_CRAYFISH` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean package. |
| Freshwater shrimps / `FW_SHRIMPS` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean package. |
| Lobsters / `LOBSTERS` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean package. |
| Freshwater fishes / `FW_FISH` | Covered | `Actinopterygii`, `Chondrichthyes`, `Myxini`, `Petromyzonti`, `Sarcopterygii` when present in this package | Fish (sharks, freshwater) | `full_fish` | Freshwater fish package; split files such as `FW_FISH_PART*.shp` are concatenated by the cleaning script. Marine fish outside this package are not queried. |
| Sharks, rays, and chimaeras / `SHARKS_RAYS_CHIMAERAS` | Covered | `Chondrichthyes` | Fish (sharks, freshwater) | `full_fish` | Cartilaginous fish package. |
| Other fish spatial packages not listed above | Not covered | TBD | TBD | none | Kept out until the relevant folder is downloaded and mapped explicitly; this includes marine fish packages outside the current freshwater fish and sharks/rays/chimaeras sources. |
| Corals | Not covered | TBD | none | none | Outside the current animal-label scope. |
| Molluscs, including cone snails or freshwater mollusc packages | Not covered | TBD | none | none | Outside the current animal-label scope. |
| Insects and other terrestrial/freshwater arthropods not listed above | Not covered | TBD | none | none | Excluded by default because broad insect coverage would create many low-signal API calls. Add only explicit packages if needed later. |
| Plants, including conifers, cycads, mangroves, and seagrasses | Not covered | TBD | none | none | Outside the current animal-label scope. |
| Any other IUCN downloadable spatial category | Not covered until mapped | TBD | TBD | none | Add the folder pattern to `SPATIAL_PACKAGE_CONFIG`, include it in a `RUN_MODE_SPATIAL_PACKAGES` entry, choose a UI group/run mode, then document it here. |

Some downloads are split into several shapefile parts, such as `MAMMALS_PART1.shp` / `MAMMALS_PART2.shp` and `FW_FISH_PART*.shp`; these are chunks of the same spatial package and should be concatenated by the cleaning script. Match spatial records to API rows with `id_no == taxonid`. Do not match on `assessment_id`.

The notebook launches `scripts/clean_spatial_data.py` after the IUCN API fetch. It writes the current target taxa to `data/processed/iucn_target_taxa.csv`, filters the heavy source files once, and outputs `data/processed/iucn_spatial_clean.geojson`. `data/processed/` is also ignored by git.

For infrarank taxa that have no spatial records of their own, the notebook can do a second, narrow spatial-cleaning pass for their parent species only. Those parent geometries are copied onto the displayed infrarank rows and marked with `spatial_lookup_source = parent_species`; parent species are not added as displayed taxa.

Official IUCN AOO/EOO fields are kept as raw assessment attributes: `estimated_area_of_occupancy` and `estimated_extent_of_occurrence`. Polygon-derived areas are exported separately as `computed_range_area_km2` and `computed_range_component_area_km2`; these are range geometry measurements, not substitutes for IUCN AOO.

Before centroid placement, `presence` is used as a strong priority per taxon, not as a hard filter. The representative geometry is chosen from the best available presence bucket: Extant, then Probably Extant, then Possibly Extant, then Possibly Extinct, then Presence Uncertain, then Extinct. This keeps useful historical range information for EW species when no current wild range is available.

`origin` is ignored: native, reintroduced, introduced, vagrant, origin uncertain, and assisted-colonisation records are not filtered differently.

`seasonal` is used as a secondary soft priority per taxon. After the best presence bucket is selected, the representative geometry is chosen from the best available seasonal bucket: Resident, then Breeding, then Non-breeding, then Passage, then Seasonality Uncertain.

Credit requirement: IUCN spatial data must be credited in any derived product. The notebook keeps species-level spatial citation fields when present and exports both `spatial_credit` and `iucn_dataset_citation`.

### Channel 3 — Wikidata (SPARQL API)
What we take: the translation dictionary and primary image. We query Wikidata with an IUCN species ID and get back the best available Wikipedia sitelink plus the `P18` image when available.

Wikipedia language priority is: English, German, French, Japanese, Russian, Spanish, Italian, Chinese, Polish, Portuguese, then the first remaining Wikipedia sitelink returned by Wikidata.

For infrarank taxa without a resolved Wikipedia article, the notebook makes one extra batched Wikidata lookup for the needed parent species IDs. If a parent article exists, the infrarank keeps its own IUCN identity and conservation status but inherits the parent species article, image lookup, and pageviews signal. If an infrarank has an article but still has zero pageviews or no usable image, parent species lookups are attempted only for those missing fields. Parent lookup IDs are queried only when absent from the local Wikidata cache, so parents already resolved earlier are reused. Rows using parent article/pageviews are marked with `wiki_lookup_source = parent_species`; rows using only a parent image are marked with `image_lookup_source = parent_species`.

### Channel 4 — Wikipedia Pageviews (public REST API)
What we take: the cultural popularity score. Given the article title from Wikidata, the API returns the total view count over the past 12 months.

When Wikidata has no `P18` image, the notebook queries the selected Wikipedia article's page summary and uses its thumbnail as a fallback popup image. If both are missing, it can search Wikimedia Commons by scientific/common name and keep attribution metadata when available.

Image attribution fields are exported alongside `image_url`. The popup links to Wikidata, IUCN, and the image/source URL when available.

---

## Python Pipeline

All heavy processing runs locally and produces a single lightweight GeoJSON file. Nothing heavy is left for the browser.

The notebook is intentionally kept as an orchestration layer. Reusable helper functions live in `scripts/pipeline_helpers.py`, while the heavy spatial pre-cleaning entry point lives in `scripts/clean_spatial_data.py`.

### Step 1 — IUCN filtering & label-point computation

- Build the target list from the selected local IUCN spatial packages, then query the IUCN API for latest global assessments only for those taxon IDs.
- Keep only statuses EW, CR, EN, VU, NT, and CD (displayed as NT).
- Keep assessment date/year, citation URL, population trend, raw number of mature individuals, raw estimated area of occupancy, raw estimated extent of occurrence, and IUCN spatial availability flags.
- Run the spatial cleaning script from the notebook to keep only source records matching the current target `taxonid`s.
- Read the cleaned spatial file instead of reopening the raw shapefiles in the notebook.
- For each species, compute one or more **label points** from its habitat geometry:
  - one contiguous range polygon → one centroid-like point inside the polygon;
  - multiple disjoint range polygons → nearby components are clustered with `RANGE_CLUSTER_BUFFER_KM`, the largest cluster always gets a point, then secondary clusters get a point only if they pass `SECONDARY_RANGE_CLUSTER_MIN_SHARE`, capped by `MAX_RANGE_CENTROIDS_PER_SPECIES`;
  - no range polygon → one centroid from the observation points.
- Do not drop small fragments before clustering: for highly threatened species, the most representative known range can be tiny. The secondary-cluster share rule only limits additional label points after the largest cluster has been kept.
- Future idea: replace the fixed 200 km range-clustering buffer with an adaptive buffer, for example scaled by species range size or polygon density.
- Export the dissolved source geometry separately as `animals-spatial.geojson` for future polygon/point work.

### Step 2 — Popularity harvesting

For each valid species:
1. Query Wikidata (SPARQL) to retrieve the preferred Wikipedia sitelink and `P18` image.
2. Query the matching Wikimedia Pageviews project to get the 12-month view count.
3. Query the selected Wikipedia page summary only when a Wikidata image is missing, and use its thumbnail as fallback.
4. If both are missing, search Wikimedia Commons by scientific name first, then main common name, and keep the first usable bitmap image with available attribution metadata. Skip candidate image titles or URLs containing `distrib`, `range`, or `extent`, since those are likely maps rather than animal photos.
5. Store the final `image_url`, `image_source`, image lookup traceability fields, image attribution fields, and popularity score.

Be polite to the Wikipedia API: set a proper `User-Agent` header (include your email) and add `time.sleep(0.1)` between requests.

The notebook fetches each external image/pageviews resource once per unique article or taxon, then fills duplicate label-point rows created by multi-centroid species.

Current image priority:

- `Wikidata P18`
- selected Wikipedia page thumbnail
- Wikimedia Commons search by exact scientific name, then exact main common name

Future improvement ideas:

- Use the selected Wikidata item to collect Commons categories or sitelinks, then search inside those narrower Commons results.
- Add manual review flags for Commons fallback images whose search term came from the main common name.
- Avoid scraping or hotlinking IUCN images unless the rights and credit requirements are handled explicitly.

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
    "commons_image_page_url": null,
    "commons_image_author": null,
    "commons_image_license": null,
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
    "range_cluster_count": 5,
    "range_cluster_component_count": 3,
    "range_cluster_buffer_km": 200,
    "range_cluster_area_share": 0.52,
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

Expected output depends on `RUN_MODE`: sample runs stay small, while broad spatial-package runs can produce thousands of label points and a multi-MB `animals.geojson`.

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
2. **Bootstrap the Python pipeline** locally in sample mode: query the IUCN API for a small mammal set using the same downstream steps as the larger runs.
3. **Wire up the Wikidata → Pageviews bridge** in Python to confirm you can generate a popularity score for those animals.
4. **Use the generated browser dataset**: `index.html` now loads `animals.geojson`, with inline sample data kept only as a fallback.
5. **Scale the pipeline by spatial package**: run `full_mammals`, `full_other`, then `full_fish`, export `animals.geojson`, and deploy to GitHub Pages. Birds stay separate until their spatial format is handled.

---

## Reference

- [Notable People by Topi Tjukanov](https://tjukanovt.github.io/notable-people) — visual and UX inspiration
- [MapLibre GL JS docs](https://maplibre.org/maplibre-gl-js/docs/)
- [IUCN Red List API](https://api.iucnredlist.org/)
- [Wikidata SPARQL endpoint](https://query.wikidata.org/)
- [Wikimedia Pageviews API](https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews)
- [maplibre-gl-starfield plugin](https://github.com/markmclaren/maplibre-gl-starfield)
