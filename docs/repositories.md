# Irish Genealogy Research — Repositories and Sources

*Version 1.5 — May 2026*
*Audience: All roles. This document is a practical reference for transcription and ingestion sessions. It defines the pre-populated global repository and source set.*

---

## 1. Overview

The following repositories and sources are pre-populated in the foundational layer. They cover the primary online Irish genealogical sources and the logainm.ie place authority.

Deep links to individual records are constructed at runtime by the Python layer. For each Source that supports direct linking, the `record_url_template` contains `{parameter_name}` placeholders filled by merging `source_parameters` (Source-level constants) with `Record.record_parameters` (per-Record values). See `data_dictionary.md` §2.2 for the construction specification.

**Place authority** (Repository 8, Source 13) differs from all other sources: logainm data is loaded directly into `place_authority` via `src/fetch_places.py` or `src/db seed-places` and does not produce Records or RecordedEvents. See §4 below.

---

## 2. Repositories

| repository_id | Name | URL |
|---|---|---|
| 1 | National Archives of Ireland | nationalarchives.ie |
| 2 | National Library of Ireland | nli.ie |
| 3 | Askaboutireland.ie | askaboutireland.ie |
| 4 | irishgenealogy.ie | irishgenealogy.ie |
| 5 | Central Statistics Office | cso.ie |
| 6 | Military Archives | militaryarchives.ie |
| 7 | Duchas.ie | duchas.ie |
| 8 | Logainm.ie | logainm.ie |

---

## 3. Sources

---

### Source 1 — Griffith's Valuation

| Field | Value |
|---|---|
| source_id | 1 |
| repository_id | 3 (Askaboutireland.ie) |
| type | valuation |
| coverage | c.1847–1864 |
| source_url | https://www.askaboutireland.ie/griffiths-valuation |
| record_url_template | https://www.askaboutireland.ie/griffith-valuation/index.xml?action=doNameSearch&familyname={occupier_surname}&firstname={occupier_forename}&countyname={county} |
| source_parameters | null |
| record_parameter_names | occupier_surname, occupier_forename, county |
| column_schema | occupier_surname, occupier_forename, lessor_surname, lessor_forename, county, barony, parish, townland, street, map_reference, acres, roods, perches, land_valuation, building_valuation, total_valuation |

**Notes:** Primary mid-nineteenth century land survey. Census substitute for the period. Static deep linking not supported — template executes a parameterised name and county search.

---

### Source 2 — Tithe Applotment Books

| Field | Value |
|---|---|
| source_id | 2 |
| repository_id | 1 (National Archives of Ireland) |
| type | tithe |
| coverage | 1823–1837 |
| source_url | https://titheapplotmentbooks.nationalarchives.ie |
| record_url_template | https://titheapplotmentbooks.nationalarchives.ie/reels/tab//{reel_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | reel_id, image_id |
| column_schema | reel_id, image_id, occupier_surname, occupier_forename, county, parish, townland, year, land_holding_class, acres, roods, perches, tithe_amount_pounds, tithe_amount_shillings, tithe_amount_pence |

**Notes:** Pre-Famine agricultural occupiers. Double slash in URL path is mandatory.

---

### Source 3 — Census 1901

| Field | Value |
|---|---|
| source_id | 3 |
| repository_id | 1 (National Archives of Ireland) |
| type | census |
| coverage | 1901 |
| census_night | 31 March 1901 |
| source_url | https://nationalarchives.ie/collections/search-the-census/ |
| record_url_template | https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id} |
| source_parameters | null |
| record_parameter_names | document_id |
| column_schema | id, census_year, county, surname, firstname, townland, townland_clean, ded, age, sex, house_number, relation_to_head, religion, education, occupation, marriage_status, birthplace, language, deafdumb, image_group, religion_updated, occupation_updated, relation_to_head_updated, language_updated, images, ded_clean |
| nai_ingest_mapping | document_id ← first image id from `images` field; household_id ← `image_group`; role ← `relation_to_head_updated` |

**Notes:** Same NAI download schema as 1911. Marital history fields (`marriage_years`, `children_born`, `children_living`) are absent — those columns are in the download schema but empty for 1901 entries.

---

### Source 4 — Census 1911

| Field | Value |
|---|---|
| source_id | 4 |
| repository_id | 1 (National Archives of Ireland) |
| type | census |
| coverage | 1911 |
| census_night | 2 April 1911 |
| source_url | https://nationalarchives.ie/collections/search-the-census/ |
| record_url_template | https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id} |
| source_parameters | null |
| record_parameter_names | document_id |
| column_schema | id, census_year, county, surname, firstname, townland, townland_clean, ded, age, sex, house_number, relation_to_head, religion, education, occupation, marriage_status, marriage_years, children_born, children_living, birthplace, language, deafdumb, image_group, religion_updated, occupation_updated, relation_to_head_updated, language_updated, images, ded_clean |
| nai_ingest_mapping | document_id ← first image id from `images` field; household_id ← `image_group`; role ← `relation_to_head_updated` |

