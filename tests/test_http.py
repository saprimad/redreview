import json
import secrets
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from src.server import make_handler
from src.store import Store
from transport import dispatch


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'http.sqlite3')
        self.token = secrets.token_urlsafe(32)
        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.store, self.token))
        except PermissionError:
            self.temp.cleanup()
            self.skipTest('Sandbox prohibits sockets; identical handler tests run in memory.')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        h = {'X-Redreview-Token':self.token, 'Content-Type':'application/json'}
        h.update(headers or {})
        req = Request(self.base+path, data=json.dumps(data).encode() if data is not None else None, headers=h)
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, r.read(), r.headers
        except HTTPError as e:
            return e.code, e.read(), e.headers

    def test_demo_assets_and_export_guard(self):
        status, body, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'redreview', body)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('/app.js')[0], 200)
        self.assertEqual(self.request('/../../etc/passwd')[0], 404)
        status, body, _ = self.request('/api/demo', {})
        self.assertEqual(status, 200)
        project = json.loads(body)
        reviewers = json.loads(self.request('/api/reviewers?project='+project['id'])[1])
        self.assertEqual(len(reviewers), 3)
        pid = project['id']
        v = json.loads(self.request(f'/api/view?project={pid}&reviewer={reviewers[0]["id"]}')[1])
        self.assertEqual(len(v['records']), 4)
        self.assertEqual(self.request(f'/api/backup?project={pid}')[0], 400)
        self.assertEqual(self.request(f'/api/export?project={pid}&category=audit')[0], 400)
        status, body, _ = self.request(f'/api/backup?project={pid}&blinded=false')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['format'], 'redreview')

    def test_csrf_origin_host_and_confirmation_guards(self):
        self.assertEqual(self.request('/api/create', {'name':'test'}, {'X-Redreview-Token':''})[0], 403)
        self.assertEqual(self.request('/api/create', {'name':'test'}, {'Origin':'https://evil.example'})[0], 400)
        self.assertEqual(self.request('/api/projects', headers={'Host':'evil.example'})[0], 400)
        self.assertEqual(self.request('/api/session', headers={'Sec-Fetch-Site':'cross-site'})[0], 400)
        p = json.loads(self.request('/api/create', {'name':'test'})[1])
        self.assertEqual(self.request('/api/update', {'project':p['id'],'changes':{'archived':True}})[0], 400)
        self.assertFalse(self.store.projects()[0]['archived'])
        self.assertEqual(self.request('/api/restore', {'backup':{}})[0], 400)

    def test_error_payloads_are_actionable(self):
        p = json.loads(self.request('/api/create', {'name':'test'})[1])
        status, body, _ = self.request('/api/import', {'project':p['id'],'source':'test','format':'ris','text':'TY  - JOUR\nTI  - Missing end'})
        self.assertEqual(status, 400)
        self.assertIn('ER', json.loads(body)['error'])
        self.assertEqual(self.request('/api/restore', {'confirmed':True,'backup':{'format':'redreview','version':1}})[0], 400)
        self.assertEqual(len(self.store.projects()), 1)


class MemoryHttpTests(HttpTests):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'memory.sqlite3')
        self.token = 'test-only'

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        return dispatch(self.store, self.token, path, data, headers)


class TailscaleHostTests(MemoryHttpTests):
    def request(self, path, data=None, headers=None):
        return dispatch(self.store, self.token, path, data, headers, allowed_hosts=['100.64.0.10:8844'])

    def test_tailscale_page_health_and_same_origin_mutation(self):
        public = {'Host':'100.64.0.10:8844', 'Origin':'http://100.64.0.10:8844'}
        self.assertEqual(self.request('/', headers=public)[0], 200)
        status, body, _ = self.request('/api/health', headers=public)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['app'], 'redreview')
        status, body, _ = self.request('/api/create', {'name':'iPhone test'}, public)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['name'], 'iPhone test')

    def test_other_hosts_and_cross_origin_remain_rejected(self):
        for headers in ({'Host':'192.168.1.10:8844'}, {'Host':'100.64.0.10:8844','Origin':'https://evil.example'}, {'Host':'100.64.0.10:8844','Origin':'http://127.0.0.1:8844'}, {'Host':'127.0.0.1:8844','Origin':'http://100.64.0.10:8844'}, {'Host':'100.64.0.10:8844','Sec-Fetch-Site':'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('/api/create', {'name':'Should not create'}, headers)[0], 400)
        self.assertEqual(self.store.projects(), [])

    def test_invalid_authorities_rejected(self):
        from src.server import validate_authority
        for authority in ('*', '0.0.0.0:8844', 'http://100.64.0.10:8844', '100.64.0.10:8844/path', 'host:0', 'host:65536', 'a..b:8844'):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                validate_authority(authority)
