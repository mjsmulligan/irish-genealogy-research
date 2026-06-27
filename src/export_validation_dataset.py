"""
Export validation dataset for manual researcher review.

Purpose: Generate a CSV with all recorded persons across all 3 census sources,
including linkage status. This allows researchers to identify false positives
(incorrect linkages) and false negatives (missed linkages).

Output: validation_dataset.csv with columns:
  - census_year: Census year (1901, 1911, 1926)
  - household_id: Unique record identifier for the household
  - position_in_household: Sequence within household for sorting
  - name_as_recorded: Name exactly as in source
  - age_as_recorded: Age as stated in source
  - role: Household relationship role
  - occupation: Occupation as recorded
  - place_as_recorded: Place of residence
  - person_id: Linked person ID (NULL if not linked)
  - linked_to_years: Which other census years this person is linked to (e.g., "1911, 1926")
  - validation_notes: Space for researcher to add notes during manual review
"""

import csv
import psycopg2
import psycopg2.extras
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import os

load_dotenv()


def get_connection():
    """Open database connection."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set in environment")
    return psycopg2.connect(db_url)


def export_validation_dataset(output_path: str = "validation_dataset.csv"):
    """
    Export all recorded persons with linkage status for manual validation.

    Researchers review this to identify:
    - False positives: people linked who shouldn't be (same name, different people)
    - False negatives: people who should be linked but aren't (same person across censuses)
    """

    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Query: get all census persons with their linkage info
            query = """
            WITH census_persons AS (
                SELECT
                    rp.recorded_person_id,
                    r.record_id AS household_id,
                    ROW_NUMBER() OVER (PARTITION BY r.record_id ORDER BY rp.recorded_person_id) AS position_in_household,
                    r.date AS census_year,
                    rp.name_as_recorded,
                    rp.age_as_recorded,
                    rp.role,
                    rp.occupation_as_recorded,
                    rp.place_as_recorded
                FROM recorded_person rp
                JOIN record r ON rp.record_id = r.record_id
                JOIN source s ON r.source_id = s.source_id
                WHERE s.type = 'census'
            ),
            person_linkages AS (
                SELECT
                    cp.recorded_person_id,
                    prp.person_id,
                    STRING_AGG(
                        DISTINCT cp2.census_year::TEXT,
                        ', '
                        ORDER BY cp2.census_year::TEXT
                    ) AS linked_to_years
                FROM census_persons cp
                LEFT JOIN person_recorded_person prp ON cp.recorded_person_id = prp.recorded_person_id
                LEFT JOIN census_persons cp2 ON prp.person_id IS NOT NULL
                    AND cp2.recorded_person_id IN (
                        SELECT recorded_person_id FROM person_recorded_person
                        WHERE person_id = prp.person_id
                            AND recorded_person_id != cp.recorded_person_id
                    )
                GROUP BY cp.recorded_person_id, prp.person_id
            )
            SELECT
                cp.census_year,
                cp.household_id,
                cp.position_in_household,
                cp.name_as_recorded,
                cp.age_as_recorded,
                cp.role,
                cp.occupation_as_recorded,
                cp.place_as_recorded,
                pl.person_id,
                pl.linked_to_years,
                '' AS validation_notes
            FROM census_persons cp
            LEFT JOIN person_linkages pl ON cp.recorded_person_id = pl.recorded_person_id
            ORDER BY cp.census_year, cp.household_id, cp.position_in_household
            """

            cur.execute(query)
            rows = cur.fetchall()

            # Write to CSV
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                if not rows:
                    print("No census records found in database")
                    return

                # Get column names from first row
                fieldnames = list(rows[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))

            print(f"✓ Validation dataset exported to {output_path}")
            print(f"  Total records: {len(rows)}")

            # Summary stats by census year
            by_year = {}
            for row in rows:
                year = row['census_year']
                if year not in by_year:
                    by_year[year] = {'total': 0, 'linked': 0}
                by_year[year]['total'] += 1
                if row['person_id'] is not None:
                    by_year[year]['linked'] += 1

            print(f"\n  Linkage breakdown by census year:")
            for year in sorted(by_year.keys()):
                stats = by_year[year]
                rate = 100 * stats['linked'] / stats['total']
                print(f"    {year}: {stats['linked']:4d}/{stats['total']:4d} linked ({rate:5.1f}%)")

            linked_total = sum(1 for row in rows if row['person_id'] is not None)
            print(f"\n  Overall linkage rate: {100 * linked_total / len(rows):.1f}%")

    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    output_file = sys.argv[1] if len(sys.argv) > 1 else "validation_dataset.csv"
    export_validation_dataset(output_file)
