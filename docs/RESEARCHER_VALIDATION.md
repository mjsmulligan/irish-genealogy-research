# Researcher Validation Guide

## Purpose

The validation dataset is designed for genealogists and researchers to manually review and validate the computer-generated linkages produced by the GRA pipeline. This provides a "researcher benchmark" for what level of linking is expected in Tullynaught across the three census sources (1901, 1911, 1926).

## Generating the Validation Dataset

Export the complete validation dataset (all persons from all three censuses) with one command:

```bash
python -m src.cli export-validation -o validation_dataset.csv
```

This creates a CSV file ready for manual review in Excel, Google Sheets, or any spreadsheet application.

## Dataset Structure

The validation CSV contains one row per person record with these columns:

| Column | Purpose |
|--------|---------|
| `census_year` | Census year (1901-03-31, 1911-04-02, 1926-04-18) |
| `household_id` | Unique household record identifier |
| `position_in_household` | Person's sequence within the household (1st, 2nd, 3rd, etc.) |
| `name_as_recorded` | Name exactly as it appears in the source |
| `age_as_recorded` | Age as stated in the source |
| `role` | Relationship to head (head, spouse, son, daughter, etc.) |
| `occupation_as_recorded` | Occupation as recorded in source |
| `place_as_recorded` | Place of residence details |
| `person_id` | **Linked person ID** (empty if not linked) |
| `linked_to_years` | Which census years this person is linked to (e.g., "1911-04-02, 1926-04-18") |
| `validation_notes` | **Empty column** — add your notes here during review |

## Finding Issues in the Validation Dataset

### False Positives (Incorrect Linkages)

These are records where the algorithm linked two people who **should not** be linked (different people with similar names, etc.).

**How to identify:**
- Look at rows where `person_id` is populated
- Check if `linked_to_years` shows multiple census years
- Verify the name, age progression, and occupations match **logically** across censuses
  - Names should be similar (allowing for spelling variations)
  - Age should increase by ~10 years between 1901 and 1911, ~15 years between 1911 and 1926
  - Occupations should be plausible for the same person
- If the progression doesn't make sense, it's a **false positive**

**Example of a false positive:**
```
1901: John Smith, age 25, farmer → person_id 100
1911: John Smith, age 35, farmer → person_id 100
1926: John Smith, age 48, farmer → person_id 100
```
If the ages don't match (e.g., 25 → 30 → 50), that's a false positive.

### False Negatives (Missed Linkages)

These are records where the algorithm **failed to link** two people who **should** be linked (same person across censuses, but marked as `person_id` empty).

**How to identify:**
- Look at rows where `person_id` is empty
- Check if you can match this person to other census years by name, age, occupation, and place
- If you find a match manually, it's a **false negative**

**Example of a false negative:**
```
1901: Patrick Boyle, age 30, farmer, household_id 5 → person_id empty
1911: Patrick Boyle, age 40, farmer, household_id 12 → person_id 200
1926: Patrick Boyle, age 55, farmer, household_id 18 → person_id 200
```
The 1901 record should be linked to the same person (person_id 200), but wasn't.

## Review Process

1. **Sort by household and census year** — this helps you see families together
2. **Check age progression first** — within a household, ages should be consistent relative to each other
3. **Note inconsistencies in the `validation_notes` column:**
   - For false positives: `"Should not link: ages don't match" `
   - For false negatives: `"Should link to 1911 Patrick Boyle, hh 12"`
4. **Flag patterns** — if several people in the same household are incorrectly linked, make a note
5. **Save your annotated CSV** — this becomes your researcher benchmark

## Summary Statistics

After exporting, the script displays:

```
✓ Validation dataset exported to validation_dataset.csv
  Total records: 3167

  Linkage breakdown by census year:
    1901-03-31:  255/1193 linked ( 21.4%)
    1911-04-02:  341/1080 linked ( 31.6%)
    1926-04-18:  129/ 894 linked ( 14.4%)

  Overall linkage rate: 22.9%
```

These percentages represent what the algorithm currently links. Your manual review will establish what the **researcher-expected** linkage rate should be.

## Using Your Annotated CSV as a Benchmark

Once you've completed your manual review:

1. Count your corrections:
   - How many false positives did you find?
   - How many false negatives did you find?

2. Calculate the "researcher benchmark":
   - True Positive Rate (correctly linked): `(linked - false_positives) / linked * 100%`
   - Recall (not missed): `(correctly_linked) / (all_actual_same_persons) * 100%`

3. This benchmark becomes your **quality gate** for future runs of the pipeline

## Tips for Accuracy

- **Be conservative with names** — spelling variations are common (O'Brien vs Obrien, etc.)
- **Check siblings** — if a household has linked person_ids, verify siblings are consistent
- **Consider emigration** — people listed in 1901 may not appear in 1911/1926 (emigrated or died)
- **Household instability** — servants, boarders, and visitors may not reappear in later censuses
- **Look for helpers** — use the `linked_to_years` column to see patterns of what IS linked
