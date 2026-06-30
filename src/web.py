"""Simple Flask web app for browsing GRA persons and linkages."""

from flask import Flask, render_template, request, jsonify
from src.db.db import open_db
import os

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')

# Add built-in functions to Jinja2 context
app.jinja_env.globals.update(max=max, min=min)

def get_db():
    """Get database connection."""
    repo = open_db()
    check_version = __import__('src.db.db', fromlist=['check_version']).check_version
    check_version(repo)
    return repo


@app.route('/')
def index():
    """List all persons with linkage stats, filters, and sorting."""
    repo = get_db()

    # Get filter params
    status = request.args.get('status', '')
    score_band = request.args.get('score_band', '')
    coverage = request.args.get('coverage', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    # Build base query with weakest link score
    query = '''
    WITH person_data AS (
      SELECT
        p.person_id,
        p.status,
        COUNT(DISTINCT prp.recorded_person_id) as record_count,
        COUNT(DISTINCT CASE WHEN r.record_id IS NOT NULL THEN r.source_id END) as census_count,
        STRING_AGG(DISTINCT s.title, ', ' ORDER BY s.title) as censuses,
        COALESCE(MAX(rp.name_as_recorded), 'Unknown') as label,
        MIN(rs.score) as weakest_link_score
      FROM person p
      LEFT JOIN person_recorded_person prp ON p.person_id = prp.person_id
      LEFT JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
      LEFT JOIN record r ON rp.record_id = r.record_id
      LEFT JOIN source s ON r.source_id = s.source_id
      LEFT JOIN (
        SELECT DISTINCT
          rs1.recorded_person_id_1,
          rs1.recorded_person_id_2,
          rs1.score
        FROM recorded_relationship rs1
        WHERE rs1.type = 'similarity'
      ) rs ON (
        prp.recorded_person_id = rs.recorded_person_id_1 OR
        prp.recorded_person_id = rs.recorded_person_id_2
      )
      GROUP BY p.person_id, p.status
    )
    SELECT * FROM person_data WHERE 1=1
    '''

    params = []

    # Apply status filter
    if status:
        query += ' AND status = %s'
        params.append(status)

    # Apply score band filter
    if score_band == 'amber':
        query += ' AND (weakest_link_score IS NULL OR weakest_link_score < 0.80)'
    elif score_band == 'red':
        query += ' AND (weakest_link_score IS NULL OR weakest_link_score < 0.60)'

    # Apply coverage filter
    if coverage:
        query += ' AND census_count = %s'
        params.append(int(coverage))

    # Sort by weakest link score ascending (most uncertain first), then by person_id
    query += ' ORDER BY COALESCE(weakest_link_score, 1.0) ASC, person_id ASC'

    # Count total after filters
    count_query = f'SELECT COUNT(*) as count FROM ({query}) as filtered'
    total_result = repo.fetch_one(count_query, tuple(params))
    total = total_result['count']
    total_pages = (total + per_page - 1) // per_page

    # Get paginated results
    query += ' LIMIT %s OFFSET %s'
    params.extend([per_page, offset])

    persons = repo.fetch_all(query, tuple(params))

    # Format censuses as list for template
    for person in persons:
        if person['censuses']:
            person['censuses'] = person['censuses'].split(', ')
        else:
            person['censuses'] = []

    repo.close()

    return render_template('index.html',
                         persons=persons,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         per_page=per_page,
                         status=status,
                         score_band=score_band,
                         coverage=coverage)


@app.route('/person/<int:person_id>')
def detail(person_id):
    """Show detail view for a person with cross-census table."""
    repo = get_db()

    # Get person
    person = repo.fetch_one('SELECT * FROM person WHERE person_id = %s', (person_id,))
    if not person:
        return render_template('404.html'), 404

    # Get all recorded persons for this person
    recorded_query = '''
    SELECT
      rp.recorded_person_id,
      rp.name_as_recorded,
      rp.role,
      rp.age,
      r.record_id,
      r.source_id,
      r.date,
      r.place_as_recorded as townland,
      s.title as source_title
    FROM person_recorded_person prp
    JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
    JOIN record r ON rp.record_id = r.record_id
    JOIN source s ON r.source_id = s.source_id
    WHERE prp.person_id = %s
    ORDER BY r.source_id, r.record_id
    '''

    recorded_persons = repo.fetch_all(recorded_query, (person_id,))

    # Group by census year (source_title is the census year)
    by_census = {}
    for rp in recorded_persons:
        census_year = rp['source_title']
        if census_year not in by_census:
            by_census[census_year] = []
        by_census[census_year].append(rp)

    census_years = sorted(by_census.keys())

    # Get household members for each recorded person
    household_members = {}
    head_of_household = {}

    for census_year, rp_list in by_census.items():
        household_members[census_year] = []
        head_of_household[census_year] = None

        for rp in rp_list:
            # Get all persons in same household (record)
            household_query = '''
            SELECT DISTINCT
              rp2.recorded_person_id,
              rp2.name_as_recorded,
              rp2.role,
              prp2.person_id
            FROM recorded_person rp2
            LEFT JOIN person_recorded_person prp2 ON rp2.recorded_person_id = prp2.recorded_person_id
            WHERE rp2.record_id = %s
            ORDER BY rp2.recorded_person_id
            '''

            household = repo.fetch_all(household_query, (rp['record_id'],))

            # Find head of household and other members
            for hh in household:
                if hh['role'] == 'Head':
                    if head_of_household[census_year] is None:
                        head_of_household[census_year] = hh['name_as_recorded']
                else:
                    # Only add other members if they're not this person
                    if hh['recorded_person_id'] != rp['recorded_person_id']:
                        household_members[census_year].append({
                            'name': hh['name_as_recorded'],
                            'role': hh['role'],
                            'person_id': hh['person_id']
                        })

    # Get pairwise similarity scores for this person
    pairwise_query = '''
    SELECT DISTINCT
      rs.recorded_person_id_1,
      rs.recorded_person_id_2,
      rs.score
    FROM recorded_relationship rs
    WHERE rs.type = 'similarity'
      AND (rs.recorded_person_id_1 IN (
        SELECT prp.recorded_person_id
        FROM person_recorded_person prp
        WHERE prp.person_id = %s
      ) OR rs.recorded_person_id_2 IN (
        SELECT prp.recorded_person_id
        FROM person_recorded_person prp
        WHERE prp.person_id = %s
      ))
    ORDER BY rs.score DESC
    '''

    similarity_scores = repo.fetch_all(pairwise_query, (person_id, person_id))

    # Build pairwise comparison labels (1901 vs 1911, etc.)
    pairwise_scores = []
    seen_pairs = set()

    for score_row in similarity_scores:
        rp1_id = score_row['recorded_person_id_1']
        rp2_id = score_row['recorded_person_id_2']

        # Find which census years these belong to
        year1 = None
        year2 = None

        for year, rp_list in by_census.items():
            for rp in rp_list:
                if rp['recorded_person_id'] == rp1_id:
                    year1 = year
                if rp['recorded_person_id'] == rp2_id:
                    year2 = year

        if year1 and year2 and year1 != year2:
            pair_key = tuple(sorted([year1, year2]))
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                pairwise_scores.append({
                    'label': f'{pair_key[0]} vs {pair_key[1]}',
                    'score': score_row['score']
                })

    repo.close()

    # Add image URL placeholder (to be implemented with NAI pattern)
    for rp_list in by_census.values():
        for rp in rp_list:
            rp['image_url'] = None  # TODO: construct from NAI_IMAGE_URL_PATTERN

    return render_template('detail.html',
                         person=person,
                         by_census=by_census,
                         census_years=census_years,
                         head_of_household=head_of_household,
                         household_members=household_members,
                         pairwise_scores=pairwise_scores)


@app.route('/api/search')
def search():
    """Search persons by name."""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])

    repo = get_db()

    # Search recorded persons and get their persons
    query = '''
    SELECT DISTINCT
      p.person_id,
      p.status,
      COUNT(DISTINCT rp.recorded_person_id) as record_count
    FROM person p
    JOIN person_recorded_person prp ON p.person_id = prp.person_id
    JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
    WHERE rp.name_as_recorded ILIKE %s
    GROUP BY p.person_id, p.status
    LIMIT 20
    '''

    results = repo.fetch_all(query, (f'%{q}%',))
    repo.close()

    return jsonify([{'id': r['person_id'], 'text': f"Person {r['person_id']} ({r['record_count']} records)"}
                   for r in results])


@app.route('/audit')
def audit_log():
    """Show audit log of all changes."""
    repo = get_db()

    # Get filters
    entity_type = request.args.get('entity_type', '')
    entity_id = request.args.get('entity_id', '', type=int)
    limit = request.args.get('limit', 500, type=int)

    # Build query
    query = 'SELECT * FROM conclusion_log WHERE 1=1'
    params = []

    if entity_type:
        query += ' AND entity_type = %s'
        params.append(entity_type)

    if entity_id:
        query += ' AND entity_id = %s'
        params.append(entity_id)

    query += ' ORDER BY created_at DESC LIMIT %s'
    params.append(limit)

    logs = repo.fetch_all(query, tuple(params))
    repo.close()

    # Group by change_group_id for display
    grouped = {}
    for log in logs:
        group_id = log['change_group_id']
        if group_id not in grouped:
            grouped[group_id] = []
        grouped[group_id].append(log)

    return render_template('audit.html',
                         logs=logs,
                         grouped_logs=grouped,
                         entity_type=entity_type,
                         entity_id=entity_id,
                         total_logs=len(logs))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
