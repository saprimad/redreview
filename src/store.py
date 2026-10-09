"""Transactional local review repository and immutable decision history."""
import base64
import csv
import io
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from .parsers import FIELDS, parse, similarity, doi, title_key

CHART_FIELDS = ['author', 'year', 'country', 'study design', 'population', 'concept', 'context', 'key findings']
KINDS = ('reviewer', 'batch', 'record', 'decision', 'chart', 'pdf', 'audit')


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


def required(value, label, limit=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{label} must contain 1–{limit} characters.')
    return value.strip()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('Database version is newer than this application; do not downgrade.')
            if version == 0:
                db.executescript('''BEGIN;
                CREATE TABLE projects(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE entities(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX entities_project_kind ON entities(project,kind);
                PRAGMA user_version=1;
                COMMIT;''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
                # Bound v1 projects so every generated backup fits the restore limit.
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='entities'").fetchone():
                    oversized = db.execute("SELECT project FROM entities GROUP BY project HAVING SUM(length(CAST(data AS BLOB))) > ?", (85 * 1024 * 1024,)).fetchone()
                    if oversized:
                        raise ValueError('This project exceeds the v1 85 MiB storage limit. Use smaller PDFs or split the review; this action was rolled back.')
        finally:
            db.close()

    def rows(self, db, project, kind):
        return [json.loads(x[0]) for x in db.execute('SELECT data FROM entities WHERE project=? AND kind=? ORDER BY rowid', (project, kind))]

    def put(self, db, project, kind, item):
        db.execute('INSERT INTO entities VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (item['id'], project, kind, json.dumps(item, ensure_ascii=False)))

    def project(self, db, pid):
        row = db.execute('SELECT data FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            raise ValueError('Project not found. Open an existing project.')
        return json.loads(row[0])

    def entity(self, db, pid, kind, eid):
        row = db.execute('SELECT data FROM entities WHERE id=? AND project=? AND kind=?', (eid, pid, kind)).fetchone()
        if not row:
            raise ValueError(f'{kind.title()} not found in this project.')
        return json.loads(row[0])

    def audit(self, db, pid, actor, action, details):
        self.put(db, pid, 'audit', {'id': uid(), 'timestamp': now(), 'reviewer': actor, 'action': action, 'details': details})

    def projects(self):
        with self.connect() as db:
            return [json.loads(x[0]) for x in db.execute('SELECT data FROM projects ORDER BY rowid')]

    def create(self, name, demo=False):
        p = {'id': uid(), 'name': required(name, 'Project name', 200), 'question': '', 'criteria': '', 'stage': 'abstract', 'archived': False, 'demo': demo, 'fields': CHART_FIELDS.copy(), 'created': now()}
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES (?,?)', (p['id'], json.dumps(p)))
            self.audit(db, p['id'], 'local operator', 'project.create', {'name': p['name']})
            self.put(db, p['id'], 'reviewer', {'id': uid(), 'name': 'Reviewer 1', 'role': 'reviewer'})
        return p

    def update(self, pid, changes):
        with self.connect() as db:
            p = self.project(db, pid)
            before = p.copy()
            if p['archived'] and any(key != 'archived' for key in changes):
                raise ValueError('Restore this archived project to active before changing its settings.')
            for key in ('name', 'question', 'criteria', 'stage', 'archived', 'fields'):
                if key in changes:
                    p[key] = changes[key]
            p['name'] = required(p['name'], 'Project name', 200)
            if p['stage'] not in ('abstract', 'fulltext', 'chart') or not isinstance(p['archived'], bool):
                raise ValueError('Invalid stage or archive flag.')
            if not isinstance(p['question'], str) or not isinstance(p['criteria'], str):
                raise ValueError('Question and criteria must be text.')
            if not isinstance(p['fields'], list) or not 1 <= len(p['fields']) <= 40 or len(set(p['fields'])) != len(p['fields']):
                raise ValueError('Provide 1–40 distinct chart field names.')
            p['fields'] = [required(f, 'Chart field', 100) for f in p['fields']]
            db.execute('UPDATE projects SET data=? WHERE id=?', (json.dumps(p), pid))
            self.audit(db, pid, 'local operator', 'project.update', {'before': before, 'after': p})
        return p

    def writable(self, db, pid):
        p = self.project(db, pid)
        if p['archived']:
            raise ValueError('This project is archived. Restore it to active before editing.')
        return p

    def add_reviewer(self, pid, name, role):
        with self.connect() as db:
            self.writable(db, pid)
            if role not in ('reviewer', 'adjudicator'):
                raise ValueError('Choose reviewer or adjudicator.')
            name = required(name, 'Reviewer name', 100)
            if any(r['name'].casefold() == name.casefold() for r in self.rows(db, pid, 'reviewer')):
                raise ValueError('A reviewer with this name already exists.')
            r = {'id': uid(), 'name': name, 'role': role}
            self.put(db, pid, 'reviewer', r)
            self.audit(db, pid, name, 'reviewer.create', r)
        return r

    def import_records(self, pid, text, fmt, source, mapping=None):
        records = parse(text, fmt, mapping)
        with self.connect() as db:
            self.writable(db, pid)
            batch = {'id': uid(), 'source': required(source, 'Source database', 200), 'format': fmt, 'timestamp': now(), 'original': text, 'count': len(records)}
            self.put(db, pid, 'batch', batch)
            for data, raw in records:
                self.put(db, pid, 'record', dict(data, id=uid(), batch=batch['id'], source=batch['source'], raw=raw, merged_into=None, merge_history=[]))
            self.audit(db, pid, 'local operator', 'import', {'batch': batch['id'], 'count': len(records), 'source': source})
        return {'count': len(records), 'batch': batch['id']}

    def import_discovery(self, pid, records, allow_uncertain=False):
        """Import provider snapshots; never trust metadata supplied by the browser."""
        if not isinstance(allow_uncertain, bool):
            raise ValueError('Uncertain-match confirmation must be true or false.')
        report = {'imported': [], 'duplicates': [], 'uncertain': [], 'failures': []}
        with self.connect() as db:
            project = self.writable(db, pid)
            if project.get('demo'):
                raise ValueError('Import real articles into a non-demo project to keep synthetic data separate.')
            existing = self.rows(db, pid, 'record')
            batch = {'id': uid(), 'source': 'Scholarly discovery', 'format': 'discovery', 'timestamp': now(),
                     'original': json.dumps(records, ensure_ascii=False), 'count': 0}
            for item in records:
                title = item.get('title', '').strip()
                rid = item['result_id']
                if not title:
                    report['failures'].append({'result_id': rid, 'reason': 'Provider did not supply a title; record was not imported.'})
                    continue
                exact, possible = [], []
                for old in existing:
                    reason = None
                    if item.get('doi') and doi(item['doi']) == doi(old.get('doi', '')):
                        reason = 'DOI'
                    elif item.get('pmid') and item['pmid'] == old.get('pmid'):
                        reason = 'PMID'
                    elif item.get('provider_id') and item['provider_id'] == old.get('provider_id') and item['provider'] == old.get('provider'):
                        reason = 'Provider identifier'
                    if reason:
                        exact.append((old, reason))
                        continue
                    # Conflicting known IDs should not be silently treated as the same article.
                    conflict = any(item.get(k) and old.get(k) and item[k] != old[k] for k in ('doi', 'pmid'))
                    score, _ = similarity(dict(item, doi=''), dict(old, doi=''))
                    compatible_year = not item.get('year') or not old.get('year') or item['year'] == old['year']
                    if not conflict and compatible_year and score >= .94 and len(title_key(title)) >= 25:
                        possible.append({'record': old['id'], 'title': old['title'], 'year': old['year'], 'score': round(score, 3)})
                if exact:
                    old, reason = exact[0]
                    retrieval = {k: item.get(k) for k in ('provider', 'provider_id', 'search_query', 'retrieved_at', 'doi', 'pmid')}
                    old.setdefault('discovery_retrievals', []).append(retrieval)
                    self.put(db, pid, 'record', old)
                    report['duplicates'].append({'result_id': rid, 'record': old['id'], 'title': old['title'], 'reason': reason})
                    continue
                if possible and not allow_uncertain:
                    report['uncertain'].append({'result_id': rid, 'title': title, 'matches': possible})
                    continue
                data = {f: str(item.get(f) or '') for f in FIELDS}
                data.update({k: item.get(k) for k in ('journal', 'pmid', 'provider', 'provider_id', 'search_query', 'retrieved_at', 'oa_url', 'pdf_url', 'is_oa')})
                record = dict(data, id=uid(), batch=batch['id'], source=item['provider'], raw=item,
                              merged_into=None, merge_history=[], uncertain_matches=possible)
                self.put(db, pid, 'record', record)
                existing.append(record)
                batch['count'] += 1
                report['imported'].append({'result_id': rid, 'record': record['id'], 'title': title})
            if batch['count']:
                self.put(db, pid, 'batch', batch)
            self.audit(db, pid, 'local operator', 'discovery.import', dict(report, retrievals=records, allow_uncertain=allow_uncertain))
        return report

    def merge(self, pid, keep, other, undo=False):
        with self.connect() as db:
            self.writable(db, pid)
            a = self.entity(db, pid, 'record', keep)
            b = self.entity(db, pid, 'record', other)
            if keep == other or a['merged_into']:
                raise ValueError('Choose two different active records.')
            if undo:
                if b['merged_into'] != keep:
                    raise ValueError('This merge is no longer active.')
                b['merged_into'] = None
            else:
                if b['merged_into'] or any(r['merged_into'] == other for r in self.rows(db, pid, 'record')):
                    raise ValueError('Undo existing merges before merging this record. Nested merges are unsupported.')
                b['merged_into'] = keep
            b['merge_history'].append({'timestamp': now(), 'target': keep, 'action': 'undo' if undo else 'merge'})
            self.put(db, pid, 'record', b)
            self.audit(db, pid, 'local operator', 'merge.undo' if undo else 'merge.confirm', {'keep': keep, 'other': other})

    def decide(self, pid, data):
        with self.connect() as db:
            self.writable(db, pid)
            record = self.entity(db, pid, 'record', data.get('record'))
            reviewer = self.entity(db, pid, 'reviewer', data.get('reviewer'))
            if record['merged_into']:
                raise ValueError('Screen the canonical record or undo the merge first.')
            stage, choice = data.get('stage'), data.get('choice')
            if stage not in ('abstract', 'fulltext') or choice not in ('include', 'exclude', 'maybe'):
                raise ValueError('Invalid screening stage or decision.')
            reason = str(data.get('reason', '')).strip()
            if choice == 'exclude' and not reason:
                raise ValueError('Provide an exclusion reason before saving Exclude.')
            adjudication = data.get('adjudication', False)
            if not isinstance(adjudication, bool):
                raise ValueError('Invalid adjudication flag.')
            if adjudication:
                if reviewer['role'] != 'adjudicator':
                    raise ValueError('Select an adjudicator profile to resolve a conflict.')
                existing = self.latest(self.rows(db, pid, 'decision'), record['id'], stage)
                if len({x['choice'] for x in existing if not x['adjudication']}) < 2:
                    raise ValueError('No conflicting reviewer decisions to adjudicate.')
            labels = data.get('labels', [])
            if not isinstance(labels, list) or any(not isinstance(x, str) for x in labels):
                raise ValueError('Labels must be text.')
            d = {'id': uid(), 'record': record['id'], 'reviewer': reviewer['id'], 'reviewer_name': reviewer['name'], 'stage': stage, 'choice': choice, 'reason': reason, 'notes': str(data.get('notes', '')), 'labels': labels, 'adjudication': adjudication, 'timestamp': now()}
            self.put(db, pid, 'decision', d)
            self.audit(db, pid, reviewer['name'], 'decision.adjudicate' if adjudication else 'decision.save', d)
        return d

    @staticmethod
    def latest(decisions, rid, stage):
        latest = {}
        for d in decisions:
            if d['record'] == rid and d['stage'] == stage:
                latest[(d['reviewer'], d['adjudication'])] = d
        return list(latest.values())

    @classmethod
    def outcome(cls, decisions, rid, stage):
        current = cls.latest(decisions, rid, stage)
        ordinary = [x for x in current if not x['adjudication']]
        adjudicated = [x for x in current if x['adjudication']]
        # A later independent decision invalidates a stale adjudication.
        if adjudicated:
            a = max(adjudicated, key=lambda x: x['timestamp'])
            if all(d['timestamp'] <= a['timestamp'] for d in ordinary):
                return a['choice']
        choices = {x['choice'] for x in ordinary}
        return next(iter(choices)) if len(choices) == 1 else 'conflict' if choices else 'pending'

    def chart(self, pid, data):
        with self.connect() as db:
            p = self.writable(db, pid)
            record = self.entity(db, pid, 'record', data.get('record'))
            if record['merged_into']:
                raise ValueError('Chart the canonical record or undo the merge first.')
            r = self.entity(db, pid, 'reviewer', data.get('reviewer'))
            values = data.get('values')
            if not isinstance(values, dict) or any(f not in p['fields'] for f in values):
                raise ValueError('Chart values must use configured fields.')
            for v in values.values():
                if not isinstance(v, dict) or v.get('status') not in ('missing', 'value', 'na') or not isinstance(v.get('value'), str):
                    raise ValueError('Each chart field needs a value, missing, or not applicable status.')
                if v['status'] == 'value' and not v['value'].strip():
                    raise ValueError('Enter a value or mark the field missing.')
            item = {'id': uid(), 'record': data['record'], 'reviewer': r['id'], 'reviewer_name': r['name'], 'values': values, 'timestamp': now()}
            self.put(db, pid, 'chart', item)
            self.audit(db, pid, r['name'], 'chart.save', item)
        return item

    def attach(self, pid, rid, name, content, reviewer):
        try:
            binary = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as e:
            raise ValueError('Invalid PDF encoding. Select the file again.') from e
        if not binary.startswith(b'%PDF-') or len(binary) > 25 * 1024 * 1024:
            raise ValueError('Choose a valid PDF no larger than 25 MiB.')
        with self.connect() as db:
            self.writable(db, pid)
            self.entity(db, pid, 'record', rid)
            r = self.entity(db, pid, 'reviewer', reviewer)
            pdf = {'id': uid(), 'record': rid, 'name': required(name, 'PDF filename', 250), 'content': content, 'timestamp': now()}
            self.put(db, pid, 'pdf', pdf)
            self.audit(db, pid, r['name'], 'pdf.attach', {k: v for k, v in pdf.items() if k != 'content'})
        return {k: v for k, v in pdf.items() if k != 'content'}

    def view(self, pid, reviewer, blinded=True):
        with self.connect() as db:
            p = self.project(db, pid)
            reviewers = self.rows(db, pid, 'reviewer')
            self.entity(db, pid, 'reviewer', reviewer)
            records = self.rows(db, pid, 'record')
            decisions = self.rows(db, pid, 'decision')
            charts = self.rows(db, pid, 'chart')
            active = [r for r in records if not r['merged_into']]
            duplicates = []
            for i, a in enumerate(active):
                for b in active[i + 1:]:
                    score, reason = similarity(a, b)
                    if score >= .9:
                        duplicates.append({'keep': a['id'], 'other': b['id'], 'score': round(score, 3), 'reason': reason})
            visible = [d for d in decisions if d['reviewer'] == reviewer and not d['adjudication']] if blinded else decisions
            for r in records:
                r['provenance'] = [{'id': x['id'], 'source': x['source'], 'batch': x['batch'], 'raw': x['raw']} for x in records if x['id'] == r['id'] or x['merged_into'] == r['id']]
                r['outcome'] = {s: self.outcome(visible, r['id'], s) for s in ('abstract', 'fulltext')}
            pdfs = [{k: v for k, v in f.items() if k != 'content'} for f in self.rows(db, pid, 'pdf')]
            own_progress = {s: sum(bool(self.latest(visible, r['id'], s)) for r in active) for s in ('abstract', 'fulltext')}
            return {'project': p, 'reviewers': reviewers, 'records': records, 'decisions': visible, 'charts': [x for x in charts if not blinded or x['reviewer'] == reviewer], 'pdfs': pdfs, 'duplicates': duplicates, 'audit': [] if blinded else self.rows(db, pid, 'audit'), 'counts': {'imported_records': len(records), 'duplicate_records_removed': len(records) - len(active), 'active_records': len(active), 'attached_reports': len(pdfs), 'studies': None, 'own_progress': own_progress, **({} if blinded else self.counts(records, decisions, pdfs))}}

    def counts(self, records, decisions, pdfs):
        active = [r for r in records if not r['merged_into']]
        counts = {}
        for stage in ('abstract', 'fulltext'):
            for state in ('pending', 'include', 'exclude', 'maybe', 'conflict'):
                counts[f'{stage}_{state}'] = sum(self.outcome(decisions, r['id'], stage) == state for r in active)
        counts['reports_assessed'] = sum(self.outcome(decisions, f['record'], 'fulltext') != 'pending' for f in pdfs if any(r['id'] == f['record'] for r in active))
        return counts

    def backup(self, pid):
        with self.connect() as db:
            return {'format': 'redreview', 'version': 1, 'project': self.project(db, pid), 'entities': {kind: self.rows(db, pid, kind) for kind in KINDS}}

    def restore(self, payload):
        if not isinstance(payload, dict) or payload.get('format') != 'redreview' or payload.get('version') != 1:
            raise ValueError('Not a supported redreview v1 backup.')
        p, entities = payload.get('project'), payload.get('entities')
        if not isinstance(p, dict) or not isinstance(entities, dict) or set(entities) != set(KINDS):
            raise ValueError('Backup is incomplete.')
        required(p.get('name'), 'Backup project name', 200)
        if p.get('stage') not in ('abstract', 'fulltext', 'chart') or not isinstance(p.get('fields'), list) or not p['fields'] or len(p['fields']) > 40:
            raise ValueError('Invalid project configuration in backup.')
        if not isinstance(p.get('archived'), bool) or not isinstance(p.get('demo'), bool) or not isinstance(p.get('question'), str) or not isinstance(p.get('criteria'), str):
            raise ValueError('Invalid project metadata in backup.')
        if any(not isinstance(f, str) or not f.strip() for f in p['fields']) or len(set(p['fields'])) != len(p['fields']):
            raise ValueError('Invalid chart fields in backup.')
        ids, by_kind = {}, {}
        for kind in KINDS:
            if not isinstance(entities[kind], list):
                raise ValueError('Invalid backup entity list.')
            by_kind[kind] = set()
            for item in entities[kind]:
                if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in ids:
                    raise ValueError('Invalid or duplicate backup identifiers.')
                ids[item['id']] = uid()
                by_kind[kind].add(item['id'])
        if not entities['reviewer']:
            raise ValueError('Backup must include a reviewer.')
        for r in entities['reviewer']:
            required(r.get('name'), 'Reviewer name', 100)
            if r.get('role') not in ('reviewer', 'adjudicator'):
                raise ValueError('Invalid reviewer role in backup.')
        for b in entities['batch']:
            if not isinstance(b.get('original'), str) or not isinstance(b.get('source'), str):
                raise ValueError('Invalid import batch in backup.')
        for r in entities['record']:
            required(r.get('title'), 'Record title')
            if any(not isinstance(r.get(f), str) for f in FIELDS) or not isinstance(r.get('raw'), dict) or not isinstance(r.get('merge_history'), list):
                raise ValueError('Invalid bibliographic record in backup.')
            if r.get('batch') not in by_kind['batch'] or r.get('merged_into') and r['merged_into'] not in by_kind['record']:
                raise ValueError('Broken record provenance in backup.')
            if r.get('merged_into') == r['id']:
                raise ValueError('Invalid self merge in backup.')
        merged = {r['id']: r.get('merged_into') for r in entities['record']}
        if any(target and merged[target] for target in merged.values()):
            raise ValueError('Nested or cyclic merges in backup are unsupported.')
        for kind in ('decision', 'chart', 'pdf'):
            for item in entities[kind]:
                if item.get('record') not in by_kind['record'] or kind != 'pdf' and item.get('reviewer') not in by_kind['reviewer']:
                    raise ValueError('Broken record/reviewer reference in backup.')
                if kind == 'pdf':
                    try:
                        binary = base64.b64decode(item.get('content', ''), validate=True)
                    except (ValueError, TypeError) as e:
                        raise ValueError('Invalid PDF in backup.') from e
                    if not binary.startswith(b'%PDF-') or len(binary) > 25 * 1024 * 1024:
                        raise ValueError('Invalid PDF in backup.')
                    required(item.get('name'), 'PDF filename', 250)
                if kind == 'decision' and (item.get('choice') not in ('include', 'exclude', 'maybe') or item.get('stage') not in ('abstract', 'fulltext') or not isinstance(item.get('adjudication'), bool) or not isinstance(item.get('labels'), list) or not isinstance(item.get('notes'), str) or not isinstance(item.get('reason'), str)):
                    raise ValueError('Invalid decision in backup.')
                if kind == 'chart' and (not isinstance(item.get('values'), dict) or any(not isinstance(v, dict) or v.get('status') not in ('value', 'missing', 'na') or not isinstance(v.get('value'), str) for v in item['values'].values())):
                    raise ValueError('Invalid chart in backup.')
                required(item.get('timestamp'), 'Event timestamp', 100)
        for a in entities['audit']:
            if any(not isinstance(a.get(k), str) for k in ('timestamp', 'reviewer', 'action')) or not isinstance(a.get('details'), dict):
                raise ValueError('Invalid audit event in backup.')
        old_pid = p['id']
        pid = uid()
        ids[old_pid] = pid
        # Remap ID values recursively, including nested audit evidence.
        def remap(value):
            if isinstance(value, dict):
                return {k: v if k in ('raw', 'original', 'content') else remap(v) for k, v in value.items()}
            if isinstance(value, list):
                return [remap(v) for v in value]
            return ids.get(value, value) if isinstance(value, str) else value
        p = remap(p)
        p['name'] = p['name'][:185] + ' (restored)'
        p['archived'] = False
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES (?,?)', (pid, json.dumps(p)))
            for kind in KINDS:
                for item in entities[kind]:
                    self.put(db, pid, kind, remap(item))
            self.audit(db, pid, 'local operator', 'backup.restore', {'original_project': old_pid, 'restored_as': pid})
        return p

    def export(self, pid, category):
        backup = self.backup(pid)
        e, p = backup['entities'], backup['project']
        records = {r['id']: r for r in e['record']}
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        def cell(v):
            value = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else '' if v is None else str(v)
            # Prevent spreadsheet formula execution, including whitespace prefixes.
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        def row(values):
            writer.writerow([cell(v) for v in values])
        if category == 'records':
            fields = ['id', 'title', 'author', 'year', 'journal', 'abstract', 'doi', 'pmid', 'provider', 'provider_id', 'source', 'batch', 'search_query', 'retrieved_at', 'url', 'oa_url', 'pdf_url', 'is_oa', 'merged_into', 'discovery_retrievals']
            row(fields)
            for r in records.values():
                row([r.get(f, '') for f in fields])
        elif category == 'decisions':
            row(['record_id', 'title', 'merged_into', 'reviewer', 'stage', 'decision', 'reason', 'notes', 'labels', 'adjudication', 'timestamp'])
            for d in e['decision']:
                r = records[d['record']]
                row([r['id'], r['title'], r['merged_into'], d['reviewer_name'], d['stage'], d['choice'], d['reason'], d['notes'], d['labels'], d['adjudication'], d['timestamp']])
        elif category == 'charted':
            fields = list(dict.fromkeys(p['fields'] + [f for c in e['chart'] for f in c['values']]))
            row(['record_id', 'title', 'reviewer', 'timestamp'] + [s for f in fields for s in (f, f + ' status')])
            for c in e['chart']:
                values = []
                for f in fields:
                    v = c['values'].get(f, {'status': 'missing', 'value': ''})
                    values.extend([v['value'] if v['status'] == 'value' else '', v['status']])
                row([c['record'], records[c['record']]['title'], c['reviewer_name'], c['timestamp']] + values)
        elif category == 'audit':
            row(['event_id', 'reviewer', 'timestamp', 'action', 'details'])
            for a in e['audit']:
                row([a['id'], a['reviewer'], a['timestamp'], a['action'], a['details']])
        elif category == 'counts':
            active = [r for r in e['record'] if not r['merged_into']]
            counts = dict(imported_records=len(records), duplicate_records_removed=len(records) - len(active), active_records=len(active), attached_reports=len(e['pdf']), studies=None, **self.counts(e['record'], e['decision'], e['pdf']))
            row(['metric', 'count', 'unit'])
            for k, v in counts.items():
                row([k, 'not modelled' if v is None else v, 'studies' if k == 'studies' else 'reports' if 'reports' in k else 'records'])
        else:
            raise ValueError('Unknown export. Choose records, decisions, charted, audit, or counts.')
        return ('\ufeff' + out.getvalue()).encode('utf-8')
