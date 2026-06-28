"""
GRA — Census Data Fetcher from National Archives API
Fetches census CSV files for 1901, 1911, 1926 from the National Archives API.

Requires that place_authority has been seeded (via fetch-places) first.
Uses logainm_id to look up the DED and county, then downloads census data.

CLI usage:
    # Download all three census years
    python -m src.cli fetch-census --logainm-id 111482

    # Download specific year(s)
    python -m src.cli fetch-census --logainm-id 111482 --year 1901

    # With explicit API key
    python -m src.cli fetch-census --logainm-id 111482 --api-key KEY123
"""

from __future__ import annotations

import csv
import io
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg2.extensions
import requests


# Base URLs for census APIs
_CENSUS_BASE_URLS = {
    1901: "https://api-census.nationalarchives.ie/census/query/census-records.csv",
    1911: "https://api-census.nationalarchives.ie/census/query/census-records.csv",
    1926: "https://c26-api.nationalarchives.ie/api/census/query_c26a/census-records.csv",
}

# Output directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"


@dataclass
class FetchCensusResult:
    """Result of fetching census data."""
    ded_name: str
    county_name: str
    files_saved: int
    records_per_year: dict[int, int]  # {1901: N, 1911: N, 1926: N}
    errors: list[str]
    output_dir: str


def _ensure_data_dir() -> None:
    """Create /data folder if it doesn't exist."""
    DATA_DIR.mkdir(exist_ok=True)


def _get_ded_context(conn: psycopg2.extensions.connection, logainm_id: int) -> tuple[str, str]:
    """
    Query place_authority to get county and DED names for a logainm_id.

    Returns:
        Tuple of (county_name, ded_name)

    Raises:
        ValueError: If no DED with matching logainm_id found.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT county_name, name_en, ded_name FROM place_authority WHERE logainm_id = %s AND place_type = 'ded'",
        (logainm_id,),
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        raise ValueError(
            f"No DED found in place_authority with logainm_id={logainm_id}. "
            "Run fetch-places first to seed the place authority."
        )

    # For a DED record, ded_name column is NULL (self-reference), so use name_en
    county_name = row["county_name"]
    ded_name = row["ded_name"] or row["name_en"]
    return county_name, ded_name


def _fetch_census_year(county: str, ded: str, year: int, max_retries: int = 3) -> list[dict]:
    """
    Fetch census CSV data for a single year via pagination.

    Args:
        county: County name (e.g., "Donegal")
        ded: DED name (e.g., "Tullynaught")
        year: Census year (1901, 1911, or 1926)
        max_retries: Number of retry attempts on network error

    Returns:
        List of record dicts from the CSV
    """
    base_url = _CENSUS_BASE_URLS.get(year)
    if not base_url:
        raise ValueError(f"Unsupported census year: {year}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    all_records = []
    limit = 1000
    offset = 0

    while True:
        params = {
            "county": county,
            "ded__icontains": ded,
            "limit": limit,
            "offset": offset,
        }

        # Retry on network error
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Failed to fetch {year} census at offset {offset} after {max_retries} attempts: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff

        # Parse response
        try:
            df = pd.read_csv(io.StringIO(response.text))
        except pd.errors.EmptyDataError:
            break

        if df.empty:
            break

        all_records.append(df)
        print(f"  {year}: Fetched {len(df)} records at offset {offset}.")

        # Last page
        if len(df) < limit:
            break

        offset += limit
        time.sleep(1)  # Rate limit: 1s between pages

    if not all_records:
        return []

    final_df = pd.concat(all_records, ignore_index=True)
    return final_df.to_dict("records")


def fetch_census(
    conn: psycopg2.extensions.connection,
    logainm_id: int,
    years: list[int] | None = None,
) -> FetchCensusResult:
    """
    Main function: fetch census data for specified years.

    Calls fetch-places internally to seed place_authority, then downloads
    census CSV files from National Archives API.

    Args:
        conn: Database connection
        logainm_id: Logainm ID of the DED
        years: List of census years to fetch (default: [1901, 1911, 1926])

    Returns:
        FetchCensusResult with metrics and any errors
    """
    if years is None:
        years = [1901, 1911, 1926]

    # Ensure data directory exists
    _ensure_data_dir()

    # Get county and DED from place_authority
    try:
        county_name, ded_name = _get_ded_context(conn, logainm_id)
    except ValueError as e:
        return FetchCensusResult(
            ded_name="",
            county_name="",
            files_saved=0,
            records_per_year={},
            errors=[str(e)],
            output_dir=str(DATA_DIR),
        )

    records_per_year = {}
    errors = []
    files_saved = 0

    # Download each year
    for year in sorted(years):
        try:
            print(f"Fetching {year} census for {ded_name}, {county_name}...")
            records = _fetch_census_year(county_name, ded_name, year)
            records_per_year[year] = len(records)

            if records:
                # Write to CSV
                output_path = DATA_DIR / f"{ded_name}_{year}.csv"

                with open(output_path, "w", newline="", encoding="utf-8") as f:
                    fieldnames = list(records[0].keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(records)

                files_saved += 1
                print(f"  Saved to: {output_path}")
            else:
                print(f"  No records found for {year}.")

        except Exception as e:
            error_msg = f"Error fetching {year} census: {e}"
            errors.append(error_msg)
            print(f"  ERROR: {error_msg}")

    return FetchCensusResult(
        ded_name=ded_name,
        county_name=county_name,
        files_saved=files_saved,
        records_per_year=records_per_year,
        errors=errors,
        output_dir=str(DATA_DIR),
    )


def print_fetch_census_report(result: FetchCensusResult) -> None:
    """Print summary report of census fetch operation."""
    print(f"\nfetch-census complete — {result.ded_name}, {result.county_name}")
    print(f"  Files saved: {result.files_saved}")

    for year in sorted(result.records_per_year.keys()):
        count = result.records_per_year[year]
        print(f"  {year}: {count:,} records")

    if result.errors:
        print(f"  Errors: {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")

    print(f"  Output directory: {result.output_dir}")
