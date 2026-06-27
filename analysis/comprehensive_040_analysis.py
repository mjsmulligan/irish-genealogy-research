#!/usr/bin/env python3
import psycopg2
import json
from collections import defaultdict
import re

def soundex(s):
    if not s:
        return "0000"
    s = s.upper()
    first = s[0]
    soundex_dict = {
        'B': '1', 'F': '1', 'P': '1', 'V': '1',
        'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
        'D': '3', 'T': '3', 'L': '4', 'M': '5', 'N': '5', 'R': '6'
    }
    code = ""
    prev = soundex_dict.get(first, '0')
    for c in s[1:]:
        digit = soundex_dict.get(c, '0')
        if digit != '0' and digit != prev:
            code += digit
        if digit != '0':
            prev = digit
    code = first + code
    while len(code) < 4:
        code += '0'
    return code[:4]

def parse_record(raw_text):
    try:
        lines = raw_text.split('\n')
        if len(lines) < 2:
            return None
        header = lines[0].split(',')
        data_line = lines[1]
        data_parts = data_line.split(',')
        
        idx = {}
        for field in ['surname', 'firstname', 'age', 'occupation', 'relation_to_head', 'townland_clean', 'census_year']:
            try:
                idx[field] = header.index(field)
            except ValueError:
                idx[field] = None
        
        result = {}
        for field, i in idx.items():
            if i is not None and i < len(data_parts):
                result[field] = data_parts[i]
        
        if 'census_year' in result:
            result['census_year'] = int(result['census_year'])
        
        return result if result else None
    except Exception as e:
        return None

def parse_age(age_str):
    if not age_str:
        return None
    try:
        if '-' in str(age_str):
            return float(str(age_str).split('-')[0])
        return float(age_str)
    except:
        return None

conn = psycopg2.connect(dbname="gra_test", user="mmulligan", host="localhost", port=5432)
cursor = conn.cursor()

# Get ALL linkages at 0.40
cursor.execute("""
    SELECT rs.record_similarity_id, rs.record_id_1, rs.record_id_2, rs.score,
           rec1.raw_text, rec2.raw_text
    FROM record_similarity rs
    JOIN record rec1 ON rs.record_id_1 = rec1.record_id
    JOIN record rec2 ON rs.record_id_2 = rec2.record_id
    WHERE rs.score >= 0.40
    ORDER BY rs.score ASC
""")

linkages_040 = cursor.fetchall()
conn.close()

print(f"Analyzing ALL {len(linkages_040)} linkages at 0.40 threshold\n")

# Comprehensive analysis
pass_fail_matrix = {
    'occupational': {'pass': 0, 'fail': 0, 'unknown': 0},
    'role_transition': {'pass': 0, 'fail': 0, 'unknown': 0},
    'surname_phonetic': {'pass': 0, 'fail': 0, 'unknown': 0},
    'age_outlier': {'pass': 0, 'fail': 0, 'unknown': 0},
    'first_name': {'pass': 0, 'fail': 0, 'unknown': 0},
    'geographic': {'pass': 0, 'fail': 0, 'unknown': 0},
}

problematic_linkages = []

