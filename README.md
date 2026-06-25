# An Endangered Globe

Today, more than 48,600 species are threatened with extinction. That's 28% of the 172,600 species assessed by the IUCN in 2025. This interactive 3D globe maps some of these threatened species, primarily vertebrates (Animalia). Inspired by [Topi Tjukanov's Notable People](https://tjukanovt.github.io/notable-people), the map displays no city names — the world's geography is redrawn entirely through the names of threatened animals.

## Table of Contents

- [Concept](#concept)
- [IUCN Categories Included](#iucn-categories-included)
- [Data Architecture](#data-architecture)
  - [Channel 1 — IUCN Red List API](#channel-1--iucn-red-list-api)
  - [Channel 2 — IUCN Spatial Data](#channel-2--iucn-spatial-data)
  - [Channel 3 — Wikidata (SPARQL API)](#channel-3--wikidata-sparql-api)
  - [Channel 4 — Wikipedia Pageviews (public REST API)](#channel-4--wikipedia-pageviews-public-rest-api)
- [Python Pipeline](#python-pipeline)
  - [Step 1 — IUCN filtering & label-point computation](#step-1--iucn-filtering--label-point-computation)
  - [Step 2 — Popularity harvesting](#step-2--popularity-harvesting)
  - [Step 3 — Clean GeoJSON export](#step-3--clean-geojson-export)
- [Web Interface](#web-interface)
- [Reference](#reference)

---

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
- `sample_mammals` — small run seeded from the local `MAMMALS` spatial package for fast iteration.
- `sample_birds` — small run seeded from the local `BIRDS` spatial package for fast iteration.
- `full_mammals` — taxa present in the local `MAMMALS` spatial package.
- `full_other` — taxa present in the local `REPTILES`, `AMPHIBIANS`, `FW_CRABS`, `FW_CRAYFISH`, `FW_SHRIMPS`, and `LOBSTERS` spatial packages.
- `full_fish` — taxa present in the local `FW_FISH` and `SHARKS_RAYS_CHIMAERAS` spatial packages.
- `full_birds` — taxa present in the local `BIRDS` spatial package.

The API fetch is rank-aware but not rank-exclusive: it keeps the IUCN taxon rank in `taxon_rank`. When a species mentions infrarank children but no fetched/displayable child has an endangered category, the parent species is kept.

`USE_PARENT_SPATIAL_FALLBACK` (default `False`): when enabled, the notebook also fetches IUCN details for infrarank children absent from the shapefiles and lets them inherit the parent species geometry as a spatial lookup source. Disabled by default because it produces multiple points at identical coordinates when several subspecies share one parent. When disabled, only taxa with their own spatial record are displayed.

Ignored edge case for speed and simplicity: a non-threatened parent species whose missing infrarank child is threatened and absent from the shapefiles. The pipeline does not fetch LC/DD/NE parent taxa solely to discover this case.

Current displayed animal groups:
- Mammals
- Birds
- Other (Reptiles, Amphib., Crust.)
- Fish (sharks, freshwater)

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

- `sample_mammals`, `full_mammals` → `data/shapefiles/MAMMALS/*.shp`
- `sample_birds`, `full_birds` → `data/shapefiles/BIRDS/*.gpkg`
- `full_other` → `data/shapefiles/REPTILES/*.shp`, `AMPHIBIANS/*.shp`, `FW_CRABS/*.shp`, `FW_CRAYFISH/*.shp`, `FW_SHRIMPS/*.shp`, `LOBSTERS/*.shp`
- `full_fish` → `data/shapefiles/FW_FISH/*.shp`, `SHARKS_RAYS_CHIMAERAS/*.shp`

The cleaning script uses the target table's explicit `spatial_package` value when choosing folders. `taxon_class` is not used for spatial routing.

Spatial download coverage log for IUCN spatial-download categories. Keep this ledger in sync with the official [IUCN spatial data download page](https://www.iucnredlist.org/resources/spatial-data-download) whenever a new package is downloaded or wired into the pipeline.

| IUCN spatial category / local folder | Status | IUCN class metadata expected | UI group | Run mode | Notes |
|---|---|---|---|---|---|
| Mammals / `MAMMALS` | Covered | `Mammalia` | Mammals | `sample_mammals`, `full_mammals` | Split files such as `MAMMALS_PART*.shp` are concatenated by the cleaning script. |
| Birds / `BIRDS` | Covered | `Aves` | Birds | `sample_birds`, `full_birds` | BirdLife BOTW GPKG format; taxon ID column is `sisid`. |
| Amphibians / `AMPHIBIANS` | Covered | `Amphibia` | Other (Reptiles, Amphib., Crust.) | `full_other` | Grouped with reptiles and selected crustaceans in the UI. |
| Reptiles / `REPTILES` | Covered | `Reptilia` | Other (Reptiles, Amphib., Crust.) | `full_other` | Grouped with amphibians and selected crustaceans in the UI. |
| Freshwater crabs / `FW_CRABS` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean spatial files. |
| Freshwater crayfish / `FW_CRAYFISH` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean spatial files. |
| Freshwater shrimps / `FW_SHRIMPS` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean spatial files. |
| Lobsters / `LOBSTERS` | Covered | `Malacostraca` | Other (Reptiles, Amphib., Crust.) | `full_other` | Selected crustacean spatial files. |
| Freshwater fishes / `FW_FISH` | Covered | `Actinopterygii`, `Chondrichthyes`, `Myxini`, `Petromyzonti`, `Sarcopterygii` when present in these spatial files | Fish (sharks, freshwater) | `full_fish` | Freshwater fish spatial files; split files such as `FW_FISH_PART*.shp` are concatenated by the cleaning script. Marine fish outside these spatial files are not queried. |
| Sharks, rays, and chimaeras / `SHARKS_RAYS_CHIMAERAS` | Covered | `Chondrichthyes` | Fish (sharks, freshwater) | `full_fish` | Cartilaginous fish spatial files. |
| Other fishes not listed above | Not covered | TBD | TBD | none | Kept out until the relevant folder is downloaded and mapped explicitly; this includes marine fish packages outside the current freshwater fish and sharks/rays/chimaeras sources. |
| Corals | Not covered | TBD | none | none | Outside the current animal-label scope. |
| Molluscs, including cone snails and freshwater molluscs | Not covered | TBD | none | none | Outside the current animal-label scope. |
| Insects and other terrestrial/freshwater arthropods | Not covered | TBD | none | none | Excluded by default because broad insect coverage would create many low-signal API calls. Add only explicit packages if needed later. |
| Plants, including conifers, cycads, mangroves, and seagrasses | Not covered | TBD | none | none | Outside the current animal-label scope. |
| Any other IUCN downloadable spatial category | Not covered until mapped | TBD | TBD | none | Add the folder pattern to `SPATIAL_PACKAGE_CONFIG`, include it in a `RUN_MODE_SPATIAL_PACKAGES` entry, choose a UI group/run mode, then document it here. |

Some downloads are split into several shapefile parts, such as `MAMMALS_PART1.shp` / `MAMMALS_PART2.shp` and `FW_FISH_PART*.shp`; these are chunks of the same spatial package and should be concatenated by the cleaning script. Match spatial records to API rows with `id_no == taxonid`. Do not match on `assessment_id`.

The notebook launches `scripts/clean_spatial_data.py` after the IUCN API fetch. It writes the current target taxa to `data/processed/iucn_target_taxa.csv`, filters the heavy source files once, and outputs `data/processed/iucn_spatial_clean.geojson`. `data/processed/` is also ignored by git.

When `USE_PARENT_SPATIAL_FALLBACK = True`, the notebook does a second, narrow spatial-cleaning pass for parent species of infrarank taxa with no spatial records of their own. Those parent geometries are copied onto the displayed infrarank rows and marked with `spatial_lookup_source = parent_species`; parent species are not added as displayed taxa. Disabled by default.

Official IUCN AOO/EOO fields are kept as raw assessment attributes: `estimated_area_of_occupancy` and `estimated_extent_of_occurrence`. Polygon-derived areas are exported separately as `computed_range_area_km2` and `computed_range_component_area_km2`; these are range geometry measurements, not substitutes for IUCN AOO.

Before centroid placement, `presence` is used as a strong priority per taxon, not as a hard filter. The representative geometry is chosen from the best available presence bucket: Extant, then Probably Extant, then Possibly Extant, then Possibly Extinct, then Presence Uncertain, then Extinct. This keeps useful historical range information for EW species when no current wild range is available.

`origin` is ignored: native, reintroduced, introduced, vagrant, origin uncertain, and assisted-colonisation records are not filtered differently.

`seasonal` is used as a secondary soft priority per taxon. After the best presence bucket is selected, the representative geometry is chosen from the best available seasonal bucket: Resident, then Breeding, then Non-breeding, then Passage, then Seasonality Uncertain.

Credit requirement: IUCN spatial data must be credited in any derived product. The notebook keeps species-level spatial citation fields when present and exports both `spatial_credit` and `iucn_dataset_citation`.

### Channel 3 — Wikidata (SPARQL API)
What we take: the translation dictionary and primary image. We query Wikidata with an IUCN species ID and get back the best available Wikipedia sitelink plus the `P18` image when available.

Wikipedia language priority is: English, German, French, Japanese, Russian, Spanish, Italian, Chinese, Polish, Portuguese, then the first remaining Wikipedia sitelink returned by Wikidata.

**Wikipedia article resolution fallback chain** — for taxa not resolved by the initial IUCN ID → Wikidata batch query:

1. **Wikidata SPARQL — P225 batch** (scientific name property): batches up to 100 name variants at a time, with subspecies normalisation (`ssp.` / `subsp.` variants).
2. **Wikidata entity search** (`wbsearchentities`): searched by scientific name then common name for each still-unresolved taxon.
3. **Wikipedia direct title lookup**: tries the scientific name then the common name as a Wikipedia article title, resolving redirects.
4. **Wikispecies lookup**: checks `species.wikimedia.org` for an article matching the scientific name. Useful for taxa assessed at subspecies level that have a Wikispecies page but no Wikipedia article.
5. **HTTP retry**: rows that failed due to network errors in passes 2–4 are retried at the end of the chain.

For infrarank taxa without a resolved Wikipedia article, the notebook makes one extra batched Wikidata lookup for the needed parent species IDs. If a parent article exists, the infrarank keeps its own IUCN identity and conservation status but inherits the parent species article, image lookup, and pageviews signal. If an infrarank has an article but still has zero pageviews or no usable image, parent species lookups are attempted only for those missing fields. Parent lookup IDs are queried only when absent from the local Wikidata cache, so parents already resolved earlier are reused. Rows using parent article/pageviews are marked with `wiki_lookup_source = parent_species`; rows using only a parent image are marked with `image_lookup_source = parent_species`.

### Channel 4 — Wikipedia Pageviews (public REST API)
What we take: the cultural popularity score. Given the article title from Wikidata, the API returns the total view count over the past 12 months. The query uses `user` (human traffic only), excluding bots and automated crawlers.

Species with no resolved Wikipedia article after all fallback steps, and species whose article received zero pageviews in the past year, are both assigned a popularity of **1**. This ensures they still appear on the globe (the label sort key is `−popularity`, so a zero would suppress them) while ranking below any article with real traffic.

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

### Step 2 — Popularity harvesting

For each valid species:
1. Resolve a Wikipedia article via the fallback chain described in Channel 3 above.
2. Query the matching Wikimedia Pageviews project (Wikipedia or Wikispecies) to get the 12-month view count.
3. Query the Wikipedia page thumbnail for all taxa; prefer it over Wikidata P18 when both exist.
4. If no image yet, fall back in order to: Wikidata P18 → Wikimedia Commons search by scientific name then common name → iNaturalist.
5. Skip candidate image titles or URLs containing `distrib`, `range`, or `extent` unless those terms also appear in the species name itself, since they likely indicate range maps rather than photos.
6. Store the final `image_url`, `image_source`, image lookup traceability fields, image attribution fields, and popularity score.

Individual API responses are cached on disk in `data/cache/iucn/` (IUCN) and the Wikimedia token raises the rate limit to 5,000 req/hour.

The notebook fetches each external image/pageviews resource once per unique article or taxon, then fills duplicate label-point rows created by multi-centroid species.

Current image priority:

1. Selected Wikipedia page thumbnail
2. Wikidata `P18`
3. Wikimedia Commons search by exact scientific name, then exact main common name
4. iNaturalist (includes all-rights-reserved photos, with attribution)

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

For dataset-level credit, use:

```text
IUCN 2025. The IUCN Red List of Threatened Species. Version 2025-2. https://www.iucnredlist.org. Downloaded on 14 June 2026.
```

If you download a different spatial version or download date, update `IUCN_RED_LIST_VERSION`, `IUCN_RED_LIST_VERSION_YEAR`, `IUCN_DATA_LAST_UPDATED`, and `SPATIAL_DATA_DOWNLOAD_DATE` in the notebook before exporting.

Expected output depends on `RUN_MODE`: sample runs stay small, while broad spatial-package runs can produce thousands of label points and a multi-MB `animals.geojson`.

---

## Web Interface

### Stack (100% free, open-source)

| Role | Tool |
|---|---|
| 3D Globe engine | [MapLibre GL JS v5](https://maplibre.org/) — WebGL, native globe projection |
| Base map | CartoDB Dark Matter (no labels) — dark, label-free tiles |
| Starfield | [maplibre-gl-starfield](https://github.com/markmclaren/maplibre-gl-starfield) — custom celestial-vault motion |
| Hosting | GitHub Pages (static, no server needed) |

### Visual atmosphere

**Dark space background.** A custom starfield (600 stars) is rendered in a dedicated SVG layer behind the WebGL canvas. Instead of depth-based parallax, the stars move as a single curved celestial vault when the globe rotates, with a slight center-based rotation to avoid flat sliding.

**Styled globe.** CartoDB Dark Matter provides the label-free vector geometry, while the prototype overrides land, water, and boundary colors to create a saturated violet-blue globe inspired by Notable People.

**Thin label halos.** Species labels use a very light text halo so names stay legible without a heavy outline.

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

## Reference

- [Notable People by Topi Tjukanov](https://tjukanovt.github.io/notable-people) — visual and UX inspiration
- [MapLibre GL JS docs](https://maplibre.org/maplibre-gl-js/docs/)
- [IUCN Red List API](https://api.iucnredlist.org/)
- [Wikidata SPARQL endpoint](https://query.wikidata.org/)
- [Wikimedia Pageviews API](https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews)
- [maplibre-gl-starfield plugin](https://github.com/markmclaren/maplibre-gl-starfield)
