# Irish Genealogy Research — Repositories and Sources

*Version 1.3 — May 2026*
*Audience: All roles. This document is a practical reference for transcription and ingestion sessions. It defines the pre-populated global repository and source set available to all projects without setup.*

---

## 1. Overview

The following repositories and sources are pre-populated in the global foundational layer. They cover the primary online Irish genealogical sources. A dedicated session should be used to verify and extend URL patterns, column schemas, and date coverage for each source as work progresses.

Deep links to individual records are constructed at runtime by the Python layer. For each Source that supports direct linking, the `record_url_template` contains placeholders in `{parameter_name}` syntax. Placeholders are filled by merging two parameter sets: `source_parameters` (constants that are the same for every Record in the Source) and `record_parameters` on each Record (values that vary per Record). See `data_dictionary.md` §2.2 for the full construction specification.

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

---

## 3. Sources

Sources are the primary ingestion targets. Each source defines the shared context for all Records ingested from it — including the column schema for parsing raw_text and the URL template for reconstructing links to individual records.

---

### Source 1 — Griffith's Valuation

| Field | Value |
|---|---|
| source_id | 1 |
| repository_id | 3 (Askaboutireland.ie) |
| type | valuation |
| coverage | c.1847–1864, varies by county |
| source_url | https://www.askaboutireland.ie/griffiths-valuation |
| record_url_template | https://www.askaboutireland.ie/griffith-valuation/index.xml?action=doNameSearch&familyname={occupier_surname}&firstname={occupier_forename}&countyname={county} |
| source_parameters | null |
| record_parameter_names | occupier_surname, occupier_forename, county |
| column_schema | occupier_surname, occupier_forename, lessor_surname, lessor_forename, county, barony, parish, townland, street, map_reference, acres, roods, perches, land_valuation, building_valuation, total_valuation |

**Notes:** Griffith's Valuation is the primary mid-nineteenth century land survey. It is considered the census substitute for the period given the destruction of earlier census records. Each entry is anchored to the survey date for the relevant county rather than a single national date. Static deep linking to unique individual record identifiers is not supported by this repository due to session-based architecture; the template instead executes a parameterised name and county search query. All three URL parameters (`occupier_surname`, `occupier_forename`, `county`) are Record-level — they vary per entry — so `source_parameters` is null.

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

**Notes:** The Tithe Applotment Books record pre-Famine agricultural occupiers tithed to support the established church. The record URL points straight to the National Archives of Ireland's static PDF images. Both `reel_id` (the microfilm reel folder) and `image_id` (the page within that reel) vary per Record, so `source_parameters` is null. Note that the double slash (`//`) within the file directory path is mandatory for server resolution.

---

### Source 3 — Census 1901

| Field | Value |
|---|---|
| source_id | 3 |
| repository_id | 1 (National Archives of Ireland) |
| type | census |
| coverage | 1901 |
| source_url | https://nationalarchives.ie/collections/search-the-census/ |
| record_url_template | https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id} |
| source_parameters | null |
| record_parameter_names | document_id |
| column_schema | document_id, household_id, line_number, surname, forename, relation_to_head, religion, literacy, age, sex, occupation, marriage_status, birthplace, irish_language, medical_disability, county, ded, townland, house_number |

**Notes:** The 1901 census is the earliest surviving complete decennial return for the island. The template targets the NAI's centralised PDF delivery mechanism directly. The `document_id` is a flat, unique string representing the specific Form A page scan and varies per Record, so `source_parameters` is null. The legacy domain `census.nationalarchives.ie` is obsolete.

---

### Source 4 — Census 1911

| Field | Value |
|---|---|
| source_id | 4 |
| repository_id | 1 (National Archives of Ireland) |
| type | census |
| coverage | 1911 |
| source_url | https://nationalarchives.ie/collections/search-the-census/ |
| record_url_template | https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id} |
| source_parameters | null |
| record_parameter_names | document_id |
| column_schema | id, census_year, county, surname, firstname, townland, townland_clean, ded, age, sex, house_number, relation_to_head, religion, education, occupation, marriage_status, marriage_years, children_born, children_living, birthplace, language, deafdumb, image_group, religion_updated, occupation_updated, relation_to_head_updated, language_updated, images, ded_clean |
| nai_ingest_mapping | document_id ← first image id extracted from `images` field; household_id ← `image_group`; role ← `relation_to_head_updated` (fallback: `relation_to_head`) via census role mapping table in `data_dictionary.md` §6.4 |

**Notes:** The column_schema reflects the NAI census download CSV format exactly as published. This is the gold standard input format for census ingest — no column transformation is required. The `images` field contains a JSON-serialised list of image objects; Python extracts the first Form A image ID as `document_id` for `record_parameters` and for the deep link. The `image_group` field is the NAI's household grouping identifier and serves as `household_id` for grouping persons into Records. One Record is created per household (one Form A page); all persons in the household share that Record. Role assignment is fully automated via the `relation_to_head_updated` mapping — no Claude involvement required. The `_updated` suffix fields (`religion_updated`, `occupation_updated`, `relation_to_head_updated`, `language_updated`) contain NAI-normalised values and are preferred over their raw counterparts for all structured fields. The 1911 census adds marital history fields (`marriage_years`, `children_born`, `children_living`) that enable precise family reconstruction modelling.

