import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from src.discovery import Discovery, ProviderError, crossref_record, openalex_record, pubmed_records
from src.store import Store
from tests.transport import MemorySocket
from src.server import make_handler
from types import SimpleNamespace

CROSSREF = {'DOI': '10.1000/TEST', 'title': ['A real supplied study title'], 'author': [{'given': 'A', 'family': 'Researcher'}], 'published': {'date-parts': [[2024, 2]]}, 'container-title': ['Journal'], 'abstract': '<jats:p>Reported &amp; measured.</jats:p>'}
OPENALEX = {'id': 'https://openalex.org/W123', 'display_name': 'A real supplied study title', 'doi': 'https://doi.org/10.1000/test', 'publication_year': 2024, 'authorships': [{'author': {'display_name': 'A Researcher'}}], 'abstract_inverted_index': {'Reported': [0], 'measured.': [2], 'and': [1]}, 'primary_location': {'source': {'display_name': 'Journal'}, 'landing_page_url': 'https://publisher.example/article'}, 'open_access': {'is_oa': True}, 'best_oa_location': {'is_oa': True, 'landing_page_url': 'https://repository.example/article', 'pdf_url': 'https://repository.example/file.pdf'}}
PUBMED = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345</PMID><Article><ArticleTitle>A <i>supplied</i> title</ArticleTitle><Journal><Title>Journal</Title><JournalIssue><PubDate><MedlineDate>2023 Winter</MedlineDate></PubDate></JournalIssue></Journal><AuthorList><Author><ForeName>A</ForeName><LastName>Researcher</LastName></Author></AuthorList><Abstract><AbstractText Label="RESULTS">Measured <b>data</b>.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/test</ArticleId><ArticleId IdType="pmc">PMC12345</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''


