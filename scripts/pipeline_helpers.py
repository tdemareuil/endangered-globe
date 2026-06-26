#!/usr/bin/env python3
"""Helper functions for the endangered-globe notebook.

The notebook should stay readable and focus on orchestration. Reusable helpers for
IUCN fetching, spatial centroid logic, Wikidata/Wikimedia calls, and GeoJSON
export live here.
"""

from __future__ import annotations

import glob
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid
from tqdm.notebook import tqdm

# Runtime configuration. The notebook calls configure() after defining its knobs.
IUCN_TOKEN = ""
WIKIMEDIA_TOKEN = ""  # Optional — raises rate limit from 500 to 5,000 req/hour
USER_AGENT = "EndangeredGlobe/1.0"
TARGET_CATEGORIES = ["EW", "CR", "EN", "VU", "NT", "CD"]
SLEEP_WIKI = 0.15       # Wikimedia action/REST API (token-authenticated, ~6.6 req/s)
SLEEP_PAGEVIEWS = 1.0  # AQS pageviews endpoint (IP-based limit, token not honoured)
SLEEP_IUCN = 0.5
SPATIAL_DATA_DIR = "data/shapefiles"
PREFILTERED_SPATIAL_DIR = "data/processed/spatial_prefiltered"
BIRDS_FILTER_CSV = ""
SAMPLE_LIMIT = 200
USE_IUCN_CACHE = True
USE_PARENT_SPATIAL_FALLBACK = False
GLOBAL_SCOPE_CODE = 1
IUCN_RED_LIST_VERSION = "2025-2"
IUCN_DATASET_CITATION = ""
SPATIAL_DATA_DOWNLOAD_DATE = ""
IUCN_DATA_LAST_UPDATED = ""
IUCN_BASE = "https://api.iucnredlist.org/api/v4"
IUCN_CACHE_DIR = "data/cache/iucn"
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
PAGEVIEWS_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
PAGEVIEWS_AGENT = "user"  # "user" = human only, "all-agents" = humans + bots
WIKIPEDIA_SUMMARY_URL = "https://{project}/api/rest_v1/page/summary/{title}"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
START = ""
END = ""

OTHER_TAXON_GROUP = "Other (Reptiles, Amphib., Crust.)"
FISH_TAXON_GROUP = "Fishes (not comprehensive)"
MOLLUSCS_TAXON_GROUP = "Crustaceans, Molluscs (not comprehensive)"

SPATIAL_PACKAGE_CONFIG = {
    "MAMMALS": {"patterns": ["MAMMALS/*.shp"], "taxon_group": "Mammals"},
    "REPTILES": {"patterns": ["REPTILES/*.shp"], "taxon_group": OTHER_TAXON_GROUP},
    "AMPHIBIANS": {"patterns": ["AMPHIBIANS/*.shp"], "taxon_group": OTHER_TAXON_GROUP},
    "FW_CRABS": {"patterns": ["FW_CRABS/*.shp"], "taxon_group": OTHER_TAXON_GROUP},
    "FW_CRAYFISH": {
        "patterns": ["FW_CRAYFISH/*.shp"],
        "taxon_group": OTHER_TAXON_GROUP,
    },
    "FW_SHRIMPS": {"patterns": ["FW_SHRIMPS/*.shp"], "taxon_group": OTHER_TAXON_GROUP},
    "LOBSTERS": {"patterns": ["LOBSTERS/*.shp"], "taxon_group": OTHER_TAXON_GROUP},
    "FW_FISH": {"patterns": ["FW_FISH/*.shp"], "taxon_group": FISH_TAXON_GROUP},
    "SHARKS_RAYS_CHIMAERAS": {
        "patterns": ["SHARKS_RAYS_CHIMAERAS/*.shp"],
        "taxon_group": FISH_TAXON_GROUP,
    },
    # Marine fish — subfolders under MARINE FISH/
    "CROAKERS_DRUMS":           {"patterns": ["MARINE FISH/CROAKERS_DRUMS/*.shp"],           "taxon_group": FISH_TAXON_GROUP},
    "EELS":                     {"patterns": ["MARINE FISH/EELS/*.shp"],                     "taxon_group": FISH_TAXON_GROUP},
    "GROUPERS":                 {"patterns": ["MARINE FISH/GROUPERS/*.shp"],                 "taxon_group": FISH_TAXON_GROUP},
    "HAGFISH":                  {"patterns": ["MARINE FISH/HAGFISH/*.shp"],                  "taxon_group": FISH_TAXON_GROUP},
    "SALMONIDS":                {"patterns": ["MARINE FISH/SALMONIDS/*.shp"],                "taxon_group": FISH_TAXON_GROUP},
    "SEABREAMS_SNAPPERS_GRUNTS":{"patterns": ["MARINE FISH/SEABREAMS_SNAPPERS_GRUNTS/*.shp"],"taxon_group": FISH_TAXON_GROUP},
    "STURGEONS_PADDLEFISHES":   {"patterns": ["MARINE FISH/STURGEONS_PADDLEFISHES/*.shp"],   "taxon_group": FISH_TAXON_GROUP},
    "SYNGNATHIFORM_FISHES":     {"patterns": ["MARINE FISH/SYNGNATHIFORM_FISHES/*.shp"],     "taxon_group": FISH_TAXON_GROUP},
    "TUNAS_BILLFISHES_SWORDFISH":{"patterns": ["MARINE FISH/TUNAS_BILLFISHES_SWORDFISH/*.shp"],"taxon_group": FISH_TAXON_GROUP},
    "WRASSES_PARROTFISHES":     {"patterns": ["MARINE FISH/WRASSES_PARROTFISHES/*.shp"],     "taxon_group": FISH_TAXON_GROUP},
    # Molluscs — subfolders under MOLLUSCS/
    "ABALONES":          {"patterns": ["MOLLUSCS/ABALONES/*.shp"],    "taxon_group": MOLLUSCS_TAXON_GROUP},
    "CONE_SNAILS":       {"patterns": ["MOLLUSCS/CONE_SNAILS/*.shp"], "taxon_group": MOLLUSCS_TAXON_GROUP},
    "REEF_FORMING_CORALS":{"patterns": ["MOLLUSCS/REEF_FORMING_CORALS/*.shp"], "taxon_group": MOLLUSCS_TAXON_GROUP},
    # BirdLife BOTW GPKG — single layer "all_species", taxon ID column is "sisid", no category column
    "BIRDS": {"patterns": ["BIRDS/*.gpkg"], "taxon_group": "Birds"},
}

MARINE_FISH_PACKAGES = [
    "CROAKERS_DRUMS", "EELS", "GROUPERS", "HAGFISH", "SALMONIDS",
    "SEABREAMS_SNAPPERS_GRUNTS", "STURGEONS_PADDLEFISHES", "SYNGNATHIFORM_FISHES",
    "TUNAS_BILLFISHES_SWORDFISH", "WRASSES_PARROTFISHES",
]

MOLLUSCS_PACKAGES = ["ABALONES", "CONE_SNAILS", "REEF_FORMING_CORALS"]

RUN_MODE_SPATIAL_PACKAGES = {
    "sample_mammals":     ["MAMMALS"],
    "sample_birds":       ["BIRDS"],
    "sample_fish":        ["FW_FISH", "SHARKS_RAYS_CHIMAERAS"],
    "sample_other":       ["REPTILES", "AMPHIBIANS", "FW_CRABS", "FW_CRAYFISH", "FW_SHRIMPS", "LOBSTERS"],
    "sample_marine_fish": MARINE_FISH_PACKAGES,
    "sample_molluscs":    MOLLUSCS_PACKAGES,
    "full_mammals":       ["MAMMALS"],
    "full_other":         ["REPTILES", "AMPHIBIANS", "FW_CRABS", "FW_CRAYFISH", "FW_SHRIMPS", "LOBSTERS"],
    "full_fish":          ["FW_FISH", "SHARKS_RAYS_CHIMAERAS"],
    "full_birds":         ["BIRDS"],
    "full_marine_fish":   MARINE_FISH_PACKAGES,
    "full_molluscs":      MOLLUSCS_PACKAGES,
}

CATEGORY_LABEL_TO_CODE = {
    "EXTINCT": "EX",
    "EXTINCT IN THE WILD": "EW",
    "CRITICALLY ENDANGERED": "CR",
    "ENDANGERED": "EN",
    "VULNERABLE": "VU",
    "NEAR THREATENED": "NT",
    "LEAST CONCERN": "LC",
    "DATA DEFICIENT": "DD",
    "NOT EVALUATED": "NE",
    "CONSERVATION DEPENDENT": "CD",
}
IUCN_CATEGORY_CODES = set(CATEGORY_LABEL_TO_CODE.values())

PRESENCE_PRIORITY = {1: 1, 2: 2, 3: 3, 4: 4, 6: 5, 5: 6}
PRESENCE_LABELS = {
    1: "Extant",
    2: "Probably Extant",
    3: "Possibly Extant",
    4: "Possibly Extinct",
    5: "Extinct",
    6: "Presence Uncertain",
}
SEASONAL_PRIORITY = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
SEASONAL_LABELS = {
    1: "Resident",
    2: "Breeding",
    3: "Non-breeding",
    4: "Passage",
    5: "Seasonality Uncertain",
}

WIKIPEDIA_LANGUAGE_PRIORITY = [
    "en",
    "de",
    "ja",
    "fr",
    "es",
    "ru",
    "it",
    "zh",
    "pt",
    "pl",
    "nl",
    "uk",
    "ca",
    "sv",
    "cs",
    "fi",
    "ko",
    "tr",
    "no",
    "da",
    "eo",
]
WIKIPEDIA_LANGUAGE_RANK = {
    lang: rank for rank, lang in enumerate(WIKIPEDIA_LANGUAGE_PRIORITY)
}
WIKIDATA_FIELDS = [
    "wiki_title",
    "wiki_language",
    "wiki_project",
    "wiki_url",
    "wikidata_url",
    "wikidata_image_url",
]
wikidata_map = {}
IUCN_TAXON_ID_ENDPOINT_TEMPLATE = None
IUCN_TAXON_ID_ENDPOINT_CANDIDATES = [
    "/taxa/{taxonid}/assessments",
    "/taxa/id/{taxonid}/assessments",
    "/taxa/sis/{taxonid}/assessments",
    "/taxa/{taxonid}",
    "/taxa/id/{taxonid}",
    "/taxa/sis/{taxonid}",
    "/taxon/{taxonid}",
    "/species/{taxonid}",
]


def configure(**kwargs):
    """Set runtime values supplied by the notebook configuration cell."""
    globals().update({key: value for key, value in kwargs.items() if value is not None})


def set_pageview_window(start, end):
    """Set the Wikimedia pageview window used by get_pageviews()."""
    configure(START=start, END=end)


