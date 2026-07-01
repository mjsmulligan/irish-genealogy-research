"""Simple Flask web app for browsing GRA persons and linkages."""

from flask import Flask, render_template, request, jsonify
from src.db.db import open_db
from markupsafe import Markup, escape
from pathlib import Path
import os
import re
import json
import ast

_HERE = Path(__file__).parent
app = Flask(__name__, template_folder=str(_HERE / 'templates'), static_folder=str(_HERE / 'static'))

# Add built-in functions to Jinja2 context
app.jinja_env.globals.update(max=max, min=min)


_PERSON_RE = re.compile(r'\bPerson (\d+)\b')


@app.template_filter('linkify_persons')
def linkify_persons(text: str) -> Markup:
    """Replace 'Person NNNNN' with a hyperlink to /person/NNNNN."""
    escaped = str(escape(text))
    linked = _PERSON_RE.sub(
        lambda m: f'<a href="/person/{m.group(1)}">Person {m.group(1)}</a>',
        escaped,
    )
    return Markup(linked)


def build_image_url(source_id, record_parameters, raw_text=None):
    """
    Construct NAI census image URL based on source_id and record data.

    For 1901/1911: extracts document_id from record_parameters JSON
    For 1926: extracts aform_name from raw_text CSV
    """
    if source_id == 3:  # Census 1901
        try:
            params = json.loads(record_parameters) if isinstance(record_parameters, str) else record_parameters
            doc_id = params.get('document_id')
            if doc_id:
                return f"https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={doc_id}"
        except (json.JSONDecodeError, TypeError):
            pass
    elif source_id == 4:  # Census 1911
        try:
            params = json.loads(record_parameters) if isinstance(record_parameters, str) else record_parameters
            doc_id = params.get('document_id')
            if doc_id:
                return f"https://nationalarchives.ie/collections/search-the-census/view-pdf/?doc={doc_id}"
        except (json.JSONDecodeError, TypeError):
            pass
    elif source_id == 5:  # Census 1926
        # Parse CSV to find aform_name
        if raw_text:
            try:
                lines = raw_text.strip().split('\n')
                if len(lines) > 1:
                    # First line is header, second line is data
                    header = lines[0].split(',')
                    if 'aform_name' in header:
                        aform_idx = header.index('aform_name')
                        data_row = lines[1].split(',')
                        if aform_idx < len(data_row):
                            aform_name = data_row[aform_idx].strip()
                            if aform_name and aform_name != 'nan':
                                return f"https://nationalarchives.ie/collections/search-the-1926-census/view-1926-pdf/?doc={aform_name}"
            except (IndexError, ValueError):
                pass

    return None

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
    townland = request.args.get('townland', '').strip()
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
        MIN(rs.score) as weakest_link_score,
        STRING_AGG(DISTINCT LOWER(r.place_as_recorded), ', ') as places
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

    # Apply townland filter
    if townland:
        query += ' AND places ILIKE %s'
        params.append(f'%{townland.lower()}%')

    # Sort by weakest link score descending (strongest first), then by person_id
    query += ' ORDER BY COALESCE(weakest_link_score, 0.0) DESC, person_id ASC'

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
                         coverage=coverage,
                         townland=townland)


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
      r.record_parameters,
      r.raw_text,
      s.title as source_title
    FROM person_recorded_person prp
    JOIN recorded_person rp ON prp.recorded_person_id = rp.recorded_person_id
    JOIN record r ON rp.record_id = r.record_id
    JOIN source s ON r.source_id = s.source_id
    WHERE prp.person_id = %s
    ORDER BY r.source_id, r.record_id
    '''

    recorded_persons = repo.fetch_all(recorded_query, (person_id,))

    # Add image URLs to each recorded person
    for rp in recorded_persons:
        rp['image_url'] = build_image_url(rp['source_id'], rp['record_parameters'], rp['raw_text'])

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
              rp2.age,
              prp2.person_id
            FROM recorded_person rp2
            LEFT JOIN person_recorded_person prp2 ON rp2.recorded_person_id = prp2.recorded_person_id
            WHERE rp2.record_id = %s
            ORDER BY rp2.recorded_person_id
            '''

            household = repo.fetch_all(household_query, (rp['record_id'],))

            # Find head of household and other members
            for hh in household:
                if hh['role'] == 'head':
                    if head_of_household[census_year] is None:
                        head_of_household[census_year] = hh['name_as_recorded']
                else:
                    # Only add other members if they're not this person
                    if hh['recorded_person_id'] != rp['recorded_person_id']:
                        household_members[census_year].append({
                            'name': hh['name_as_recorded'],
                            'role': hh['role'],
                            'age': hh['age'],
                            'person_id': hh['person_id']
                        })

    # Build name-aligned grid for household members display.
    # Slot key: person_id-based if linked, else normalised name.
    _census_order = ['Census 1901', 'Census 1911', 'Census 1926']
    _slot_keys = []
    _slot_info = {}  # slot_key -> {label, person_id}

    for _cy in _census_order:
        for _m in household_members.get(_cy, []):
            _pid = _m.get('person_id')
            _skey = f"p:{_pid}" if _pid else f"n:{_m['name'].lower().strip()}"
            if _skey not in _slot_info:
                _slot_keys.append(_skey)
                _slot_info[_skey] = {'label': _m['name'], 'person_id': _pid}

    household_grid = []
    for _skey in _slot_keys:
        _by_year = {}
        for _cy in _census_order:
            _matched = None
            for _m in household_members.get(_cy, []):
                _pid = _m.get('person_id')
                _mk = f"p:{_pid}" if _pid else f"n:{_m['name'].lower().strip()}"
                if _mk == _skey:
                    _matched = _m
                    break
            _by_year[_cy] = _matched
        household_grid.append({
            'label': _slot_info[_skey]['label'],
            'person_id': _slot_info[_skey]['person_id'],
            'by_year': _by_year,
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

    return render_template('detail.html',
                         person=person,
                         by_census=by_census,
                         census_years=census_years,
                         head_of_household=head_of_household,
                         household_members=household_members,
                         household_grid=household_grid,
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

    # Sort logs within each group by created_at (ascending) to preserve creation order
    for group_id in grouped:
        grouped[group_id].sort(key=lambda x: x['created_at'])

    # Limit to first 20 groups
    grouped_limited = dict(list(grouped.items())[:20])

    return render_template('audit.html',
                         logs=logs,
                         grouped_logs=grouped_limited,
                         entity_type=entity_type,
                         entity_id=entity_id,
                         total_logs=len(logs))


@app.route('/review')
def review():
    """Show the latest review report."""
    reports_dir = Path(__file__).parent.parent.parent / 'reports'
    report = None
    report_file = None
    available_reports = []
    error = None

    if reports_dir.exists():
        json_files = sorted(reports_dir.glob('report_*.json'), reverse=True)
        available_reports = [f.name for f in json_files]
        requested = request.args.get('report')
        if requested and (reports_dir / requested).exists():
            target = reports_dir / requested
        elif json_files:
            target = json_files[0]
        else:
            target = None

        if target:
            report_file = target.name
            try:
                report = json.loads(target.read_text(encoding='utf-8'))
            except Exception as e:
                error = f"Could not read report: {e}"
        else:
            error = "No report files found. Run python -m src.cli review to generate one."
    else:
        error = f"Reports directory not found: {reports_dir}"

    type_filter = request.args.get('type', '')
    items = report.get('items', []) if report else []
    if type_filter:
        items = [i for i in items if i.get('finding_type') == type_filter]
    items = items[:500]

    return render_template('review.html',
                           report=report,
                           report_file=report_file,
                           available_reports=available_reports,
                           items=items,
                           type_filter=type_filter,
                           error=error)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