---

### Source 5 — Census 1926

| Field | Value |
|---|---|
| source_id | 5 |
| repository_id | 1 (National Archives of Ireland) |
| type | census |
| coverage | 1926 |
| source_url | https://nationalarchives.ie/collections/search-the-1926-census/ |
| record_url_template | https://nationalarchives.ie/collections/search-the-1926-census/view-1926-pdf/?doc={document_id} |
| source_parameters | null |
| record_parameter_names | document_id |
| column_schema | aform_name, county, townland, ded, first_name, surname, relationship_to_head, updated_relationship_to_head, updated_sex, updated_marriage, irish_or_english, years_married, birthplace_county, children_born_alive, children_living, updated_age, geocode, institution_name, institution_type, image_group, a_id |
| nai_ingest_mapping | document_id ← `aform_name`; household_id ← `image_group`; role ← `updated_relationship_to_head` (fallback: `relationship_to_head`) via census role mapping table in `data_dictionary.md` §6.4 |

**Notes:** The 1926 Census was the first census executed by the independent Irish Free State. The 1926 source uses a distinct URL path (`view-1926-pdf`) from the 1901 and 1911 templates, requiring a separate Source entry. `document_id` is the sole Record-level parameter and `source_parameters` is null. The column schema reflects the 1926 NAI download format and captures its QA-clean fields, including `aform_name` for the Form A document ID and `updated_relationship_to_head` for relationship inference. The ingest pipeline normalizes these fields into the shared census schema so the same household and role inference logic can handle 1901, 1911, and 1926.

---

### Source 6 — Civil Birth Registrations

| Field | Value |
|---|---|
| source_id | 6 |
| repository_id | 4 (irishgenealogy.ie) |
| type | birth_registration |
| coverage | 1864–1925 (index & register images) |
| source_url | https://www.irishgenealogy.ie |
| record_url_template | https://civilrecords.irishgenealogy.ie/churchrecords/images/birth_returns/births_{year}/{folder_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | year, folder_id, image_id |
| column_schema | year, folder_id, image_id, registration_id, group_id, child_forename, child_surname, sex, date_of_birth, place_of_birth, father_name, father_occupation, mother_name, mother_maiden_name, informant_qualification, informant_address, registration_date, registrar_district, superintendent_district, county |

**Notes:** Civil registration of births covers all denominations from 1 January 1864. All three URL parameters (`year`, `folder_id`, `image_id`) vary per Record — year changes across records even within a single ingestion batch — so `source_parameters` is null. The index provides mother's maiden names consistently for entries from 1900 onward; earlier register images must be manually transcribed to capture this field.

---

### Source 7 — Civil Marriage Registrations

