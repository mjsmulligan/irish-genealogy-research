-- Migration 005: Prevent same-census linking at database level
-- Purpose: Add trigger to reject any attempt to link a person to multiple records from same census

-- Schema v4.3 (from v4.2)
-- Adds trigger function and trigger on person_recorded_person to prevent same-census links

CREATE OR REPLACE FUNCTION check_no_same_census_link()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if this person is already linked to another recorded_person from the same source_id
    IF EXISTS (
        SELECT 1 FROM person_recorded_person prp
        JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
        JOIN record r ON rp.record_id = r.record_id
        WHERE prp.person_id = NEW.person_id
        AND r.source_id = (
            SELECT r2.source_id FROM recorded_person rp2
            JOIN record r2 ON rp2.record_id = r2.record_id
            WHERE rp2.recorded_person_id = NEW.recorded_person_id
        )
        AND prp.recorded_person_id != NEW.recorded_person_id
    ) THEN
        RAISE EXCEPTION 'Cannot link person % to recorded_person % from same census source',
            NEW.person_id, NEW.recorded_person_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS prevent_same_census_link ON person_recorded_person;

CREATE TRIGGER prevent_same_census_link
BEFORE INSERT ON person_recorded_person
FOR EACH ROW
EXECUTE FUNCTION check_no_same_census_link();

-- Update schema version
UPDATE gra_meta SET value = '43' WHERE key = 'schema_version';
