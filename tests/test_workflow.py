import base64
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from src.parsers import parse, similarity
from src.store import Store

FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures'
PDF = base64.b64encode(b'%PDF-1.4\nsynthetic fixture, not a renderable document\n%%EOF').decode()


class ParserTests(unittest.TestCase):
    def test_ris_multiline_and_repeated_authors(self):
        text = 'TY  - JOUR\nTI  - A representative title\nAU  - One\nAU  - Two\nAB  - First line\n  continuation\nDO  - https://doi.org/10.123/ABC\nER  -\n'
        data, raw = parse(text, 'ris')[0]
        self.assertEqual(data['author'], 'One; Two')
        self.assertEqual(data['abstract'], 'First line\ncontinuation')
        self.assertEqual(data['doi'], '10.123/abc')
        self.assertEqual(raw['AU'], ['One', 'Two'])

    def test_representative_fixtures(self):
        self.assertEqual(len(parse((FIXTURES / 'sample.ris').read_text(), 'ris')), 4)
        row, raw = parse((FIXTURES / 'sample.bib').read_text(), 'bib')[0]
        self.assertEqual(row['title'], 'Community {gardens} and adult wellbeing')
        self.assertIn('@article', raw['original'])
        row, _ = parse((FIXTURES / 'sample.csv').read_text(), 'csv', {'title': 'Article title', 'abstract': 'Summary'})[0]
        self.assertIn('café', row['abstract'])
        self.assertIn(',', row['title'])

    def test_csv_multiline_and_excel_bom(self):
        rows = parse('\ufefftitle,abstract\r\n"A title","line one\nline two"\r\n', 'csv')
        self.assertEqual(rows[0][0]['abstract'], 'line one\nline two')

    def test_actionable_parser_failures(self):
        cases = [('title,year\nx,2024,extra', 'csv', 'columns'), ('TY  - JOUR\nTI  - title', 'ris', 'ER'), ('@article{x,title={broken}', 'bib', 'unbalanced'), ('@string{x="foo"}', 'bib', 'macros'), ('wrong,year\nx,2024', 'csv', 'title'), ('TY  - JOUR\nER  -', 'ris', 'title')]
        for text, fmt, error in cases:
            with self.subTest(fmt=fmt, text=text):
                with self.assertRaisesRegex(ValueError, error):
                    parse(text, fmt)

    def test_title_similarity_and_short_title_guard(self):
        self.assertGreater(similarity({'title':'Community gardens and adult wellbeing','doi':''}, {'title':'Community gardens and adult well-being','doi':''})[0], .9)
        self.assertEqual(similarity({'title':'A','doi':''}, {'title':'A','doi':''})[0], 0)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'review.sqlite3')
        self.project = self.store.create('Test review')
        self.pid = self.project['id']
        with self.store.connect() as db:
            self.r1 = self.store.rows(db, self.pid, 'reviewer')[0]
        self.r2 = self.store.add_reviewer(self.pid, 'Second', 'reviewer')
        self.adj = self.store.add_reviewer(self.pid, 'Adjudicator', 'adjudicator')
        self.store.import_records(self.pid, (FIXTURES / 'sample.ris').read_text(), 'ris', 'Synthetic source')
        self.records = self.store.backup(self.pid)['entities']['record']
        self.rid = self.records[0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def decision(self, reviewer, choice, **kwargs):
        data = dict(record=self.rid, reviewer=reviewer['id'], stage='abstract', choice=choice, reason='Ineligible population' if choice == 'exclude' else '', notes='private note', labels=['population'])
        data.update(kwargs)
        return self.store.decide(self.pid, data)

    def test_atomic_import_failure(self):
        before = self.store.backup(self.pid)
        with self.assertRaisesRegex(ValueError, 'title'):
            self.store.import_records(self.pid, 'title,year\nGood,2024\n,2023', 'csv', 'Source')
        self.assertEqual(before, self.store.backup(self.pid))

    def test_duplicate_provenance_undo_and_decision_preservation(self):
        self.decision(self.r2, 'include', record=self.records[1]['id'])
        self.store.attach(self.pid, self.records[1]['id'], 'secondary.pdf', PDF, self.r2['id'])
        before = self.store.backup(self.pid)
        v = self.store.view(self.pid, self.r1['id'])
        pair = v['duplicates'][0]
        self.assertEqual(pair['reason'], 'DOI')
        self.store.merge(self.pid, pair['keep'], pair['other'])
        v = self.store.view(self.pid, self.r1['id'])
        canonical = next(r for r in v['records'] if r['id'] == pair['keep'])
        self.assertEqual(len(canonical['provenance']), 2)
        self.assertEqual(v['counts']['active_records'], 3)
        self.assertEqual(v['counts']['duplicate_records_removed'], 1)
        self.assertEqual(before['entities']['batch'], self.store.backup(self.pid)['entities']['batch'])
        self.store.merge(self.pid, pair['keep'], pair['other'], undo=True)
        after = self.store.backup(self.pid)
        self.assertEqual([r['raw'] for r in before['entities']['record']], [r['raw'] for r in after['entities']['record']])
        self.assertEqual(before['entities']['decision'], after['entities']['decision'])
        self.assertEqual(before['entities']['pdf'], after['entities']['pdf'])
        self.assertEqual(self.store.view(self.pid, self.r1['id'])['counts']['active_records'], 4)

    def test_independence_and_blinded_presentation(self):
        self.decision(self.r1, 'include')
        self.decision(self.r2, 'exclude', notes='SECRET OTHER NOTE')
        v = self.store.view(self.pid, self.r1['id'], True)
        self.assertEqual(len(v['decisions']), 1)
        self.assertNotIn('SECRET OTHER NOTE', json.dumps(v))
        self.assertEqual(v['audit'], [])
        self.assertNotIn('abstract_conflict', v['counts'])
        self.assertEqual(v['records'][0]['outcome']['abstract'], 'include')
        other = self.store.view(self.pid, self.r2['id'], True)
        self.assertEqual(other['records'][0]['outcome']['abstract'], 'exclude')
        unblinded = self.store.view(self.pid, self.r1['id'], False)
        self.assertEqual(unblinded['records'][0]['outcome']['abstract'], 'conflict')

    def test_adjudication_and_stale_resolution(self):
        self.decision(self.r1, 'include')
        self.decision(self.r2, 'exclude')
        with self.assertRaisesRegex(ValueError, 'adjudicator'):
            self.decision(self.r1, 'include', adjudication=True)
        self.decision(self.adj, 'include', adjudication=True)
        self.assertEqual(self.store.view(self.pid, self.r1['id'], False)['records'][0]['outcome']['abstract'], 'include')
        self.decision(self.r2, 'maybe')
        v = self.store.view(self.pid, self.r1['id'], False)
        self.assertEqual(v['records'][0]['outcome']['abstract'], 'conflict')
        self.assertEqual(len(v['decisions']), 4)
        self.assertEqual(len([a for a in v['audit'] if a['action'].startswith('decision.')]), 4)

    def test_exclusion_reason_and_project_boundary(self):
        with self.assertRaisesRegex(ValueError, 'reason'):
            self.decision(self.r1, 'exclude', reason='')
        other = self.store.create('Other')
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.store.decide(other['id'], dict(record=self.rid, reviewer=self.r1['id'], stage='abstract', choice='include'))

    def test_chart_missing_vs_na_and_versions(self):
        self.store.chart(self.pid, dict(record=self.rid, reviewer=self.r1['id'], values={'country':{'status':'missing','value':''}, 'context':{'status':'na','value':''}, 'key findings':{'status':'value','value':'café'}}))
        self.store.chart(self.pid, dict(record=self.rid, reviewer=self.r1['id'], values={'country':{'status':'value','value':'Exampleland'}}))
        data = self.store.export(self.pid, 'charted').decode('utf-8-sig')
        rows = list(csv.DictReader(io.StringIO(data)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['country status'], 'missing')
        self.assertEqual(rows[0]['context status'], 'na')
        self.assertEqual(rows[0]['key findings'], 'café')
        self.assertEqual(rows[1]['country'], 'Exampleland')
        self.assertEqual(len(self.store.view(self.pid, self.r2['id'], True)['charts']), 0)

    def test_exports_history_utf8_formula_escape_and_counts(self):
        self.decision(self.r1, 'include', notes=' =HYPERLINK("evil")')
        self.decision(self.r1, 'exclude')
        output = self.store.export(self.pid, 'decisions')
        self.assertTrue(output.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.DictReader(io.StringIO(output.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['notes'][0], "'")
        self.assertEqual(rows[1]['decision'], 'exclude')
        self.assertEqual(rows[1]['reviewer'], 'Reviewer 1')
        self.assertTrue(rows[1]['timestamp'])
        counts = {r['metric']: r for r in csv.DictReader(io.StringIO(self.store.export(self.pid, 'counts').decode('utf-8-sig')))}
        self.assertEqual(counts['abstract_exclude']['count'], '1')
        self.assertEqual(counts['studies']['count'], 'not modelled')
        self.assertEqual(counts['attached_reports']['unit'], 'reports')
        audit = list(csv.DictReader(io.StringIO(self.store.export(self.pid, 'audit').decode('utf-8-sig'))))
        self.assertEqual(len([x for x in audit if x['action']=='decision.save']), 2)

    def test_backup_restore_includes_pdf_and_preserves_all_history(self):
        self.decision(self.r1, 'include')
        self.decision(self.r2, 'exclude')
        self.store.attach(self.pid, self.rid, 'fixture.pdf', PDF, self.r1['id'])
        self.store.merge(self.pid, self.records[0]['id'], self.records[1]['id'])
        before = self.store.backup(self.pid)
        restored = self.store.restore(json.loads(json.dumps(before)))
        after = self.store.backup(restored['id'])
        self.assertNotEqual(restored['id'], self.pid)
        self.assertEqual(after['entities']['pdf'][0]['content'], PDF)
        self.assertEqual(len(after['entities']['decision']), 2)
        self.assertEqual(len(after['entities']['audit']), len(before['entities']['audit']) + 1)
        self.assertEqual(after['entities']['record'][1]['merged_into'], after['entities']['record'][0]['id'])
        self.assertEqual(after['entities']['record'][0]['raw'], before['entities']['record'][0]['raw'])
        r1 = after['entities']['reviewer'][0]['id']
        self.assertEqual(self.store.view(restored['id'], r1, False)['records'][0]['outcome']['abstract'], 'conflict')
        self.assertEqual(self.store.backup(self.pid), before)

    def test_corrupt_restore_does_not_create_partial_project(self):
        before = self.store.projects()
        payload = self.store.backup(self.pid)
        payload['entities']['record'][0]['batch'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.store.restore(payload)
        self.assertEqual(self.store.projects(), before)
        payload = self.store.backup(self.pid)
        payload['entities']['record'][0]['merged_into'] = payload['entities']['record'][1]['id']
        payload['entities']['record'][1]['merged_into'] = payload['entities']['record'][0]['id']
        with self.assertRaisesRegex(ValueError, 'cyclic'):
            self.store.restore(payload)
        self.assertEqual(self.store.projects(), before)

    def test_migrations_and_archive(self):
        reopened = Store(self.store.path)
        with reopened.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.store.update(self.pid, {'name':'Renamed', 'archived':True})
        with self.assertRaisesRegex(ValueError, 'archived'):
            self.decision(self.r1, 'include')
        with self.assertRaisesRegex(ValueError, 'archived'):
            self.store.update(self.pid, {'name':'Should not change'})
        self.store.update(self.pid, {'archived':False})
        self.decision(self.r1, 'include')


if __name__ == '__main__':
    unittest.main()
