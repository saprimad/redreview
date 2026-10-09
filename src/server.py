"""Explicit-host HTTP transport. Mutations require a per-session CSRF token."""
import argparse
import base64
import json
import ipaddress
import mimetypes
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .store import Store
from .discovery import Discovery, ProviderError

ROOT = Path(__file__).resolve().parent.parent


def validate_authority(value):
    """Accept explicit IPv4/hostname authorities, never URL/wildcard origins."""
    import re
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?:[0-9]{1,5}', value):
        raise ValueError('Allowed hosts must be explicit host:port values, without a scheme, path or wildcard.')
    host, port = value.rsplit(':', 1)
    if not 1 <= int(port) <= 65535 or host == '0.0.0.0' or '..' in host:
        raise ValueError('Invalid allowed host or port.')
    return value.lower()


def make_handler(store, token, allowed_hosts=(), discovery=None):
    discovery = discovery or Discovery()
    configured_hosts = {validate_authority(host) for host in allowed_hosts}
    class Handler(BaseHTTPRequestHandler):
        def send(self, payload, status=200, content_type='application/json; charset=utf-8', download=None):
            if not isinstance(payload, bytes):
                payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'SAMEORIGIN')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-src 'self' blob:; object-src 'self' blob:; base-uri 'none'; form-action 'self'")
            if download:
                self.send_header('Content-Disposition', f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(payload)

        def trusted(self):
            host = self.headers.get('Host', '').lower()
            expected = f'127.0.0.1:{self.server.server_port}'
            allowed = configured_hosts | {expected}
            if host not in allowed:
                raise ValueError('This host is not allowed. Use a configured RedReview address.')
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{host}':
                raise ValueError('Cross-origin requests are not allowed.')
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise ValueError('Cross-site requests are not allowed.')

        def do_GET(self):
            try:
                self.trusted()
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == '/api/health':
                    self.send({'app': 'redreview', 'version': '0.2.0'})
                elif url.path == '/api/session':
                    self.send({'token': token})
                elif url.path == '/api/projects':
                    self.send(store.projects())
                elif url.path == '/api/view':
                    self.send(store.view(q.get('project'), q.get('reviewer'), q.get('blinded', 'true') != 'false'))
                elif url.path == '/api/reviewers':
                    with store.connect() as db:
                        store.project(db, q.get('project'))
                        self.send(store.rows(db, q.get('project'), 'reviewer'))
                elif url.path in ('/api/export', '/api/backup'):
                    # Explicit unblinded mode is necessary for whole-project disclosures.
                    if q.get('blinded') != 'false':
                        raise ValueError('Disable blinding before exporting the whole project or its backup.')
                    if url.path == '/api/backup':
                        self.send(json.dumps(store.backup(q.get('project')), ensure_ascii=False).encode(), content_type='application/json', download='redreview-backup.json')
                    else:
                        category = q.get('category')
                        self.send(store.export(q.get('project'), category), content_type='text/csv; charset=utf-8', download=f'redreview-{category}.csv')
                elif url.path == '/api/pdf':
                    with store.connect() as db:
                        pdf = store.entity(db, q.get('project'), 'pdf', q.get('id'))
                        self.send(base64.b64decode(pdf['content']), content_type='application/pdf')
                else:
                    allowed = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css'}
                    if url.path not in allowed:
                        self.send({'error': 'Page not found.'}, 404)
                        return
                    path = ROOT / 'web' / allowed[url.path]
                    self.send(path.read_bytes(), content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
            except (ValueError, KeyError, TypeError) as e:
                self.send({'error': str(e)}, 400)
            except (OSError, sqlite3.Error):
                self.send({'error': 'Cannot read local data. Check file permissions and available disk space.'}, 500)

        def do_POST(self):
            try:
                self.trusted()
                if not secrets.compare_digest(self.headers.get('X-Redreview-Token', ''), token):
                    self.send({'error': 'Session expired. Reload the application.'}, 403)
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 100 * 1024 * 1024:
                    raise ValueError('Request is empty or exceeds the 100 MiB limit.')
                d = json.loads(self.rfile.read(size))
                if not isinstance(d, dict):
                    raise ValueError('Expected an object.')
                path = urlparse(self.path).path
                pid = d.get('project')
                if path == '/api/create':
                    result = store.create(d.get('name'))
                elif path == '/api/update':
                    if d.get('changes', {}).get('archived') and d.get('confirmed') is not True:
                        raise ValueError('Confirm archiving before proceeding.')
                    result = store.update(pid, d.get('changes', {}))
                elif path == '/api/reviewer':
                    result = store.add_reviewer(pid, d.get('name'), d.get('role'))
                elif path == '/api/discovery/search':
                    result = discovery.search(d)
                elif path == '/api/discovery/import':
                    records = discovery.selected(d.get('search_id'), d.get('result_ids'))
                    result = store.import_discovery(pid, records, d.get('allow_uncertain', False))
                elif path == '/api/import':
                    result = store.import_records(pid, d.get('text', ''), d.get('format'), d.get('source'), d.get('mapping'))
                elif path == '/api/merge':
                    if d.get('confirmed') is not True:
                        raise ValueError('Inspect and confirm the duplicate merge first.')
                    store.merge(pid, d.get('keep'), d.get('other'), d.get('undo', False))
                    result = {'ok': True}
                elif path == '/api/decision':
                    result = store.decide(pid, d)
                elif path == '/api/chart':
                    result = store.chart(pid, d)
                elif path == '/api/attach':
                    result = store.attach(pid, d.get('record'), d.get('name'), d.get('content'), d.get('reviewer'))
                elif path == '/api/restore':
                    if d.get('confirmed') is not True:
                        raise ValueError('Confirm creating a restored project first.')
                    result = store.restore(d.get('backup'))
                elif path == '/api/demo':
                    p = store.create('DEMO — Community wellbeing (synthetic)', demo=True)
                    store.update(p['id'], {'question': 'How are community gardens described in synthetic wellbeing studies?', 'criteria': 'Include community gardening studies involving adults. Exclude unrelated topics. All demo records are fictional.'})
                    store.import_records(p['id'], (ROOT / 'fixtures' / 'sample.ris').read_text(), 'ris', 'Synthetic sample database')
                    snapshot = store.backup(p['id'])
                    store.attach(p['id'], snapshot['entities']['record'][0]['id'], 'SYNTHETIC-demo-report.pdf', base64.b64encode((ROOT / 'fixtures' / 'synthetic-report.pdf').read_bytes()).decode(), snapshot['entities']['reviewer'][0]['id'])
                    store.add_reviewer(p['id'], 'Reviewer 2', 'reviewer')
                    store.add_reviewer(p['id'], 'Adjudicator', 'adjudicator')
                    result = p
                else:
                    self.send({'error': 'Unknown action.'}, 404)
                    return
                self.send(result)
            except ProviderError as e:
                if e.retry_after is not None:
                    # Client displays the cooldown; no automatic retry storms.
                    self.send({'error': str(e), 'retry_after': e.retry_after}, e.status)
                else:
                    self.send({'error': str(e)}, e.status)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                self.send({'error': str(e)}, 400)
            except (OSError, sqlite3.Error):
                self.send({'error': 'Cannot write local data. Check permissions and free disk space; retry the action.'}, 500)

        def log_message(self, fmt, *args):
            # Avoid logging project contents, URL queries, or credentials.
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description='redreview local review workspace')
    parser.add_argument('--port', type=int, default=8844)
    parser.add_argument('--bind', default='127.0.0.1', help='Specific IPv4 address to listen on; defaults to loopback.')
    parser.add_argument('--allow-host', action='append', default=[], help='Additional explicit host:port accepted by Host/Origin checks. Repeat if needed.')
    parser.add_argument('--data', default=str(ROOT / '.data' / 'redreview.sqlite3'))
    args = parser.parse_args()
    try:
        bind_ip = ipaddress.IPv4Address(args.bind)
        if bind_ip.is_unspecified or bind_ip.is_multicast:
            raise ValueError('Use a specific bind address; wildcard and multicast listeners are disabled.')
        if not 1 <= args.port <= 65535:
            raise ValueError('Port must be between 1 and 65535.')
        allowed_hosts = [validate_authority(h) for h in args.allow_host]
        allowed_hosts.append(f'{bind_ip}:{args.port}')
    except ValueError as error:
        parser.error(str(error))
    store = Store(args.data)
    try:
        server = ThreadingHTTPServer((str(bind_ip), args.port), make_handler(store, secrets.token_urlsafe(32), allowed_hosts))
    except OSError as error:
        parser.exit(1, f'Cannot start the local server: {error}. Check socket permissions or use another --port.\n')
    print(f'redreview listener: http://{bind_ip}:{args.port}', flush=True)
    for authority in sorted(set(allowed_hosts)):
        print(f'Allowed address: http://{authority}', flush=True)
    print(f'Local database: {Path(args.data).resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
