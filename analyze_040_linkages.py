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
        'D': '3', 'T': '3', 'L': '4',
        'M': '5', 'N': '5', 'R': '6'
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
        
        try:
            surname_idx = header.index('surname')
            firstname_idx = header.index('firstname')
            age_idx = header.index('age')
            occupation_idx = header.index('occupation')
            relation_idx = header.index('relation_to_head')
            townland_idx = header.index('townland_clean')
            census_year_idx = header.index('census_year')
        except ValueError:
            return None
        
        return {
            'surname': data_parts[surname_idx] if surname_idx < len(data_parts) else None,
            'firstname': data_parts[firstname_idx] if firstname_idx < len(data_parts) else None,
            'age': data_parts[age_idx] if age_idx < len(data_parts) else None,
            'occupation': data_parts[occupation_idx] if occupation_idx < len(data_parts) else None,
            'relation': data_parts[relation_idx] if relation_idx < len(data_parts) else None,
            'townland': data_parts[townland_idx] if townland_idx < len(data_parts) else None,
            'census_year': int(data_parts[census_year_idx]) if census_year_idx < len(data_parts) else None,
        }
    except Exception as e:
        return None

def parse_age(age_str):
    if not age_str:
        return None
    try:
        if '-' in str(age_str):
            parts = str(age_str).split('-')
            return float(parts[0])
        return float(age_str)
    except:
        return None

IRISH_NAME_VARIANTS = {
    'john': ['sean', 'shawn', 'jon', 'johnny'],
    'william': ['liam', 'willy', 'bill'],
    'james': ['jim', 'jimmy', 'seamus'],
    'mary': ['marie', 'maura', 'maira'],
    'patrick': ['paddy', 'pat'],
    'michael': ['mike', 'mick', 'micheal'],
}

def is_plausible_name_variant(name1, name2):
    n1 = name1.lower()
    n2 = name2.lower()
    if n1 == n2:
        return True
    for key, variants in IRISH_NAME_VARIANTS.items():
        if n1 == key or n1 in variants:
            if n2 == key or n2 in variants:
                return True
    return False

conn = psycopg2.connect(
    dbname="gra_test",
    user="mmulligan",
    host="localhost",
    port=5432
)
cursor = conn.cursor()

print("Extracting similarities at 0.40 threshold...")
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
print(f"Found {len(linkages_040)} linkages at 0.40 threshold\n")

# Analyze first 100
stats = {
    'exact_surname': 0, 'phonetic_surname': 0, 'surname_mismatch': 0,
    'exact_first': 0, 'variant_first': 0, 'suspicious_first': 0,
    'plausible_age': 0, 'suspicious_age': 0, 'age_regression': 0,
    'same_occupation': 0, 'plausible_occ': 0, 'suspicious_occ': 0,
    'same_role': 0, 'coherent_role': 0, 'suspicious_role': 0,
    'same_townland': 0, 'moved': 0,
}

linkage_details = []

sample = linkages_040[:100]
print(f"Analyzing {len(sample)} weakest linkages...\n")