**Notes:** Gold standard NAI CSV format. `_updated` suffix fields are NAI-normalised and preferred over raw counterparts. One Record per household (`image_group`).

---

### Source 5 — Census 1926

| Field | Value |
|---|---|
| source_id | 5 |
| repository_id | 1 (National Archives of Ireland) |
| type | census |
| coverage | 1926 |
| census_night | 18 April 1926 |
| source_url | https://nationalarchives.ie/collections/search-the-1926-census/ |
| record_url_template | https://nationalarchives.ie/collections/search-the-1926-census/view-1926-pdf/?doc={document_id} |
| source_parameters | null |
| record_parameter_names | document_id |
| column_schema | aform_name, county, townland, ded, first_name, surname, relationship_to_head, updated_relationship_to_head, updated_sex, updated_marriage, updated_irish_language, updated_religion, years_married, irish_or_english, birthplace_county, children_born_alive, children_living, updated_age, geocode, institution_name, institution_type, image_group, a_id |
| nai_ingest_mapping | document_id ← `aform_name`; household_id ← `image_group`; role ← `updated_relationship_to_head` |

**Notes:** First census of the Irish Free State. Different download schema from 1901/1911: no `occupation` column, no `house_number`, no `education`. Age is `updated_age` (integer). Birthplace is county-level only (`birthplace_county`). Ingest pipeline normalises 1926 rows into the shared census schema before processing.

---

### Source 6 — Civil Birth Registrations

| Field | Value |
|---|---|
| source_id | 6 |
| repository_id | 4 (irishgenealogy.ie) |
| type | birth_registration |
| coverage | 1864–1925 |
| source_url | https://www.irishgenealogy.ie |
| record_url_template | https://civilrecords.irishgenealogy.ie/churchrecords/images/birth_returns/births_{year}/{folder_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | year, folder_id, image_id |
| column_schema | year, folder_id, image_id, registration_id, group_id, child_forename, child_surname, sex, date_of_birth, place_of_birth, father_name, father_occupation, mother_name, mother_maiden_name, informant_qualification, informant_address, registration_date, registrar_district, superintendent_district, county |

---

### Source 7 — Civil Marriage Registrations