class ProviderTests(unittest.TestCase):
    def test_provider_metadata_and_missing_fields(self):
        cr = crossref_record(CROSSREF)
        self.assertEqual(cr['abstract'], 'Reported & measured.')
        self.assertEqual(cr['doi'], '10.1000/test')
        self.assertIsNone(cr['is_oa'])
        self.assertEqual(cr['pdf_url'], '')
        self.assertEqual(crossref_record({})['title'], '')
        oa = openalex_record(OPENALEX)
        self.assertEqual(oa['abstract'], 'Reported and measured.')
        self.assertTrue(oa['pdf_url'].endswith('.pdf'))
        closed = dict(OPENALEX, best_oa_location={'is_oa': False, 'pdf_url': 'https://example.org/paywalled.pdf'})
        self.assertEqual(openalex_record(closed)['pdf_url'], '')
        pm = pubmed_records(PUBMED)[0]
        self.assertEqual(pm['title'], 'A supplied title')
        self.assertEqual(pm['abstract'], 'RESULTS: Measured data.')
        self.assertEqual(pm['year'], '2023')
        self.assertEqual(pm['pmid'], '12345')
        self.assertIsNone(pm['is_oa'])
        self.assertEqual(pm['pdf_url'], '')

    def test_search_pagination_filters_cache_and_snapshot(self):
        d = Discovery()
        with patch.object(d, 'request', return_value={'message': {'items': [CROSSREF], 'total-results': 45}}) as request:
            result = d.search(dict(query='gardens', page=2, year_from='2020', year_to='2025', journal='0028-0836'))
            self.assertEqual(request.call_args.args[2]['offset'], 20)
            self.assertIn('issn:0028-0836', request.call_args.args[2]['filter'])
            self.assertTrue(result['has_more'])
            cached = d.search(dict(query='gardens', page=2, year_from='2020', year_to='2025', journal='0028-0836'))
            self.assertTrue(cached['cached'])
            self.assertEqual(request.call_count, 1)
            item = d.selected(result['search_id'], [result['records'][0]['result_id']])[0]
            self.assertEqual(item['search_query']['query'], 'gardens')
            self.assertTrue(item['retrieved_at'])
            with self.assertRaises(ValueError):
                d.selected(result['search_id'], ['invented-result'])

    def test_doi_and_openalex_filters(self):
        d = Discovery()
        with patch.object(d, 'request', return_value={'message': CROSSREF}) as request:
            self.assertEqual(len(d.search(dict(query='https://doi.org/10.1000/TEST', mode='doi'))['records']), 1)
            self.assertIn('10.1000%2Ftest', request.call_args.args[1])
        with patch.object(d, 'request', return_value=None):
            self.assertEqual(d.search(dict(query='10.1000/missing', mode='doi'))['total'], 0)
        with patch.object(d, 'request', return_value={'results': [OPENALEX], 'meta': {'count': 1}}) as request:
            d.search(dict(provider='openalex', mode='title', query='garden', oa=True, journal='S123', year_to='2024'))
            params = request.call_args.args[2]
            self.assertEqual(params['search.title'], 'garden')
            self.assertIn('open_access.is_oa:true', params['filter'])
            self.assertIn('primary_location.source.id:S123', params['filter'])

    def test_pubmed_batched_fetch_query_translation(self):
        d = Discovery()
        with patch.object(d, 'request', side_effect=[{'esearchresult': {'idlist': ['12345'], 'count': '1', 'querytranslation': 'translated query'}}, PUBMED]) as request:
            result = d.search(dict(provider='pubmed', query='garden', journal='Nature', oa=True, year_from='2020'))
            self.assertIn('"free full text"[Filter]', request.call_args_list[0].args[2]['term'])
            self.assertEqual(request.call_args_list[1].args[2]['id'], '12345')
            self.assertTrue(any('translated query' in n for n in result['notes']))

    def test_pubmed_title_handles_hyphens_and_phrase_index(self):
        d = Discovery()
        with patch.object(d, 'request', return_value={'esearchresult': {'idlist': [], 'count': '0'}}) as request:
            d.search(dict(provider='pubmed', mode='title', query='The Pfizer-BioNTech COVID-19 vaccine'))
            self.assertEqual(request.call_args.args[2]['term'], '(Pfizer[Title] AND BioNTech[Title] AND COVID[Title] AND 19[Title] AND vaccine[Title])')
        with self.assertRaises(ValueError):
            d.search(dict(provider='pubmed', mode='title', query='?!'))

    def test_input_validation(self):
        for fields in [dict(query=''), dict(query='x', provider='fake'), dict(query='x', oa=True), dict(query='x', page=501), dict(query='x', year_from='2025', year_to='2020'), dict(query='bad', mode='doi'), dict(query='10.1000/x', mode='doi', journal='Nature'), dict(query='x', journal='Nature')]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                Discovery().search(fields)

    def test_network_errors_rate_limit_and_secret_redaction(self):
        d = Discovery()
        with patch('src.discovery.urlopen', side_effect=URLError('secret-token')):
            with self.assertRaises(ProviderError) as caught:
                d.search(dict(query='garden'))
            self.assertNotIn('secret-token', str(caught.exception))
        d = Discovery()
        error = HTTPError('https://api.openalex.org/secret-token', 429, 'rate limited', {'Retry-After': '30'}, None)
        with patch('src.discovery.urlopen', side_effect=error) as request:
            with self.assertRaises(ProviderError) as caught:
                d.search(dict(provider='openalex', query='garden'))
            self.assertEqual(caught.exception.retry_after, 30)
            with self.assertRaises(ProviderError):
                d.search(dict(provider='openalex', query='other'))
            self.assertEqual(request.call_count, 1)
        with patch.dict('os.environ', {'OPENALEX_API_KEY': 'private-test-key'}):
            with patch('src.discovery.urlopen', side_effect=URLError('hidden')) as request:
                with self.assertRaises(ProviderError):
                    Discovery().request('openalex', 'works', {'search': 'garden'})
                req = request.call_args.args[0]
                self.assertNotIn('private-test-key', req.full_url)
                self.assertEqual(req.get_header('Authorization'), 'Bearer private-test-key')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'data.sqlite3')
        self.project = self.store.create('Review')['id']
        self.discovery = Discovery()

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, data):
        with patch.object(self.discovery, 'request', return_value={'results': data, 'meta': {'count': len(data)}}):
            result = self.discovery.search(dict(provider='openalex', query=str(time.time_ns())))
        return result['records']

    def test_import_exact_doi_pmid_provider_and_uncertain(self):
        records = self.snapshot([OPENALEX])
        report = self.store.import_discovery(self.project, records)
        self.assertEqual(len(report['imported']), 1)
        report = self.store.import_discovery(self.project, records)
        self.assertEqual(report['duplicates'][0]['reason'], 'DOI')
        w = dict(OPENALEX, id='https://openalex.org/W124', doi=None)
        possible = self.snapshot([w])
        report = self.store.import_discovery(self.project, possible)
        self.assertEqual(len(report['uncertain']), 1)
        self.assertEqual(len(self.store.backup(self.project)['entities']['record']), 1)
        self.assertEqual(len(self.store.import_discovery(self.project, possible, True)['imported']), 1)
        self.assertEqual(self.store.import_discovery(self.project, possible)['duplicates'][0]['reason'], 'Provider identifier')
        pm = dict(records[0], doi='', provider='pubmed', provider_id='555', pmid='555', title='A different article about population outcomes')
        self.store.import_discovery(self.project, [pm])
        same = dict(pm, provider='openalex', provider_id='https://openalex.org/W555')
        self.assertEqual(self.store.import_discovery(self.project, [same])['duplicates'][0]['reason'], 'PMID')

    def test_missing_metadata_conflicting_ids_and_years(self):
        original = self.snapshot([OPENALEX])
        self.store.import_discovery(self.project, original)
        conflict = dict(original[0], doi='10.1000/distinct', provider_id='https://openalex.org/W999')
        self.assertEqual(len(self.store.import_discovery(self.project, [conflict])['imported']), 1)
        other_year = dict(original[0], doi='', provider_id='', year='2000')
        self.assertEqual(len(self.store.import_discovery(self.project, [other_year])['imported']), 1)
        missing = dict(original[0], title='')
        self.assertEqual(len(self.store.import_discovery(self.project, [missing])['failures']), 1)

    def test_screen_chart_pdf_export_and_restore(self):
        records = self.snapshot([OPENALEX])
        rid = self.store.import_discovery(self.project, records)['imported'][0]['record']
        reviewer = self.store.backup(self.project)['entities']['reviewer'][0]['id']
        self.store.decide(self.project, dict(record=rid, reviewer=reviewer, stage='abstract', choice='include', reason='', notes='notes', labels=[], adjudication=False))
        self.store.chart(self.project, dict(record=rid, reviewer=reviewer, values={'year': {'status': 'value', 'value': '2024'}}))
        self.store.attach(self.project, rid, 'sample.pdf', base64.b64encode(b'%PDF-1.4\nexample').decode(), reviewer)
        backup = self.store.backup(self.project)
        restored = self.store.restore(backup)
        new = self.store.backup(restored['id'])
        r = new['entities']['record'][0]
        self.assertEqual(r['search_query'], records[0]['search_query'])
        self.assertEqual(r['provider_id'], OPENALEX['id'])
        self.assertEqual(len(new['entities']['pdf']), 1)
        self.assertIn(b'openalex', self.store.export(self.project, 'records'))
        self.assertIn(b'include', self.store.export(self.project, 'decisions'))
        self.assertEqual(len(self.store.view(self.project, reviewer)['decisions']), 1)

    def test_demo_and_archive_guard(self):
        records = self.snapshot([OPENALEX])
        demo = self.store.create('Synthetic', demo=True)['id']
        with self.assertRaises(ValueError):
            self.store.import_discovery(demo, records)
        self.store.update(self.project, {'archived': True})
        with self.assertRaises(ValueError):
            self.store.import_discovery(self.project, records)

    def dispatch(self, path, data):
        body = json.dumps(data).encode()
        req = f'POST {path} HTTP/1.1\r\nHost: 127.0.0.1:8844\r\nConnection: close\r\nX-Redreview-Token: test\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body
        sock = MemorySocket(req)
        make_handler(self.store, 'test', discovery=self.discovery)(sock, ('127.0.0.1', 10000), SimpleNamespace(server_port=8844))
        head, body = bytes(sock.output).split(b'\r\n\r\n', 1)
        return int(head.split()[1]), json.loads(body)

    def test_http_search_import_and_error_contract(self):
        with patch.object(self.discovery, 'request', return_value={'message': {'items': [CROSSREF], 'total-results': 1}}):
            status, result = self.dispatch('/api/discovery/search', {'query': 'gardening'})
            self.assertEqual(status, 200)
        args = dict(project=self.project, search_id=result['search_id'], result_ids=[result['records'][0]['result_id']])
        self.assertEqual(len(self.dispatch('/api/discovery/import', args)[1]['imported']), 1)
        self.assertEqual(len(self.dispatch('/api/discovery/import', args)[1]['duplicates']), 1)
        self.assertEqual(self.dispatch('/api/discovery/import', dict(args, result_ids=['forged']))[0], 400)
        with patch.object(self.discovery, 'search', side_effect=ProviderError('Rate limited', 429, 20)):
            status, body = self.dispatch('/api/discovery/search', {'query': 'x'})
            self.assertEqual(status, 429)
            self.assertEqual(body['retry_after'], 20)