for link_id, rec_id_1, rec_id_2, score, raw_1, raw_2 in linkages_040:
    r1 = parse_record(raw_1)
    r2 = parse_record(raw_2)
    if not r1 or not r2:
        continue
    
    issues = []
    
    # 1. OCCUPATIONAL PLAUSIBILITY
    occ1 = r1.get('occupation', '').lower().strip()
    occ2 = r2.get('occupation', '').lower().strip()
    
    if occ1 and occ2:
        if occ1 == occ2:
            pass_fail_matrix['occupational']['pass'] += 1
        elif occ1 == '' or occ2 == '':
            pass_fail_matrix['occupational']['unknown'] += 1
        else:
            # Check impossibilities
            a1 = parse_age(r1.get('age'))
            yr1 = r1.get('census_year')
            yr2 = r2.get('census_year')
            
            # Retired at age 40 is suspicious
            if yr1 and yr2 and a1:
                yrs_gap = yr2 - yr1
                if 'laborer' in occ1 or 'labourer' in occ1:
                    if 'retired' in occ2 and a1 + (yrs_gap/10)*10 < 50:
                        pass_fail_matrix['occupational']['fail'] += 1
                        issues.append(f"Retired at ~{a1+(yrs_gap/10)*10:.0f}: {occ1} -> {occ2}")
                    else:
                        pass_fail_matrix['occupational']['pass'] += 1
                else:
                    pass_fail_matrix['occupational']['pass'] += 1
            else:
                pass_fail_matrix['occupational']['pass'] += 1
    else:
        pass_fail_matrix['occupational']['unknown'] += 1
    
    # 2. ROLE TRANSITIONS
    rol1 = r1.get('relation_to_head', '').lower().strip() if 'relation_to_head' in r1 else ''
    rol2 = r2.get('relation_to_head', '').lower().strip() if 'relation_to_head' in r2 else ''
    
    if rol1 and rol2:
        # Rule: Head/Wife should not become Son/Daughter
        if ('head' in rol1 or 'wife' in rol1) and ('son' in rol2 or 'daughter' in rol2):
            pass_fail_matrix['role_transition']['fail'] += 1
            issues.append(f"Role inversion: {rol1} -> {rol2}")
        # Rule: Child should not become head in < 10 years
        elif ('son' in rol1 or 'daughter' in rol1):
            yr1 = r1.get('census_year')
            yr2 = r2.get('census_year')
            if yr1 and yr2 and 'head' in rol2 and (yr2 - yr1) < 10:
                pass_fail_matrix['role_transition']['fail'] += 1
                issues.append(f"Child head in {yr2-yr1} yrs")
            else:
                pass_fail_matrix['role_transition']['pass'] += 1
        else:
            pass_fail_matrix['role_transition']['pass'] += 1
    else:
        pass_fail_matrix['role_transition']['unknown'] += 1
    
    # 3. PHONETIC SURNAME CONSISTENCY
    surn1 = r1.get('surname', '').strip()
    surn2 = r2.get('surname', '').strip()
    
    if surn1 and surn2:
        if surn1.lower() == surn2.lower():
            pass_fail_matrix['surname_phonetic']['pass'] += 1
        elif soundex(surn1) == soundex(surn2):
            pass_fail_matrix['surname_phonetic']['pass'] += 1
        else:
            pass_fail_matrix['surname_phonetic']['fail'] += 1
            issues.append(f"Surname mismatch: {surn1} vs {surn2}")
    else:
        pass_fail_matrix['surname_phonetic']['unknown'] += 1
    
    # 4. AGE OUTLIERS
    a1 = parse_age(r1.get('age'))
    a2 = parse_age(r2.get('age'))
    yr1 = r1.get('census_year')
    yr2 = r2.get('census_year')
    
    if a1 is not None and a2 is not None and yr1 and yr2:
        exp_diff = yr2 - yr1
        act_diff = a2 - a1
        
        # Allow ±3 year tolerance
        if abs(act_diff - exp_diff) <= 3:
            pass_fail_matrix['age_outlier']['pass'] += 1
        elif act_diff < 0:
            pass_fail_matrix['age_outlier']['fail'] += 1
            issues.append(f"Age regression: {a1} ({yr1}) -> {a2} ({yr2})")
        else:
            pass_fail_matrix['age_outlier']['fail'] += 1
            issues.append(f"Age gap {act_diff} vs expected {exp_diff}")
    else:
        pass_fail_matrix['age_outlier']['unknown'] += 1
    
    # 5. FIRST NAME CONSISTENCY
    first1 = r1.get('firstname', '').strip()
    first2 = r2.get('firstname', '').strip()
    
    if first1 and first2:
        if first1.lower() == first2.lower():
            pass_fail_matrix['first_name']['pass'] += 1
        # Simple check: common variants
        elif (first1.lower() in ['elizabeth', 'liz', 'lizzie', 'betty']) and (first2.lower() in ['elizabeth', 'liz', 'lizzie', 'betty']):
            pass_fail_matrix['first_name']['pass'] += 1
        elif (first1.lower() in ['john', 'johnny', 'jon']) and (first2.lower() in ['john', 'johnny', 'jon']):
            pass_fail_matrix['first_name']['pass'] += 1
        else:
            pass_fail_matrix['first_name']['fail'] += 1
            issues.append(f"First name change: {first1} -> {first2}")
    else:
        pass_fail_matrix['first_name']['unknown'] += 1
    
    # 6. GEOGRAPHIC COHERENCE
    town1 = r1.get('townland_clean', '').strip() if 'townland_clean' in r1 else ''
    town2 = r2.get('townland_clean', '').strip() if 'townland_clean' in r2 else ''
    
    if town1 and town2:
        if town1.lower() == town2.lower():
            pass_fail_matrix['geographic']['pass'] += 1
        else:
            pass_fail_matrix['geographic']['fail'] += 1
            issues.append(f"Geographic move: {town1} -> {town2}")
    else:
        pass_fail_matrix['geographic']['unknown'] += 1
    
    if issues:
        problematic_linkages.append({
            'score': score,
            'name1': f"{first1} {surn1}",
            'name2': f"{first2} {surn2}",
            'years': f"{yr1} to {yr2}",
            'issues': issues
        })

# Report
print("COMPREHENSIVE QUALITY SCAN: 0.40 THRESHOLD LINKAGES")
print("=" * 70)
print(f"Total linkages analyzed: {len([l for l in linkages_040 if parse_record(l[4]) and parse_record(l[5])])}")

print("\n\nDIMENSION ANALYSIS:")
print("-" * 70)

for dimension, results in pass_fail_matrix.items():
    total = sum(results.values())
    if total > 0:
        pass_pct = (results['pass'] / total) * 100
        fail_pct = (results['fail'] / total) * 100
        print(f"\n{dimension.upper()}:")
        print(f"  PASS: {results['pass']} ({pass_pct:.1f}%)")
        print(f"  FAIL: {results['fail']} ({fail_pct:.1f}%)")
        print(f"  UNKNOWN: {results['unknown']}")
        
        if results['fail'] > 0:
            print(f"  --> {results['fail']} FAILING linkages detected")

# Top problematic
print("\n\nTOP 25 MOST PROBLEMATIC LINKAGES:")
print("-" * 70)
problematic_linkages.sort(key=lambda x: x['score'])

for i, link in enumerate(problematic_linkages[:25], 1):
    print(f"\n{i}. Score: {link['score']:.4f} | {link['years']}")
    print(f"   {link['name1']} -> {link['name2']}")
    for issue in link['issues']:
        print(f"   ISSUE: {issue}")

# Summary
print("\n\nCRITICAL FINDINGS:")
print("=" * 70)
total_analyzed = len([l for l in linkages_040 if parse_record(l[4]) and parse_record(l[5])])
fails = pass_fail_matrix['occupational']['fail'] + pass_fail_matrix['role_transition']['fail'] + \
        pass_fail_matrix['surname_phonetic']['fail'] + pass_fail_matrix['age_outlier']['fail'] + \
        pass_fail_matrix['first_name']['fail']

print(f"Total linkages at 0.40: {len(linkages_040)}")
print(f"Analyzed successfully: {total_analyzed}")
print(f"Total dimension failures: {fails}")
print(f"Failure rate: {(fails/max(1,total_analyzed*6))*100:.1f}%")

