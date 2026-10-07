#!/usr/bin/env python3
"""Build the bundled city gazetteer used to place fuel stations on the map.

The fuel dataset supplies City/State but no coordinates. This script turns the
US Census Bureau Gazetteer files (public domain) into one compact lookup table
keyed by the same normalised place key the application searches with, so the
import command never touches the network.

Two Census files are needed, because neither alone covers the dataset:
  * places      - incorporated cities, towns and CDPs
  * county subdivisions - the townships that New England and the mid-Atlantic
    use instead of places ("Mahwah township", "North Brunswick township")

Usage (downloads the source files into a cache directory):

    python scripts/build_city_coordinates.py

Re-running is safe and overwrites the output.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fuel.services.city_coordinates import name_variants  # noqa: E402

CENSUS_YEAR = "2023"
SOURCES = {
    "place": f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{CENSUS_YEAR}_Gazetteer/{CENSUS_YEAR}_Gaz_place_national.zip",
    "cousub": f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{CENSUS_YEAR}_Gazetteer/{CENSUS_YEAR}_Gaz_cousubs_national.zip",
}


def fetch(url: str, cache_dir: Path) -> bytes:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / url.rsplit("/", 1)[-1]
    if not cached.exists():
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=180) as response:
            cached.write_bytes(response.read())
    return cached.read_bytes()


def rows_from_zip(archive: bytes):
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        text = zf.read(name).decode("latin-1")
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        yield {k.strip(): (v.strip() if v else "") for k, v in row.items()}


def build(cache_dir: Path) -> dict[tuple[str, str], tuple[float, float]]:
    table: dict[tuple[str, str], tuple[float, float]] = {}
    # Places are loaded first so an incorporated city wins over a same-named
    # township when both exist in a state.
    for label in ("place", "cousub"):
        added = 0
        for row in rows_from_zip(fetch(SOURCES[label], cache_dir)):
            latitude, longitude = row.get("INTPTLAT"), row.get("INTPTLONG")
            state = row.get("USPS", "")
            if not latitude or not longitude or len(state) != 2:
                continue
            coordinate = (round(float(latitude), 5), round(float(longitude), 5))
            for key in name_variants(row.get("NAME", "")):
                if (key, state) not in table:
                    table[(key, state)] = coordinate
                    added += 1
        print(f"{label}: added {added} keys")
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=REPO_ROOT / "data" / "us_city_coordinates.csv.gz"
    )
    parser.add_argument("--cache-dir", type=Path, default=REPO_ROOT / ".census-cache")
    args = parser.parse_args()

    table = build(args.cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", newline="", compresslevel=9) as handle:
        writer = csv.writer(handle)
        for (key, state), (latitude, longitude) in sorted(table.items()):
            writer.writerow([key, state, latitude, longitude])
    size_kb = args.output.stat().st_size / 1024
    print(f"wrote {len(table)} entries to {args.output} ({size_kb:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
