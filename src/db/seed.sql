-- GRA — Genealogy Research Assistant
-- Seed data: 7 repositories, 12 sources
-- Version 1.3 — May 2026
--
-- Applied automatically by src/db.py init_db() after schema creation.
-- Safe to re-run on an empty database; will fail on duplicate primary keys
-- if run against a populated database.

-- ---------------------------------------------------------------------------
-- REPOSITORIES
-- ---------------------------------------------------------------------------

INSERT INTO repository VALUES (1, 'National Archives of Ireland', 'nationalarchives.ie', NULL);
INSERT INTO repository VALUES (2, 'National Library of Ireland', 'nli.ie', NULL);
INSERT INTO repository VALUES (3, 'Askaboutireland.ie', 'askaboutireland.ie', NULL);
INSERT INTO repository VALUES (4, 'irishgenealogy.ie', 'irishgenealogy.ie', NULL);
INSERT INTO repository VALUES (5, 'Central Statistics Office', 'cso.ie', NULL);
INSERT INTO repository VALUES (6, 'Military Archives', 'militaryarchives.ie', NULL);
INSERT INTO repository VALUES (7, 'Duchas.ie', 'duchas.ie', NULL);

-- ---------------------------------------------------------------------------
-- SOURCES
-- ---------------------------------------------------------------------------

-- Source 1 — Griffith's Valuation
INSERT INTO source VALUES (
    1, 3,
    'Griffith''s Valuation',
    'valuation',
    1847, 1864,
    'https://www.askaboutireland.ie/griffiths-valuation',
    'https://www.askaboutireland.ie/griffith-valuation/index.xml?action=doNameSearch&familyname={occupier_surname}&firstname={occupier_forename}&countyname={county}',
    NULL,
    '["occupier_surname", "occupier_forename", "county"]',
    '["occupier_surname", "occupier_forename", "lessor_surname", "lessor_forename", "county", "barony", "parish", "townland", "street", "map_reference", "acres", "roods", "perches", "land_valuation", "building_valuation", "total_valuation"]',
    NULL,
    'Griffith''s Primary Valuation. Askaboutireland.ie. Accessed May 2026.'
);

-- Source 2 — Tithe Applotment Books
INSERT INTO source VALUES (
    2, 1,
    'Tithe Applotment Books',
    'tithe',
    1823, 1837,
    'https://titheapplotmentbooks.nationalarchives.ie',
    'https://titheapplotmentbooks.nationalarchives.ie/reels/tab//{reel_id}/{image_id}.pdf',
    NULL,
    '["reel_id", "image_id"]',
    '["reel_id", "image_id", "occupier_surname", "occupier_forename", "county", "parish", "townland", "year", "land_holding_class", "acres", "roods", "perches", "tithe_amount_pounds", "tithe_amount_shillings", "tithe_amount_pence"]',
    NULL,
    'Tithe Applotment Books 1823–1837. National Archives of Ireland. Accessed May 2026.'
);

-- Source 3 — Census 1901
INSERT INTO source VALUES (
    3, 1,
    'Census 1901',
    'census',
    1901, 1901,
    'https://nationalarchives.ie/collections/search-the-census/',
    'https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id}',
    NULL,
    '["document_id"]',
    '["id", "census_year", "county", "surname", "firstname", "townland", "townland_clean", "ded", "age", "sex", "house_number", "relation_to_head", "religion", "education", "occupation", "marriage_status", "birthplace", "language", "deafdumb", "image_group", "religion_updated", "occupation_updated", "relation_to_head_updated", "language_updated", "images", "ded_clean"]',
    NULL,
    'Census of Ireland 1901. National Archives of Ireland. nationalarchives.ie. Accessed May 2026.'
);

-- Source 4 — Census 1911
INSERT INTO source VALUES (
    4, 1,
    'Census 1911',
    'census',
    1911, 1911,
    'https://nationalarchives.ie/collections/search-the-census/',
    'https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id}',
    NULL,
    '["document_id"]',
    '["id", "census_year", "county", "surname", "firstname", "townland", "townland_clean", "ded", "age", "sex", "house_number", "relation_to_head", "religion", "education", "occupation", "marriage_status", "marriage_years", "children_born", "children_living", "birthplace", "language", "deafdumb", "image_group", "religion_updated", "occupation_updated", "relation_to_head_updated", "language_updated", "images", "ded_clean"]',
    NULL,
    'Census of Ireland 1911. National Archives of Ireland. nationalarchives.ie. Accessed May 2026.'
);

-- Source 5 — Census 1926
INSERT INTO source VALUES (
    5, 1,
    'Census 1926',
    'census',
    1926, 1926,
    'https://nationalarchives.ie/collections/search-the-1926-census/',
    'https://nationalarchives.ie/collections/search-the-1926-census/view-1926-pdf/?doc={document_id}',
    NULL,
    '["document_id"]',
    '["document_id", "household_id", "line_number", "surname", "forename", "relation_to_head", "age_years", "age_months", "sex", "marriage_status", "orphanhood_status", "birthplace", "irish_language", "religion", "personal_occupation", "employer_name", "employer_business", "unemployment_duration", "years_married", "children_born_alive", "dependencies_under_16", "county", "ded", "townland", "house_number"]',
    NULL,
    'Census of Ireland 1926. National Archives of Ireland. nationalarchives.ie. Accessed May 2026.'
);

