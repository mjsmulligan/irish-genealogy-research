-- GRA Seed data: 8 repositories, 13 sources
-- Version 1.5 — May 2026
-- place_authority entries are NOT seeded here — loaded via fetch_places or seed-places CLI.

INSERT INTO repository VALUES (1, 'National Archives of Ireland', 'nationalarchives.ie', NULL);
INSERT INTO repository VALUES (2, 'National Library of Ireland', 'nli.ie', NULL);
INSERT INTO repository VALUES (3, 'Askaboutireland.ie', 'askaboutireland.ie', NULL);
INSERT INTO repository VALUES (4, 'irishgenealogy.ie', 'irishgenealogy.ie', NULL);
INSERT INTO repository VALUES (5, 'Central Statistics Office', 'cso.ie', NULL);
INSERT INTO repository VALUES (6, 'Military Archives', 'militaryarchives.ie', NULL);
INSERT INTO repository VALUES (7, 'Duchas.ie', 'duchas.ie', NULL);
INSERT INTO repository VALUES (8, 'Logainm.ie', 'logainm.ie', 'Official Irish placename authority operated by Foras na Gaeilge');

INSERT INTO source VALUES (3, 1, 'Census 1901', 'census', 1901, 1901, NULL, 'https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id}', NULL, '["document_id"]', '["id","census_year","county","surname","firstname","townland","townland_clean","ded","age","sex","house_number","relation_to_head","religion","education","occupation","marriage_status","birthplace","language","deafdumb","image_group","religion_updated","occupation_updated","relation_to_head_updated","language_updated","images","ded_clean"]', NULL, NULL);
INSERT INTO source VALUES (4, 1, 'Census 1911', 'census', 1911, 1911, NULL, 'https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={document_id}', NULL, '["document_id"]', '["id","census_year","county","surname","firstname","townland","townland_clean","ded","age","sex","house_number","relation_to_head","religion","education","occupation","marriage_status","marriage_years","children_born","children_living","birthplace","language","deafdumb","image_group","religion_updated","occupation_updated","relation_to_head_updated","language_updated","images","ded_clean"]', NULL, NULL);
INSERT INTO source VALUES (5, 1, 'Census 1926', 'census', 1926, 1926, NULL, 'https://nationalarchives.ie/collections/search-the-1926-census/view-1926-pdf/?doc={document_id}', NULL, '["document_id"]', '["aform_name","county","townland","ded","first_name","surname","relationship_to_head","updated_relationship_to_head","updated_sex","updated_marriage","updated_irish_language","updated_religion","years_married","irish_or_english","birthplace_county","children_born_alive","children_living","updated_age","geocode","institution_name","institution_type","image_group","a_id"]', NULL, NULL);
INSERT INTO source VALUES (13, 8, 'logainm.ie Place Authority', 'place_authority', NULL, NULL, 'https://www.logainm.ie', 'https://www.logainm.ie/en/{logainm_id}', NULL, '["logainm_id"]', '["place_id","logainm_id","name_en","place_type","parent_name","parent_id","parent_type","ded_name","ded_id","county_name","county_id","barony_name","barony_id","civil_parish_name","civil_parish_id","latitude","longitude","logainm_url","notes"]', NULL, 'logainm.ie Place Authority. Foras na Gaeilge. logainm.ie. Accessed May 2026.');
