
---

### Repository 8 — logainm.ie

| Field | Value |
|---|---|
| repository_id | 8 |
| Name | Logainm.ie |
| URL | logainm.ie |
| Notes | Official Irish placename authority operated by Foras na Gaeilge. Provides canonical English and Irish names, administrative hierarchy (county, barony, civil parish, DED), and coordinates for all Irish placenames including townlands. |

---

### Source 13 — logainm.ie Place Authority

| Field | Value |
|---|---|
| source_id | 13 |
| repository_id | 8 (logainm.ie) |
| type | place_authority |
| coverage | Current — logainm.ie is a live reference authority |
| source_url | https://www.logainm.ie |
| API base | https://www.logainm.ie/api/v1.1/ |
| record_url_template | https://www.logainm.ie/en/{logainm_id} |
| column_schema | place_id, logainm_id, name_en, place_type, parent_name, parent_id, parent_type, ded_name, ded_id, county_name, county_id, barony_name, barony_id, civil_parish_name, civil_parish_id, latitude, longitude, logainm_url, notes |

**Notes:** Unlike all other sources, logainm data is loaded directly into the `place_authority` foundational table rather than through the evidence pipeline (no Records or RecordedEvents are created). The `place_authority` source type is reserved for this purpose. Two loading mechanisms are supported:

1. **API fetch:** `python -m src.fetch_places --logainm-id <ID> --db genealogy.db` — fetches the named entity and all its child townlands directly from the API and writes to `place_authority`. Requires `LOGAINM_API_KEY`.

2. **CSV import:** `python -m src.db seed-places --file places.csv` — loads a CSV in the column_schema format above. Used for pre-fetched data, manually-added entities (church parishes), or offline workflows.

**Fetching a DED:** Provide the logainm ID of the DED (electoral division) to fetch all townlands within it. For Tullynaught: `--logainm-id 111482`. The fetcher retrieves the DED record, then fetches each townland individually to populate the full hierarchy columns.

**Church parishes:** logainm.ie does not catalogue Catholic church parishes. These are added manually — add rows to a CSV with `logainm_id` blank and `place_type = church_parish`, then import via `seed-places`.

**Changelog addition:**

| Version | Date | Change |
|---|---|---|
| 1.5 | May 2026 | Added Repository 8 (logainm.ie) and Source 13 (place_authority). Documented two loading mechanisms (API fetch and CSV import). Added church parish manual entry note. |