| Field | Value |
|---|---|
| source_id | 7 |
| repository_id | 4 (irishgenealogy.ie) |
| type | marriage_registration |
| coverage | 1845–1950 (Non-Catholic from 1845; all denominations from 1864) |
| source_url | https://www.irishgenealogy.ie |
| record_url_template | https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_{year}/{folder_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | year, folder_id, image_id |
| column_schema | year, folder_id, image_id, registration_id, group_id, date_of_marriage, groom_forename, groom_surname, groom_age, groom_condition, groom_occupation, groom_residence, groom_father_name, groom_father_occupation, bride_forename, bride_surname, bride_age, bride_condition, bride_occupation, bride_residence, bride_father_name, bride_father_occupation, place_of_celebration, witness_1_name, witness_2_name, celebrant, registrar_district, county |

**Notes:** Civil marriage registration captures two generations of occupation and residency data, along with formal witnesses. Non-Catholic marriages are registered from 1 April 1845; all denominations including Roman Catholic marriages are covered from 1 January 1864. As with births and deaths, all three URL parameters vary per Record and `source_parameters` is null.

---

### Source 8 — Civil Death Registrations

| Field | Value |
|---|---|
| source_id | 8 |
| repository_id | 4 (irishgenealogy.ie) |
| type | death_registration |
| coverage | 1864–1975 (Register images 1871–1975; index only 1864–1870) |
| source_url | https://www.irishgenealogy.ie |
| record_url_template | https://civilrecords.irishgenealogy.ie/churchrecords/images/deaths_returns/deaths_{year}/{folder_id}/{image_id}.pdf |
| source_parameters | null |
| record_parameter_names | year, folder_id, image_id |
| column_schema | year, folder_id, image_id, registration_id, group_id, deceased_forename, deceased_surname, sex, condition, age_at_death, estimated_birth_year, occupation, date_of_death, place_of_death, cause_of_death, duration_of_illness, informant_qualification, informant_address, registration_date, registrar_district, superintendent_district, county |

**Notes:** Civil death registrations record exact place of death, cause of death, and details of the informant. Age at death is a valuable indicator for family reconstruction but should be cross-verified because it depends on the informant's accuracy. All three URL parameters vary per Record and `source_parameters` is null.

---

### Source 9 — Catholic Parish Registers

| Field | Value |
|---|---|
| source_id | 9 |
| repository_id | 2 (National Library of Ireland) |
| type | parish_register |
| coverage | Varies by parish — typically 1820s–1880s for most parishes |
| source_url | https://registers.nli.ie |
| record_url_template | https://registers.nli.ie/pages/{vtls_id}_{image_number} |
| source_parameters | {"vtls_id": null} — set per ingest batch to the microfilm identifier (e.g. 634016) |
| record_parameter_names | image_number |
| column_schema | vtls_id, image_number, event_id, event_type, event_date, principal_1_forename, principal_1_surname, principal_2_forename, principal_2_surname, father_forename, father_surname, mother_forename, mother_surname, sponsor_1_name, sponsor_2_name, priest, parish_name, diocese, county |

**Notes:** The NLI Catholic Parish Registers are microfilmed sacramental records. The `vtls_id` identifies the specific microfilm volume and is constant across all Records ingested from a single microfilm — it is a Source-level parameter. The `image_number` identifies the individual folio page within that microfilm and varies per Record. A separate Source entry should be created for each microfilm volume (each distinct `vtls_id`), with `source_parameters` set to `{"vtls_id": <value>}` at the time of that ingest session.

---

### Source 10 — Bureau of Military History Witness Statements

| Field | Value |
|---|---|
| source_id | 10 |
| repository_id | 6 (Military Archives) |
| type | military |
| coverage | Statements recorded 1947–1957; events covered 1913–1921 |
| source_url | https://bmh.militaryarchives.ie |
| record_url_template | https://bmh.militaryarchives.ie/reels/bmh/BMH.WS{statement_number}.pdf |
| source_parameters | null |
| record_parameter_names | statement_number |
| column_schema | statement_number, witness_surname, witness_forename, witness_address, witness_organisation, witness_rank, pages, date_of_statement, county |

**Notes:** The Bureau of Military History collected personal witness statements from participants in the revolutionary period. The `statement_number` is a 4-digit zero-padded identifier unique to each statement and varies per Record, so `source_parameters` is null. Each statement is a self-contained document and maps to a single Record.

---

### Source 11 — Military Service Pensions Collection

| Field | Value |
|---|---|
| source_id | 11 |
| repository_id | 6 (Military Archives) |
| type | military |
| coverage | Applications processed 1924–1962; service periods 1916–1923 |
| source_url | http://mspcsearch.militaryarchives.ie |
| record_url_template | http://mspcsearch.militaryarchives.ie/docs/files/PDF_Pensions/{release_id}/{file_directory}/{filename}.pdf |
| source_parameters | {"release_id": null} — set per ingest batch to the collection release identifier (e.g. "A") |
| record_parameter_names | file_directory, filename |
| column_schema | release_id, file_directory, filename, file_reference, applicant_surname, applicant_forename, alternative_name, date_of_birth, date_of_death, address, organization, rank, service_periods, pension_awarded, next_of_kin, associated_files |

**Notes:** The Military Service Pensions Collection contains detailed personal, residential, and service declarations from veterans or their dependents. The `release_id` identifies the digitisation release batch and is constant across all Records in a given ingest session — it is a Source-level parameter. `file_directory` and `filename` identify the individual pension file within that release and vary per Record. A separate Source entry should be created for each release batch, with `source_parameters` set to `{"release_id": <value>}` at the time of that ingest session.

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

**Notes:** The Schools Collection consists of local folklore, family customs, and historical memory recorded by schoolchildren across primary schools in the late 1930s. All three URL parameters (`volume_id`, `school_id`, `page_id`) vary per Record across a typical ingestion batch spanning multiple schools and volumes, so `source_parameters` is null. Where an ingest session is scoped to a single school or volume, `volume_id` or `school_id` could be promoted to `source_parameters` as a convenience — but this is not required by the schema.

---

*This document should be brought into context for all transcription and ingestion sessions.*

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | May 2026 | Initial repositories document — 7 repositories, 12 sources |
| 1.1 | May 2026 | Minor corrections |
| 1.2 | May 2026 | Replaced single `record_url_template` parameter model with two-level parameter system. Added `source_parameters` and `record_parameter_names` fields to all Source entries. Sources 9 (NLI Parish Registers) and 11 (Military Service Pensions) identified as requiring Source-level parameters (`vtls_id` and `release_id` respectively). Updated §1 overview to explain deep link construction. Updated §3 section intro. |
| 1.3 | May 2026 | Updated Source 4 (Census 1911) column_schema to match NAI census download CSV format exactly. Added `nai_ingest_mapping` field documenting `document_id`, `household_id`, and role extraction from the download format. Updated notes to describe NAI download as gold standard input, explain `_updated` field preference, image extraction for `document_id`, and `image_group` as `household_id`. |
