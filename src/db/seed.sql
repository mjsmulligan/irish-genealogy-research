-- GRA Seed data: 8 repositories, 13 sources
-- Version 2.0 — 19 June 2026 (Postgres; explicit IDs via OVERRIDING SYSTEM VALUE)
-- place_authority entries are NOT seeded here — loaded via fetch-places or seed-places CLI.

INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (1, 'National Archives of Ireland', 'nationalarchives.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (2, 'National Library of Ireland', 'nli.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (3, 'Askaboutireland.ie', 'askaboutireland.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (4, 'irishgenealogy.ie', 'irishgenealogy.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (5, 'Central Statistics Office', 'cso.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (6, 'Military Archives', 'militaryarchives.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (7, 'Duchas.ie', 'duchas.ie', NULL);
INSERT INTO repository OVERRIDING SYSTEM VALUE VALUES (8, 'Logainm.ie', 'logainm.ie', 'Official Irish placename authority operated by Foras na Gaeilge');

-- Advance sequences past the highest seeded IDs.
-- pg_get_serial_sequence() does not work with GENERATED ALWAYS AS IDENTITY columns;
-- the sequence names follow the pattern {table}_{column}_seq.
SELECT setval('repository_repository_id_seq', 8);

INSERT INTO source OVERRIDING SYSTEM VALUE VALUES (3,  1, 'Census 1901', 'census', 1901, 1901, NULL, 'https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id}', NULL, '["document_id"]', '["id","census_year","county","surname","firstname","townland","townland_clean","ded","age","sex","house_number","relation_to_head","religion","education","occupation","marriage_status","birthplace","language","deafdumb","image_group","religion_updated","occupation_updated","relation_to_head_updated","language_updated","images","ded_clean"]', NULL, NULL);
INSERT INTO source OVERRIDING SYSTEM VALUE VALUES (4,  1, 'Census 1911', 'census', 1911, 1911, NULL, 'https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id}', NULL, '["document_id"]', '["id","census_year","county","surname","firstname","townland","townland_clean","ded","age","sex","house_number","relation_to_head","religion","education","occupation","marriage_status","marriage_years","children_born","children_living","birthplace","language","deafdumb","image_group","religion_updated","occupation_updated","relation_to_head_updated","language_updated","images","ded_clean"]', NULL, NULL);
INSERT INTO source OVERRIDING SYSTEM VALUE VALUES (5,  1, 'Census 1926', 'census', 1926, 1926, NULL, 'https://nationalarchives.ie/collections/search-the-1926-census/view-1926-pdf/?doc={document_id}', NULL, '["document_id"]', '["aform_name","county","townland","ded","first_name","surname","relationship_to_head","updated_relationship_to_head","updated_sex","updated_marriage","updated_irish_language","updated_religion","years_married","irish_or_english","birthplace_county","children_born_alive","children_living","updated_age","geocode","institution_name","institution_type","image_group","a_id"]', NULL, NULL);
INSERT INTO source OVERRIDING SYSTEM VALUE VALUES (13, 8, 'logainm.ie Place Authority', 'place_authority', NULL, NULL, 'https://www.logainm.ie', 'https://www.logainm.ie/en/{logainm_id}', NULL, '["logainm_id"]', '["place_id","logainm_id","name_en","place_type","parent_name","parent_id","parent_type","ded_name","ded_id","county_name","county_id","barony_name","barony_id","civil_parish_name","civil_parish_id","latitude","longitude","logainm_url","notes"]', NULL, 'logainm.ie Place Authority. Foras na Gaeilge. logainm.ie. Accessed May 2026.');

SELECT setval('source_source_id_seq', 13);
