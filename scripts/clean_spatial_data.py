#!/usr/bin/env python3
"""Pre-filter IUCN spatial files for the endangered-globe notebook.

The raw IUCN spatial downloads are large. This script keeps only spatial
records matching the API target taxon IDs and preserves distribution codes used
later for representative label placement. It writes a smaller GeoJSON/GPKG that
the notebook can read quickly.
"""

from __future__ import annotations

import argparse
import glob
import os
from collections import Counter
from pathlib import Path

import geopandas as gpd
import pandas as pd


PACKAGE_PATTERNS = {
    "MAMMALS": ["MAMMALS/*.shp"],
    "REPTILES": ["REPTILES/*.shp"],
    "AMPHIBIANS": ["AMPHIBIANS/*.shp"],
    "FW_CRABS": ["FW_CRABS/*.shp"],
    "FW_CRAYFISH": ["FW_CRAYFISH/*.shp"],
    "FW_SHRIMPS": ["FW_SHRIMPS/*.shp"],
    "LOBSTERS": ["LOBSTERS/*.shp"],
    "FW_FISH": ["FW_FISH/*.shp"],
    "SHARKS_RAYS_CHIMAERAS": ["SHARKS_RAYS_CHIMAERAS/*.shp"],
    "BIRDS": ["BIRDS/*.gpkg"],
}

PRESENCE_CODES = None  # Keep all presence codes; the notebook ranks them before centroid placement.