| Field | Value |
|---|---|
| source_id | 7 |
| repository_id | 4 (irishgenealogy.ie) |
| type | marriage_registration |
| coverage | 1845–1950 |
| source_url | https://www.irishgenealogy.ie |
| record_url_template | https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_{year}/{folder_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | year, folder_id, image_id |
| column_schema | year, folder_id, image_id, registration_id, group_id, date_of_marriage, groom_forename, groom_surname, groom_age, groom_condition, groom_occupation, groom_residence, groom_father_name, groom_father_occupation, bride_forename, bride_surname, bride_age, bride_condition, bride_occupation, bride_residence, bride_father_name, bride_father_occupation, place_of_celebration, witness_1_name, witness_2_name, celebrant, registrar_district, county |

**Notes:** Non-Catholic marriages from 1 April 1845; all denominations from 1 January 1864.

---

### Source 8 — Civil Death Registrations

| Field | Value |
|---|---|
| source_id | 8 |
| repository_id | 4 (irishgenealogy.ie) |
| type | death_registration |
| coverage | 1864–1975 |
| source_url | https://www.irishgenealogy.ie |
| record_url_template | https://civilrecords.irishgenealogy.ie/churchrecords/images/deaths_returns/deaths_{year}/{folder_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | year, folder_id, image_id |
| column_schema | year, folder_id, image_id, registration_id, group_id, deceased_forename, deceased_surname, sex, condition, age_at_death, estimated_birth_year, occupation, date_of_death, place_of_death, cause_of_death, duration_of_illness, informant_qualification, informant_address, registration_date, registrar_district, superintendent_district, county |

---

### Source 9 — Catholic Parish Registers

| Field | Value |
|---|---|
| source_id | 9 |
| repository_id | 2 (National Library of Ireland) |
| type | parish_register |
| coverage | Typically 1820s–1880s |
| source_url | https://registers.nli.ie |
| record_url_template | https://registers.nli.ie/pages/{vtls_id}_{image_number} |
| source_parameters | {"vtls_id": null} — set per ingest batch |
| record_parameter_names | image_number |
| column_schema | vtls_id, image_number, event_id, event_type, event_date, principal_1_forename, principal_1_surname, principal_2_forename, principal_2_surname, father_forename, father_surname, mother_forename, mother_surname, sponsor_1_name, sponsor_2_name, priest, parish_name, diocese, county |

**Notes:** `vtls_id` is the microfilm identifier — constant per ingest batch (source-level parameter). A separate Source entry should be created per microfilm volume with `source_parameters` set to `{"vtls_id": <value>}`.

---

### Source 10 — Bureau of Military History Witness Statements

| Field | Value |
|---|---|
| source_id | 10 |
| repository_id | 6 (Military Archives) |
| type | military |
| coverage | Statements 1947–1957; events 1913–1921 |
| source_url | https://bmh.militaryarchives.ie |
| record_url_template | https://bmh.militaryarchives.ie/reels/bmh/BMH.WS{statement_number}.pdf |
| source_parameters | null |
| record_parameter_names | statement_number |
| column_schema | statement_number, witness_surname, witness_forename, witness_address, witness_organisation, witness_rank, pages, date_of_statement, county |

---

### Source 11 — Military Service Pensions Collection

| Field | Value |
|---|---|
| source_id | 11 |
| repository_id | 6 (Military Archives) |
| type | military |
| coverage | Applications 1924–1962; service 1916–1923 |
| source_url | http://mspcsearch.militaryarchives.ie |
| record_url_template | http://mspcsearch.militaryarchives.ie/docs/files/PDF_Pensions/{release_id}/{file_directory}/{filename}.pdf |
| source_parameters | {"release_id": null} — set per ingest batch |
| record_parameter_names | file_directory, filename |
| column_schema | release_id, file_directory, filename, file_reference, applicant_surname, applicant_forename, alternative_name, date_of_birth, date_of_death, address, organization, rank, service_periods, pension_awarded, next_of_kin, associated_files |

**Notes:** `release_id` is the digitisation batch identifier — constant per ingest batch.

---

### Source 12 — Duchas Schools Collection

| Field | Value |
|---|---|
| source_id | 12 |
| repository_id | 7 (Duchas.ie) |
| type | folklore |
| coverage | 1937–1939 |
| source_url | https://www.duchas.ie/en/cbes |
| record_url_template | https://www.duchas.ie/en/cbes/{volume_id}/{school_id}/{page_id} |
| source_parameters | null |
| record_parameter_names | volume_id, school_id, page_id |
| column_schema | volume_id, school_id, page_id, story_title, collector_name, informant_name, informant_age, school_name, parish_name, county |

---

## 4. Place Authority Source

### Repository 8 — Logainm.ie

| Field | Value |
|---|---|
| repository_id | 8 |
| Name | Logainm.ie |
| URL | logainm.ie |
| Notes | Official Irish placename authority operated by Foras na Gaeilge. Provides canonical English and Irish names, full administrative hierarchy (province, county, barony, civil parish, DED), and coordinates for all Irish placenames including townlands. |

---

### Source 13 — logainm.ie Place Authority

| Field | Value |
|---|---|
| source_id | 13 |
| repository_id | 8 (logainm.ie) |
| type | place_authority |
| coverage | Current — live reference authority |
| source_url | https://www.logainm.ie |
| API base | https://www.logainm.ie/api/v1.1/ |
| record_url_template | https://www.logainm.ie/en/{logainm_id} |
| source_parameters | null |
| record_parameter_names | logainm_id |
| column_schema | place_id, logainm_id, name_en, place_type, parent_name, parent_id, parent_type, ded_name, ded_id, county_name, county_id, barony_name, barony_id, civil_parish_name, civil_parish_id, latitude, longitude, logainm_url, notes |

**Notes:** Unlike all other sources, logainm data is loaded directly into `place_authority` — not through the evidence pipeline. No Records or RecordedEvents are created. Two loading mechanisms:

1. **API fetch:** `python -m src.fetch_places --logainm-id <ID> --db genealogy.db` — fetches the named entity and all child townlands. Requires `LOGAINM_API_KEY` environment variable. The `--logainm-id` argument is the numeric ID from the logainm.ie URL (e.g. `111482` for Tullynaught DED at `https://www.logainm.ie/en/111482`).

2. **CSV import:** `python -m src.db seed-places --file places.csv` — loads a CSV matching the `column_schema` above. Used for pre-fetched data, offline workflows, or manually-added entities.

**Church parishes:** logainm.ie does not catalogue Catholic church parishes. Add these manually by appending rows with `logainm_id` blank and `place_type = church_parish` to the CSV before import.

**Fetching a DED and its townlands:** The fetcher retrieves the parent DED record and then fetches each child townland individually via the logainm API, populating all hierarchy columns (`ded_id`, `county_id`, `barony_id`, `civil_parish_id`). Some townlands legitimately lack barony and civil parish entries in logainm — these columns are stored as null. For Tullynaught DED: 17 of 33 townlands have null `barony_id`/`civil_parish_id`.

**Idempotency:** Both loading mechanisms are idempotent. Re-running against a populated database skips rows whose `logainm_id` is already present (for logainm-sourced rows) or whose `(name_en, place_type)` pair is already present (for manually-added rows).

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial repositories document — 7 repositories, 12 sources |
| 1.1 | May 2026 | Minor corrections |
| 1.2 | May 2026 | Two-level deep link parameter system (`source_parameters`, `record_parameter_names`) |
| 1.3 | May 2026 | Source 4 (Census 1911) updated to NAI download format; `nai_ingest_mapping` added |
| 1.4 | May 2026 | Sources 3 (Census 1901) and 5 (Census 1926) corrected against actual NAI schemas; `census_night` added to census sources |
| 1.5 | May 2026 | Repository 8 (logainm.ie) and Source 13 (place_authority) added. §4 Place Authority Source section added. Two loading mechanisms documented (API fetch and CSV import). Church parish manual entry and idempotency noted. |