def read_local_secret(path):
    """Read a local secret file ignored by git, returning an empty string if absent."""
    path = Path(path)
    return path.read_text().strip() if path.exists() else ""


def clean_str(value):
    """Return a stripped string, or '' for None/NaN/non-string values."""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() == "nan" else s


def wikimedia_headers():
    """Build request headers for Wikimedia APIs, injecting Bearer token when configured."""
    h = {"User-Agent": USER_AGENT}
    token = (WIKIMEDIA_TOKEN or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def require_iucn_token():
    """Return the configured IUCN token, or stop early with a setup error."""
    token = (IUCN_TOKEN or "").strip()
    if not token or token == "YOUR_TOKEN_HERE":
        raise RuntimeError(
            "Set IUCN_TOKEN in the notebook or export it as an environment variable before querying IUCN."
        )
    return token


def iucn_cache_path(path, params):
    """Build a stable local cache filename for one IUCN request."""
    key = json.dumps({"path": path, "params": params or {}}, sort_keys=True)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(IUCN_CACHE_DIR, f"{digest}.json")


def iucn_get(path, params=None, retries=4):
    """GET one IUCN API resource with auth, local JSON cache, and rate limiting."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    cache_path = iucn_cache_path(path, params)
    if USE_IUCN_CACHE and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    headers = {"Authorization": require_iucn_token(), "User-Agent": USER_AGENT}
    for attempt in range(retries):
        try:
            r = requests.get(f"{IUCN_BASE}{path}", params=params, headers=headers, timeout=45)
        except requests.exceptions.SSLError as e:
            wait = 2 ** attempt * 5
            tqdm.write(f"  [IUCN] SSL error — waiting {wait}s before retry ({e})")
            time.sleep(wait)
            continue
        except requests.exceptions.ConnectionError as e:
            wait = 2 ** attempt * 5
            tqdm.write(f"  [IUCN] connection error — waiting {wait}s before retry ({e})")
            time.sleep(wait)
            continue
        if r.status_code == 401:
            raise RuntimeError("IUCN rejected the API token. Check IUCN_TOKEN.")
        if r.status_code == 429:
            wait = 2 ** attempt * 5
            tqdm.write(f"  [IUCN] 429 rate limit — waiting {wait}s before retry")
            time.sleep(wait)
            continue
        r.raise_for_status()
        break
    else:
        r.raise_for_status()
    data = r.json()

    if USE_IUCN_CACHE:
        os.makedirs(IUCN_CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    time.sleep(SLEEP_IUCN)
    return data


def iucn_get_optional(path, params=None, allowed_statuses=(404,), retries=4):
    """GET one IUCN resource, returning None for expected missing endpoints/rows."""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    cache_path = iucn_cache_path(path, params)
    if USE_IUCN_CACHE and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    headers = {"Authorization": require_iucn_token(), "User-Agent": USER_AGENT}
    for attempt in range(retries):
        try:
            r = requests.get(f"{IUCN_BASE}{path}", params=params, headers=headers, timeout=45)
        except requests.exceptions.SSLError as e:
            wait = 2 ** attempt * 5
            tqdm.write(f"  [IUCN] SSL error — waiting {wait}s before retry ({e})")
            time.sleep(wait)
            continue
        except requests.exceptions.ConnectionError as e:
            wait = 2 ** attempt * 5
            tqdm.write(f"  [IUCN] connection error — waiting {wait}s before retry ({e})")
            time.sleep(wait)
            continue
        if r.status_code in allowed_statuses:
            time.sleep(SLEEP_IUCN)
            return None
        if r.status_code == 401:
            raise RuntimeError("IUCN rejected the API token. Check IUCN_TOKEN.")
        if r.status_code == 429:
            wait = 2 ** attempt * 5
            tqdm.write(f"  [IUCN] 429 rate limit — waiting {wait}s before retry")
            time.sleep(wait)
            continue
        r.raise_for_status()
        break
    else:
        r.raise_for_status()
    data = r.json()
    if USE_IUCN_CACHE:
        os.makedirs(IUCN_CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    time.sleep(SLEEP_IUCN)
    return data


def wikimedia_retry_after(response, default=10):
    """Return seconds to wait from a Wikimedia 429 Retry-After header, or default."""
    header = response.headers.get("Retry-After", "")
    if header:
        try:
            wait = int(header)
            tqdm.write(f"  [Wikimedia] Retry-After: {wait}s")
            return wait
        except ValueError:
            pass
    return default


def geometry_vertex_count(geom):
    """Count total vertices in a Shapely geometry (all parts and interior rings)."""
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    return sum(
        len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors)
        for p in parts if hasattr(p, "exterior")
    )


def title_fix_possessive(s):
    """Title-case a string but lowercase the 's' in possessives (e.g. \"Lion'S\" → \"Lion's\")."""
    return re.sub(r"'(\w)", lambda m: "'" + m.group(1).lower(), str(s).title())


def pick_path(obj, *paths):
    """Return the first non-empty nested value found in a dict-like API response."""
    for path in paths:
        cur = obj
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break
        if cur not in (None, ""):
            return cur
    return None


def normalize_category(value):
    """Normalize IUCN category labels or codes to short codes like CR, EN, VU."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in IUCN_CATEGORY_CODES:
        return text
    return CATEGORY_LABEL_TO_CODE.get(text)


def bool_or_none(value):
    """Coerce API booleans represented as bools, strings, or blanks to bool/None."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def taxon_class_from_detail(detail):
    """Extract the raw IUCN taxonomic class from an assessment detail for metadata/debugging."""
    taxon = (
        detail.get("taxon")
        if isinstance(detail, dict) and isinstance(detail.get("taxon"), dict)
        else {}
    )
    value = pick_path(taxon, ("class_name",), ("class",))
    if value in (None, ""):
        return None
    return str(value).strip()


def taxon_group_from_spatial_package(spatial_package):
    """Display grouping derived from the IUCN spatial package used for the taxon."""
    packages = [
        part.strip() for part in str(spatial_package or "").split(";") if part.strip()
    ]
    groups = [
        SPATIAL_PACKAGE_CONFIG[package]["taxon_group"]
        for package in packages
        if package in SPATIAL_PACKAGE_CONFIG
    ]
    groups = sorted(set(groups))
    if not groups:
        return "Unknown"
    return groups[0] if len(groups) == 1 else "; ".join(groups)


def format_counter(counter):
    """Format a small Counter for readable progress summaries."""
    if not counter:
        return "none"
    return ", ".join(f"{key}: {value:,}" for key, value in counter.most_common())


def join_non_empty(values, sep=";"):
    """Join non-empty values from a group into one stable metadata string."""
    cleaned = []
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return sep.join(sorted(set(cleaned)))


def spatial_category_is_displayable(value):
    """Use shapefile category as a conservative prefilter for self display rows only."""
    categories = {
        normalize_category(part)
        for part in str(value or "").replace(",", ";").split(";")
    }
    categories.discard(None)
    if not categories:
        return True
    return bool(categories & set(TARGET_CATEGORIES))


def first_existing_column(columns, candidates):
    """Return the first matching column name, case-insensitively."""
    lower_to_original = {str(col).lower(): col for col in columns}
    for candidate in candidates:
        found = lower_to_original.get(candidate.lower())
        if found is not None:
            return found
    return None


def read_shapefile_attributes(path):
    """Read shapefile attributes without geometry when supported by the local geospatial stack."""
    try:
        return gpd.read_file(path, ignore_geometry=True)
    except TypeError:
        return gpd.read_file(path).drop(columns="geometry", errors="ignore")


def spatial_manifest_from_clean_file(clean_path, run_mode):
    """Build the API seed manifest from an already-cleaned spatial GeoJSON.

    Reads spatial_package and spatial_category columns written by clean_spatial_data.py
    pre-filter mode, applies the sample limit for sample run modes, and returns a
    manifest DataFrame in the same format as selected_spatial_manifest_for_run_mode.
    """
    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"Clean spatial file not found: {clean_path}. Run the spatial cleaning cell first.")

    os.environ["OGR_GEOJSON_MAX_OBJ_SIZE"] = "0"
    gdf = gpd.read_file(clean_path)
    required = {"taxonid", "spatial_package"}
    missing = required - set(gdf.columns)
    if missing:
        raise ValueError(f"Clean spatial file is missing columns: {missing}. Re-run spatial cleaning in pre-filter mode.")

    gdf["taxonid"] = gdf["taxonid"].astype(int)
    all_spatial_taxonids = set(gdf["taxonid"].unique())

    manifest = (
        gdf[["taxonid", "spatial_package", "spatial_category"]]
        .drop_duplicates()
        .groupby("taxonid", as_index=False)
        .agg(
            spatial_package=("spatial_package", lambda s: "; ".join(sorted(set(s.dropna().astype(str))))),
            spatial_category=("spatial_category", lambda s: next((v for v in s if pd.notna(v)), None)),
        )
        .sort_values("taxonid")
        .reset_index(drop=True)
    )

    displayable_mask = manifest["spatial_category"].map(spatial_category_is_displayable)
    missing_category = manifest["spatial_category"].fillna("").astype(str).str.strip().eq("")
    manifest = manifest[displayable_mask | missing_category].copy()

    if run_mode in ("sample_mammals", "sample_birds", "sample_fish", "sample_other"):
        manifest = manifest.head(SAMPLE_LIMIT).copy()

    manifest.attrs["all_spatial_taxonids"] = all_spatial_taxonids
    print(f"Spatial manifest from clean file: {len(manifest):,} taxa ({run_mode})")
    return manifest


def build_spatial_taxon_manifest(packages):
    """Build the API seed list from taxon IDs present in the selected spatial packages."""
    records = []
    for package in packages:
        config = SPATIAL_PACKAGE_CONFIG[package]
        paths = []
        for pattern in config["patterns"]:
            paths.extend(glob.glob(os.path.join(SPATIAL_DATA_DIR, pattern)))
        if not paths:
            print(f"Warning: no local shapefiles found for spatial package {package}")
            continue
        for path in sorted(paths):
            attrs = read_shapefile_attributes(path)
            id_col = first_existing_column(
                attrs.columns, ["id_no", "sisid", "taxonid", "taxon_id"]
            )
            if id_col is None:
                print(f"Warning: {path} has no taxon ID column; skipped")
                continue
            category_col = first_existing_column(
                attrs.columns,
                ["category", "red_list_category", "rl_category", "rlcat", "status"],
            )
            manifest_part = pd.DataFrame(
                {
                    "taxonid": pd.to_numeric(attrs[id_col], errors="coerce"),
                    "spatial_category": (
                        attrs[category_col].map(normalize_category)
                        if category_col
                        else None
                    ),
                }
            )
            manifest_part = manifest_part[manifest_part["taxonid"].notna()].copy()
            manifest_part["taxonid"] = manifest_part["taxonid"].astype(int)
            unique_taxa = manifest_part["taxonid"].nunique()
            kept_self = (
                manifest_part.groupby("taxonid")["spatial_category"]
                .agg(
                    lambda values: spatial_category_is_displayable(
                        join_non_empty(values)
                    )
                )
                .sum()
            )
            for row in manifest_part.drop_duplicates(
                subset=["taxonid", "spatial_category"]
            ).itertuples(index=False):
                records.append(
                    {
                        "taxonid": int(row.taxonid),
                        "spatial_package": package,
                        "spatial_category": row.spatial_category,
                        "spatial_manifest_file": os.path.basename(path),
                    }
                )
            if category_col:
                print(
                    f"  {package}: {os.path.basename(path)} → {unique_taxa:,} unique taxon IDs; "
                    f"{int(kept_self):,} with displayable spatial category"
                )
            else:
                print(
                    f"  {package}: {os.path.basename(path)} → {unique_taxa:,} unique taxon IDs; no spatial category column"
                )
    if not records:
        raise RuntimeError(f"No spatial taxon IDs found for packages: {packages}")
    manifest = pd.DataFrame(records)
    package_summary = manifest.groupby("taxonid", as_index=False).agg(
        spatial_package=("spatial_package", join_non_empty),
        spatial_category=("spatial_category", join_non_empty),
        spatial_manifest_file=("spatial_manifest_file", join_non_empty),
    )
    return package_summary.sort_values("taxonid").reset_index(drop=True)


def selected_spatial_manifest_for_run_mode(run_mode):
    """Return displayable spatial-package taxon seeds for the current run mode."""
    if run_mode not in RUN_MODE_SPATIAL_PACKAGES:
        raise ValueError(f"RUN_MODE must be one of {sorted(RUN_MODE_SPATIAL_PACKAGES)}")
    packages = RUN_MODE_SPATIAL_PACKAGES[run_mode]
    print(f"Spatial-package whitelist for {run_mode}: {', '.join(packages)}")
    full_manifest = build_spatial_taxon_manifest(packages)
    all_spatial_taxonids = set(full_manifest["taxonid"].astype(int))

    displayable_mask = full_manifest["spatial_category"].map(
        spatial_category_is_displayable
    )
    missing_category = (
        full_manifest["spatial_category"].fillna("").astype(str).str.strip().eq("")
    )
    manifest = full_manifest[displayable_mask].copy()
    skipped = len(full_manifest) - len(manifest)
    print(
        f"Spatial category prefilter: {len(manifest):,}/{len(full_manifest):,} taxa kept for IUCN fetch; "
        f"{skipped:,} skipped as non-displayable spatial categories; "
        f"{missing_category.sum():,} had no spatial category and were kept"
    )
    if run_mode in ("sample_mammals", "sample_birds", "sample_fish", "sample_other"):
        manifest = manifest.head(SAMPLE_LIMIT).copy()
    manifest.attrs["all_spatial_taxonids"] = all_spatial_taxonids
    print(f"Spatial whitelist taxa fetched by API: {len(manifest):,}")
    return manifest


def coerce_assessment_detail(data):
    """Accept small response-shape variations and return the assessment dict."""
    if isinstance(data, dict):
        return data.get("assessment") or data
    if isinstance(data, list) and data:
        return data[0]
    return {}


def extract_population_trend(detail):
    """Return the English IUCN population trend label when present."""
    return pick_path(
        detail,
        ("population_trend", "description", "en"),
        ("population_trend", "description"),
        ("population_trend",),
    )


def extract_number_of_mature_individuals(detail):
    """Return IUCN's raw Number of mature individuals value from supplementary info."""
    value = pick_path(
        detail,
        ("supplementary_info", "population_size"),
        ("population_size",),
    )
    if isinstance(value, str) and value.strip().lower() in {"u", "unknown"}:
        return None
    return value


def extract_estimated_area_of_occupancy(detail):
    """Return IUCN's raw Estimated Area of Occupancy value when present."""
    return pick_path(
        detail,
        ("supplementary_info", "estimated_area_of_occupancy"),
        ("estimated_area_of_occupancy",),
    )


def extract_estimated_extent_of_occurrence(detail):
    """Return IUCN's raw Estimated Extent of Occurrence value when present."""
    return pick_path(
        detail,
        ("supplementary_info", "estimated_extent_of_occurrence"),
        ("supplementary_info", "estimated_extent_of_occurence"),
        ("estimated_extent_of_occurrence",),
        ("estimated_extent_of_occurence",),
    )


def extract_common_name(taxon):
    """Extract the preferred English common name from the nested taxon object."""
    if not isinstance(taxon, dict):
        return None
    common_names = (
        pick_path(taxon, ("common_names",), ("commonNames",), ("taxon_common_names",))
        or []
    )
    if isinstance(common_names, list):
        candidates = [item for item in common_names if isinstance(item, dict)]
        main = next(
            (item for item in candidates if item.get("main") or item.get("primary")),
            None,
        )
        main = main or (candidates[0] if candidates else None)
        if main:
            return pick_path(main, ("name",), ("common_name",), ("description", "en"))
    return pick_path(taxon, ("main_common_name",), ("common_name",))


def extract_scientific_name(taxon):
    """Extract or reconstruct the scientific name from the nested taxon object."""
    if not isinstance(taxon, dict):
        return None
    name = pick_path(taxon, ("scientific_name",), ("scientificName",), ("name",))
    if name:
        return name
    parts = [
        pick_path(taxon, ("genus_name",), ("genus",)),
        pick_path(taxon, ("species_name",), ("species",)),
        pick_path(taxon, ("infra_name",), ("subspecies",)),
    ]
    return " ".join(str(part) for part in parts if part) or None


def taxon_rank_from_taxon(taxon):
    """Return the IUCN taxon rank bucket exposed by the assessment detail."""
    if not isinstance(taxon, dict):
        return "unknown"
    if bool_or_none(taxon.get("infrarank")):
        return "infrarank"
    if bool_or_none(taxon.get("subpopulation")):
        return "subpopulation"
    if bool_or_none(taxon.get("species")):
        return "species"
    return "unknown"


def taxon_ids_from_children(children):
    """Extract integer IUCN taxon IDs from nested child taxon objects."""
    ids = []
    if not isinstance(children, list):
        return ids
    for child in children:
        if not isinstance(child, dict):
            continue
        child_id = pick_path(
            child, ("sis_id",), ("sis_taxon_id",), ("taxonid",), ("id",)
        )
        try:
            ids.append(int(child_id))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


def parent_taxonid_from_taxon(taxon):
    """Best-effort parent species ID for infrarank/subpopulation taxa."""
    if not isinstance(taxon, dict):
        return None
    for key in ["species_taxa", "parent_taxa", "parent_taxon"]:
        value = taxon.get(key)
        if isinstance(value, list) and value:
            parent_id = pick_path(
                value[0], ("sis_id",), ("sis_taxon_id",), ("taxonid",), ("id",)
            )
        elif isinstance(value, dict):
            parent_id = pick_path(
                value, ("sis_id",), ("sis_taxon_id",), ("taxonid",), ("id",)
            )
        else:
            parent_id = None
        try:
            return int(parent_id)
        except (TypeError, ValueError):
            continue
    return None


def replace_species_with_available_infraranks(df):
    """Display child infraranks only when at least one child has an endangered category."""
    display_categories = {"EW", "CR", "EN", "VU", "NT"}
    if "category_iucn" in df.columns:
        display_category = df["category_iucn"]
    else:
        display_category = df["category"].replace("CD", "NT")
    displayable_ids = set(
        df.loc[display_category.isin(display_categories), "taxonid"].astype(int)
    )
    drop_parent_ids = set()
    species_without_displayable_children = 0

    for row in df.itertuples(index=False):
        if getattr(row, "taxon_rank", None) != "species":
            continue
        child_ids = getattr(row, "child_infrarank_taxonids", None) or []
        if not child_ids:
            continue
        displayable_child_ids = set(child_ids) & displayable_ids
        if displayable_child_ids:
            drop_parent_ids.add(int(row.taxonid))
        else:
            species_without_displayable_children += 1

    if drop_parent_ids:
        print(
            f"Species vs. subspecies selection: replacing {len(drop_parent_ids):,} parent species with fetched infrarank taxa that have an endangered category"
        )
        df = df[~df["taxonid"].isin(drop_parent_ids)].copy()
    if species_without_displayable_children:
        print(
            f"Species vs. subspecies selection: {species_without_displayable_children:,} species list infrarank children, but no fetched/displayable child had an endangered category; parent species kept"
        )
    return df


def fetch_assessment_detail(assessment_id):
    """Fetch the full IUCN assessment detail for one assessment id."""
    return coerce_assessment_detail(iucn_get(f"/assessment/{assessment_id}"))


def iter_assessment_candidates(data):
    """Yield assessment-like dicts from several possible IUCN taxon-id response shapes."""
    if data is None:
        return
    if isinstance(data, list):
        for item in data:
            yield from iter_assessment_candidates(item)
        return
    if not isinstance(data, dict):
        return
    if (
        data.get("assessment_id")
        or data.get("red_list_category")
        or data.get("assessment")
    ):
        yield coerce_assessment_detail(data)
    for key in ["assessment", "latest_assessment", "latest", "data", "result"]:
        value = data.get(key)
        if isinstance(value, (dict, list)):
            yield from iter_assessment_candidates(value)
    for key in ["assessments", "results", "items"]:
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                yield from iter_assessment_candidates(item)


def choose_latest_global_assessment(candidates):
    """Pick the latest global assessment candidate from a taxon-id lookup response."""
    usable = [
        item
        for item in candidates
        if isinstance(item, dict) and (item.get("assessment_id") or item.get("id"))
    ]
    if not usable:
        return None

    def score(item):
        scopes = item.get("scopes") or []
        global_scope = any(
            str(scope.get("code")) == str(GLOBAL_SCOPE_CODE)
            for scope in scopes
            if isinstance(scope, dict)
        )
        latest = bool_or_none(item.get("latest")) is not False
        return (
            global_scope,
            latest,
            str(item.get("assessment_date") or ""),
            str(item.get("year_published") or ""),
        )

    return sorted(usable, key=score, reverse=True)[0]


def fetch_latest_assessment_by_taxonid(taxonid):
    """Fetch the latest global assessment detail for one IUCN SIS taxon ID."""
    global IUCN_TAXON_ID_ENDPOINT_TEMPLATE
    params = {"latest": "true", "scope_code": GLOBAL_SCOPE_CODE}
    templates = []
    if IUCN_TAXON_ID_ENDPOINT_TEMPLATE:
        templates.append(IUCN_TAXON_ID_ENDPOINT_TEMPLATE)
    templates.extend(
        template
        for template in IUCN_TAXON_ID_ENDPOINT_CANDIDATES
        if template not in templates
    )

    last_error = None
    for template in templates:
        path = template.format(taxonid=int(taxonid))
        try:
            data = iucn_get_optional(path, params=params)
        except requests.HTTPError as exc:
            last_error = exc
            continue
        assessment = choose_latest_global_assessment(iter_assessment_candidates(data))
        if assessment:
            IUCN_TAXON_ID_ENDPOINT_TEMPLATE = template
            if (
                assessment.get("taxon")
                and assessment.get("red_list_category")
                and (
                    assessment.get("documentation")
                    or assessment.get("supplementary_info")
                )
            ):
                return coerce_assessment_detail(assessment)
            assessment_id = assessment.get("assessment_id") or assessment.get("id")
            return fetch_assessment_detail(assessment_id)
    if last_error:
        raise last_error
    return None


def assessment_to_species_row(
    assessment,
    spatial_package=None,
    spatial_category=None,
    spatial_lookup_taxonid=None,
    spatial_lookup_source="self",
):
    """Turn one IUCN assessment/detail into a display row, or return a skip reason."""
    assessment_id = assessment.get("assessment_id") or assessment.get("id")
    if not assessment_id:
        return None, "missing_assessment_id"
    try:
        assessment_id_int = int(assessment_id)
    except (TypeError, ValueError):
        return None, "invalid_assessment_id"

    detail = (
        assessment
        if isinstance(assessment, dict) and assessment.get("taxon")
        else fetch_assessment_detail(assessment_id)
    )
    if not isinstance(detail, dict) or not detail:
        return None, "empty_or_unexpected_detail"
    taxon = detail.get("taxon") if isinstance(detail.get("taxon"), dict) else {}
    taxon_class = taxon_class_from_detail(detail)
    category = normalize_category(
        pick_path(
            detail,
            ("red_list_category", "code"),
            ("red_list_category", "description", "en"),
            ("red_list_category",),
            ("category",),
            ("category_code",),
        )
    )
    if category not in TARGET_CATEGORIES:
        return None, f"detail_category_out_of_scope:{category or 'unknown'}"

    taxonid = pick_path(
        detail, ("sis_taxon_id",), ("taxon", "sis_id"), ("taxon", "sis_taxon_id")
    )
    taxonid = taxonid or assessment.get("sis_taxon_id")
    if not taxonid:
        return None, "missing_taxonid"
    try:
        taxonid_int = int(taxonid)
    except (TypeError, ValueError):
        return None, "invalid_taxonid"
    scientific_name = (
        extract_scientific_name(taxon)
        or pick_path(detail, ("scientific_name",))
        or assessment.get("taxon_scientific_name")
    )

    return {
        "taxonid": taxonid_int,
        "assessment_id": assessment_id_int,
        "assessment_date": pick_path(detail, ("assessment_date",))
        or assessment.get("assessment_date"),
        "year_published": pick_path(detail, ("year_published",))
        or assessment.get("year_published"),
        "iucn_assessment_url": pick_path(detail, ("url",)) or assessment.get("url"),
        "iucn_citation": pick_path(detail, ("citation",)) or assessment.get("citation"),
        "scientific_name": scientific_name,
        "main_common_name": extract_common_name(taxon) or extract_common_name(detail),
        "category": category,
        "population_trend": extract_population_trend(detail),
        "number_of_mature_individuals": extract_number_of_mature_individuals(detail),
        "estimated_area_of_occupancy": extract_estimated_area_of_occupancy(detail),
        "estimated_extent_of_occurrence": extract_estimated_extent_of_occurrence(
            detail
        ),
        "taxon_rank": taxon_rank_from_taxon(taxon),
        "parent_taxonid": parent_taxonid_from_taxon(taxon),
        "child_infrarank_taxonids": taxon_ids_from_children(
            taxon.get("infrarank_taxa")
        ),
        "taxon_class": taxon_class,
        "spatial_package": spatial_package,
        "spatial_category": spatial_category,
        "taxon_group": taxon_group_from_spatial_package(spatial_package),
        "spatial_lookup_taxonid": int(spatial_lookup_taxonid or taxonid_int),
        "spatial_lookup_source": spatial_lookup_source,
        "iucn_has_ranges": bool_or_none(detail.get("assessment_ranges")),
        "iucn_has_points": bool_or_none(detail.get("assessment_points")),
    }, None


def fetch_iucn_species_from_spatial_manifest(manifest):
    """Fetch display rows from displayable spatial taxa plus missing infraranks of displayable parents."""
    rows = []
    seen_taxa = set()
    detail_cache = {}
    all_spatial_taxonids = set(
        manifest.attrs.get("all_spatial_taxonids", set(manifest["taxonid"].astype(int)))
    )
    stats = Counter()
    skip_reasons = Counter()

    def get_detail(taxonid):
        taxonid = int(taxonid)
        if taxonid not in detail_cache:
            detail_cache[taxonid] = fetch_latest_assessment_by_taxonid(taxonid)
        return detail_cache[taxonid]

    def maybe_add_row(
        detail,
        spatial_package,
        spatial_category,
        spatial_lookup_taxonid,
        spatial_lookup_source,
    ):
        row, skip_reason = assessment_to_species_row(
            detail,
            spatial_package=spatial_package,
            spatial_category=spatial_category,
            spatial_lookup_taxonid=spatial_lookup_taxonid,
            spatial_lookup_source=spatial_lookup_source,
        )
        if skip_reason:
            skip_reasons[skip_reason] += 1
            return None
        if row["taxonid"] in seen_taxa:
            stats["duplicates"] += 1
            return None
        rows.append(row)
        seen_taxa.add(row["taxonid"])
        return row

    for seed in tqdm(
        manifest.itertuples(index=False),
        total=len(manifest),
        desc="Fetch IUCN from spatial IDs",
    ):
        stats["spatial_seed_taxa"] += 1
        parent_taxonid = int(seed.taxonid)
        detail = get_detail(parent_taxonid)
        if not detail:
            skip_reasons["missing_taxon_assessment"] += 1
            continue

        if not spatial_category_is_displayable(getattr(seed, "spatial_category", None)):
            stats["self_rows_prefiltered_by_spatial_category"] += 1
            continue

        parent_row = maybe_add_row(
            detail,
            seed.spatial_package,
            getattr(seed, "spatial_category", None),
            parent_taxonid,
            "self",
        )
        if not parent_row:
            stats["parents_not_displayable_for_child_discovery"] += 1
            continue

        if USE_PARENT_SPATIAL_FALLBACK:
            taxon = detail.get("taxon") if isinstance(detail.get("taxon"), dict) else {}
            child_ids = [
                child_id
                for child_id in taxon_ids_from_children(taxon.get("infrarank_taxa"))
                if child_id not in all_spatial_taxonids
            ]
            if child_ids:
                stats["display_parents_with_missing_spatial_children"] += 1
            for child_id in child_ids:
                stats["missing_spatial_child_candidates"] += 1
                child_detail = get_detail(child_id)
                if not child_detail:
                    skip_reasons["missing_child_assessment"] += 1
                    continue
                added = maybe_add_row(
                    child_detail,
                    seed.spatial_package,
                    getattr(seed, "spatial_category", None),
                    parent_taxonid,
                    "parent_species",
                )
                if added:
                    stats["display_children_using_parent_geometry"] += 1

    if not rows:
        raise RuntimeError(
            "IUCN returned no usable display taxa from the selected spatial packages."
        )
    self_rows = sum(1 for row in rows if row.get("spatial_lookup_source") == "self")
    parent_geometry_rows = sum(
        1 for row in rows if row.get("spatial_lookup_source") == "parent_species"
    )
    print("IUCN spatial-package fetch summary")
    print(f"- Spatial seed taxa fetched from API: {stats['spatial_seed_taxa']:,}")
    print(
        f"- Display rows kept: {len(rows):,} ({self_rows:,} direct shapefile taxa + {parent_geometry_rows:,} children using parent geometry)"
    )
    print(
        f"- Missing-spatial child candidates tested from displayable parents: {stats['missing_spatial_child_candidates']:,}"
    )
    print(
        f"- Missing-spatial children added with parent geometry: {stats['display_children_using_parent_geometry']:,}"
    )
    print(
        f"- Parent rows not used for child discovery after API validation: {stats['parents_not_displayable_for_child_discovery']:,}"
    )
    print(
        f"- Self rows skipped by shapefile category prefilter: {stats['self_rows_prefiltered_by_spatial_category']:,}"
    )
    print(
        f"- Child/self rows skipped after API detail: {sum(skip_reasons.values()):,} ({format_counter(skip_reasons)})"
    )
    print(f"- Duplicate rows ignored: {stats['duplicates']:,}")
    return pd.DataFrame(rows)


def load_clean_spatial_file(path, allowed_taxon_ids=None):
    """Load a cleaned spatial file, normalize required columns, and optionally filter IDs."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Run the spatial cleaning cell first: {path}")
    os.environ["OGR_GEOJSON_MAX_OBJ_SIZE"] = "0"
    gdf = gpd.read_file(path)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    required_spatial_cols = {"taxonid", "geometry"}
    missing_spatial_cols = required_spatial_cols - set(gdf.columns)
    if missing_spatial_cols:
        raise ValueError(
            f"Clean spatial file is missing columns: {sorted(missing_spatial_cols)}"
        )
    for metadata_col in [
        "source_path",
        "spatial_citation",
        "spatial_year",
        "spatial_presence",
        "spatial_seasonal",
    ]:
        if metadata_col not in gdf.columns:
            gdf[metadata_col] = None

    gdf["taxonid"] = pd.to_numeric(gdf["taxonid"], errors="coerce")
    gdf = gdf[gdf["taxonid"].notna()].copy()
    gdf["taxonid"] = gdf["taxonid"].astype(int)
    if allowed_taxon_ids is not None:
        gdf = gdf[gdf["taxonid"].isin(set(allowed_taxon_ids))].copy()
    return gdf


def polygon_parts(geometry):
    """Return every polygon component inside a geometry, recursively."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return [part for part in geometry.geoms if not part.is_empty]
    if geometry.geom_type == "GeometryCollection":
        parts = []
        for part in geometry.geoms:
            parts.extend(polygon_parts(part))
        return parts
    return []


def point_parts(geometry):
    """Return every observation point inside a geometry, recursively."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    if geometry.geom_type == "MultiPoint":
        return [part for part in geometry.geoms if not part.is_empty]
    if geometry.geom_type == "GeometryCollection":
        parts = []
        for part in geometry.geoms:
            parts.extend(point_parts(part))
        return parts
    return []


def safe_centroid(geometry):
    """Use centroid when it falls inside the shape, otherwise a guaranteed interior point."""
    centroid = geometry.centroid
    return centroid if geometry.covers(centroid) else geometry.representative_point()


def spatial_code(value):
    """Normalize numeric IUCN spatial distribution codes."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def presence_priority(value):
    """Rank presence records for representative centroid placement."""
    code = spatial_code(value)
    return PRESENCE_PRIORITY.get(code, 99)


def presence_label(value):
    """Return a readable label for a selected IUCN presence code."""
    code = spatial_code(value)
    return PRESENCE_LABELS.get(code)


def seasonal_priority(value):
    """Rank seasonal records for representative centroid placement."""
    code = spatial_code(value)
    return SEASONAL_PRIORITY.get(code, 99)


def seasonal_label(value):
    """Return a readable label for a selected IUCN seasonal code."""
    code = spatial_code(value)
    return SEASONAL_LABELS.get(code)


def best_presence_records(gdf):
    """Keep records from the best available presence bucket per taxon."""
    if gdf.empty or "spatial_presence" not in gdf.columns:
        return gdf.copy()
    ranked = gdf.copy()
    ranked["_presence_priority"] = ranked["spatial_presence"].map(presence_priority)
    best = ranked.groupby("taxonid")["_presence_priority"].transform("min")
    return ranked[ranked["_presence_priority"] == best].drop(
        columns="_presence_priority"
    )


def best_seasonal_records(gdf):
    """Keep records from the best available season per taxon: resident, breeding, non-breeding, passage, uncertain."""
    if gdf.empty or "spatial_seasonal" not in gdf.columns:
        return gdf.copy()
    ranked = gdf.copy()
    ranked["_seasonal_priority"] = ranked["spatial_seasonal"].map(seasonal_priority)
    best = ranked.groupby("taxonid")["_seasonal_priority"].transform("min")
    return ranked[ranked["_seasonal_priority"] == best].drop(
        columns="_seasonal_priority"
    )


def first_non_empty(values):
    """Return the first non-empty value in a pandas group."""
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if text:
            return text
    return None


def latest_year(values):
    """Return the latest numeric year found in a pandas group, as text."""
    years = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return str(int(years.max())) if not years.empty else None


def build_spatial_credit(citation, year):
    """Format IUCN's required spatial-data credit for one species or dataset."""
    citation = first_non_empty([citation])
    year = first_non_empty([year])
    if citation:
        prefix = citation.rstrip(". ")
        if year and year not in prefix:
            prefix = f"{prefix} {year}"
        return f"{prefix}. The IUCN Red List of Threatened Species. Version {IUCN_RED_LIST_VERSION}. https://www.iucnredlist.org. Downloaded on {SPATIAL_DATA_DOWNLOAD_DATE}."
    return IUCN_DATASET_CITATION


def cluster_range_parts(parts, buffer_km):
    """Group nearby disjoint range components by intersecting metric buffers."""
    part_gdf = gpd.GeoDataFrame(
        {"geometry": parts}, geometry="geometry", crs="EPSG:4326"
    )
    metric = part_gdf.to_crs(6933)
    metric["geometry"] = metric["geometry"].apply(make_valid)
    metric["part_index"] = range(len(metric))
    metric["area_km2"] = metric.area / 1e6
    metric["buffer_geometry"] = metric.geometry.buffer(buffer_km * 1000)

    idx_list = list(range(len(metric)))
    buffer_list = metric["buffer_geometry"].tolist()
    tree = STRtree(buffer_list)

    clusters = []
    remaining = set(idx_list)
    while remaining:
        seed = remaining.pop()
        cluster = {seed}
        frontier = {seed}
        while frontier:
            current = frontier.pop()
            candidates = tree.query(buffer_list[current], predicate="intersects")
            touching = {int(c) for c in candidates if int(c) in remaining}
            remaining -= touching
            frontier |= touching
            cluster |= touching
        clusters.append(cluster)

    rows = []
    for cluster_id, part_indexes in enumerate(clusters, start=1):
        cluster_metric = metric[metric["part_index"].isin(part_indexes)].copy()
        cluster_geometry_metric = unary_union(cluster_metric.geometry.tolist())
        cluster_geometry = (
            gpd.GeoSeries([cluster_geometry_metric], crs=6933).to_crs(4326).iloc[0]
        )
        rows.append(
            {
                "cluster_id": cluster_id,
                "geometry": cluster_geometry,
                "cluster_area_km2": float(cluster_metric["area_km2"].sum()),
                "cluster_component_count": len(part_indexes),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def build_sparql_query(iucn_ids):
    """Batch SPARQL: resolve IUCN taxon IDs to Wikipedia sitelinks and Wikidata images."""
    values = " ".join(f'"{i}"' for i in iucn_ids)
    return f"""
SELECT ?iucn_id ?taxon ?article ?article_lang ?wiki_project ?article_title ?wikidata_image_url WHERE {{
  VALUES ?iucn_id {{ {values} }}
  ?taxon wdt:P627 ?iucn_id .          # P627 = IUCN taxon ID
  OPTIONAL {{ ?taxon wdt:P18 ?wikidata_image_url . }} # P18 = image
  ?article schema:about ?taxon ;
            schema:inLanguage ?article_lang ;
            schema:isPartOf ?wiki_site .
  FILTER(CONTAINS(STR(?wiki_site), ".wikipedia.org/"))
  BIND(REPLACE(STR(?wiki_site), "^https?://", "") AS ?wiki_project_slash)
  BIND(REPLACE(?wiki_project_slash, "/$", "") AS ?wiki_project)
  BIND(REPLACE(STR(?article), CONCAT("https://", ?wiki_project, "/wiki/"), "") AS ?article_title)
}}
"""


def article_rank(article_lang):
    """Rank Wikipedia languages; any unlisted language remains usable after the preferred list."""
    return WIKIPEDIA_LANGUAGE_RANK.get(
        str(article_lang), len(WIKIPEDIA_LANGUAGE_PRIORITY)
    )


def query_wikidata_batch(iucn_ids, batch_size=500):
    """Run SPARQL in batches to avoid query size limits."""
    mapping = {}
    ids = list(map(str, iucn_ids))
    for i in tqdm(range(0, len(ids), batch_size), desc="Wikidata batches"):
        batch = ids[i : i + batch_size]
        sparql = build_sparql_query(batch)
        r = requests.post(
            WIKIDATA_ENDPOINT,
            data={"query": sparql},
            headers={**wikimedia_headers(), "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/sparql-results+json"},
            timeout=60,
        )
        r.raise_for_status()
        for row in r.json()["results"]["bindings"]:
            iid = row["iucn_id"]["value"]
            wikidata_url = row["taxon"]["value"].replace("http://", "https://", 1)
            title = urllib.parse.unquote(row["article_title"]["value"])
            lang = row["article_lang"]["value"]
            project = row["wiki_project"]["value"]
            article_url = row["article"]["value"]
            rank = article_rank(lang)
            entry = mapping.setdefault(
                iid,
                {
                    "wikidata_url": wikidata_url,
                    "wiki_title": title,
                    "wiki_language": lang,
                    "wiki_project": project,
                    "wiki_url": article_url,
                    "wiki_rank": rank,
                    "wikidata_image_url": None,
                },
            )
            if rank < entry.get("wiki_rank", 999):
                entry.update(
                    {
                        "wiki_title": title,
                        "wiki_language": lang,
                        "wiki_project": project,
                        "wiki_url": article_url,
                        "wiki_rank": rank,
                    }
                )
            image = row.get("wikidata_image_url", {}).get("value")
            if image and not entry["wikidata_image_url"]:
                entry["wikidata_image_url"] = image.replace("http://", "https://", 1)
        time.sleep(1.0)  # Wikidata rate limit: be gentle
    return mapping


def scientific_name_variants(name):
    """Return P225 lookup candidates for a scientific name.

    IUCN writes subspecies as 'Genus species ssp. subspecies'; Wikidata P225 uses
    either the bare trinomial ('Genus species subspecies') or the formal 'subsp.' form.
    We try all three so both conventions are covered.
    """
    variants = [name]
    if " ssp. " in name:
        variants.append(name.replace(" ssp. ", " "))  # bare trinomial
        variants.append(name.replace(" ssp. ", " subsp. "))  # formal subsp.
    return variants


def build_sparql_name_query(sci_names):
    """Fallback SPARQL: find Wikidata items by exact scientific name (P225)."""
    values = " ".join(f'"{name}"' for name in sci_names)
    return f"""
SELECT ?sci_name_match ?taxon ?article ?article_lang ?wiki_project ?article_title ?wikidata_image_url WHERE {{
  VALUES ?sci_name_match {{ {values} }}
  ?taxon wdt:P225 ?sci_name_match .
  OPTIONAL {{ ?taxon wdt:P18 ?wikidata_image_url . }}
  ?article schema:about ?taxon ;
            schema:inLanguage ?article_lang ;
            schema:isPartOf ?wiki_site .
  FILTER(CONTAINS(STR(?wiki_site), ".wikipedia.org/"))
  BIND(REPLACE(STR(?wiki_site), "^https?://", "") AS ?wiki_project_slash)
  BIND(REPLACE(?wiki_project_slash, "/$", "") AS ?wiki_project)
  BIND(REPLACE(STR(?article), CONCAT("https://", ?wiki_project, "/wiki/"), "") AS ?article_title)
}}
"""


def build_sparql_qid_query(qids):
    """SPARQL to get Wikipedia sitelinks for a known list of Wikidata QIDs."""
    values = " ".join(f"wd:{qid}" for qid in qids)
    return f"""
SELECT ?taxon ?article ?article_lang ?wiki_project ?article_title ?wikidata_image_url WHERE {{
  VALUES ?taxon {{ {values} }}
  OPTIONAL {{ ?taxon wdt:P18 ?wikidata_image_url . }}
  ?article schema:about ?taxon ;
            schema:inLanguage ?article_lang ;
            schema:isPartOf ?wiki_site .
  FILTER(CONTAINS(STR(?wiki_site), ".wikipedia.org/"))
  BIND(REPLACE(STR(?wiki_site), "^https?://", "") AS ?wiki_project_slash)
  BIND(REPLACE(?wiki_project_slash, "/$", "") AS ?wiki_project)
  BIND(REPLACE(STR(?article), CONCAT("https://", ?wiki_project, "/wiki/"), "") AS ?article_title)
}}
"""


def _wikidata_entry_from_sparql_row(row):
    """Build a wikidata_map entry dict from one SPARQL result row."""
    wikidata_url = row["taxon"]["value"].replace("http://", "https://", 1)
    title = urllib.parse.unquote(row["article_title"]["value"])
    lang = row["article_lang"]["value"]
    project = row["wiki_project"]["value"]
    article_url = row["article"]["value"]
    image = (row.get("wikidata_image_url") or {}).get("value")
    return {
        "wikidata_url": wikidata_url,
        "wiki_title": title,
        "wiki_language": lang,
        "wiki_project": project,
        "wiki_url": article_url,
        "wiki_rank": article_rank(lang),
        "wikidata_image_url": (
            image.replace("http://", "https://", 1) if image else None
        ),
    }


def _merge_entry(mapping, iid, candidate):
    """Merge a candidate entry into mapping, keeping the best-ranked language."""
    existing = mapping.get(iid)
    if existing is None:
        mapping[iid] = candidate
    else:
        if candidate["wiki_rank"] < existing["wiki_rank"]:
            existing.update(
                {
                    k: candidate[k]
                    for k in (
                        "wiki_title",
                        "wiki_language",
                        "wiki_project",
                        "wiki_url",
                        "wiki_rank",
                    )
                }
            )
        if candidate["wikidata_image_url"] and not existing["wikidata_image_url"]:
            existing["wikidata_image_url"] = candidate["wikidata_image_url"]


def wikidata_entity_search(search_term, retries=3):
    """Search Wikidata by label and return a mapping entry if a Wikipedia sitelink is found.

    Retries with exponential backoff on 429 rate-limit responses.
    """
    for attempt in range(retries):
        try:
            r = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "search": search_term,
                    "language": "en",
                    "type": "item",
                    "format": "json",
                    "limit": 5,
                },
                headers=wikimedia_headers(),
                timeout=15,
            )
            if r.status_code == 429:
                wait = wikimedia_retry_after(r, default=2**attempt * 3)
                print(f"\n  [Pass 2 wbsearchentities] 429 — waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        except requests.exceptions.Timeout:
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt * 2)
    else:
        return None

    qids = [hit["id"] for hit in r.json().get("search", [])]
    if not qids:
        return None

    sparql = build_sparql_qid_query(qids)
    for attempt in range(retries):
        r2 = requests.post(
            WIKIDATA_ENDPOINT,
            data={"query": sparql},
            headers={**wikimedia_headers(), "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/sparql-results+json"},
            timeout=30,
        )
        if r2.status_code == 429:
            wait = wikimedia_retry_after(r2, default=2**attempt * 3)
            print(f"\n  [Pass 2 SPARQL] 429 — waiting {wait}s", flush=True)
            time.sleep(wait)
            continue
        r2.raise_for_status()
        break
    else:
        return None
    rows = r2.json()["results"]["bindings"]
    if not rows:
        return None
    best = min(rows, key=lambda row: article_rank(row["article_lang"]["value"]))
    return _wikidata_entry_from_sparql_row(best)


def query_wikidata_by_names(unresolved_taxonids, df, cache_path=None):
    """Retry Wikidata lookup by scientific name for taxa not resolved by IUCN taxon ID.

    Pass 1 — P225 batch query with ssp./subsp. normalization for subspecies names.
    Pass 2 — wbsearchentities entity search for taxa still missing after Pass 1.

    cache_path: optional JSON file; already-resolved taxa are skipped and results
    are written incrementally so the run can be resumed after an interruption.

    Returns a {str(taxonid): entry} dict ready to merge into wikidata_map.
    """
    if not unresolved_taxonids:
        return {}

    # ── Load cache ───────────────────────────────────────────────────────────────
    mapping = {}        # taxonid → found entry
    not_found_cached = set()  # taxonids confirmed not found in a previous run
    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as _f:
                    _raw = json.load(_f)
                for _k, _v in _raw.items():
                    if _v.get("not_found"):
                        not_found_cached.add(_k)
                    else:
                        mapping[_k] = _v
                print(f"  Wikidata name cache: {len(mapping)} found + {len(not_found_cached)} not-found entries loaded from {cache_path}")
            except Exception as _e:
                print(f"  Warning: could not read cache {cache_path}: {_e}")

    def _save_cache():
        if not cache_path:
            return
        try:
            with open(cache_path, "w") as _f:
                json.dump({**mapping, **{k: {"not_found": True} for k in not_found_cached}}, _f)
        except Exception as _e:
            print(f"  Warning: could not save cache: {_e}")

    unresolved_set = {str(t) for t in unresolved_taxonids if str(t) not in mapping and str(t) not in not_found_cached}
    if not unresolved_set:
        print(f"  All taxa already in cache ({len(mapping)} found, {len(not_found_cached)} not-found) — nothing to fetch")
        return mapping

    unresolved_rows = df[
        df["taxonid"].astype(str).isin(unresolved_set)
    ].drop_duplicates(subset="taxonid")

    # Build variant → taxonid mapping (one IUCN name can expand to 2–3 P225 candidates)
    variant_to_taxonids = {}
    canonical_name = {}  # variant → original IUCN name for reporting
    for _, row in unresolved_rows.iterrows():
        name = clean_str(row.get("scientific_name"))
        if not name:
            continue
        iid = str(row["taxonid"])
        for variant in scientific_name_variants(name):
            variant_to_taxonids.setdefault(variant, []).append(iid)
            canonical_name[variant] = name

    if not variant_to_taxonids:
        return {}

    all_variants = list(variant_to_taxonids.keys())
    print(f"Wikidata name fallback: {len(unresolved_set)} unique taxa unresolved")

    # ── Pass 1: P225 batch query ────────────────────────────────────────────────
    _mapping_before_p1 = len(mapping)
    batch_size = 100
    for i in range(0, len(all_variants), batch_size):
        batch = all_variants[i : i + batch_size]
        sparql = build_sparql_name_query(batch)
        batch_num = i // batch_size + 1
        for attempt in range(5):
            try:
                r = requests.post(
                    WIKIDATA_ENDPOINT,
                    data={"query": sparql},
                    headers={**wikimedia_headers(), "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/sparql-results+json"},
                    timeout=30,
                )
            except Exception as e:
                print(f"  P225 batch {batch_num} attempt {attempt+1} error: {e}")
                time.sleep(2 ** attempt * 2)
                continue
            if r.status_code == 429:
                wait = wikimedia_retry_after(r, default=2 ** attempt * 10)
                print(f"  [P225 SPARQL] 429 — waiting {wait}s (batch {batch_num}, attempt {attempt+1}/5)")
                time.sleep(wait)
                continue
            try:
                r.raise_for_status()
            except Exception as e:
                print(f"  P225 batch {batch_num} failed: {e}")
                break
            for row in r.json()["results"]["bindings"]:
                matched_variant = row["sci_name_match"]["value"]
                entry = _wikidata_entry_from_sparql_row(row)
                for iid in variant_to_taxonids.get(matched_variant, []):
                    _merge_entry(mapping, iid, entry)
            _save_cache()
            break
        time.sleep(1.0)

    # ── Passes 2–4: per-taxon sequential fallback ────────────────────────────────
    _p1_resolved = len(mapping) - _mapping_before_p1
    print(f"  Pass 1 (P225): resolved {_p1_resolved} / {len(unresolved_set)} — {len(unresolved_set) - _p1_resolved} remaining for per-taxon search")
    # For each taxon not resolved by P225, try wbsearchentities → Wikipedia direct
    # not-found once all three options are exhausted.
    pending_rows = unresolved_rows[~unresolved_rows["taxonid"].astype(str).isin(mapping.keys())]
    http_retry_rows = []

    for i, (_, row) in enumerate(pending_rows.iterrows(), 1):
        sci_name = clean_str(row.get("scientific_name"))
        common_name = clean_str(row.get("main_common_name"))
        iid = str(row["taxonid"])
        print(f"  [{i}/{len(pending_rows)}] {sci_name}", end=" ...", flush=True)

        entry = None
        http_error = False

        # Pass 2: wbsearchentities
        for search_term in filter(None, [sci_name, common_name]):
            try:
                entry = wikidata_entity_search(search_term)
            except requests.exceptions.RequestException as e:
                print(f" [wbsearch HTTP error: {e}]", end="", flush=True)
                http_error = True
            except Exception as e:
                print(f" [wbsearch error: {e}]", end="", flush=True)
            finally:
                time.sleep(3.0)
            if entry:
                break

        # Pass 3: Wikipedia direct title lookup
        if not entry:
            for search_term in filter(None, [sci_name, common_name]):
                try:
                    entry = wikipedia_direct_search(search_term)
                except requests.exceptions.RequestException as e:
                    print(f" [wiki HTTP error: {e}]", end="", flush=True)
                    http_error = True
                except Exception as e:
                    print(f" [wiki error: {e}]", end="", flush=True)
                finally:
                    time.sleep(SLEEP_WIKI * 10)
                if entry:
                    break

        # Pass 4: Wikispecies
        if not entry and sci_name:
            entry = search_wikispecies(sci_name)
            time.sleep(SLEEP_WIKI * 10)

        # Outcome
        if entry:
            print(" found", flush=True)
            _merge_entry(mapping, iid, entry)
            _save_cache()
        elif http_error:
            print(" http error — will retry", flush=True)
            http_retry_rows.append(row)
        else:
            print(" not found", flush=True)
            not_found_cached.add(iid)
            _save_cache()

    # ── HTTP retry: one final attempt for taxa that HTTP-errored above ────────────
    if http_retry_rows:
        print(f"HTTP retry: {len(http_retry_rows)} taxa")
        time.sleep(5.0)
        for row in http_retry_rows:
            sci_name = clean_str(row.get("scientific_name"))
            common_name = clean_str(row.get("main_common_name"))
            iid = str(row["taxonid"])
            if iid in mapping:
                continue
            print(f"  retry {sci_name}", end=" ...", flush=True)
            entry = None
            for search_term in filter(None, [sci_name, common_name]):
                for fn in [wikidata_entity_search, wikipedia_direct_search]:
                    try:
                        entry = fn(search_term)
                    except Exception:
                        pass
                    finally:
                        time.sleep(3.0)
                    if entry:
                        break
                if entry:
                    break
            if not entry and sci_name:
                try:
                    entry = search_wikispecies(sci_name)
                except Exception:
                    pass
                finally:
                    time.sleep(SLEEP_WIKI * 10)
            print(" found" if entry else " not found", flush=True)
            if entry:
                _merge_entry(mapping, iid, entry)
            else:
                not_found_cached.add(iid)
            _save_cache()

    # ── Summary ─────────────────────────────────────────────────────────────────
    if mapping:
        print("  Resolved:")
        for _, row in unresolved_rows.iterrows():
            iid = str(row["taxonid"])
            if iid not in mapping:
                continue
            entry = mapping[iid]
            sci = row.get("scientific_name", "")
            wiki_title = entry.get("wiki_title", "—")
            wikidata_url = entry.get("wikidata_url", "—")
            wiki_url = entry.get("wiki_url", "—")
            print(f"    {sci}  →  {wiki_title}  |  {wikidata_url}  |  {wiki_url}")

    still_missing_names = sorted(
        {
            str(row.get("scientific_name", ""))
            for _, row in unresolved_rows.iterrows()
            if str(row["taxonid"]) not in mapping
        }
    )
    if still_missing_names:
        print(f"  Still missing after all fallbacks (Wikidata P225, entity search, Wikipedia direct): {still_missing_names}")
    return mapping  # found entries only; not_found_cached is persisted in the cache file


def search_wikispecies(scientific_name, retries=3):
    """Check if a Wikispecies article exists for a scientific name.

    Returns a wikidata_map-compatible entry dict or None.
    """
    title = scientific_name.strip()
    for attempt in range(retries):
        try:
            r = requests.get(
                "https://species.wikimedia.org/w/api.php",
                params={"action": "query", "titles": title, "redirects": 1, "format": "json"},
                headers=wikimedia_headers(),
                timeout=15,
            )
            if r.status_code == 429:
                wait = wikimedia_retry_after(r, default=2 ** attempt * 3)
                print(f"\n  [Pass 4 Wikispecies] 429 — waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        except requests.exceptions.Timeout:
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt * 2)
    else:
        return None

    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        if page.get("pageid") and page.get("pageid") != -1:
            resolved_title = page.get("title", title)
            encoded = urllib.parse.quote(resolved_title.replace(" ", "_"), safe="")
            return {
                "wiki_title": resolved_title,
                "wiki_project": "species.wikimedia.org",
                "wiki_language": "en",
                "wiki_url": f"https://species.wikimedia.org/wiki/{encoded}",
                "wikidata_url": None,
                "wikidata_image_url": None,
            }
    return None


def search_inaturalist_image(scientific_name, retries=3):
    """Search iNaturalist taxa API for a photo (CC-licensed or all-rights-reserved).

    Returns (image_url, attribution, license_code, inat_url) or (None, None, None, None).
    All-rights-reserved photos are included — callers must display attribution and link back.
    """
    for attempt in range(retries):
        try:
            r = requests.get(
                "https://api.inaturalist.org/v1/taxa",
                params={"q": scientific_name, "rank": "species,subspecies", "per_page": 1, "is_active": "true"},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            if r.status_code == 429:
                wait = 2 ** attempt * 3
                tqdm.write(f"  [iNaturalist] 429 for {scientific_name!r} — waiting {wait}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        except requests.exceptions.Timeout:
            tqdm.write(f"  [iNaturalist] timeout for {scientific_name!r} (attempt {attempt + 1}/{retries})")
            if attempt == retries - 1:
                return None, None, None, None
            time.sleep(2 ** attempt * 2)
        except Exception as e:
            tqdm.write(f"  [iNaturalist] error for {scientific_name!r}: {e}")
            return None, None, None, None
    else:
        tqdm.write(f"  [iNaturalist] gave up after {retries} retries for {scientific_name!r}")
        return None, None, None, None

    results = r.json().get("results", [])
    if not results:
        return None, None, None, None

    taxon = results[0]
    matched_name = (taxon.get("name") or "").lower()
    if scientific_name.lower().split()[0] not in matched_name:
        return None, None, None, None

    photo = taxon.get("default_photo")
    if not photo:
        return None, None, None, None

    taxon_id = taxon.get("id")
    taxon_slug = (taxon.get("name") or "").replace(" ", "-")
    inat_url = f"https://www.inaturalist.org/taxa/{taxon_id}-{taxon_slug}" if taxon_id else None

    image_url = photo.get("medium_url") or photo.get("url")
    attribution = re.sub(r",?\s*uploaded by [^,)]+", "", photo.get("attribution", "")).strip()
    license_code = (photo.get("license_code") or "all rights reserved").lower()
    return image_url, attribution, license_code, inat_url


def wikipedia_direct_search(search_term, lang="en", retries=3):
    """Check if a Wikipedia page exists for search_term (resolving redirects). Returns an entry dict or None."""
    for attempt in range(retries):
        try:
            r = requests.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "titles": search_term, "redirects": True, "format": "json"},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            if r.status_code == 429:
                wait = wikimedia_retry_after(r, default=2 ** attempt * 3)
                print(f"\n  [Pass 3 Wikipedia direct] 429 — waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        except requests.exceptions.Timeout:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 2)
    else:
        return None

    pages = r.json().get("query", {}).get("pages", {})
    for page_id, page in pages.items():
        if page_id == "-1":
            return None
        resolved_title = page.get("title", search_term)
        project = f"{lang}.wikipedia.org"
        wiki_url = f"https://{project}/wiki/{urllib.parse.quote(resolved_title.replace(' ', '_'))}"
        return {
            "wiki_title": resolved_title,
            "wiki_language": lang,
            "wiki_project": project,
            "wiki_url": wiki_url,
            "wikidata_url": None,
            "wikidata_image_url": None,
            "wiki_rank": article_rank(lang),
        }
    return None


def log_dropped(dropped_log, ids_before, ids_after, stage, reason, ref_df=None):
    """Append dropped taxa to dropped_log with metadata from ref_df when available."""
    lost = set(int(x) for x in ids_before) - set(int(x) for x in ids_after)
    if not lost:
        return
    for tid in lost:
        row = {"taxonid": tid, "drop_stage": stage, "drop_reason": reason,
               "scientific_name": None, "main_common_name": None,
               "category_iucn": None, "taxon_group": None}
        if ref_df is not None and not ref_df.empty:
            match = ref_df[ref_df["taxonid"].astype(int) == tid]
            if not match.empty:
                r = match.iloc[0]
                row["scientific_name"] = r.get("scientific_name")
                row["main_common_name"] = r.get("main_common_name")
                row["category_iucn"] = r.get("category_iucn") or r.get("category")
                row["taxon_group"] = r.get("taxon_group")
        dropped_log.append(row)
    print(f"  [{stage}] {len(lost)} taxa dropped: {reason}")


def get_pageviews(project, title, retries=4):
    """Return total Wikipedia views over the last 12 months for one project/title, or 0 on error."""
    encoded = urllib.parse.quote(title, safe="")
    project = project or "en.wikipedia.org"
    url = f"{PAGEVIEWS_BASE}/{project}/all-access/{PAGEVIEWS_AGENT}/{encoded}/monthly/{START}/{END}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=wikimedia_headers(), timeout=15)
            if r.status_code == 404:
                return 0
            if r.status_code == 429:
                wait = wikimedia_retry_after(r, default=30)
                tqdm.write(f"  [pageviews] 429 for {title!r} — waiting {wait}s then retrying")
                time.sleep(wait)
                continue
            if not r.ok:
                tqdm.write(f"  [pageviews] HTTP {r.status_code} for {title!r}")
                return 0
            items = r.json().get("items", [])
            return sum(item["views"] for item in items)
        except Exception as e:
            tqdm.write(f"  [pageviews] error for {title!r}: {e}")
            return 0
    tqdm.write(f"  [pageviews] gave up after {retries} retries for {title!r}")
    return 0


def get_wikipedia_thumbnail(project, title, retries=4):
    """Return a Wikipedia thumbnail/original image URL for a page title, or None.

    Uses the per-language rest_v1 summary endpoint which reliably returns
    originalimage and thumbnail fields. The Bearer token is not sent here as
    this endpoint is on the per-language domain, not api.wikimedia.org.
    """
    project = project or "en.wikipedia.org"
    encoded = urllib.parse.quote(title, safe="")
    url = WIKIPEDIA_SUMMARY_URL.format(project=project, title=encoded)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                wait = wikimedia_retry_after(r, default=2 ** attempt * 5)
                tqdm.write(f"  [thumbnail] 429 — waiting {wait}s for {url}")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            image = pick_path(data, ("originalimage", "source"), ("thumbnail", "source"))
            return image.replace("http://", "https://", 1) if image else None
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt * 2)
    return None


def clean_commons_metadata(value):
    """Convert Commons extmetadata HTML-ish fields to compact plain text."""
    if not value:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def commons_metadata_value(extmetadata, key):
    """Read one Wikimedia Commons extmetadata value by key."""
    value = (
        (extmetadata.get(key) or {}).get("value")
        if isinstance(extmetadata, dict)
        else None
    )
    return clean_commons_metadata(value)


def commons_search_terms(scientific_name, common_name):
    """Return cautious Commons search terms, preferring exact scientific-name matches."""
    terms = []
    if scientific_name and isinstance(scientific_name, str) and scientific_name.strip():
        terms.append(("scientific_name", f'"{scientific_name.strip()}"'))
    if common_name and isinstance(common_name, str) and common_name.strip():
        terms.append(("common_name", f'"{common_name.strip()}"'))
    return terms


def wikimedia_filename(url):
    """Extract and normalise the canonical filename from any Wikimedia image URL.

    Strips path prefixes, thumbnail size suffixes, URL encoding, copy-number
    suffixes (e.g. ' (1)'), and lowercases for comparison.
    """
    if not url:
        return ""
    decoded = urllib.parse.unquote(str(url)).replace("_", " ").lower()
    decoded = re.sub(r"/\d+px-", "/", decoded)
    filename = decoded.rstrip("/").split("/")[-1]
    filename = re.sub(r"^special:filepath/", "", filename)
    filename = re.sub(r" \(\d+\)(\.[^.]+)$", r"\1", filename)  # strip " (2).jpg"
    filename = re.sub(r" \d+(\.[^.]+)$", r"\1", filename)       # strip " 2.jpg"
    # Strip common editing suffixes before the extension (edit, crop, cropped, edited, etc.)
    _edit_pattern = re.compile(r"[ _-](?:edit(?:ed)?|crop(?:ped)?)(\.[^.]+)$")
    while True:
        new = _edit_pattern.sub(r"\1", filename)
        if new == filename:
            break
        filename = new
    return filename.strip()


def wikimedia_tiff_to_thumbnail(url, width=800):
    """Convert a Wikimedia Commons TIFF URL to its JPEG thumbnail equivalent.

    Handles two URL formats:
    - Special:FilePath: commons.wikimedia.org/wiki/Special:FilePath/File.tif
      → append ?width=800 (Wikimedia serves a JPEG at that width)
    - upload.wikimedia.org: .../commons/a/bc/File.tif
      → .../commons/thumb/a/bc/File.tif/800px-File.jpg
    """
    if not url or not isinstance(url, str):
        return url
    lower = url.lower().split("?")[0]
    if not (lower.endswith(".tif") or lower.endswith(".tiff")):
        return url

    # Special:FilePath format
    if "Special:FilePath" in url or "special:filepath" in url.lower():
        base = url.split("?")[0]
        return f"{base}?width={width}"

    # upload.wikimedia.org format
    if "upload.wikimedia.org" not in url or "/thumb/" in url:
        return url
    parts = url.split("/")
    filename = parts[-1]
    basename = filename.rsplit(".", 1)[0]
    thumb_parts = parts[:]
    idx = next((i + 1 for i, p in enumerate(thumb_parts) if p == "commons"), None)
    if idx is None:
        return url
    thumb_parts.insert(idx, "thumb")
    thumb_parts.append(f"{width}px-{basename}.jpg")
    return "/".join(thumb_parts)


def is_probable_range_map_title(value, scientific_name=None, common_name=None):
    """Reject image titles or URLs that likely describe a range/distribution map, not the animal.

    A token match is ignored when the same token appears in the species' scientific or common name
    — e.g. 'Varzea Piculet' contains 'area', 'Range frog' contains 'range'.
    """
    normalized = urllib.parse.unquote(str(value or "")).lower().replace("_", " ")
    sci = str(scientific_name).lower() if scientific_name and not isinstance(scientific_name, float) else ""
    common = str(common_name).lower() if common_name and not isinstance(common_name, float) else ""
    for token in ["distrib", "extent", "area", "map"]:
        if token in normalized and token not in sci and token not in common:
            return True
    for pattern in [r'\brange', r'\bzon']:
        if re.search(pattern, normalized) and not re.search(pattern, sci) and not re.search(pattern, common):
            return True
    return False


def search_commons_image(scientific_name, common_name):
    """Find the first usable Wikimedia Commons bitmap image, with attribution metadata when available."""
    for search_source, search_term in commons_search_terms(
        scientific_name, common_name
    ):
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": search_term,
            "gsrnamespace": 6,
            "gsrlimit": 10,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 900,
            "format": "json",
            "formatversion": 2,
        }
        try:
            r = requests.get(
                COMMONS_API_URL,
                params=params,
                headers=wikimedia_headers(),
                timeout=20,
            )
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", [])
        except Exception:
            continue
        for page in pages:
            if is_probable_range_map_title(page.get("title")):
                tqdm.write(f"  [Commons] excluded (map-like title): {page.get('title')!r} for {scientific_name!r}")
                continue
            imageinfo = (page.get("imageinfo") or [{}])[0]
            mime = imageinfo.get("mime")
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            image_url = imageinfo.get("thumburl") or imageinfo.get("url")
            if not image_url or is_probable_range_map_title(image_url):
                tqdm.write(f"  [Commons] excluded (map-like URL): {image_url!r} for {scientific_name!r}")
                continue
            extmetadata = imageinfo.get("extmetadata") or {}
            return {
                "commons_image_url": image_url.replace("http://", "https://", 1),
                "commons_image_page_url": imageinfo.get("descriptionurl"),
                "commons_image_title": page.get("title"),
                "commons_image_author": commons_metadata_value(extmetadata, "Artist"),
                "commons_image_license": commons_metadata_value(
                    extmetadata, "LicenseShortName"
                )
                or commons_metadata_value(extmetadata, "UsageTerms"),
                "commons_image_license_url": commons_metadata_value(
                    extmetadata, "LicenseUrl"
                ),
                "commons_image_credit": commons_metadata_value(extmetadata, "Credit"),
                "commons_image_search_source": search_source,
                "commons_image_search_term": search_term,
            }
    return {}


def ensure_wikidata_entries(iucn_ids):
    """Query Wikidata only for lookup IDs not already present in wikidata_map."""
    ids = sorted({int(value) for value in iucn_ids if pd.notna(value)})
    missing_ids = [taxonid for taxonid in ids if str(taxonid) not in wikidata_map]
    if missing_ids:
        wikidata_map.update(query_wikidata_batch(missing_ids))


def wikidata_entry_for_id(taxonid):
    """Return one cached Wikidata mapping entry for a numeric IUCN taxon ID."""
    if pd.isna(taxonid):
        return {}
    return wikidata_map.get(str(int(taxonid))) or {}


def apply_wikidata_entry_to_mask(frame, mask, taxonid_series, source_label):
    """Replace article/image lookup fields for rows selected by mask using a taxonid series."""
    for field in WIKIDATA_FIELDS:
        frame.loc[mask, field] = taxonid_series[mask].map(
            lambda taxonid: wikidata_entry_for_id(taxonid).get(field)
        )
    frame.loc[mask, "wiki_lookup_taxonid"] = taxonid_series[mask].astype(int)
    frame.loc[mask, "wiki_lookup_source"] = source_label


def clean_json_value(value):
    """Convert pandas/numpy nulls and scalar values into JSON-safe Python values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item") and not isinstance(value, str):
        try:
            return value.item()
        except Exception:
            pass
    return value


def feature_properties(row):
    """Build the shared GeoJSON properties for centroid and spatial features."""
    return {
        "taxonid": int(row.taxonid),
        "assessment_id": int(row.assessment_id),
        "assessment_date": clean_json_value(row.assessment_date),
        "year_published": clean_json_value(row.year_published),
        "iucn_assessment_url": clean_json_value(row.iucn_assessment_url),
        "iucn_citation": clean_json_value(row.iucn_citation),
        "wiki_title": clean_json_value(row.wiki_title),
        "wiki_language": clean_json_value(row.wiki_language),
        "wiki_project": clean_json_value(row.wiki_project),
        "wiki_url": clean_json_value(row.wiki_url),
        "wikidata_url": clean_json_value(row.wikidata_url),
        "wikidata_image_url": clean_json_value(row.wikidata_image_url),
        "wiki_lookup_taxonid": clean_json_value(
            getattr(row, "wiki_lookup_taxonid", None)
        ),
        "wiki_lookup_source": clean_json_value(
            getattr(row, "wiki_lookup_source", None)
        ),
        "wikipedia_thumbnail_url": clean_json_value(row.wikipedia_thumbnail_url),
        "commons_image_url": clean_json_value(row.commons_image_url),
        "commons_image_page_url": clean_json_value(row.commons_image_page_url),
        "commons_image_title": clean_json_value(row.commons_image_title),
        "commons_image_author": clean_json_value(row.commons_image_author),
        "commons_image_license": clean_json_value(row.commons_image_license),
        "commons_image_license_url": clean_json_value(row.commons_image_license_url),
        "commons_image_credit": clean_json_value(row.commons_image_credit),
        "commons_image_search_source": clean_json_value(
            row.commons_image_search_source
        ),
        "commons_image_search_term": clean_json_value(row.commons_image_search_term),
        "image_url": clean_json_value(row.image_url),
        "image_source": clean_json_value(row.image_source),
        "image_lookup_taxonid": clean_json_value(
            getattr(row, "image_lookup_taxonid", None)
        ),
        "image_lookup_source": clean_json_value(
            getattr(row, "image_lookup_source", None)
        ),
        "label": row.label,
        "scientific_name": clean_json_value(getattr(row, "scientific_name", None)),
        "main_common_name": clean_json_value(getattr(row, "main_common_name", None)),
        "category_iucn": row.category_iucn,
        "population_trend": clean_json_value(row.population_trend),
        "number_of_mature_individuals": clean_json_value(
            row.number_of_mature_individuals
        ),
        "estimated_area_of_occupancy": clean_json_value(
            row.estimated_area_of_occupancy
        ),
        "estimated_extent_of_occurrence": clean_json_value(
            row.estimated_extent_of_occurrence
        ),
        "taxon_class": row.taxon_class,
        "taxon_group": row.taxon_group,
        "taxon_rank": clean_json_value(row.taxon_rank),
        "parent_taxonid": clean_json_value(row.parent_taxonid),
        "child_infrarank_taxonids": clean_json_value(row.child_infrarank_taxonids),
        "iucn_has_ranges": clean_json_value(row.iucn_has_ranges),
        "iucn_has_points": clean_json_value(row.iucn_has_points),
        "centroid_source": clean_json_value(row.centroid_source),
        "centroid_rank": clean_json_value(row.centroid_rank),
        "centroid_count": clean_json_value(row.centroid_count),
        "range_component_count": clean_json_value(row.range_component_count),
        "range_cluster_count": clean_json_value(row.range_cluster_count),
        "range_cluster_component_count": clean_json_value(
            row.range_cluster_component_count
        ),
        "range_cluster_buffer_km": clean_json_value(row.range_cluster_buffer_km),
        "range_cluster_area_share": clean_json_value(row.range_cluster_area_share),
        "spatial_presence": clean_json_value(row.spatial_presence),
        "spatial_presence_label": clean_json_value(row.spatial_presence_label),
        "spatial_seasonal": clean_json_value(row.spatial_seasonal),
        "spatial_seasonal_label": clean_json_value(row.spatial_seasonal_label),
        "spatial_lookup_taxonid": clean_json_value(
            getattr(row, "spatial_lookup_taxonid", None)
        ),
        "spatial_lookup_source": clean_json_value(
            getattr(row, "spatial_lookup_source", None)
        ),
        "computed_range_area_km2": clean_json_value(row.computed_range_area_km2),
        "computed_range_component_area_km2": clean_json_value(
            row.computed_range_component_area_km2
        ),
        "range_component_area_km2": clean_json_value(row.range_component_area_km2),
        "observation_point_count": clean_json_value(row.observation_point_count),
        "source_paths": clean_json_value(row.source_paths),
        "spatial_citation": clean_json_value(row.spatial_citation),
        "spatial_year": clean_json_value(row.spatial_year),
        "spatial_credit": clean_json_value(row.spatial_credit),
        "iucn_dataset_citation": clean_json_value(row.iucn_dataset_citation),
        "iucn_data_last_updated": clean_json_value(row.iucn_data_last_updated),
        "popularity": int(row.popularity),
    }


def run_spatial_prefilter(packages, output_path, birds_filter_csv=None, input_dir=None):
    """Run clean_spatial_data.py in pre-filter mode (no API targets, category-based filter)."""
    cmd = [
        sys.executable, "scripts/clean_spatial_data.py",
        "--packages", ",".join(packages),
        "--input-dir", str(input_dir or SPATIAL_DATA_DIR),
        "--output", str(output_path),
    ]
    if birds_filter_csv:
        cmd += ["--birds-filter-csv", str(birds_filter_csv)]
    subprocess.run(cmd, check=True)


def run_spatial_cleaning(targets_path, output_path, input_dir=None):
    """Run clean_spatial_data.py in post-API mode (filter by taxon IDs from targets CSV)."""
    cmd = [
        sys.executable, "scripts/clean_spatial_data.py",
        "--targets", str(targets_path),
        "--input-dir", str(input_dir or SPATIAL_DATA_DIR),
        "--output", str(output_path),
    ]
    subprocess.run(cmd, check=True)


def attach_wikidata_fields(frame, mapping):
    """Attach Wikidata/Wikipedia fields using the row-level wiki_lookup_taxonid."""
    lookup_ids = frame["wiki_lookup_taxonid"].map(
        lambda value: str(int(value)) if pd.notna(value) else None
    )
    for field in WIKIDATA_FIELDS:
        frame[field] = lookup_ids.map(
            lambda taxonid: (mapping.get(taxonid) or {}).get(field) if taxonid else None
        )


def geojson_text_col(frame, col):
    """Return a safe text Series for optional GeoJSON-inspection columns."""
    if col not in frame.columns:
        return pd.Series("", index=frame.index)
    return frame[col].fillna("").astype(str)
