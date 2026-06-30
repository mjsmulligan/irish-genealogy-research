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
    """List all persons with linkage stats."""
    repo = get_db()

    # Get page params
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    # Get total count
    result = repo.fetch_one('SELECT COUNT(*) as count FROM person')
    total = result['count']
    total_pages = (total + per_page - 1) // per_page

    # Get persons with linkage stats and a label
    query = '''
    SELECT
      p.person_id,
      p.status,
      COUNT(DISTINCT prp.recorded_person_id) as record_count,
      COUNT(DISTINCT CASE WHEN r.record_id IS NOT NULL THEN r.source_id END) as census_count,
      STRING_AGG(DISTINCT s.title, ', ' ORDER BY s.title) as censuses,
      COALESCE(MAX(rp.name_as_recorded), 'Unknown') as label
    FROM person p
    LEFT JOIN person_recorded_person prp ON p.person_id = prp.person_id
    LEFT JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
    LEFT JOIN record r ON rp.record_id = r.record_id
    LEFT JOIN source s ON r.source_id = s.source_id
    GROUP BY p.person_id, p.status
    ORDER BY p.person_id
    LIMIT %s OFFSET %s
    '''

    persons = repo.fetch_all(query, (per_page, offset))
    repo.close()

    return render_template('index.html',
                         persons=persons,
                         page=page,
                         total_pages=total_pages,
                         total=total)


@app.route('/person/<int:person_id>')
def detail(person_id):
    """Show detail view for a person."""
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

    # Get relationships with other person's name
    relationships_query = '''
    SELECT
      rel.relationship_id,
      rel.type,
      rel.person_id_1,
      rel.person_id_2,
      CASE
        WHEN rel.person_id_1 = %s THEN rel.person_id_2
        ELSE rel.person_id_1
      END as other_person_id,
      CASE
        WHEN rel.person_id_1 = %s THEN other_p.label
        ELSE self_p.label
      END as other_person_label
    FROM relationship rel
    LEFT JOIN (
      SELECT DISTINCT prp.person_id, MAX(rp.name_as_recorded) as label
      FROM person_recorded_person prp
      JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
      GROUP BY prp.person_id
    ) other_p ON other_p.person_id = rel.person_id_2
    LEFT JOIN (
      SELECT DISTINCT prp.person_id, MAX(rp.name_as_recorded) as label
      FROM person_recorded_person prp
      JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
      GROUP BY prp.person_id
    ) self_p ON self_p.person_id = rel.person_id_1
    WHERE rel.person_id_1 = %s OR rel.person_id_2 = %s
    '''

    relationships = repo.fetch_all(relationships_query, (person_id, person_id, person_id, person_id))
    repo.close()

    # Group recorded persons by census
    by_census = {}
    for rp in recorded_persons:
        census_year = rp['source_title']
        if census_year not in by_census:
            by_census[census_year] = []
        by_census[census_year].append(rp)

    return render_template('detail.html',
                         person=person,
                         by_census=by_census,
                         relationships=relationships)


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