PRESENCE_LABELS = {
    1: "Extant",
    2: "Probably Extant",
    3: "Possibly Extant",
    4: "Possibly Extinct",
    5: "Extinct",
    6: "Presence Uncertain",
}
SEASONAL_LABELS = {
    1: "Resident",
    2: "Breeding",
    3: "Non-breeding",
    4: "Passage",
    5: "Seasonality Uncertain",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", required=True, help="CSV written by the notebook with at least taxonid.")
    parser.add_argument("--input-dir", default="data/shapefiles", help="Directory containing extracted IUCN spatial files.")
    parser.add_argument("--output", default="data/processed/iucn_spatial_clean.geojson", help="Clean spatial output path.")
    parser.add_argument("--all-shapefiles", action="store_true", help="Read every .shp under input-dir instead of package-specific folders.")
    return parser.parse_args()


def first_existing_column(columns, candidates):
    """Return the first existing column name, matching case-insensitively."""
    by_lower = {str(col).lower(): col for col in columns}
    for candidate in candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def format_counter(counter):
    """Format a Counter compactly for notebook logs."""
    if not counter:
        return "none"
    return ", ".join(f"{key}: {value:,}" for key, value in counter.most_common())


def code_reason(column, value, labels):
    """Describe one rejected IUCN spatial distribution code."""
    if pd.isna(value):
        return f"{column}=missing"
    try:
        code = int(value)
    except (TypeError, ValueError):
        return f"{column}=invalid:{value}"
    label = labels.get(code, "Unknown")
    return f"{column}={code} {label}"


def allowed_code_mask(gdf, column, allowed_codes):
    """Return an allowed-code mask; accept everything when absent/disabled."""
    if column is None or allowed_codes is None:
        return pd.Series(True, index=gdf.index)
    codes = pd.to_numeric(gdf[column], errors="coerce")
    return codes.isin(allowed_codes)


def filter_iucn_distribution_records(gdf):
    """Apply hard distribution filters, preserving all presence/origin/seasonal codes by default."""
    presence_col = first_existing_column(gdf.columns, ["presence"])

    checks = [
        (presence_col, PRESENCE_CODES, PRESENCE_LABELS, "presence"),
    ]
    keep_mask = pd.Series(True, index=gdf.index)
    drop_reasons = Counter()

    for column, allowed_codes, labels, reason_name in checks:
        if column is None or allowed_codes is None:
            continue
        mask = allowed_code_mask(gdf, column, allowed_codes)
        newly_dropped = keep_mask & ~mask
        if newly_dropped.any():
            for value in gdf.loc[newly_dropped, column]:
                drop_reasons[code_reason(reason_name, value, labels)] += 1
        keep_mask &= mask

    return gdf[keep_mask].copy(), drop_reasons


def target_packages(targets):
    """Return explicit IUCN spatial packages from the target table, if available."""
    if "spatial_package" not in targets.columns:
        return []
    packages = set()
    for value in targets["spatial_package"].dropna().unique():
        for package in str(value).split(";"):
            package = package.strip()
            if package:
                packages.add(package)
    return sorted(packages)


def shapefile_paths(input_dir, packages, all_shapefiles=False):
    """Resolve spatial source paths from explicit IUCN spatial packages."""
    input_dir = Path(input_dir)
    packages = packages or []
    if all_shapefiles:
        return sorted(str(path) for path in input_dir.glob("**/*.shp"))
    if not packages:
        raise ValueError("Target table must contain spatial_package values, or run with --all-shapefiles")

    paths = []
    for package in packages:
        package_paths = []
        for pattern in PACKAGE_PATTERNS.get(package, []):
            package_paths.extend(glob.glob(str(input_dir / pattern)))
        if not package_paths:
            print(f"Warning: no extracted shapefiles found for package {package}; this package will have no spatial records")
        paths.extend(package_paths)

    return sorted(set(paths))


def is_polygon_like(geometry):
    """Return True when a geometry contains polygon range data."""
    if geometry is None or geometry.is_empty:
        return False
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return True
    if geometry.geom_type == "GeometryCollection":
        return any(is_polygon_like(part) for part in geometry.geoms)
    return False


def is_point_like(geometry):
    """Return True when a geometry contains point observation data."""
    if geometry is None or geometry.is_empty:
        return False
    if geometry.geom_type in {"Point", "MultiPoint"}:
        return True
    if geometry.geom_type == "GeometryCollection":
        return any(is_point_like(part) for part in geometry.geoms)
    return False


def normalize_name(value):
    """Normalize scientific names for lightweight equality checks."""
    if value is None or pd.isna(value):
        return None
    return " ".join(str(value).strip().lower().split()) or None


def print_scientific_name_check(gdf, targets, path):
    """Warn when spatial sci_name disagrees with the API target table for same taxonid."""
    sci_col = first_existing_column(gdf.columns, ["sci_name", "scientific_name"])
    if sci_col is None or "scientific_name" not in targets.columns:
        return

    target_names = (
        targets[["taxonid", "scientific_name"]]
        .dropna(subset=["scientific_name"])
        .drop_duplicates(subset=["taxonid"])
        .assign(_target_name=lambda d: d["scientific_name"].map(normalize_name))
        .set_index("taxonid")["_target_name"]
        .to_dict()
    )
    if not target_names:
        return

    spatial_names = gdf[["taxonid", sci_col]].copy()
    spatial_names["spatial_name"] = spatial_names[sci_col].map(normalize_name)
    checked = 0
    mismatches = []
    for row in spatial_names.itertuples(index=False):
        target_name = target_names.get(int(row.taxonid))
        spatial_name = row.spatial_name
        if not target_name or not spatial_name:
            continue
        checked += 1
        if target_name != spatial_name:
            mismatches.append((int(row.taxonid), target_name, spatial_name))

    if not checked:
        return
    if mismatches:
        print(f"  warning: {len(mismatches):,}/{checked:,} taxonid name checks mismatch in {os.path.basename(path)}")
        for taxonid, target_name, spatial_name in mismatches[:5]:
            print(f"    {taxonid}: API={target_name!r}, spatial={spatial_name!r}")
    else:
        print(f"  taxonid/name check: {checked:,}/{checked:,} spatial rows match API scientific_name")


def clean_spatial_data(targets_path, input_dir, output_path, all_shapefiles=False):
    """Build a small spatial file matching the notebook's target taxon IDs."""
    targets = pd.read_csv(targets_path)
    if "taxonid" not in targets.columns:
        raise ValueError(f"{targets_path} must contain a taxonid column")

    target_ids = set(pd.to_numeric(targets["taxonid"], errors="coerce").dropna().astype(int))
    if not target_ids:
        raise ValueError(f"{targets_path} contains no usable taxonid values")

    packages = target_packages(targets)
    paths = shapefile_paths(input_dir, packages, all_shapefiles=all_shapefiles)
    if not paths:
        source_text = ", ".join(packages) if packages else "all packages"
        raise FileNotFoundError(f"No shapefiles found in {input_dir} for {source_text}")

    print(f"Target taxa: {len(target_ids):,}")
    if packages:
        print(f"Spatial packages: {', '.join(packages)}")
    print(f"Spatial files: {len(paths):,}")

    frames = []
    for path in paths:
        print(f"Loading {path}...")
        gdf = gpd.read_file(path)
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)

        id_col = first_existing_column(gdf.columns, ["id_no", "sisid", "taxonid", "taxon_id"])
        if id_col is None:
            print(f"  skipped: no taxon id column")
            continue

        ids = pd.to_numeric(gdf[id_col], errors="coerce")
        gdf = gdf[ids.notna()].copy()
        gdf["taxonid"] = ids[ids.notna()].astype(int)
        gdf = gdf[gdf["taxonid"].isin(target_ids)]
        if gdf.empty:
            print("  no target taxa")
            continue
        print_scientific_name_check(gdf, targets, path)

        before = len(gdf)
        gdf, drop_reasons = filter_iucn_distribution_records(gdf)
        if gdf.empty:
            print(f"  no usable distribution records after filtering {before:,} target rows; dropped: {format_counter(drop_reasons)}")
            continue

        citation_col = first_existing_column(gdf.columns, ["citation", "cite", "source", "sources"])
        year_col = first_existing_column(gdf.columns, ["year", "yr", "year_", "yrcompiled"])
        legend_col = first_existing_column(gdf.columns, ["legend"])
        presence_col = first_existing_column(gdf.columns, ["presence"])
        seasonal_col = first_existing_column(gdf.columns, ["seasonal"])

        gdf["source_path"] = os.path.basename(path)
        gdf["spatial_citation"] = gdf[citation_col] if citation_col else None
        gdf["spatial_year"] = gdf[year_col] if year_col else None
        gdf["spatial_legend"] = gdf[legend_col] if legend_col else None
        gdf["spatial_presence"] = gdf[presence_col] if presence_col else None
        gdf["spatial_seasonal"] = gdf[seasonal_col] if seasonal_col else None

        keep_cols = [
            "taxonid",
            "geometry",
            "source_path",
            "spatial_citation",
            "spatial_year",
            "spatial_legend",
            "spatial_presence",
            "spatial_seasonal",
        ]
        frames.append(gdf[keep_cols])
        if drop_reasons:
            print(f"  kept {len(gdf):,}/{before:,} target records; dropped: {format_counter(drop_reasons)}")
        else:
            print(f"  kept {len(gdf):,}/{before:,} target records; dropped: none")

    if not frames:
        raise RuntimeError("No spatial records matched the target taxa after filtering")

    all_spatial = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    all_spatial = all_spatial[all_spatial.geometry.notna() & ~all_spatial.geometry.is_empty].copy()

    polygon_mask = all_spatial.geometry.map(is_polygon_like)
    point_mask = all_spatial.geometry.map(is_point_like)
    polygon_taxa = set(all_spatial.loc[polygon_mask, "taxonid"].astype(int))

    polygons = all_spatial[polygon_mask].copy()
    fallback_points = all_spatial[point_mask & ~all_spatial["taxonid"].astype(int).isin(polygon_taxa)].copy()
    cleaned = gpd.GeoDataFrame(pd.concat([polygons, fallback_points], ignore_index=True), geometry="geometry", crs="EPSG:4326")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    driver = "GeoJSON" if output_path.suffix.lower() in {".geojson", ".json"} else None
    if driver:
        cleaned.to_file(output_path, driver=driver)
    else:
        cleaned.to_file(output_path)

    print(f"Written: {output_path}")
    print(f"Clean records: {len(cleaned):,}")
    print(f"Species with polygons: {len(polygon_taxa):,}")
    print(f"Species with fallback points: {fallback_points['taxonid'].nunique():,}")


def main():
    args = parse_args()
    clean_spatial_data(
        targets_path=args.targets,
        input_dir=args.input_dir,
        output_path=args.output,
        all_shapefiles=args.all_shapefiles,
    )


if __name__ == "__main__":
    main()