for link_idx, (link_id, rec_id_1, rec_id_2, score, raw_1, raw_2) in enumerate(sample):
    r1 = parse_record(raw_1)
    r2 = parse_record(raw_2)
    if not r1 or not r2:
        continue
    
    detail = {
        'score': score, 'year1': r1.get('census_year'), 'year2': r2.get('census_year'),
        'name1': f"{r1.get('firstname', '')} {r1.get('surname', '')}", 
        'name2': f"{r2.get('firstname', '')} {r2.get('surname', '')}",
        'issues': []
    }
    
    # Surname
    s1, s2 = r1.get('surname', ''), r2.get('surname', '')
    if s1 and s2:
        if s1.lower() == s2.lower():
            stats['exact_surname'] += 1
        elif soundex(s1) == soundex(s2):
            stats['phonetic_surname'] += 1
        else:
            stats['surname_mismatch'] += 1
            detail['issues'].append(f"Surname mismatch: {s1} vs {s2}")
    
    # First name
    f1, f2 = r1.get('firstname', ''), r2.get('firstname', '')
    if f1 and f2:
        if f1.lower() == f2.lower():
            stats['exact_first'] += 1
        elif is_plausible_name_variant(f1, f2):
            stats['variant_first'] += 1
        else:
            stats['suspicious_first'] += 1
            detail['issues'].append(f"Suspicious name: {f1} to {f2}")
    
    # Age
    a1, a2 = parse_age(r1.get('age')), parse_age(r2.get('age'))
    if a1 and a2:
        yr1, yr2 = r1.get('census_year'), r2.get('census_year')
        if yr1 and yr2:
            exp_diff = yr2 - yr1
            act_diff = a2 - a1
            if abs(act_diff - exp_diff) <= 3:
                stats['plausible_age'] += 1
            elif act_diff < 0:
                stats['age_regression'] += 1
                detail['issues'].append(f"Age regression: {a1} to {a2}")
            else:
                stats['suspicious_age'] += 1
                detail['issues'].append(f"Age gap: {a1} ({yr1}) to {a2} ({yr2})")
    
    # Occupation
    occ1, occ2 = r1.get('occupation', '').lower(), r2.get('occupation', '').lower()
    if occ1 and occ2:
        if occ1 == occ2:
            stats['same_occupation'] += 1
        elif 'farmer' in occ1 and 'farmer' in occ2:
            stats['plausible_occ'] += 1
        else:
            stats['plausible_occ'] += 1
    
    # Role
    rol1, rol2 = r1.get('relation', '').lower(), r2.get('relation', '').lower()
    if rol1 and rol2:
        if rol1 == rol2:
            stats['same_role'] += 1
        elif ('head' in rol1 and ('son' in rol2 or 'daughter' in rol2)) or \
             ('wife' in rol1 and ('son' in rol2 or 'daughter' in rol2)):
            stats['suspicious_role'] += 1
            detail['issues'].append(f"Role inversion: {rol1} to {rol2}")
        else:
            stats['coherent_role'] += 1
    
    # Townland
    t1, t2 = r1.get('townland', '').lower(), r2.get('townland', '').lower()
    if t1 and t2:
        if t1 == t2:
            stats['same_townland'] += 1
        else:
            stats['moved'] += 1
            detail['issues'].append(f"Geographic move: {t1} to {t2}")
    
    linkage_details.append(detail)

print("QUALITY ANALYSIS RESULTS")
print("=" * 50)
print(f"Total linkages at 0.40: {len(linkages_040)}")
print(f"Sample analyzed: {len(linkage_details)}")
print(f"\n1. SURNAME CONSISTENCY:")
print(f"   Exact: {stats['exact_surname']}, Phonetic: {stats['phonetic_surname']}, Mismatch: {stats['surname_mismatch']}")
print(f"\n2. FIRST NAME CONSISTENCY:")
print(f"   Exact: {stats['exact_first']}, Variant: {stats['variant_first']}, Suspicious: {stats['suspicious_first']}")
print(f"\n3. AGE PROGRESSION:")
print(f"   Plausible: {stats['plausible_age']}, Suspicious: {stats['suspicious_age']}, Regression: {stats['age_regression']}")
print(f"\n4. OCCUPATIONAL:")
print(f"   Same: {stats['same_occupation']}, Plausible: {stats['plausible_occ']}, Suspicious: {stats['suspicious_occ']}")
print(f"\n5. HOUSEHOLD ROLE:")
print(f"   Same: {stats['same_role']}, Coherent: {stats['coherent_role']}, Suspicious: {stats['suspicious_role']}")
print(f"\n6. GEOGRAPHIC:")
print(f"   Same townland: {stats['same_townland']}, Moved: {stats['moved']}")

print(f"\n\nTOP 20 PROBLEMATIC LINKAGES")
print("=" * 50)
problematic = [l for l in linkage_details if len(l.get('issues', [])) > 0]
problematic.sort(key=lambda x: x['score'])

for i, link in enumerate(problematic[:20], 1):
    print(f"\n{i}. Score: {link['score']:.4f} | {link['year1']} to {link['year2']}")
    print(f"   {link['name1']} vs {link['name2']}")
    for issue in link['issues']:
        print(f"   - {issue}")

conn.close()