-- Source 6 — Civil Birth Registrations
INSERT INTO source VALUES (
    6, 4,
    'Civil Birth Registrations',
    'birth_registration',
    1864, 1925,
    'https://www.irishgenealogy.ie',
    'https://civilrecords.irishgenealogy.ie/churchrecords/images/birth_returns/births_{year}/{folder_id}/{image_id}.pdf',
    NULL,
    '["year", "folder_id", "image_id"]',
    '["year", "folder_id", "image_id", "registration_id", "group_id", "child_forename", "child_surname", "sex", "date_of_birth", "place_of_birth", "father_name", "father_occupation", "mother_name", "mother_maiden_name", "informant_qualification", "informant_address", "registration_date", "registrar_district", "superintendent_district", "county"]',
    NULL,
    'Civil Birth Registrations. General Register Office, Ireland. irishgenealogy.ie. Accessed May 2026.'
);

-- Source 7 — Civil Marriage Registrations
INSERT INTO source VALUES (
    7, 4,
    'Civil Marriage Registrations',
    'marriage_registration',
    1845, 1950,
    'https://www.irishgenealogy.ie',
    'https://civilrecords.irishgenealogy.ie/churchrecords/images/marriage_returns/marriages_{year}/{folder_id}/{image_id}.pdf',
    NULL,
    '["year", "folder_id", "image_id"]',
    '["year", "folder_id", "image_id", "registration_id", "group_id", "date_of_marriage", "groom_forename", "groom_surname", "groom_age", "groom_condition", "groom_occupation", "groom_residence", "groom_father_name", "groom_father_occupation", "bride_forename", "bride_surname", "bride_age", "bride_condition", "bride_occupation", "bride_residence", "bride_father_name", "bride_father_occupation", "place_of_celebration", "witness_1_name", "witness_2_name", "celebrant", "registrar_district", "county"]',
    NULL,
    'Civil Marriage Registrations. General Register Office, Ireland. irishgenealogy.ie. Accessed May 2026.'
);

-- Source 8 — Civil Death Registrations
INSERT INTO source VALUES (
    8, 4,
    'Civil Death Registrations',
    'death_registration',
    1864, 1975,
    'https://www.irishgenealogy.ie',
    'https://civilrecords.irishgenealogy.ie/churchrecords/images/deaths_returns/deaths_{year}/{folder_id}/{image_id}.pdf',
    NULL,
    '["year", "folder_id", "image_id"]',
    '["year", "folder_id", "image_id", "registration_id", "group_id", "deceased_forename", "deceased_surname", "sex", "condition", "age_at_death", "estimated_birth_year", "occupation", "date_of_death", "place_of_death", "cause_of_death", "duration_of_illness", "informant_qualification", "informant_address", "registration_date", "registrar_district", "superintendent_district", "county"]',
    NULL,
    'Civil Death Registrations. General Register Office, Ireland. irishgenealogy.ie. Accessed May 2026.'
);

-- Source 9 — Catholic Parish Registers
-- Note: source_parameters.vtls_id is null here; set per ingest batch to the microfilm identifier.
INSERT INTO source VALUES (
    9, 2,
    'Catholic Parish Registers',
    'parish_register',
    NULL, NULL,
    'https://registers.nli.ie',
    'https://registers.nli.ie/pages/{vtls_id}_{image_number}',
    '{"vtls_id": null}',
    '["image_number"]',
    '["vtls_id", "image_number", "event_id", "event_type", "event_date", "principal_1_forename", "principal_1_surname", "principal_2_forename", "principal_2_surname", "father_forename", "father_surname", "mother_forename", "mother_surname", "sponsor_1_name", "sponsor_2_name", "priest", "parish_name", "diocese", "county"]',
    NULL,
    'Catholic Parish Registers. National Library of Ireland. registers.nli.ie. Accessed May 2026.'
);

-- Source 10 — Bureau of Military History Witness Statements
INSERT INTO source VALUES (
    10, 6,
    'Bureau of Military History Witness Statements',
    'military',
    1947, 1957,
    'https://bmh.militaryarchives.ie',
    'https://bmh.militaryarchives.ie/reels/bmh/BMH.WS{statement_number}.pdf',
    NULL,
    '["statement_number"]',
    '["statement_number", "witness_surname", "witness_forename", "witness_address", "witness_organisation", "witness_rank", "pages", "date_of_statement", "county"]',
    NULL,
    'Bureau of Military History Witness Statements. Military Archives, Ireland. bmh.militaryarchives.ie. Accessed May 2026.'
);

-- Source 11 — Military Service Pensions Collection
-- Note: source_parameters.release_id is null here; set per ingest batch to the release identifier.
INSERT INTO source VALUES (
    11, 6,
    'Military Service Pensions Collection',
    'military',
    1924, 1962,
    'http://mspcsearch.militaryarchives.ie',
    'http://mspcsearch.militaryarchives.ie/docs/files/PDF_Pensions/{release_id}/{file_directory}/{filename}.pdf',
    '{"release_id": null}',
    '["file_directory", "filename"]',
    '["release_id", "file_directory", "filename", "file_reference", "applicant_surname", "applicant_forename", "alternative_name", "date_of_birth", "date_of_death", "address", "organization", "rank", "service_periods", "pension_awarded", "next_of_kin", "associated_files"]',
    NULL,
    'Military Service Pensions Collection. Military Archives, Ireland. mspcsearch.militaryarchives.ie. Accessed May 2026.'
);

-- Source 12 — Duchas Schools Collection
INSERT INTO source VALUES (
    12, 7,
    'Duchas Schools Collection',
    'folklore',
    1937, 1939,
    'https://www.duchas.ie/en/cbes',
    'https://www.duchas.ie/en/cbes/{volume_id}/{school_id}/{page_id}',
    NULL,
    '["volume_id", "school_id", "page_id"]',
    '["volume_id", "school_id", "page_id", "story_title", "collector_name", "informant_name", "informant_age", "school_name", "parish_name", "county"]',
    NULL,
    'Duchas Schools Collection 1937–1939. Duchas.ie. Accessed May 2026.'
);
